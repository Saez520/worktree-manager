# Python backend transition notes

The entrypoint is `python3 -m worktree_manager`, and `worktree.sh` delegates to that same package. The package is the only lifecycle implementation: there is no second engine. It uses the Python standard library and centralizes Git subprocess calls in `GitRepository`. The JSON envelope is contract version 1; human output remains the default.

## Current implementation status

The Python package implements the standalone lifecycle and target-direct operations. Preserve-dirty interruption recovery is fail-closed: a non-terminal transaction marked `preserve_dirty` returns `pending_intervention` (exit 5), preserving its journal and recovery resources until explicit validated recovery. This is distinct from a validated durable squash on a non-preserve-dirty close, which remains `no_pending_work` (exit 0) until `complete` resumes the close.

`tests/parity.sh` differentially exercises isolated repositories for CLI JSON/human output, lifecycle, preserve-dirty restoration, lock contention, crash recovery (including repeated recovery), and target-direct link/abort/drift/recover/complete behavior. Crash recovery compares exit statuses, worktree and index state, refs, and journal phases. The harness also injects a target-direct descriptor-phase crash and compares the ordered recovery statuses (6, 0), blocked phase, retained evidence, and parent index. The first recovery is fail-closed and non-mutating; subsequent recovery reports the blocked terminal state without deleting evidence.

## Parity requirements

A full parity verdict requires comparison of retained descriptor, journal, lock, and parent index before and after repeated recovery. The target-direct descriptor crash fixture kills each backend only after the durable `staged_started` descriptor transition. It requires the exact recovery exit sequence `(6, 0)`, a persisted `blocked` phase, and intact, hash-verified HEAD/index snapshot evidence. Comparing only final state or normalizing the first failure to success is incorrect. Compare result, exit code, Git/index state, logical persisted evidence, refs/backups, and retained worktrees; normalize only documented variable values. Bash journal/meta and Python snapshot filenames are different physical encodings and are not compared as literal inventories; missing logical evidence remains a hard failure. Any untested case or behavioral difference blocks the release of a wrapper.

The MCP service, the subtree behavior and the distribution rules are described in `docs/mcp-contract.md` and in the repository README.
