"""Packaging, tarball self-containment, independence and network behaviour."""
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent

EXPECTED_FILES = [
    "worktree.sh",
    "worktree_manager/**/*.py",
    "mcp-server.mjs",
    "worktree.mjs",
    "setup.mjs",
    "GUIDE.md",
    "README.md",
    "docs/installation.md",
    "docs/mcp-contract.md",
    "scripts/python.mjs",
    "scripts/postinstall.mjs",
]

RUNTIME_REL_PATHS = (
    [str(p.relative_to(PACKAGE_DIR)) for p in (PACKAGE_DIR / "worktree_manager").glob("*.py")]
    + ["mcp-server.mjs", "worktree.mjs", "scripts/python.mjs", "scripts/postinstall.mjs"]
)

FORBIDDEN_TOKENS = ("flowtask", ".flowtask", "flowtask_worktree_consume")


def run(args, **kwargs):
    kwargs.setdefault("cwd", str(PACKAGE_DIR))
    kwargs.setdefault("text", True)
    return subprocess.run(args, **kwargs)


class NpmPackageTests(unittest.TestCase):
    def test_manifest_fields(self):
        manifest = json.loads((PACKAGE_DIR / "package.json").read_text())
        self.assertEqual(manifest["name"], "worktree-for-agents")
        self.assertEqual(manifest["version"], "1.2.2")
        self.assertNotIn("bin", manifest)
        self.assertNotIn("license", manifest)
        self.assertEqual(manifest.get("type"), "module")
        self.assertEqual(manifest["files"], EXPECTED_FILES)
        self.assertEqual(manifest["publishConfig"]["access"], "public")
        self.assertEqual(manifest["scripts"]["postinstall"], "node scripts/postinstall.mjs")
        self.assertEqual(manifest["scripts"]["prepublishOnly"], "node scripts/verify-package.mjs")

    def test_verify_package_passes(self):
        result = run(["node", "scripts/verify-package.mjs"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("package verification passed", result.stdout)

    def test_pack_lists_expected_files_and_excludes_rest(self):
        result = run(["npm", "pack", "--dry-run", "--json"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = json.loads(result.stdout)
        self.assertTrue(entries)
        packed = {item["path"] for item in entries[0]["files"]}
        for required in ("package.json", "mcp-server.mjs", "worktree.mjs", "setup.mjs",
                         "GUIDE.md", "README.md", "worktree.sh",
                         "docs/installation.md", "docs/mcp-contract.md",
                         "scripts/python.mjs", "scripts/postinstall.mjs"):
            self.assertIn(required, packed)
        self.assertTrue(any(p.startswith("worktree_manager/") and p.endswith(".py") for p in packed))
        for prefix in ("tests/", "traces/", ".git/", "node_modules/"):
            self.assertFalse(any(p.startswith(prefix) or f"/{prefix}" in f"/{p}" for p in packed), prefix)
        self.assertFalse(any("__pycache__" in p for p in packed))
        self.assertFalse(any("verify-package" in p for p in packed))

    def test_extracted_tarball_handshake_lists_seven_tools(self):
        with tempfile.TemporaryDirectory() as d:
            pack = run(["npm", "pack", "--pack-destination", d], capture_output=True)
            self.assertEqual(pack.returncode, 0, pack.stderr)
            tarballs = list(Path(d).glob("*.tgz"))
            self.assertEqual(len(tarballs), 1)
            with tarfile.open(tarballs[0]) as tf:
                tf.extractall(d)
            extracted = Path(d) / "package"
            proc = subprocess.Popen(
                ["node", str(extracted / "mcp-server.mjs")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                cwd=str(extracted),
            )
            stdin_text = "\n".join([
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            ]) + "\n"
            stdout, stderr = proc.communicate(stdin_text, timeout=30)
            self.assertEqual(proc.returncode, 0, stderr)
            lines = [line for line in stdout.splitlines() if line.strip()]
            tools = json.loads(lines[1])["result"]["tools"]
            self.assertEqual(len(tools), 7)

    def test_worktree_list_with_empty_home_and_no_flowtask_paths(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as home:
            repo = Path(d) / "demo"
            repo.mkdir()
            run(["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True)
            run(["git", "-C", str(repo), "config", "user.name", "test"], check=True)
            run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            (repo / ".gitignore").write_text(".worktrees/\n")
            (repo / "file").write_text("base\n")
            run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
            run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, capture_output=True)
            env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=str(Path(home) / ".config"))
            env.pop("FLOWTASK_HOME", None)
            result = subprocess.run(
                ["node", str(PACKAGE_DIR / "worktree.mjs"), "--repo", str(repo), "--json", "list"],
                text=True, capture_output=True, cwd=str(PACKAGE_DIR), env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(result.stdout)
            self.assertEqual(document["operation"], "list")
            self.assertEqual(document["result"], "success")

    def test_offline_install_from_local_tarball(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as prefix:
            pack = run(["npm", "pack", "--pack-destination", d], capture_output=True)
            self.assertEqual(pack.returncode, 0, pack.stderr)
            tarball = str(next(Path(d).glob("*.tgz")))
            install = run(
                ["npm", "install", "-g", "--prefix", prefix, "--offline", tarball],
                capture_output=True,
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            launcher = Path(prefix) / "lib" / "node_modules" / "worktree-for-agents" / "mcp-server.mjs"
            self.assertTrue(launcher.exists())
            proc = subprocess.Popen(
                ["node", str(launcher)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            stdin_text = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
            stdout, stderr = proc.communicate(stdin_text, timeout=30)
            proc.stdin.close() if not proc.stdin.closed else None
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise
            tools = json.loads(stdout.splitlines()[0])["result"]["tools"]
            self.assertEqual(len(tools), 7)

    def test_registry_unreachable_fails_visibly(self):
        with tempfile.TemporaryDirectory() as prefix:
            result = run(
                ["npm", "install", "--prefix", prefix,
                 "--registry", "http://127.0.0.1:9",
                 "--fetch-retries=0", "--fetch-timeout=1000",
                 "worktree-for-agents@latest"],
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(prefix) / "node_modules" / "worktree-for-agents").exists())

    def test_runtime_has_no_flowtask_reference(self):
        for rel in RUNTIME_REL_PATHS:
            source = (PACKAGE_DIR / rel).read_text().lower()
            for token in FORBIDDEN_TOKENS:
                self.assertNotIn(token, source, f"{rel} mentions {token}")


if __name__ == "__main__":
    unittest.main()
