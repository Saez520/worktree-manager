"""Small real-stdio MCP client used by end-to-end contract tests."""
import json
import subprocess
import sys


class McpClient:
    def __init__(self):
        self.process = subprocess.Popen(
            [sys.executable, "-m", "worktree_manager.mcp_transport"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        self.sequence = 0
        self.request("initialize", {"protocolVersion": "2024-11-05"})

    def request(self, method, params=None):
        self.sequence += 1
        request_id = self.sequence
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id,
                                             "method": method, "params": params or {}}) + "\n")
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        if response.get("id") != request_id or "error" in response:
            raise AssertionError(f"invalid MCP response: {response!r}")
        return response["result"]

    def call(self, name, arguments):
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        return response["structuredContent"], response["isError"]

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)
        if self.process.returncode:
            raise AssertionError(self.process.stderr.read())
        self.process.stdout.close()
        self.process.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
