import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from worktree_manager.mcp_operations import call
from worktree_manager.state_digest import canonical_hash, state_digest
from worktree_manager.models import ManagerError


class DurableBindingTests(unittest.TestCase):
    def repo(self, directory):
        root = Path(directory) / "repo"
        root.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(root), *args], check=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
        git("init", "-b", "main")
        git("config", "user.name", "Test")
        git("config", "user.email", "test@example.invalid")
        (root / ".gitignore").write_text(".worktrees/\n")
        (root / "base").write_text("base")
        git("add", ".gitignore", "base")
        git("commit", "-m", "base")
        return root, git

    def test_plan_hash_is_exact_canonical_payload(self):
        with tempfile.TemporaryDirectory() as d:
            root, _ = self.repo(d)
            response = call("worktree_create", {"repo": str(root), "work_id": "feature", "base": "main", "dry_run": True})
            data = response["data"]
            expected = {"operation": "worktree_create", "repo": str(root.resolve()), "work_id": "feature",
                        "confirm": False, "transaction_id": None, "base": "main", "preserve_dirty": None,
                        "discard": None, "discard_consent": None, "target_direct": None,
                        "parent_repo": None, "submodule_path": None, "state_digest": data["state_digest"]}
            independent = hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            self.assertEqual(data["plan_hash"], independent)
            self.assertEqual(set(expected), {"operation", "repo", "work_id", "confirm", "transaction_id", "base", "preserve_dirty", "discard", "discard_consent", "target_direct", "parent_repo", "submodule_path", "state_digest"})

    def test_binding_written_before_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            root, git = self.repo(d)
            planned = call("worktree_create", {"repo": str(root), "work_id": "feature", "base": "main", "dry_run": True})
            call("worktree_create", {"repo": str(root), "work_id": "feature", "base": "main"})
            wt = root / ".worktrees" / "feature"
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.invalid"], check=True)
            (wt / "change").write_text("change")
            subprocess.run(["git", "-C", str(wt), "add", "change"], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feature"], check=True, stdout=subprocess.PIPE)
            env = dict(os.environ, WORKTREE_MANAGER_TEST_CRASH_AFTER_TRANSACTION_PHASE="merge_started")
            crashed = subprocess.run(["python3", "-c", "from worktree_manager.mcp_operations import call; import sys; call('worktree_complete', {'repo':sys.argv[1],'work_id':'feature','base':'main','authorization':'I_AUTHORIZE_THIS_CALL','transaction_id':'binding-test'})", str(root)], env=env)
            self.assertEqual(crashed.returncode, 86)
            binding_path = root / ".git" / "worktree-manager" / "transactions" / "binding-test" / "binding.json"
            binding = json.loads(binding_path.read_text())
            self.assertTrue(binding_path.stat().st_mode & 0o777 == 0o600)
            self.assertEqual(binding["transaction_id"], "binding-test")
            self.assertEqual(binding["phase"], "prepared")

    def test_second_execute_blocked_without_replay(self):
        with tempfile.TemporaryDirectory() as d:
            root, _ = self.repo(d)
            created = call("worktree_create", {"repo": str(root), "work_id": "feature", "base": "main"})
            wt = Path(created["data"]["path"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.invalid"], check=True)
            (wt / "change").write_text("change")
            subprocess.run(["git", "-C", str(wt), "add", "change"], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feature"], check=True, stdout=subprocess.PIPE)
            request = {"repo": str(root), "work_id": "feature", "base": "main", "dry_run": True, "authorization": "I_AUTHORIZE_THIS_CALL"}
            plan = call("worktree_complete", request)["data"]
            execute = dict(request, dry_run=False, authorization="I_AUTHORIZE_THIS_CALL", transaction_id=plan["transaction_id"], plan_hash=plan["plan_hash"])
            call("worktree_complete", execute)
            before = subprocess.run(["git", "-C", str(root), "rev-list", "--count", "main"], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
            with self.assertRaises(ManagerError) as caught:
                call("worktree_complete", execute)
            self.assertIn(caught.exception.code, {"plan_mismatch", "intervention_required"})
            after = subprocess.run(["git", "-C", str(root), "rev-list", "--count", "main"], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
            self.assertEqual(before, after)

    def test_plan_mismatch_precedes_barrier_without_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root, git = self.repo(d)
            barrier = Path(d) / "barrier"
            os.environ["WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR"] = str(barrier)
            try:
                planned = call("worktree_create", {"repo": str(root), "work_id": "feature", "base": "main", "dry_run": True})["data"]
                git("commit", "--allow-empty", "-m", "state drift")
                before = state_digest(root, root / ".git" / "worktree-manager")
                with self.assertRaises(ManagerError) as caught:
                    call("worktree_create", {"repo": str(root), "work_id": "feature", "base": "main", "plan_hash": planned["plan_hash"]})
                self.assertEqual(caught.exception.code, "plan_mismatch")
                self.assertFalse(barrier.exists() and list(barrier.iterdir()))
                self.assertEqual(state_digest(root, root / ".git" / "worktree-manager"), before)
                self.assertFalse((root / ".worktrees" / "feature").exists())
            finally:
                os.environ.pop("WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR", None)


if __name__ == "__main__":
    unittest.main()
