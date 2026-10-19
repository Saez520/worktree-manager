"""Additional smoke contracts for the compatibility entry point."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / "worktree.sh"


class ShimCompatibilityTests(unittest.TestCase):
    def _git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _target_direct_fixture(self, root, name):
        target, parent = root / name / "target", root / name / "parent"
        target.mkdir(parents=True)
        parent.mkdir()
        for repo in (target, parent):
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Test")
            self._git(repo, "config", "user.email", "test@example.invalid")
            (repo / "base").write_text("base\n")
            self._git(repo, "add", "base")
            self._git(repo, "commit", "-qm", "base")
        return target, parent

    def test_target_direct_link_parent_and_abort_match_cli(self):
        # Exercise the public shim for both target-direct operations and compare
        # every observable channel/status plus resulting parent/index state.
        for action in ("link-parent", "abort"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for backend in ("shim", "direct"):
                    target, parent = self._target_direct_fixture(root, backend)
                    env = dict(os.environ, PYTHONPATH=str(ROOT))
                    prefix = [str(SHIM)] if backend == "shim" else ["python3", "-m", "worktree_manager"]
                    common = ["--repo", str(target), "target-direct"]
                    create = subprocess.run(prefix + common + ["create", "sample", "--parent-repo", str(parent), "--submodule-path", "module"], cwd=root, env=env, capture_output=True)
                    self.assertEqual(create.returncode, 0, create.stderr.decode())
                    if action == "abort":
                        staged = subprocess.run(prefix + common + ["link-parent", "sample", "--parent-repo", str(parent)], cwd=root, env=env, capture_output=True)
                        self.assertEqual(staged.returncode, 0, staged.stderr.decode())
                    linked = subprocess.run(prefix + common + [action, "sample", "--parent-repo", str(parent)], cwd=root, env=env, capture_output=True)
                    self.assertEqual(linked.returncode, 0 if action == "link-parent" else 6, linked.stderr.decode())
                    state = (self._git(parent, "ls-files", "--stage").stdout,
                             self._git(parent, "status", "--porcelain").stdout,
                             (target / ".git" / "worktree-manager" / "target-direct").exists())
                    normalized = lambda value: value.replace(str(root / backend).encode(), b"/FIXTURE")
                    observed = (linked.returncode, normalized(linked.stdout), normalized(linked.stderr), state)
                    if backend == "shim":
                        shim_observed = observed
                    else:
                        self.assertEqual(observed, shim_observed)

    def test_invalid_option_matches_python_cli_without_state(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo with spaces"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            direct_env = dict(os.environ, PYTHONPATH=str(ROOT))
            direct = subprocess.run(
                ["python3", "-m", "worktree_manager", "--repo", str(repo), "--not-an-option", "list"],
                cwd=directory, env=direct_env, capture_output=True,
            )
            shim = subprocess.run(
                [str(SHIM), "--repo", str(repo), "--not-an-option", "list"],
                cwd=directory, capture_output=True,
            )
            self.assertEqual(shim.returncode, direct.returncode)
            self.assertEqual(shim.stdout, direct.stdout)
            self.assertEqual(shim.stderr, direct.stderr)
            self.assertFalse((repo / ".git" / "worktree-manager").exists())

    def test_json_is_a_single_v1_document(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = subprocess.run(
                [str(SHIM), "--repo", str(repo), "--json", "list"],
                cwd=directory, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["contract_version"], 1)
            self.assertEqual(payload["operation"], "list")
            self.assertEqual(result.stdout.count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
