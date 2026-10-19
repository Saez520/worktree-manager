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
