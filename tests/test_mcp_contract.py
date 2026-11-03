import unittest
from worktree_manager.mcp_contract import TOOL_NAMES, validate_request
from worktree_manager.mcp_server import schemas

class ContractTests(unittest.TestCase):
    def test_exact_seven_tools_and_strict_fields(self):
        self.assertEqual(len(TOOL_NAMES), 7)
        with self.assertRaises(ValueError): validate_request("worktree_list", {"repo": "/tmp", "extra": True})
    def test_repo_must_be_absolute(self):
        with self.assertRaises(ValueError): validate_request("worktree_list", {"repo": "relative"})
    def test_tool_schemas_publish_required_inputs_and_output(self):
        by_name={item["name"]:item for item in schemas()}
        self.assertEqual(set(by_name),set(TOOL_NAMES))
        for name,item in by_name.items():
            self.assertEqual(set(item["inputSchema"]["required"]), {"repo", "work_id"} if name in {"worktree_create","worktree_complete","worktree_cleanup","worktree_status"} else {"repo"})
            self.assertIn("contract_version",item["outputSchema"]["required"])
    def test_missing_work_id_rejected_before_operation(self):
        with self.assertRaisesRegex(ValueError,"work_id"):
            validate_request("worktree_create", {"repo":"/tmp"})

if __name__ == "__main__": unittest.main()


class CommitFieldsContractTests(unittest.TestCase):
    def test_complete_accepts_commit_title_and_body(self):
        validated = validate_request("worktree_complete", {"repo": "/tmp", "work_id": "x", "commit_title": "T", "commit_body": "B"})
        self.assertEqual(validated["commit_title"], "T")
        self.assertEqual(validated["commit_body"], "B")

    def test_create_rejects_commit_fields(self):
        with self.assertRaises(ValueError):
            validate_request("worktree_create", {"repo": "/tmp", "work_id": "x", "commit_title": "T"})

    def test_commit_fields_must_be_strings(self):
        with self.assertRaises(ValueError):
            validate_request("worktree_complete", {"repo": "/tmp", "work_id": "x", "commit_title": 1})
