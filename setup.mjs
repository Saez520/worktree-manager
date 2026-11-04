import { existsSync, readFileSync, writeFileSync, copyFileSync, renameSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir, homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdtempSync } from "node:fs";
import { probePython } from "./scripts/python.mjs";

const packageDir = dirname(fileURLToPath(import.meta.url));

function readPackage() {
  const raw = readFileSync(join(packageDir, "package.json"), "utf8");
  return JSON.parse(raw);
}

function opencodeConfigCandidates() {
  if (process.platform === "win32") {
    const base = process.env.APPDATA || join(homedir(), "AppData", "Roaming");
    return [join(base, "opencode", "opencode.json")];
  }
  const xdg = process.env.XDG_CONFIG_HOME;
  if (xdg) {
    return [join(xdg, "opencode", "opencode.json")];
  }
  return [join(homedir(), ".config", "opencode", "opencode.json")];
}

function readEnvironment(configPath, key, references) {
  const environment = { path: configPath, present: existsSync(configPath), entries: {}, refsThisPackage: [] };
  if (!environment.present) {
    return environment;
  }
  try {
    const parsed = JSON.parse(readFileSync(configPath, "utf8"));
    const entries = parsed && parsed[key];
    environment.entries = entries && typeof entries === "object" && !Array.isArray(entries) ? entries : {};
  } catch {
    environment.parseError = true;
    environment.entries = {};
  }
  environment.refsThisPackage = Object.entries(environment.entries)
    .filter(([, value]) => value && typeof value === "object" && references(value))
    .map(([name]) => name);
  return environment;
}

function collectStatus() {
  const pkg = readPackage();
  const probed = probePython();
  const serverPath = join(packageDir, "mcp-server.mjs");
  const opencode = readEnvironment(opencodeConfigCandidates()[0], "mcp", (entry) =>
    Array.isArray(entry.command) &&
    entry.command.length === 2 &&
    entry.command[0] === "node" &&
    typeof entry.command[1] === "string" &&
    resolve(entry.command[1]) === resolve(serverPath)
  );
  const claude = readEnvironment(join(process.cwd(), ".mcp.json"), "mcpServers", (entry) =>
    entry.command === "node" &&
    Array.isArray(entry.args) &&
    typeof entry.args[0] === "string" &&
    resolve(entry.args[0]) === resolve(serverPath)
  );
  return {
    version: pkg.version,
    packagePath: packageDir,
    interpreter: probed,
    launch: ["node", serverPath],
    installations: [{ kind: "npm package", path: packageDir, version: pkg.version, active: true }],
    active: "npm package",
    environments: { opencode, claude },
  };
}

function printEnvironment(label, environment) {
  const lines = [];
  lines.push(`${label} config: ${environment.path} (${environment.present ? "present" : "absent"})`);
  const names = Object.keys(environment.entries || {});
  if (names.length === 0) {
    lines.push(`${label} mcp entries: (none)`);
  } else {
    lines.push(`${label} mcp entries:`);
    for (const name of names) {
      const marker = environment.refsThisPackage.includes(name) ? " (references this package)" : "";
      lines.push(`  - ${name}${marker}`);
    }
  }
  return lines;
}

function printHuman(status) {
  const lines = [];
  lines.push(`worktree-for-agents ${status.version}`);
  lines.push(`package: ${status.packagePath}`);
  if (status.interpreter.version) {
    lines.push(`python: ${status.interpreter.bin} ${status.interpreter.version}`);
  } else {
    lines.push(`python: not found (requires 3.9+)`);
  }
  lines.push(`launch: ${status.launch.join(" ")}`);
  lines.push("installations:");
  for (const inst of status.installations) {
    lines.push(`  - ${inst.kind}: ${inst.path} (version ${inst.version}, active)`);
  }
  lines.push(`active: ${status.active}`);
  lines.push(...printEnvironment("opencode", status.environments.opencode));
  lines.push(...printEnvironment("claude code", status.environments.claude));
  process.stdout.write(lines.join("\n") + "\n");
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function runWriteOpencode() {
  const candidates = opencodeConfigCandidates();
  const configPath = candidates[0];
  const configDir = dirname(configPath);
  if (!existsSync(configDir)) {
    process.stderr.write(
      `OpenCode config directory does not exist: ${configDir}. Create it manually or run OpenCode once, then rerun with --write-opencode.\n`
    );
    process.exit(1);
  }
  let parsed = {};
  let raw = null;
  if (existsSync(configPath)) {
    raw = readFileSync(configPath, "utf8");
    try {
      parsed = JSON.parse(raw);
    } catch {
      process.stderr.write(`OpenCode config is not valid JSON: ${configPath}. Fix it manually and rerun.\n`);
      process.exit(1);
    }
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    parsed = {};
  }
  if (!parsed.mcp || typeof parsed.mcp !== "object" || Array.isArray(parsed.mcp)) {
    parsed.mcp = {};
  }
  const expected = { type: "local", command: ["node", join(packageDir, "mcp-server.mjs")], enabled: true };
  const existing = parsed.mcp["worktree-for-agents"];
  if (existing !== undefined) {
    if (deepEqual(existing, expected)) {
      process.stdout.write("opencode.json already configured for worktree-for-agents.\n");
      process.exit(0);
    }
    process.stderr.write(
      `Refusing to overwrite mcp.worktree-for-agents: existing value differs from expected.\nExisting: ${JSON.stringify(existing)}\nExpected: ${JSON.stringify(expected)}\n`
    );
    process.exit(1);
  }
  parsed.mcp["worktree-for-agents"] = expected;
  const next = JSON.stringify(parsed, null, 2) + "\n";
  if (existsSync(configPath)) {
    copyFileSync(configPath, `${configPath}.bak`);
  }
  const stagingDir = mkdtempSync(join(tmpdir(), "worktree-for-agents-"));
  try {
    const staging = join(stagingDir, "opencode.json");
    writeFileSync(staging, next, "utf8");
    JSON.parse(readFileSync(staging, "utf8"));
    mkdirSync(dirname(configPath), { recursive: true });
    renameSync(staging, configPath);
    JSON.parse(readFileSync(configPath, "utf8"));
  } finally {
    try {
      rmSync(stagingDir, { recursive: true, force: true });
    } catch {}
  }
  process.stdout.write(`Registered mcp.worktree-for-agents in ${configPath}.\n`);
}

function runWriteClaude() {
  const configPath = join(process.cwd(), ".mcp.json");
  let parsed = {};
  if (existsSync(configPath)) {
    try {
      parsed = JSON.parse(readFileSync(configPath, "utf8"));
    } catch {
      process.stderr.write(`Claude Code config is not valid JSON: ${configPath}. Fix it manually and rerun.\n`);
      process.exit(1);
    }
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    parsed = {};
  }
  if (!parsed.mcpServers || typeof parsed.mcpServers !== "object" || Array.isArray(parsed.mcpServers)) {
    parsed.mcpServers = {};
  }
  const expected = { command: "node", args: [join(packageDir, "mcp-server.mjs")] };
  const existing = parsed.mcpServers["worktree-for-agents"];
  if (existing !== undefined) {
    if (deepEqual(existing, expected)) {
      process.stdout.write("Claude Code config already configured for worktree-for-agents.\n");
      process.exit(0);
    }
    process.stderr.write(
      `Refusing to overwrite mcpServers.worktree-for-agents: existing value differs from expected.\nExisting: ${JSON.stringify(existing)}\nExpected: ${JSON.stringify(expected)}\n`
    );
    process.exit(1);
  }
  parsed.mcpServers["worktree-for-agents"] = expected;
  const next = JSON.stringify(parsed, null, 2) + "\n";
  if (existsSync(configPath)) {
    copyFileSync(configPath, `${configPath}.bak`);
  }
  const stagingDir = mkdtempSync(join(tmpdir(), "worktree-for-agents-"));
  try {
    const staging = join(stagingDir, "mcp.json");
    writeFileSync(staging, next, "utf8");
    JSON.parse(readFileSync(staging, "utf8"));
    renameSync(staging, configPath);
    JSON.parse(readFileSync(configPath, "utf8"));
  } finally {
    try {
      rmSync(stagingDir, { recursive: true, force: true });
    } catch {}
  }
  process.stdout.write(`Registered mcpServers.worktree-for-agents in ${configPath}.\n`);
}

const args = new Set(process.argv.slice(2));
if (args.has("--write-opencode") && args.has("--write-claude")) {
  process.stderr.write("Choose one write target: --write-opencode or --write-claude.\n");
  process.exit(1);
} else if (args.has("--write-opencode")) {
  runWriteOpencode();
} else if (args.has("--write-claude")) {
  runWriteClaude();
} else if (args.has("--json")) {
  const status = collectStatus();
  process.stdout.write(JSON.stringify(status, null, 2) + "\n");
} else {
  printHuman(collectStatus());
}
