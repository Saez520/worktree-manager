"""Real Git/MCP/CLI end-to-end behavior matrix; no backend mocks."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from mcp_client import McpClient


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          text=True, capture_output=True).stdout.strip()


def fixture(repo):
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "config", "user.name", "E2E")
    git(repo, "config", "user.email", "e2e@example.invalid")
    (repo / "base.txt").write_text("base\n")
    (repo / ".gitignore").write_text(".worktrees/\nstate/\nbackups/\nlocks/\n")
    (repo / ".worktree-manager.conf").write_text(
        "state_dir=state\nbackup_dir=backups\nbackup_ref_prefix=manager/backups\n"
        "branch_prefix=worktree/\nlock_dir=locks\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")


def state(repo):
    return {
        "head": git(repo, "rev-parse", "HEAD"),
        "index": git(repo, "ls-files", "--stage"),
        "status": git(repo, "status", "--porcelain=v2", "--untracked-files=all"),
        "refs": git(repo, "for-each-ref", "--format=%(refname) %(objectname)"),
        "worktrees": git(repo, "worktree", "list", "--porcelain"),
        "state_files": sorted(str(p.relative_to(repo / ".git")) for p in
                               (repo / ".git").rglob("*") if p.is_file() and
                               ("state" in p.parts or "locks" in p.parts)),
    }


class McpE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="worktree-mcp-e2e-")
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        fixture(self.repo)
        self.client = McpClient()
        self.addCleanup(self.client.close)
        self.addCleanup(self.tmp.cleanup)
        self.evidence = []

    def call(self, tool, **args):
        before = state(self.repo)
        result, is_error = self.client.call(tool, {"repo": str(self.repo), **args})
        self.evidence.append({"tool": tool, "request": args, "response": result,
                              "isError": is_error, "git_before": before,
                              "git_after": state(self.repo)})
        return result, is_error

    def tearDown(self):
        evidence_dir = os.environ.get("MCP_E2E_EVIDENCE_DIR")
        if evidence_dir:
            dest = Path(evidence_dir); dest.mkdir(parents=True, exist_ok=True)
            (dest / f"{self.id().split('.')[-1]}.json").write_text(
                json.dumps(self.evidence, indent=2, sort_keys=True) + "\n")

    def test_all_seven_tools_real_backend_and_error_envelopes(self):
        listing = self.client.request("tools/list")["tools"]
        self.assertEqual({t["name"] for t in listing}, {
            "worktree_create", "worktree_complete", "worktree_cleanup", "worktree_recover",
            "worktree_list", "worktree_prune", "worktree_status"})
        for tool in listing:
            self.assertIn("outputSchema", tool)
            self.assertIn("required", tool["inputSchema"])

        before = state(self.repo)
        simulated, error = self.call("worktree_create", work_id="dry", dry_run=True)
        self.assertFalse(error); self.assertEqual(state(self.repo), before)
        self.assertEqual(simulated["data"]["preflight"], "passed")

        created, error = self.call("worktree_create", work_id="mcp-e2e", base="main")
        self.assertFalse(error); self.assertEqual(created["result"], "success")
        self.assertTrue((self.repo / ".worktrees/mcp-e2e").is_dir())
        listed, error = self.call("worktree_list")
        self.assertFalse(error); self.assertIn("mcp-e2e", json.dumps(listed["data"]))
        status, error = self.call("worktree_status", work_id="mcp-e2e")
        self.assertFalse(error, status); self.assertTrue(status["data"]["identity_exists"])

        # Cleanup is non-destructive without authorization and discard requires
        # a separate per-call consent, even when authorization is present.
        denied, error = self.call("worktree_cleanup", work_id="mcp-e2e")
        self.assertTrue(error); self.assertEqual(denied["error"]["code"], "authorization_required")
        (self.repo / ".worktrees/mcp-e2e/dirty.txt").write_text("keep\n")
        denied, error = self.call("worktree_cleanup", work_id="mcp-e2e",
                                  authorization="I_AUTHORIZE_THIS_CALL", discard=True)
        self.assertTrue(error); self.assertEqual(denied["error"]["code"], "discard_consent_required")
        cleaned, error = self.call("worktree_cleanup", work_id="mcp-e2e",
                                   authorization="I_AUTHORIZE_THIS_CALL", discard=True,
                                   discard_consent=True)
        self.assertFalse(error); self.assertEqual(cleaned["result"], "success")
        self.assertFalse((self.repo / ".worktrees/mcp-e2e").exists())

        recovered, error = self.call("worktree_recover", authorization="I_AUTHORIZE_THIS_CALL")
        self.assertFalse(error); self.assertIn(recovered["result"], {"success", "no_pending_work"})
        pruned, error = self.call("worktree_prune", authorization="I_AUTHORIZE_THIS_CALL")
        self.assertFalse(error); self.assertIn(pruned["result"], {"success", "no_pending_work"})

    def test_complete_and_prune_cli_equivalence_on_independent_repositories(self):
        mcp_repo = self.repo
        cli_repo = self.root / "cli"
        fixture(cli_repo)
        self.call("worktree_create", work_id="feature", base="main")
        subprocess.run([os.sys.executable, "-m", "worktree_manager", "--repo", str(cli_repo),
                        "create", "feature", "--base", "main"], check=True,
                       capture_output=True, text=True)
        for repo in (mcp_repo, cli_repo):
            wt = repo / ".worktrees/feature"
            (wt / "feature.txt").write_text("feature\n")
            git(wt, "add", "feature.txt")
            git(wt, "commit", "-qm", "feature")
        mcp_result, error = self.call("worktree_complete", work_id="feature", base="main",
                                      authorization="I_AUTHORIZE_THIS_CALL")
        self.assertFalse(error)
        cli = subprocess.run([os.sys.executable, "-m", "worktree_manager", "--repo", str(cli_repo),
                              "--json", "complete", "feature", "--base", "main"],
                             check=True, capture_output=True, text=True)
        cli_result = json.loads(cli.stdout)
        self.assertEqual(mcp_result["result"], cli_result["result"])
        self.assertEqual(git(mcp_repo, "show", "main:feature.txt"),
                         git(cli_repo, "show", "main:feature.txt"))
        self.assertFalse((mcp_repo / ".worktrees/feature").exists())
        self.assertFalse((cli_repo / ".worktrees/feature").exists())

    def test_prune_dry_run_reports_no_work_without_mutation(self):
        before = state(self.repo)
        result, error = self.call("worktree_prune", dry_run=True)
        self.assertFalse(error, result)
        self.assertEqual(result["result"], "no_pending_work")
        self.assertFalse(result["data"]["planned"])
        self.assertEqual(result["data"]["preflight"], "no_pending_work")
        self.assertEqual(result["data"]["mutations"], [])
        self.assertEqual(state(self.repo), before)

    def test_prune_dry_run_detects_stale_worktree_without_mutation(self):
        orphan = self.root / "orphan"
        git(self.repo, "worktree", "add", "--detach", str(orphan), "HEAD")
        import shutil
        shutil.rmtree(orphan)
        before = state(self.repo)
        result, error = self.call("worktree_prune", dry_run=True)
        self.assertFalse(error, result)
        self.assertEqual(result["result"], "success")
        self.assertTrue(result["data"]["planned"])
        self.assertEqual(result["data"]["preflight"], "passed")
        self.assertTrue(result["data"]["eligible_orphans"])
        self.assertEqual(result["data"]["mutations"], ["git_worktree_prune"])
        self.assertEqual(state(self.repo), before)

    def test_target_direct_recovery_through_mcp_is_blocked_then_idempotent(self):
        parent = self.root / "parent"
        target = self.root / "target"
        fixture(target)
        fixture(parent)
        subprocess.run(["git", "-C", str(parent), "-c", "protocol.file.allow=always",
                        "submodule", "add", "-q", str(target), "modules/target"], check=True)
        git(parent, "commit", "-qam", "add target submodule")
        target = parent / "modules/target"
        before_index = git(parent, "ls-files", "--stage")
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]),
                   WORKTREE_MANAGER_TEST_CRASH_AFTER_DESCRIPTOR_PHASE="staged_started")
        cli = [os.sys.executable, "-m", "worktree_manager", "--repo", str(target), "target-direct"]
        subprocess.run(cli + ["create", "mcp-target", "--parent-repo", str(parent),
                              "--submodule-path", "modules/target"], check=True,
                       capture_output=True, text=True)
        crashed = subprocess.run(cli + ["link-parent", "mcp-target", "--parent-repo", str(parent)],
                                 env=env, capture_output=True, text=True)
        self.assertIn(crashed.returncode, {137, -9})
        descriptor = next((target / ".git").rglob("descriptor"), None)
        if descriptor is None:
            common = Path(git(target, "rev-parse", "--git-common-dir"))
            if not common.is_absolute(): common = target / common
            descriptor = next(common.rglob("descriptor"))
        self.assertIn("phase=staged_started\n", descriptor.read_text())
        snapshot = descriptor.parent / "snapshot"
        saved = (snapshot / "index.bytes").read_bytes()
        self.assertEqual(git(parent, "ls-files", "--stage"), before_index)
        first, error = self.client.call("worktree_recover", {
            "repo": str(target), "transaction_id": "wt-mcp-target", "target_direct": True,
            "parent_repo": str(parent), "authorization": "I_AUTHORIZE_THIS_CALL"})
        self.assertTrue(error)
        self.assertEqual(first["error"]["code"], "intervention_required")
        self.assertEqual(git(parent, "ls-files", "--stage"), before_index)
        self.assertEqual((snapshot / "index.bytes").read_bytes(), saved)
        self.assertIn("phase=blocked\n", descriptor.read_text())
        after_block = descriptor.read_bytes()
        second, error = self.client.call("worktree_recover", {
            "repo": str(target), "transaction_id": "wt-mcp-target", "target_direct": True,
            "parent_repo": str(parent), "authorization": "I_AUTHORIZE_THIS_CALL"})
        self.assertFalse(error, second)
        self.assertEqual(second["data"]["phase"], "blocked")
        self.assertEqual(descriptor.read_bytes(), after_block)
        self.assertEqual(git(parent, "ls-files", "--stage"), before_index)

    def test_target_direct_complete_through_mcp(self):
        parent = self.root / "parent-complete"
        target = self.root / "target-complete"
        fixture(target)
        fixture(parent)
        subprocess.run(["git", "-C", str(parent), "-c", "protocol.file.allow=always",
                        "submodule", "add", "-q", str(target), "modules/target"], check=True)
        git(parent, "commit", "-qam", "add target submodule")
        target = parent / "modules/target"
        before_head = git(parent, "rev-parse", "HEAD")
        before_index = git(parent, "ls-files", "--stage")

        created, error = self.client.call("worktree_create", {
            "repo": str(target), "work_id": "complete-target",
            "parent_repo": str(parent), "submodule_path": "modules/target", "base": "main"})
        self.assertFalse(error, created)
        descriptor = Path(created["data"]["descriptor"])
        worktree = Path(created["data"]["worktree"])
        self.assertEqual(created["data"]["phase"], "ready")
        (worktree / "target-change.txt").write_text("target commit\n")
        git(worktree, "add", "target-change.txt")
        git(worktree, "commit", "-qm", "target change")

        # The existing CLI performs the staged-only parent-link prerequisite;
        # the completion being verified is invoked over the real MCP client.
        subprocess.run([os.sys.executable, "-m", "worktree_manager", "--repo", str(target),
                        "target-direct", "link-parent", "complete-target",
                        "--parent-repo", str(parent), "--submodule-path", "modules/target"],
                       check=True, capture_output=True, text=True)
        staged_index = git(parent, "ls-files", "--stage")
        self.assertNotEqual(staged_index, before_index)
        result, error = self.client.call("worktree_complete", {
            "repo": str(target), "work_id": "complete-target", "target_direct": True,
            "parent_repo": str(parent), "authorization": "I_AUTHORIZE_THIS_CALL"})
        self.assertFalse(error, result)
        self.assertEqual(result["data"]["completed"], True)
        self.assertEqual(git(parent, "rev-parse", "HEAD"), before_head)
        self.assertEqual(git(parent, "ls-files", "--stage"), staged_index)
        self.assertFalse(worktree.exists())
        self.assertEqual(descriptor.read_text().split("phase=")[1].splitlines()[0], "closed")

if __name__ == "__main__":
    unittest.main()
