"""setup.mjs diagnostics, coexistence and opt-in OpenCode registration."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
SETUP = PACKAGE_DIR / "setup.mjs"


def run_setup(args=(), env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["node", str(SETUP), *args], text=True, capture_output=True, cwd=str(PACKAGE_DIR), env=env
    )


class NpmSetupTests(unittest.TestCase):
    def test_diagnose_reports_active_without_writing(self):
        result = run_setup(())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("worktree-for-agents 1.0.0", result.stdout)
        self.assertIn("npm package", result.stdout)
        self.assertIn("active", result.stdout)
        self.assertIn("opencode config", result.stdout)

    def test_json_reports_structure(self):
        result = run_setup(("--json",))
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        self.assertEqual(status["version"], "1.0.0")
        self.assertTrue(any(i["kind"] == "npm package" and i["active"] for i in status["installations"]))

    def test_coexistence_with_global_copy(self):
        with tempfile.TemporaryDirectory() as home:
            manager = Path(home) / ".config" / "flowtask" / "worktree-manager" / "worktree_manager"
            manager.mkdir(parents=True)
            (manager / "__main__.py").write_text("# stub\n")
            (manager / "mcp_transport.py").write_text("# stub\n")
            env = {"HOME": home, "XDG_CONFIG_HOME": str(Path(home) / ".config")}
            result = run_setup(("--json",), env_extra=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            status = json.loads(result.stdout)
            kinds = {i["kind"]: i for i in status["installations"]}
            self.assertTrue(kinds["FlowTask global copy"]["present"])
            self.assertTrue(kinds["npm package"]["active"])

    def test_write_opencode_is_idempotent(self):
        with tempfile.TemporaryDirectory() as home:
            config_dir = Path(home) / ".config" / "opencode"
            config_dir.mkdir(parents=True)
            config_path = config_dir / "opencode.json"
            config_path.write_text("{}\n")
            env = {"XDG_CONFIG_HOME": str(Path(home) / ".config")}
            first = run_setup(("--write-opencode",), env_extra=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            after_first = config_path.read_bytes()
            parsed = json.loads(after_first.decode())
            entry = parsed["mcp"]["worktree-for-agents"]
            self.assertEqual(entry["type"], "local")
            self.assertEqual(entry["command"][0], "node")
            self.assertTrue(entry["command"][1].endswith("mcp-server.mjs"))
            second = run_setup(("--write-opencode",), env_extra=env)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("already configured", second.stdout)
            self.assertEqual(config_path.read_bytes(), after_first)

    def test_conflicting_entry_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as home:
            config_dir = Path(home) / ".config" / "opencode"
            config_dir.mkdir(parents=True)
            config_path = config_dir / "opencode.json"
            config_path.write_text(
                json.dumps({"mcp": {"worktree-for-agents": {"type": "local", "command": ["node", "/otro/mcp.js"], "enabled": True}}})
            )
            before = config_path.read_bytes()
            env = {"XDG_CONFIG_HOME": str(Path(home) / ".config")}
            result = run_setup(("--write-opencode",), env_extra=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Refusing to overwrite", result.stderr)
            self.assertEqual(config_path.read_bytes(), before)

    def test_missing_config_dir_fails_without_creating(self):
        with tempfile.TemporaryDirectory() as parent:
            missing = Path(parent) / "gone" / ".config"
            env = {"XDG_CONFIG_HOME": str(missing)}
            result = run_setup(("--write-opencode",), env_extra=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("does not exist", result.stderr)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
