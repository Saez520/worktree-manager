import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from worktree_manager.configuration import Configuration
from worktree_manager.lock_manager import LockManager
from worktree_manager.models import ManagerError
from worktree_manager.mcp_operations import call
from worktree_manager.state_digest import state_digest
from worktree_manager.worktree_lifecycle import WorktreeLifecycle


class PreLockOracleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
        self.git = git
        git("init", "-q", "-b", "main")
        git("config", "user.name", "Test")
        git("config", "user.email", "test@example.invalid")
        (self.root / ".gitignore").write_text(".worktrees/\n")
        (self.root / "base").write_text("base")
        git("add", ".gitignore", "base")
        git("commit", "-qm", "base")
        self.barrier = Path(self.temp.name) / "barrier"
        self.previous_barrier = os.environ.get("WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR")
        os.environ["WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR"] = str(self.barrier)
        self.addCleanup(self._restore_barrier)
        self.lifecycle = WorktreeLifecycle(Configuration.load(self.root))

    def _restore_barrier(self):
        if self.previous_barrier is None:
            os.environ.pop("WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR", None)
        else:
            os.environ["WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR"] = self.previous_barrier

    def _snapshot(self):
        refs = self.git("for-each-ref", "--format=%(refname) %(objectname)")
        worktrees = self.git("worktree", "list", "--porcelain")
        def files(root):
            if not root.exists():
                return ()
            return tuple(sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()))
        lock_root = self.lifecycle.state_root / self.lifecycle.config.lock_dir
        journal_root = self.lifecycle.journal.root
        return {
            "digest": state_digest(self.root, self.lifecycle.state_root),
            "refs": refs,
            "worktrees": worktrees,
            "journal": files(journal_root),
            "locks": files(lock_root),
            "lock_attempts": tuple(sorted(p.name for p in self.barrier.iterdir())) if self.barrier.exists() else (),
            # The lifecycle currently has no in-memory counters; any persisted counter
            # artifacts are included with the journal/lock filesystem snapshots.
            "counters": files(self.lifecycle.state_root),
        }

    def test_create_marks_validation_before_lock_acquired(self):
        phases = []
        original = LockManager._mark
        def spy(manager, phase):
            phases.append(phase)
            return original(manager, phase)
        LockManager._mark = spy
        try:
            result = self.lifecycle.create("valid", "main")
        finally:
            LockManager._mark = original
        self.assertEqual(phases, ["pre_lock_validation", "lock_acquired"])
        self.assertTrue(Path(result["path"]).is_dir())
        self.assertEqual(list(self.barrier.iterdir()), [self.barrier / "pre_lock_validation", self.barrier / "lock_acquired"])
        self.assertEqual(list((self.lifecycle.state_root / self.lifecycle.config.lock_dir).glob("**/owner")), [])

    def test_create_validation_mismatches_leave_state_and_barrier_untouched(self):
        for work_id, base in (("../bad", "main"), ("bad-base", "missing")):
            with self.subTest(work_id=work_id, base=base):
                before = self._snapshot()
                with self.assertRaises(ManagerError):
                    self.lifecycle.create(work_id, base)
                self.assertEqual(self._snapshot(), before)

    def test_cleanup_without_authorization_rejected_before_barrier(self):
        request = {"repo": str(self.root), "work_id": "missing"}
        before = self._snapshot()
        with self.assertRaises(ManagerError) as caught:
            call("worktree_cleanup", request)
        self.assertEqual(caught.exception.code, "authorization_required")
        self.assertEqual(self._snapshot(), before)

    def test_discard_without_separate_consent_has_no_effects(self):
        request = {"repo": str(self.root), "work_id": "missing", "discard": True,
                   "authorization": "I_AUTHORIZE_THIS_CALL"}
        before = self._snapshot()
        with self.assertRaises(ManagerError) as caught:
            call("worktree_cleanup", request)
        self.assertEqual(caught.exception.code, "discard_consent_required")
        self.assertEqual(self._snapshot(), before)

    def test_lock_contention_after_pre_lock_reports_only_pre_lock_attempt(self):
        created = self.lifecycle.create("contended", "main")
        lock_root = self.lifecycle.state_root / self.lifecycle.config.lock_dir
        lock_name = f"work/{self.lifecycle._lock_work_id('contended')}"
        (lock_root / lock_name).mkdir(parents=True)
        (lock_root / lock_name / "owner").write_text("other process\n")
        if self.barrier.exists():
            for marker in self.barrier.iterdir():
                marker.unlink()
        before = self._snapshot()
        with self.assertRaises(ManagerError) as caught:
            self.lifecycle.cleanup("contended")
        self.assertEqual(caught.exception.code, "resource_locked")
        after = self._snapshot()
        self.assertEqual(after["lock_attempts"], ("pre_lock_validation",))
        for key in ("digest", "refs", "worktrees", "journal", "counters"):
            self.assertEqual(after[key], before[key], key)
        self.assertTrue(Path(created["path"]).is_dir())
        self.assertEqual(after["locks"], before["locks"])

    def test_valid_cleanup_marks_validation_then_lock_before_removal(self):
        created = self.lifecycle.create("remove-me", "main")
        phases = []
        original = LockManager._mark
        def spy(manager, phase):
            phases.append(phase)
            return original(manager, phase)
        LockManager._mark = spy
        try:
            self.lifecycle.cleanup("remove-me")
        finally:
            LockManager._mark = original
        self.assertEqual(phases, ["pre_lock_validation", "lock_acquired"])
        self.assertFalse(Path(created["path"]).exists())
        lock_root = self.lifecycle.state_root / self.lifecycle.config.lock_dir
        self.assertEqual(list(lock_root.glob("**/owner")), [])

    def test_dry_run_create_does_not_mark_or_acquire_locks(self):
        result = call("worktree_create", {"repo": str(self.root), "work_id": "planned", "base": "main", "dry_run": True})
        self.assertEqual(result["result"], "success")
        self.assertFalse(self.barrier.exists() and any(self.barrier.iterdir()))
