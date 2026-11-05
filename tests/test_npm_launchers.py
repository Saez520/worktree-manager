"""Launchers MCP/CLI without bin: handshake, errors and stdout hygiene."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
MCP_SERVER = PACKAGE_DIR / "mcp-server.mjs"
CLI = PACKAGE_DIR / "worktree.mjs"
GUIDE_LITERAL = "Before you touch the main branch, offer to create an isolated worktree: create it with worktree_create, do all the work inside it, and close it with worktree_complete to integrate or worktree_cleanup to discard. If the worktree cannot be created or closed, correct the cause named in the error message before retrying."


def run_node(script, args=(), stdin_lines=(), env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.Popen(
        ["node", str(script), *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(PACKAGE_DIR),
        env=env,
    )
    stdin_text = "".join(line + "\n" for line in stdin_lines)
    try:
        stdout, stderr = proc.communicate(stdin_text, timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    return proc.returncode, stdout, stderr


class NpmLauncherTests(unittest.TestCase):
    def test_mcp_handshake_lists_seven_tools(self):
        """gap_ref: GD-05 (C1 launcher).

        criterio: the npm launcher publishes D1 in the initialize handshake.
        defecto: the launcher keeps the retired instruction while the source
        module publishes the new one.
        why_not_detected: GUIDE_LITERAL fixed the retired instruction.
        comportamiento observable: the first response's instructions equals D1.
        """
        code, stdout, stderr = run_node(
            MCP_SERVER,
            stdin_lines=[
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            ],
        )
        self.assertEqual(code, 0, stderr)
        lines = [line for line in stdout.splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first["id"], 1)
        self.assertEqual(first["result"]["serverInfo"]["name"], "worktree-for-agents")
        self.assertEqual(first["result"]["instructions"], GUIDE_LITERAL)
        second = json.loads(lines[1])
        self.assertEqual(second["id"], 2)
        self.assertEqual(len(second["result"]["tools"]), 7)

    def test_cli_version(self):
        result = subprocess.run(
            ["node", str(CLI), "--version"], text=True, capture_output=True, cwd=str(PACKAGE_DIR)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1.2.1")

    def test_no_python_exits_127(self):
        code, stdout, stderr = run_node(
            MCP_SERVER,
            stdin_lines=[],
            env_extra={"WORKTREE_MANAGER_PYTHON": "/nonexistent/python-for-test-127"},
        )
        self.assertEqual(code, 127)
        self.assertEqual(stdout, "")
        self.assertIn("Python 3.9", stderr)

    def test_incomplete_package_exits_126(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d)
            (dest / "scripts").mkdir()
            shutil.copy(MCP_SERVER, dest / "mcp-server.mjs")
            shutil.copy(PACKAGE_DIR / "scripts" / "python.mjs", dest / "scripts" / "python.mjs")
            proc = subprocess.run(
                ["node", str(dest / "mcp-server.mjs")],
                text=True,
                capture_output=True,
                cwd=str(dest),
            )
            self.assertEqual(proc.returncode, 126)
            self.assertIn("worktree_manager/mcp_transport.py", proc.stderr)

    def test_stdout_first_line_is_jsonrpc(self):
        code, stdout, stderr = run_node(
            MCP_SERVER,
            stdin_lines=[json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})],
        )
        self.assertEqual(code, 0, stderr)
        first = stdout.splitlines()[0]
        document = json.loads(first)
        self.assertEqual(document["jsonrpc"], "2.0")
        self.assertEqual(document["id"], 1)
        self.assertEqual(stderr, "")


if __name__ == "__main__":
    unittest.main()
