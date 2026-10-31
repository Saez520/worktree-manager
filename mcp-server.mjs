import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { probePython } from "./scripts/python.mjs";

const packageDir = dirname(fileURLToPath(import.meta.url));
const transport = join(packageDir, "worktree_manager", "mcp_transport.py");
const entry = join(packageDir, "worktree_manager", "__main__.py");

if (!existsSync(transport)) {
  process.stderr.write(
    "worktree-for-agents is incomplete: missing worktree_manager/mcp_transport.py. Reinstall the package.\n"
  );
  process.exit(126);
}
if (!existsSync(entry)) {
  process.stderr.write(
    "worktree-for-agents is incomplete: missing worktree_manager/__main__.py. Reinstall the package.\n"
  );
  process.exit(126);
}

const probed = probePython();
if (!probed.version) {
  process.stderr.write(
    "worktree-for-agents requires Python 3.9 or later. Install Python 3.9+ and rerun the installation.\n"
  );
  process.exit(127);
}

const env = {
  ...process.env,
  PYTHONPATH: packageDir + (process.env.PYTHONPATH ? `:${process.env.PYTHONPATH}` : ""),
};
const child = spawn(probed.bin, ["-m", "worktree_manager.mcp_transport"], {
  cwd: packageDir,
  env,
  stdio: "inherit",
});
const forward = (signal) => {
  if (child.exitCode === null && child.signalCode === null) {
    child.kill(signal);
  }
};
process.on("SIGINT", () => forward("SIGINT"));
process.on("SIGTERM", () => forward("SIGTERM"));
child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code === null ? 1 : code);
});
