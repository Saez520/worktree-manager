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
        self.assertIn("tools", dispatch({"method": "initialize", "params": {}})["capabilities"])

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
