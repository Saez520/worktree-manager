import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const packageDir = dirname(here);

function argValue(name) {
  const args = process.argv.slice(2);
  const index = args.indexOf(name);
  if (index !== -1 && index + 1 < args.length) {
    return args[index + 1];
  }
  const prefixed = args.find((a) => a.startsWith(`${name}=`));
  if (prefixed) {
    return prefixed.slice(name.length + 1);
  }
  return null;
}

const packagePath = argValue("--package") || join(packageDir, "package.json");

function fail(message) {
  process.stderr.write(`package verification failed: ${message}\n`);
  process.exit(1);
}

if (!existsSync(packagePath)) {
  fail(`manifest not found: ${packagePath}`);
}
let manifest;
try {
  manifest = JSON.parse(readFileSync(packagePath, "utf8"));
} catch (err) {
  fail(`manifest is not valid JSON: ${String(err)}`);
}

const manifestDir = dirname(packagePath);
const readLocal = (rel) => readFileSync(join(packageDir, rel), "utf8");

if (manifest.name !== "worktree-for-agents") {
  fail(`manifest name is ${JSON.stringify(manifest.name)}, expected "worktree-for-agents"`);
}

let initSource;
try {
  initSource = readLocal(join("worktree_manager", "__init__.py"));
} catch {
  fail("cannot read worktree_manager/__init__.py");
}
const versionMatch = /__version__\s*=\s*['"]([^'"]+)['"]/.exec(initSource);
if (!versionMatch) {
  fail("__version__ not found in worktree_manager/__init__.py");
}
const runtimeVersion = versionMatch[1];
if (manifest.version !== runtimeVersion) {
  fail(`manifest version ${manifest.version} differs from __version__ ${runtimeVersion}`);
}
if (manifest.version !== "1.0.0") {
  fail(`version is ${manifest.version}, expected 1.0.0`);
}

if (manifest.bin !== undefined) {
  fail("manifest must not declare bin");
}
if (manifest.dependencies && Object.keys(manifest.dependencies).length > 0) {
  fail("manifest must not declare dependencies");
}

const expectedFiles = [
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
];
const actualFiles = manifest.files;
if (!Array.isArray(actualFiles) || JSON.stringify(actualFiles) !== JSON.stringify(expectedFiles)) {
  fail(`files list differs. Expected ${JSON.stringify(expectedFiles)}, got ${JSON.stringify(actualFiles)}`);
}

for (const entry of ["mcp-server.mjs", "worktree.mjs", "setup.mjs", "GUIDE.md", join("scripts", "python.mjs"), join("scripts", "postinstall.mjs"), "README.md", join("docs", "installation.md"), join("docs", "mcp-contract.md"), "worktree.sh"]) {
  if (!existsSync(join(packageDir, entry))) {
    fail(`expected file missing: ${entry}`);
  }
}
const pyFiles = readdirSync(join(packageDir, "worktree_manager")).filter((f) => f.endsWith(".py"));
if (pyFiles.length === 0) {
  fail("worktree_manager contains no .py files");
}

const GUIDE_LITERAL = "Vas a implementar un cambio, ejecutar una spec o iniciar un flujo. ¿Quieres crear un worktree para hacerlo aislado?";
let guide;
try {
  guide = readLocal("GUIDE.md");
} catch {
  fail("cannot read GUIDE.md");
}
if (!guide.includes(GUIDE_LITERAL)) {
  fail("GUIDE.md does not contain the literal guide text");
}
let server;
try {
  server = readLocal(join("worktree_manager", "mcp_server.py"));
} catch {
  fail("cannot read worktree_manager/mcp_server.py");
}
if (!server.includes(GUIDE_LITERAL)) {
  fail("mcp_server.py does not contain the literal guide text");
}
if (!server.includes("worktree-for-agents")) {
  fail('mcp_server.py does not reference server name "worktree-for-agents"');
}

// Version must live only in __init__.py within the runtime.
for (const file of pyFiles) {
  if (file === "__init__.py") {
    continue;
  }
  const source = readLocal(join("worktree_manager", file));
  if (source.includes("1.0.0")) {
    fail(`version literal 1.0.0 found in worktree_manager/${file}; keep it only in __init__.py`);
  }
}

// Independence: runtime must not mention FlowTask except setup.mjs.
const runtimeRelPaths = [
  ...pyFiles.map((f) => join("worktree_manager", f)),
  "mcp-server.mjs",
  "worktree.mjs",
  join("scripts", "python.mjs"),
  join("scripts", "postinstall.mjs"),
];
const forbidden = ["flowtask", ".flowtask", "flowtask_worktree_consume"];
for (const rel of runtimeRelPaths) {
  const source = readLocal(rel).toLowerCase();
  for (const token of forbidden) {
    if (source.includes(token)) {
      fail(`${rel} mentions ${token}; only setup.mjs may diagnose coexistence`);
    }
  }
}

process.stdout.write("package verification passed\n");
