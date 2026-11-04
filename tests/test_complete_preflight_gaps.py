"""Contract tests for the two-step preflight/execute flow of ``worktree_complete``.

Gap coverage:

- G1 / C1: dry run without ``authorization`` followed by an authorized execute
  must complete. Defect: a client that follows the documented flow stays in
  ``plan_mismatch`` forever. Not detected before because every existing test
  sends ``authorization`` in the dry run.
- G2 / C3: a commit in a foreign worktree must not invalidate the preflight of
  another work id. Defect: parallel work produces false ``plan_mismatch``
  rejections. Not detected before because no test runs two worktrees with one
  completion in flight.
- G3 / C4-C5: a commit on the base between preflight and execute must still
  produce ``plan_mismatch`` without mutating, and the message must name the
  bound fields as ``(bound: ...)``. Defect: the TOCTOU protection is lost or
  the operator cannot tell what to correct. Not detected before because no test
  exercises base drift on complete nor asserts on the message.
"""
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from worktree_manager.mcp_operations import call
from worktree_manager.models import ManagerError


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


class CompletePreflightGapTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="complete-preflight-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "Test")
        git(self.root, "config", "user.email", "test@example.invalid")
        (self.root / ".gitignore").write_text(".worktrees/\n")
        (self.root / "base.txt").write_text("base\n")
        git(self.root, "add", ".gitignore", "base.txt")
        git(self.root, "commit", "-m", "base")

    def worktree_with_commit(self, work_id):
        created = call("worktree_create", {"repo": str(self.root), "work_id": work_id, "base": "main"})
        path = Path(created["data"]["path"])
        git(path, "config", "user.name", "Test")
        git(path, "config", "user.email", "test@example.invalid")
        (path / f"{work_id}.txt").write_text(work_id + "\n")
        git(path, "add", f"{work_id}.txt")
        git(path, "commit", "-m", work_id)
        return path

    def snapshot(self):
        transactions = self.root / ".git" / "worktree-manager" / "transactions"
        files = sorted(
            (str(p.relative_to(transactions)), hashlib.sha256(p.read_bytes()).hexdigest())
            for p in transactions.rglob("*") if p.is_file()
        ) if transactions.exists() else []
        return {
            "head": git(self.root, "rev-parse", "HEAD"),
            "refs": git(self.root, "for-each-ref", "--format=%(refname) %(objectname)"),
            "worktrees": git(self.root, "worktree", "list", "--porcelain"),
            "status": git(self.root, "status", "--porcelain=v2", "--untracked-files=all"),
            "transactions": files,
        }

    def test_complete_preflight_without_authorization_executes_with_authorization(self):
        """G1 / C1: preflight without authorization must remain usable by an authorized execute.

        Defect: a client following the documented two-step flow never completes.
        Why not detected: existing tests always send authorization in the dry run.
        Observable: dry run returns a plan hash, the authorized execute returns
        success, the base branch holds the change, and the worktree is retired.
        """
        path = self.worktree_with_commit("feature")
        preflight = call("worktree_complete", {
            "repo": str(self.root), "work_id": "feature", "base": "main", "dry_run": True,
        })["data"]
        self.assertEqual(len(preflight["plan_hash"]), 64)

        result = call("worktree_complete", {
            "repo": str(self.root), "work_id": "feature", "base": "main",
            "dry_run": False, "authorization": "I_AUTHORIZE_THIS_CALL",
            "transaction_id": preflight["transaction_id"],
            "plan_hash": preflight["plan_hash"],
        })

        self.assertEqual(result["result"], "success")
        self.assertEqual(git(self.root, "show", "main:feature.txt"), "feature")
        self.assertFalse(path.exists())
        self.assertEqual(git(self.root, "branch", "--list", "worktree/feature"), "")

    def test_complete_preflight_survives_commit_in_foreign_worktree(self):
        """G2 / C3: a foreign worktree commit must not invalidate this work id's preflight.

        Defect: parallel work causes false plan_mismatch rejections.
        Why not detected: no test runs two worktrees with one completion in flight.
        Observable: after committing on another worktree branch, the execute for
        the planned work id returns success and only its change lands on the base.
        """
        self.worktree_with_commit("feature")
        other = self.worktree_with_commit("other")
        request = {
            "repo": str(self.root), "work_id": "feature", "base": "main", "dry_run": True,
            "authorization": "I_AUTHORIZE_THIS_CALL",
        }
        preflight = call("worktree_complete", request)["data"]

        (other / "foreign.txt").write_text("foreign\n")
        git(other, "add", "foreign.txt")
        git(other, "commit", "-m", "foreign change")

        result = call("worktree_complete", dict(
            request, dry_run=False,
            transaction_id=preflight["transaction_id"],
            plan_hash=preflight["plan_hash"],
        ))

        self.assertEqual(result["result"], "success")
        self.assertEqual(git(self.root, "show", "main:feature.txt"), "feature")
        self.assertNotIn("foreign.txt", git(self.root, "ls-tree", "--name-only", "main").splitlines())
        self.assertTrue(other.is_dir())

    def test_complete_preflight_rejects_base_drift_and_names_bound_fields(self):
        """G3 / C4-C5: base drift must still fail as plan_mismatch, safely and with field names.

        Defect: the TOCTOU guard is lost, or the operator cannot tell what to fix.
        Why not detected: no test exercises base drift on complete nor asserts the message.
        Observable: an empty commit on the base between preflight and execute raises
        plan_mismatch whose message carries ``(bound: ...)`` naming the hashed fields,
        without exposing their values and without changing the repository.
        """
        path = self.worktree_with_commit("feature")
        request = {
            "repo": str(self.root), "work_id": "feature", "base": "main", "dry_run": True,
            "authorization": "I_AUTHORIZE_THIS_CALL",
        }
        preflight = call("worktree_complete", request)["data"]
        git(self.root, "commit", "--allow-empty", "-m", "base drift")

        before = self.snapshot()
        with self.assertRaises(ManagerError) as caught:
            call("worktree_complete", dict(
                request, dry_run=False,
                transaction_id=preflight["transaction_id"],
                plan_hash=preflight["plan_hash"],
            ))

        error = caught.exception
        self.assertEqual(error.code, "plan_mismatch")
        message = str(error)
        self.assertIn("(bound: ", message)
        bound = message.split("(bound: ", 1)[1].removesuffix(")")
        names = {name.strip() for name in bound.split(",")}
        self.assertIn("base", names)
        self.assertIn("state_digest", names)
        self.assertNotIn(preflight["state_digest"], message)
        self.assertNotIn(preflight["plan_hash"], message)

        self.assertEqual(self.snapshot(), before)
        self.assertTrue(path.is_dir())
        self.assertEqual(git(self.root, "branch", "--list", "worktree/feature").count("worktree/feature"), 1)


if __name__ == "__main__":
    unittest.main()
