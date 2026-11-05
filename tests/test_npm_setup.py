"""setup.mjs diagnostics and opt-in OpenCode registration."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
SETUP = PACKAGE_DIR / "setup.mjs"
RETIRED_MARKERS = ("flow" + "task", "flow" + "task_worktree_consume")


def run_setup(args=(), env_extra=None, cwd=PACKAGE_DIR):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["node", str(SETUP), *args], text=True, capture_output=True, cwd=str(cwd), env=env
    )


class NpmSetupTests(unittest.TestCase):
    def test_diagnose_reports_active_without_writing(self):
        result = run_setup(())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("worktree-for-agents 1.2.1", result.stdout)
        self.assertIn("npm package", result.stdout)
        self.assertIn("active", result.stdout)
        self.assertIn("opencode config", result.stdout)

    def test_json_reports_structure(self):
        result = run_setup(("--json",))
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        self.assertEqual(status["version"], "1.2.1")
        self.assertTrue(any(i["kind"] == "npm package" and i["active"] for i in status["installations"]))

    def test_diagnose_reports_only_npm_package(self):
        """gap_ref: GD-03 (C5).

        criterio: the diagnostic reports the active npm package, both
        environments, and no retired consumer copy or path.
        defecto: a diagnostic that still reports a global copy or a submodule.
        why_not_detected: the obsolete test asserted coexistence with them.
        comportamiento observable: exactly one installation, kind "npm package";
        keys opencode and claude; and no retired marker in either output.
        """
        with tempfile.TemporaryDirectory() as home:
            retired = Path(home) / ".config" / ("flow" + "task") / "worktree-manager" / "worktree_manager"
            retired.mkdir(parents=True)
            (retired / "__main__.py").write_text("# stub\n")
            (retired / "mcp_transport.py").write_text("# stub\n")
            project = Path(home) / "project"
            project.mkdir()
            env = {"HOME": home, "XDG_CONFIG_HOME": str(Path(home) / ".config")}

            document = run_setup(("--json",), env_extra=env, cwd=project)
            self.assertEqual(document.returncode, 0, document.stderr)
            status = json.loads(document.stdout)
            self.assertEqual([item["kind"] for item in status["installations"]], ["npm package"])
            self.assertTrue(status["installations"][0]["active"])
            self.assertEqual(status["active"], "npm package")
            self.assertEqual(set(status["environments"]), {"opencode", "claude"})
            self.assertEqual(status["launch"], ["node", str(PACKAGE_DIR / "mcp-server.mjs")])
            for environment in status["environments"].values():
                self.assertIn("refsThisPackage", environment)

            human = run_setup((), env_extra=env, cwd=project)
            self.assertEqual(human.returncode, 0, human.stderr)
            self.assertIn("npm package", human.stdout)
            self.assertIn("opencode config", human.stdout)
            self.assertIn("claude code config", human.stdout)

            output = (document.stdout + human.stdout).lower()
            for marker in RETIRED_MARKERS:
                self.assertNotIn(marker, output)

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
