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
if (manifest.version !== "1.2.0") {
  fail(`version is ${manifest.version}, expected 1.2.0`);
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

const INSTRUCTION = "Before you touch the main branch, offer to create an isolated worktree: create it with worktree_create, do all the work inside it, and close it with worktree_complete to integrate or worktree_cleanup to discard. If the worktree cannot be created or closed, correct the cause named in the error message before retrying.";
const TOOL_NAMES = [
  "worktree_create", "worktree_complete", "worktree_cleanup",
  "worktree_recover", "worktree_list", "worktree_prune", "worktree_status",
];
const DESCRIPTIONS = {
  worktree_create: "Creates an isolated worktree and its branch for a work identifier; use it before starting a change, spec, or flow so the base branch stays untouched.",
  worktree_complete: "Integrates the worktree into the base branch and removes it; use it when the isolated work is finished and should land on the base branch.",
  worktree_cleanup: "Removes the worktree and its branch without integrating; use it to discard abandoned work and, with discard and discard_consent, its uncommitted changes.",
  worktree_recover: "Continues a pending transaction by its identifier; use it after an interrupted create or complete before starting another operation.",
  worktree_list: "Lists the worktrees registered for the repository; use it to find existing work identifiers before creating or closing one.",
  worktree_prune: "Removes worktree records whose directories no longer exist; use it after deleting a worktree by hand to clean the stale registration.",
  worktree_status: "Reports one work item's worktree, journal transactions, and pending intervention; use it before completing or cleaning up to confirm the current state.",
};

let guide;
try {
  guide = readLocal("GUIDE.md");
} catch {
  fail("cannot read GUIDE.md");
}
if (!guide.includes(INSTRUCTION)) {
  fail("GUIDE.md does not contain the published instruction");
}
for (const name of TOOL_NAMES) {
  if (!guide.includes(`\`${name}\``)) {
    fail(`GUIDE.md does not list ${name}`);
  }
}

let contract;
try {
  contract = readLocal(join("worktree_manager", "mcp_contract.py"));
} catch {
  fail("cannot read worktree_manager/mcp_contract.py");
}
if (!contract.includes(INSTRUCTION)) {
  fail("mcp_contract.py does not contain the published instruction");
}
for (const name of TOOL_NAMES) {
  if (!contract.includes(DESCRIPTIONS[name])) {
    fail(`mcp_contract.py does not contain the description for ${name}`);
  }
}
if (new Set(Object.values(DESCRIPTIONS)).size !== TOOL_NAMES.length) {
  fail("operation descriptions are not all distinct");
}

let server;
try {
  server = readLocal(join("worktree_manager", "mcp_server.py"));
} catch {
  fail("cannot read worktree_manager/mcp_server.py");
}
if (!server.includes("worktree-for-agents")) {
  fail('mcp_server.py does not reference server name "worktree-for-agents"');
}
if (server.includes("Manage repository worktrees")) {
  fail("mcp_server.py still publishes the generic tool description");
}

// Version must live only in __init__.py within the runtime.
for (const file of pyFiles) {
  if (file === "__init__.py") {
    continue;
  }
  const source = readLocal(join("worktree_manager", file));
  if (source.includes("1.2.0")) {
    fail(`version literal 1.2.0 found in worktree_manager/${file}; keep it only in __init__.py`);
  }
}

// Independence: no published surface may mention a retired consumer.
const publishedRelPaths = [
  ...pyFiles.map((f) => join("worktree_manager", f)),
  "mcp-server.mjs",
  "worktree.mjs",
  "setup.mjs",
  "worktree.sh",
  "GUIDE.md",
  "README.md",
  join("docs", "installation.md"),
  join("docs", "mcp-contract.md"),
  join("scripts", "python.mjs"),
  join("scripts", "postinstall.mjs"),
  "package.json",
];
const consumerName = "flow" + "task";
const forbidden = [consumerName, "flow" + " task", "flow" + "-task"];
for (const rel of publishedRelPaths) {
  const source = readLocal(rel).toLowerCase();
  for (const token of forbidden) {
    if (source.includes(token)) {
      fail(`${rel} mentions a retired consumer identifier; remove it from the published surface`);
    }
  }
}

process.stdout.write("package verification passed\n");
