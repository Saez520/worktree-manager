import tempfile
import unittest
from pathlib import Path
from worktree_manager.mcp_operations import call

class McpGuardTests(unittest.TestCase):
    def test_relative_repository_is_rejected_before_backend(self):
        with self.assertRaises(ValueError): call("worktree_list", {"repo": "relative"})

    def test_mutation_requires_per_call_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            import subprocess
            subprocess.run(["git", "init", "-q", directory], check=True)
            with self.assertRaises(Exception) as raised:
                call("worktree_prune", {"repo": str(Path(directory)), "dry_run": False})
            self.assertIn("authorization", str(raised.exception).lower())

if __name__ == "__main__": unittest.main()
