"""Base drift: complete must never integrate a tree the branch did not validate.

The rule under test: complete integrates only when the current base tip is an
ancestor of the worktree branch. In that case the resulting tree is identical
to the branch tree. Otherwise it fails closed with `base_changed` and mutates
nothing. Real Git, real CLI and real stdio MCP; no backend mocks except the
in-process race simulation, which injects a commit through a real Git call.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp_client import McpClient

STRATEGIES = ("squash", "preserve-history")
CONFIG = ("state_dir=state\nbackup_dir=backups\nbackup_ref_prefix=manager/backups\n"
          "branch_prefix=worktree/\nlock_dir=locks\n")


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], check=check,
                          text=True, capture_output=True).stdout.strip()


def make_repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    git(path, "config", "user.name", "Drift")
    git(path, "config", "user.email", "drift@example.invalid")
    (path / "app.txt").write_text("base\n")
    (path / ".gitignore").write_text(".worktrees/\n")
    (path / ".worktree-manager.conf").write_text(CONFIG)
    git(path, "add", ".")
    git(path, "commit", "-qm", "base")
    return path


def cli(*args):
    return subprocess.run([sys.executable, "-m", "worktree_manager", "--json", *args],
                          text=True, capture_output=True)


def feature_name(work_id):
    return f"feature-{work_id}.txt"


def error_code(result):
    """Error code of a CLI result, or None when the call reported no error."""
    return (json.loads(result.stdout).get("error") or {}).get("code")


def make_work(repo, work_id="feat"):
    created = cli("--repo", str(repo), "create", work_id)
    assert created.returncode == 0, created.stdout + created.stderr
    worktree = Path(json.loads(created.stdout)["data"]["path"])
    git(worktree, "config", "user.name", "Drift")
    git(worktree, "config", "user.email", "drift@example.invalid")
    (worktree / feature_name(work_id)).write_text("feature\n")
    git(worktree, "add", ".")
    git(worktree, "commit", "-qm", "feature")
    return worktree


def drift(repo, name="drift.txt"):
    (repo / name).write_text("drift\n")
    git(repo, "add", name)
    git(repo, "commit", "-qm", "drift on main")
    return git(repo, "rev-parse", "HEAD")


def snapshot(repo, work_id="feat"):
    transactions = repo / ".git" / "state" / "transactions"
    return {
        "main": git(repo, "rev-parse", "main"),
        "branch": git(repo, "rev-parse", f"worktree/{work_id}"),
        "refs": git(repo, "for-each-ref", "--format=%(refname) %(objectname)"),
        "worktrees": git(repo, "worktree", "list", "--porcelain"),
        "status": git(repo, "status", "--porcelain", "--untracked-files=all"),
        "transactions": sorted(p.name for p in transactions.iterdir()) if transactions.is_dir() else [],
    }


class CliBaseDriftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wt-drift-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(Path(self.tmp.name) / "repo")

    def complete(self, *extra, strategy="squash", work_id="feat"):
        return cli("--repo", str(self.repo), "complete", work_id, "--merge-strategy", strategy, *extra)

    def test_a_cli_drift_is_rejected_and_nothing_mutates(self):
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                work_id = "feat-" + strategy.replace("-", "")
                make_work(self.repo, work_id)
                drift(self.repo, f"drift-{work_id}.txt")
                before = snapshot(self.repo, work_id)
                result = self.complete(strategy=strategy, work_id=work_id)
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                document = json.loads(result.stdout)
                self.assertEqual(document["result"], "failure")
                self.assertEqual(error_code(result), "base_changed")
                self.assertEqual(document["error"]["exit_code"], 5)
                details = document["error"]["details"]
                self.assertEqual(details["current_base"], before["main"])
                self.assertEqual(details["expected_base"], git(self.repo, "merge-base", "main", before["branch"]))
                self.assertEqual(snapshot(self.repo, work_id), before)

    def test_d_no_drift_still_integrates_with_branch_tree(self):
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                work_id = "ok-" + strategy.replace("-", "")
                make_work(self.repo, work_id)
                branch_tree = git(self.repo, "rev-parse", f"worktree/{work_id}^{{tree}}")
                result = self.complete(strategy=strategy, work_id=work_id)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                data = json.loads(result.stdout)["data"]
                self.assertEqual(git(self.repo, "rev-parse", "main"), data["integrated_commit"])
                self.assertEqual(git(self.repo, "rev-parse", "main^{tree}"), branch_tree)
                self.assertEqual(git(self.repo, "status", "--porcelain"), "")
                self.assertFalse(git(self.repo, "branch", "--list", f"worktree/{work_id}"))

    def _retry_after_syncing(self, how, strategy):
        work_id = f"sync-{how}-" + strategy.replace("-", "")
        worktree = make_work(self.repo, work_id)
        drift(self.repo, f"drift-{work_id}.txt")
        self.assertEqual(error_code(self.complete(strategy=strategy, work_id=work_id)), "base_changed")
        if how == "merge":
            git(worktree, "merge", "main", "-m", "sync main")
        else:
            git(worktree, "rebase", "main")
        self.assertEqual(git(worktree, "status", "--porcelain"), "")
        branch_tree = git(self.repo, "rev-parse", f"worktree/{work_id}^{{tree}}")
        result = self.complete(strategy=strategy, work_id=work_id)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(self.repo, "rev-parse", "main^{tree}"), branch_tree)
        self.assertTrue((self.repo / "drift.txt").exists() or (self.repo / f"drift-{work_id}.txt").exists())
        self.assertTrue((self.repo / feature_name(work_id)).exists())

    def test_e_f_retry_after_merge_or_rebase_integrates_exact_branch_tree(self):
        for how in ("merge", "rebase"):
            for strategy in STRATEGIES:
                with self.subTest(how=how, strategy=strategy):
                    self._retry_after_syncing(how, strategy)

    def test_g_preserve_dirty_rejects_drift_and_keeps_dirty_state(self):
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                work_id = "dirty-" + strategy.replace("-", "")
                make_work(self.repo, work_id)
                drift(self.repo, f"drift-{work_id}.txt")
                (self.repo / "app.txt").write_text("base\nlocal edit\n")
                (self.repo / f"untracked-{work_id}.txt").write_text("keep me\n")
                before = snapshot(self.repo, work_id)
                result = self.complete("--preserve-dirty", strategy=strategy, work_id=work_id)
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertEqual(error_code(result), "base_changed")
                self.assertEqual(snapshot(self.repo, work_id), before)
                self.assertEqual((self.repo / "app.txt").read_text(), "base\nlocal edit\n")
                self.assertEqual((self.repo / f"untracked-{work_id}.txt").read_text(), "keep me\n")
                git(self.repo, "checkout", "--", "app.txt")
                (self.repo / f"untracked-{work_id}.txt").unlink()

    def test_preserve_dirty_without_drift_keeps_dirty_state_and_exact_tree(self):
        make_work(self.repo, "dirty-ok")
        (self.repo / "app.txt").write_text("base\nlocal edit\n")
        branch_tree = git(self.repo, "rev-parse", "worktree/dirty-ok^{tree}")
        result = self.complete("--preserve-dirty", work_id="dirty-ok")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(self.repo, "rev-parse", "main^{tree}"), branch_tree)
        self.assertEqual((self.repo / "app.txt").read_text(), "base\nlocal edit\n")

    def test_rejected_drift_leaves_no_locks_or_backup_refs(self):
        make_work(self.repo, "clean")
        drift(self.repo)
        locks = self.repo / ".git" / "state" / "locks"
        before_locks = sorted(p.name for p in locks.iterdir()) if locks.is_dir() else []
        self.assertEqual(error_code(self.complete(work_id="clean")), "base_changed")
        self.assertEqual(sorted(p.name for p in locks.iterdir()) if locks.is_dir() else [], before_locks)
        self.assertEqual(git(self.repo, "for-each-ref", "refs/manager"), "")

    def test_base_reset_backwards_still_integrates_exact_branch_tree(self):
        """The base tip is still an ancestor of the branch, so the branch tree lands."""
        (self.repo / "later.txt").write_text("later\n")
        git(self.repo, "add", "later.txt"); git(self.repo, "commit", "-qm", "later")
        make_work(self.repo, "back")
        git(self.repo, "reset", "-q", "--hard", "HEAD~1")
        branch_tree = git(self.repo, "rev-parse", "worktree/back^{tree}")
        result = self.complete(work_id="back")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(self.repo, "rev-parse", "main^{tree}"), branch_tree)

    def test_cherry_picked_drift_is_still_rejected_conservatively(self):
        worktree = make_work(self.repo, "pick")
        commit = drift(self.repo)
        git(worktree, "cherry-pick", commit)
        before = snapshot(self.repo, "pick")
        result = self.complete(work_id="pick")
        self.assertEqual(error_code(result), "base_changed", result.stdout)
        self.assertEqual(snapshot(self.repo, "pick"), before)

    def test_race_between_verification_and_write_fails_instead_of_integrating(self):
        """main moves after the ancestor check but before the write: ff-only must refuse."""
        from worktree_manager.configuration import Configuration
        from worktree_manager.git_repository import GitRepository
        from worktree_manager.models import ManagerError
        from worktree_manager.worktree_lifecycle import WorktreeLifecycle
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                work_id = "race-" + strategy.replace("-", "")
                make_work(self.repo, work_id)
                lifecycle = WorktreeLifecycle(Configuration.load(self.repo))
                original = GitRepository.run
                moved = []
                def racing(instance, args, **kwargs):
                    if tuple(args[:2]) == ("merge", "--ff-only") and not moved:
                        moved.append(drift(self.repo, f"race-{work_id}.txt"))
                    return original(instance, args, **kwargs)
                GitRepository.run = racing
                try:
                    with self.assertRaises(ManagerError) as caught:
                        lifecycle.complete(work_id, "main", merge_strategy=strategy)
                finally:
                    GitRepository.run = original
                self.assertEqual(caught.exception.code, "base_changed")
                self.assertEqual(git(self.repo, "rev-parse", "main"), moved[0])
                self.assertTrue(git(self.repo, "branch", "--list", f"worktree/{work_id}"))
                self.assertEqual(git(self.repo, "status", "--porcelain"), "")
                self.assertFalse((self.repo / feature_name(work_id)).exists())
                tx = sorted((self.repo / ".git" / "state" / "transactions").iterdir())[-1].name
                recovered = cli("--repo", str(self.repo), "recover", tx)
                self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
                self.assertEqual(json.loads(recovered.stdout)["data"]["phase"], "restored")
                git(self.repo, "worktree", "remove", "--force", f".worktrees/{work_id}")
                git(self.repo, "branch", "-D", f"worktree/{work_id}")


class CrashTests(unittest.TestCase):
    """Crash after the ff-only landed and before the journal records it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wt-drift-crash-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(Path(self.tmp.name) / "repo")

    def crash(self, strategy):
        worktree = make_work(self.repo, "crash")
        env = dict(os.environ, WORKTREE_MANAGER_TEST_CRASH_AFTER_GIT="merge --ff-only")
        result = subprocess.run([sys.executable, "-m", "worktree_manager", "--json", "--repo", str(self.repo),
                                 "complete", "crash", "--merge-strategy", strategy],
                                text=True, capture_output=True, env=env)
        self.assertEqual(result.returncode, -9, result.stdout + result.stderr)
        tx = sorted((self.repo / ".git" / "state" / "transactions").iterdir())[-1].name
        return worktree, tx

    def test_crash_after_ff_only_recovers_only_with_exact_tree(self):
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                self.setUp()
                worktree, tx = self.crash(strategy)
                branch_tree = git(self.repo, "rev-parse", "worktree/crash^{tree}")
                self.assertEqual(git(self.repo, "rev-parse", "main^{tree}"), branch_tree)
                self.assertEqual((self.repo / ".git" / "state" / "transactions" / tx / "journal").read_text().strip(), "merge_started")
                recovered = cli("--repo", str(self.repo), "recover", tx)
                self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
                self.assertEqual(json.loads(recovered.stdout)["result"], "no_pending_work")
                self.assertTrue(worktree.exists())

    def test_crash_then_base_moves_is_ambiguous_and_fails_closed(self):
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                self.setUp()
                worktree, tx = self.crash(strategy)
                drift(self.repo, "after-crash.txt")
                recovered = cli("--repo", str(self.repo), "recover", tx)
                self.assertEqual(recovered.returncode, 5, recovered.stdout + recovered.stderr)
                self.assertEqual(error_code(recovered), "intervention_required")
                self.assertTrue(worktree.exists())
                self.assertTrue(git(self.repo, "branch", "--list", "worktree/crash"))

    def test_crash_with_tampered_tree_is_not_reported_as_durable(self):
        """HEAD has the expected parents but a tree that is not the branch tree."""
        self.setUp()
        worktree, tx = self.crash("squash")
        before = git(self.repo, "rev-parse", "HEAD~1")
        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        forged_tree = git(self.repo, "rev-parse", "HEAD~1^{tree}")  # base tree: right parents, wrong tree
        self.assertNotEqual(tree, forged_tree)
        forged = git(self.repo, "commit-tree", forged_tree, "-p", before, "-m", "forged")
        git(self.repo, "update-ref", "refs/heads/main", forged)
        git(self.repo, "reset", "--hard", "-q", "main")
        recovered = cli("--repo", str(self.repo), "recover", tx)
        self.assertEqual(recovered.returncode, 5, recovered.stdout + recovered.stderr)
        self.assertEqual(error_code(recovered), "intervention_required")


class McpBaseDriftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wt-drift-mcp-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(Path(self.tmp.name) / "repo")
        self.client = McpClient()
        self.addCleanup(self.client.close)

    def call(self, name, **arguments):
        return self.client.call(name, {"repo": str(self.repo), **arguments})

    def test_b_drift_before_dry_run_is_reported_by_the_dry_run(self):
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                work_id = "pre-" + strategy.replace("-", "")
                make_work(self.repo, work_id)
                drift(self.repo, f"drift-{work_id}.txt")
                before = snapshot(self.repo, work_id)
                document, is_error = self.call("worktree_complete", work_id=work_id, dry_run=True, merge_strategy=strategy)
                self.assertTrue(is_error, document)
                self.assertEqual((document["error"] or {}).get("code"), "base_changed")
                self.assertEqual(((document["error"] or {}).get("details") or {}).get("current_base"), before["main"])
                self.assertEqual(snapshot(self.repo, work_id), before)

    def test_b_drift_before_execute_without_preflight_is_reported_by_execute(self):
        make_work(self.repo, "pre-exec")
        drift(self.repo)
        before = snapshot(self.repo, "pre-exec")
        document, is_error = self.call("worktree_complete", work_id="pre-exec", confirm=True)
        self.assertTrue(is_error, document)
        self.assertEqual((document["error"] or {}).get("code"), "base_changed")
        self.assertEqual(snapshot(self.repo, "pre-exec"), before)

    def test_c_drift_after_dry_run_still_fails_with_plan_mismatch(self):
        make_work(self.repo, "post")
        plan, is_error = self.call("worktree_complete", work_id="post", dry_run=True)
        self.assertFalse(is_error, plan)
        drift(self.repo)
        before = snapshot(self.repo, "post")
        document, is_error = self.call("worktree_complete", work_id="post", confirm=True,
                                       plan_hash=plan["data"]["plan_hash"], transaction_id=plan["data"]["transaction_id"])
        self.assertTrue(is_error, document)
        self.assertEqual((document["error"] or {}).get("code"), "plan_mismatch")
        self.assertEqual(snapshot(self.repo, "post"), before)

    def test_d_no_drift_dry_run_then_execute_integrates_branch_tree(self):
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                work_id = "mcp-ok-" + strategy.replace("-", "")
                make_work(self.repo, work_id)
                branch_tree = git(self.repo, "rev-parse", f"worktree/{work_id}^{{tree}}")
                plan, is_error = self.call("worktree_complete", work_id=work_id, dry_run=True, merge_strategy=strategy)
                self.assertFalse(is_error, plan)
                done, is_error = self.call("worktree_complete", work_id=work_id, confirm=True, merge_strategy=strategy,
                                           plan_hash=plan["data"]["plan_hash"], transaction_id=plan["data"]["transaction_id"])
                self.assertFalse(is_error, done)
                self.assertEqual(git(self.repo, "rev-parse", "main^{tree}"), branch_tree)

    def test_e_f_mcp_retry_after_syncing_integrates_exact_branch_tree(self):
        for how in ("merge", "rebase"):
            for strategy in STRATEGIES:
                with self.subTest(how=how, strategy=strategy):
                    work_id = f"mcp-{how}-" + strategy.replace("-", "")
                    worktree = make_work(self.repo, work_id)
                    drift(self.repo, f"drift-{work_id}.txt")
                    document, is_error = self.call("worktree_complete", work_id=work_id, dry_run=True, merge_strategy=strategy)
                    self.assertEqual((document["error"] or {}).get("code"), "base_changed")
                    git(worktree, *(("merge", "main", "-m", "sync") if how == "merge" else ("rebase", "main")))
                    branch_tree = git(self.repo, "rev-parse", f"worktree/{work_id}^{{tree}}")
                    plan, is_error = self.call("worktree_complete", work_id=work_id, dry_run=True, merge_strategy=strategy)
                    self.assertFalse(is_error, plan)
                    done, is_error = self.call("worktree_complete", work_id=work_id, confirm=True, merge_strategy=strategy,
                                               plan_hash=plan["data"]["plan_hash"], transaction_id=plan["data"]["transaction_id"])
                    self.assertFalse(is_error, done)
                    self.assertEqual(git(self.repo, "rev-parse", "main^{tree}"), branch_tree)

    def test_g_preserve_dirty_drift_rejected_and_dirty_state_intact(self):
        make_work(self.repo, "mcp-dirty")
        drift(self.repo)
        (self.repo / "app.txt").write_text("base\nlocal edit\n")
        (self.repo / "scratch.txt").write_text("keep\n")
        before = snapshot(self.repo, "mcp-dirty")
        document, is_error = self.call("worktree_complete", work_id="mcp-dirty", confirm=True, preserve_dirty=True)
        self.assertTrue(is_error, document)
        self.assertEqual((document["error"] or {}).get("code"), "base_changed")
        self.assertEqual(snapshot(self.repo, "mcp-dirty"), before)
        self.assertEqual((self.repo / "scratch.txt").read_text(), "keep\n")


if __name__ == "__main__":
    unittest.main()
