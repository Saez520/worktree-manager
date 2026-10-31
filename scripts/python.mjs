import { spawnSync } from "node:child_process";

/**
 * Resolve the Python interpreter used by the packaged launchers.
 * Order: WORKTREE_MANAGER_PYTHON override, then platform defaults
 * (POSIX python3; win32 python then python3). Returns the binary name
 * or absolute path, or null when no candidate exists.
 */
export function candidates() {
  const override = process.env.WORKTREE_MANAGER_PYTHON;
  if (override && override.trim() !== "") {
    return [override];
  }
  if (process.platform === "win32") {
    return ["python", "python3"];
  }
  return ["python3"];
}

/**
 * Probe a candidate interpreter with `import sys` version output.
 * Returns { bin, version } on Python >= 3.9, or { bin, version, cause }
 * when the interpreter is missing or too old.
 */
export function probeCandidate(bin) {
  const result = spawnSync(bin, ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"], {
    encoding: "utf8",
  });
  if (result.error || result.status !== 0) {
    return { bin, version: null, cause: "not_found" };
  }
  const version = String(result.stdout || "").trim();
  const match = /^(\d+)\.(\d+)$/.exec(version);
  if (!match) {
    return { bin, version: null, cause: "unparseable_version" };
  }
  const major = Number(match[1]);
  const minor = Number(match[2]);
  if (major < 3 || (major === 3 && minor < 9)) {
    return { bin, version, cause: "too_old" };
  }
  return { bin, version };
}

/**
 * Resolve and probe in order. Returns the first usable interpreter
 * as { bin, version }, or { bin: null, version: null, cause } when
 * none is usable. Never throws for a missing interpreter.
 */
export function probePython() {
  let last = { bin: null, version: null, cause: "not_found" };
  for (const bin of candidates()) {
    const probed = probeCandidate(bin);
    if (probed.version && !probed.cause) {
      return { bin: probed.bin, version: probed.version };
    }
    last = { bin: probed.bin, version: probed.version, cause: probed.cause || "not_found" };
  }
  return last;
}

/**
 * Resolve the interpreter binary name without probing.
 * Returns the first candidate, or null when none exists.
 */
export function resolvePython() {
  const list = candidates();
  return list.length > 0 ? list[0] : null;
}
