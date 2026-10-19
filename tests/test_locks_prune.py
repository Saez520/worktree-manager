"""Acceptance tests for deterministic lifecycle locks and real prune counts."""
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worktree_manager.configuration import Configuration
from worktree_manager.lock_manager import LockManager
from worktree_manager.models import ManagerError
from worktree_manager.mcp_operations import call
from worktree_manager.recovery_manager import RecoveryManager
from worktree_manager.transaction_journal import TransactionJournal
from worktree_manager.worktree_lifecycle import WorktreeLifecycle


class LocksPruneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.root / ".gitignore").write_text(".worktrees/\n")
        (self.root / "base").write_text("base")
        self.git("add", ".gitignore", "base")
        self.git("commit", "-qm", "base")
        self.barrier = Path(self.temp.name) / "barrier"
        self.old_barrier = os.environ.get("WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR")
        os.environ["WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR"] = str(self.barrier)
        self.addCleanup(self.restore_barrier)
        self.lifecycle = WorktreeLifecycle(Configuration.load(self.root))

    def git(self, *args, check=True):
        return subprocess.run(["git", "-C", str(self.root), *args], check=check,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()

    def restore_barrier(self):
        if self.old_barrier is None:
            os.environ.pop("WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR", None)
        else:
            os.environ["WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR"] = self.old_barrier

    def test_cleanup_acquires_repository_and_work_locks(self):
        created = self.lifecycle.create("clean", "main")
        seen = []
        original = LockManager.acquire
        def spy(manager, names, operation):
            if operation == "cleanup":
                seen.extend(names)
            return original(manager, names, operation)
        with patch.object(LockManager, "acquire", spy):
            self.lifecycle.cleanup("clean")
        repo_hash = hashlib.sha256(str(self.root.resolve()).encode()).hexdigest()
        self.assertCountEqual(seen, [f"repository-{repo_hash}", "work/636c65616e"])
        self.assertFalse(Path(created["path"]).exists())
        self.assertEqual(list((self.lifecycle.state_root / "locks").glob("**/owner")), [])

    def test_prune_reports_real_count_and_is_idempotent(self):
        created = [self.lifecycle.create(f"orphan-{i}", "main") for i in range(2)]
        for item in created:
            import shutil
            shutil.rmtree(item["path"])
        result = self.lifecycle.prune()
        self.assertEqual(result["pruned"], 2)
        self.assertEqual(len(self.lifecycle.list()), 1)
        result = self.lifecycle.prune()
        self.assertEqual(result["pruned"], 0)
        response = call("worktree_prune", {"repo": str(self.root), "authorization": "I_AUTHORIZE_THIS_CALL"})
        self.assertEqual(response["result"], "no_pending_work")
        self.assertEqual(response["data"]["pruned"], 0)

    def test_recover_acquires_repository_lock_without_replay(self):
        journal = TransactionJournal(self.lifecycle.state_root)
        journal.directory("done").mkdir(parents=True)
        journal.write_phase("done", "restored")
        journal.write_binding("done", {"transaction_id": "done", "repo": str(self.root.resolve()), "work_id": "done"})
        seen = []
        original = LockManager.acquire
        def spy(manager, names, operation):
            if operation == "recover":
                seen.extend(names)
            return original(manager, names, operation)
        manager = RecoveryManager(self.lifecycle.state_root, self.root)
        with patch.object(LockManager, "acquire", spy):
            with self.assertRaises(ManagerError) as caught:
                manager.recover("missing")
        self.assertEqual(caught.exception.code, "invalid_identity")
        self.assertEqual(seen, [])
        self.assertFalse(self.barrier.exists() and any(self.barrier.iterdir()))
        tx = "recover-no-replay"
        journal.directory(tx).mkdir(parents=True)
        head = self.git("rev-parse", "HEAD")
        (journal.directory(tx) / "meta.json").write_text(__import__("json").dumps({
            "base": "main", "branch": "worktree/missing", "path": str(self.root / "missing"),
            "before": head, "origin": head, "preserve_dirty": False,
        }))
        journal.write_phase(tx, "merge_started")
        journal.write_binding(tx, {"transaction_id": tx, "repo": str(self.root.resolve()), "work_id": "missing"})
        # Recovery reconciles the unchanged HEAD; it takes the repo lock and never replays squash.
        with patch.object(LockManager, "acquire", spy):
            kind, data = manager.recover(tx)
        self.assertEqual(kind.value, "success")
        self.assertEqual(data["phase"], "restored")
        self.assertEqual(seen, [f"repository-{hashlib.sha256(str(self.root.resolve()).encode()).hexdigest()}"])
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        seen.clear()
        # Terminal recovery is a no-op.
        with patch.object(LockManager, "acquire", spy):
            self.assertEqual(manager.recover("done")[0].value, "no_pending_work")
        self.assertEqual(seen, [])

    def test_prune_dry_run_does_not_acquire_lock_or_mutate(self):
        before = self.git("worktree", "list", "--porcelain")
        phases = []
        original = LockManager._mark
        def spy(manager, phase):
            phases.append(phase)
            return original(manager, phase)
        with patch.object(LockManager, "_mark", spy):
            response = call("worktree_prune", {"repo": str(self.root), "dry_run": True})
        self.assertEqual(response["result"], "no_pending_work")
        self.assertEqual(phases, [])
        self.assertEqual(self.git("worktree", "list", "--porcelain"), before)
