import unittest
from worktree_manager.mcp_server import dispatch
import json
import subprocess
import sys

class ServerTests(unittest.TestCase):
    def test_discovery_exactly_seven(self):
        result = dispatch({"method": "tools/list"})
        self.assertEqual(len(result["tools"]), 7)
        self.assertEqual(len({t["name"] for t in result["tools"]}), 7)
    def test_initialize(self):
        """gap_ref: GD-01 (C1).

        criterio: initialize publishes the single-line instruction that orders
        offering an isolated worktree before touching the main branch.
        defecto: a regression to the previous one-line question.
        why_not_detected: the obsolete test asserted the retired literal.
        comportamiento observable: result["instructions"] equals D1 exactly.
        """
        result = dispatch({"method": "initialize", "params": {}})
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "worktree-for-agents")
        self.assertEqual(
            result["instructions"],
            "Before you touch the main branch, offer to create an isolated worktree: create it with worktree_create, do all the work inside it, and close it with worktree_complete to integrate or worktree_cleanup to discard. If the worktree cannot be created or closed, correct the cause named in the error message before retrying.",
        )

    def test_stdio_handshake_and_discovery(self):
        process = subprocess.Popen([sys.executable, "-m", "worktree_manager.mcp_transport"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        output, _ = process.communicate("\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}), ""]))
        messages = [json.loads(line) for line in output.splitlines()]
        self.assertEqual([message["id"] for message in messages], [1, 2])
        self.assertEqual(len(messages[1]["result"]["tools"]), 7)

if __name__ == "__main__": unittest.main()
