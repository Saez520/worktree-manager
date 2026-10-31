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

function globalFlowtaskDir() {
  if (process.platform === "win32") {
    const base = process.env.APPDATA || join(homedir(), "AppData", "Roaming");
    return join(base, "FlowTask", "worktree-manager");
  }
  const xdg = process.env.XDG_CONFIG_HOME;
  const base = xdg ? join(xdg, "flowtask") : join(homedir(), ".config", "flowtask");
  return join(base, "worktree-manager");
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

function checkoutStatus(dir) {
  if (!dir || !existsSync(join(dir, "worktree_manager", "__main__.py"))) {
    return { present: false };
  }
  const transport = join(dir, "worktree_manager", "mcp_transport.py");
  return { present: true, mcpTransport: existsSync(transport) };
}

function collectStatus() {
  const pkg = readPackage();
  const probed = probePython();
  const npmPackage = {
    kind: "npm package",
    path: packageDir,
    version: pkg.version,
    active: true,
  };
  const globalDir = globalFlowtaskDir();
  const globalStatus = checkoutStatus(globalDir);
  const globalCopy = {
    kind: "FlowTask global copy",
    path: globalDir,
    present: globalStatus.present || false,
  };
  const submoduleDir = resolve(join(process.cwd(), ".flowtask", "scripts", "worktree-manager"));
  const submoduleStatus = checkoutStatus(submoduleDir);
  const submodule = {
    kind: "local submodule",
    path: submoduleDir,
    present: submoduleStatus.present || false,
  };
  const configPaths = opencodeConfigCandidates();
  const configPath = configPaths[0];
  let opencode = { path: configPath, present: existsSync(configPath), entries: {} };
  if (opencode.present) {
    try {
      const parsed = JSON.parse(readFileSync(configPath, "utf8"));
      const mcp = (parsed && parsed.mcp) || {};
      opencode.entries = mcp;
    } catch {
      opencode.parseError = true;
    }
  }
  const expectedCommand = ["node", join(packageDir, "mcp-server.mjs")];
  let activeEntry = "npm package";
  const refsThisPackage = [];
  for (const [name, value] of Object.entries(opencode.entries || {})) {
    const cmd = value && value.command;
    if (Array.isArray(cmd) && cmd.length === 2 && cmd[0] === "node" && typeof cmd[1] === "string") {
      if (resolve(cmd[1]) === resolve(expectedCommand[1])) {
        refsThisPackage.push(name);
      }
    }
  }
  return {
    version: pkg.version,
    packagePath: packageDir,
    interpreter: probed,
    installations: [npmPackage, globalCopy, submodule],
    active: activeEntry,
    opencode,
    expectedCommand,
    refsThisPackage,
  };
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
  lines.push("installations:");
  for (const inst of status.installations) {
    if (inst.kind === "npm package") {
      lines.push(`  - npm package: ${inst.path} (version ${inst.version}, active)`);
    } else {
      lines.push(`  - ${inst.kind}: ${inst.path} (${inst.present ? "present" : "absent"})`);
    }
  }
  lines.push(`active: ${status.active}`);
  lines.push(`opencode config: ${status.opencode.path} (${status.opencode.present ? "present" : "absent"})`);
  const names = Object.keys(status.opencode.entries || {});
  if (names.length === 0) {
    lines.push("mcp entries: (none)");
  } else {
    lines.push("mcp entries:");
    for (const name of names) {
      const marker = status.refsThisPackage.includes(name) ? " (references this package)" : "";
      lines.push(`  - ${name}${marker}`);
    }
  }
  process.stdout.write(lines.join("\n") + "\n");
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function runWriteOpencode() {
  const status = collectStatus();
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

const args = new Set(process.argv.slice(2));
if (args.has("--write-opencode")) {
  runWriteOpencode();
} else if (args.has("--json")) {
  const status = collectStatus();
  process.stdout.write(JSON.stringify(status, null, 2) + "\n");
} else {
  printHuman(collectStatus());
}
