import { probePython } from "./python.mjs";

const probed = probePython();
if (!probed.version) {
  process.stderr.write(
    "worktree-for-agents requires Python 3.9 or later. Install Python 3.9+ and rerun the installation.\n"
  );
  process.exit(1);
}
process.stdout.write(`worktree-for-agents: Python ${probed.version} (${probed.bin})\n`);
process.stdout.write("Next: node <package>/setup.mjs\n");
