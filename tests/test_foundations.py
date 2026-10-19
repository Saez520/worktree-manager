import tempfile
import unittest
from pathlib import Path

from worktree_manager.configuration import Configuration
from worktree_manager.git_repository import GitRepository
from worktree_manager.models import ManagerError, OperationResult, ResultKind


class FoundationTests(unittest.TestCase):
    def test_json_result_has_contract_v1_envelope(self):
        result = OperationResult("list", ResultKind.NO_PENDING_WORK)
        document = result.json_document()
        self.assertEqual(document["contract_version"], 1)
        self.assertEqual(document["result"], "no_pending_work")
        self.assertNotIn("output", document["data"])

    def test_rejects_relative_repository_root(self):
        with self.assertRaises(ManagerError):
            Configuration.load(".")

    def test_git_repository_reads_identity_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            import subprocess
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c",
                            "user.email=test@example.invalid", "commit", "--allow-empty",
                            "-m", "initial"], check=True)
            repository = GitRepository(root)
            self.assertEqual(len(repository.head()), 40)
            self.assertIn("# branch.oid", repository.status())


if __name__ == "__main__":
    unittest.main()
