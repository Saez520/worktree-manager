# Worktree Manager

Standalone manager for creating, completing, cleaning up, and recovering
worktrees in a Git repository. The project does not know FlowTask and does not
depend on its paths, inherited refs, or coordination mechanisms.

## Architecture

`worktree.sh` is the entrypoint and delegates the lifecycle to the Python
package `worktree_manager`, executed with `python3 -m worktree_manager`. The
package is the only lifecycle implementation: there is no alternative shell
engine.

The package is organized into modules with one responsibility each:

| Module | Responsibility |
| --- | --- |
| `worktree_manager.cli` | Command-line interface and output contract. |
| `worktree_manager.configuration` | Reading and validation of `key=value` configuration. |
| `worktree_manager.worktree_lifecycle` | `create`, `complete`, `cleanup`, and `prune` operations. |
| `worktree_manager.target_direct_adapter` | `target-direct` operations on a submodule. |
| `worktree_manager.recovery_manager` | Recovery of pending transactions. |
| `worktree_manager.transaction_journal` | Durable transaction journal. |
| `worktree_manager.backup_store` | Backups and backup refs. |
| `worktree_manager.lock_manager` | Mutual exclusion between processes. |
| `worktree_manager.git_repository` | Git access from a single point. |
| `worktree_manager.mcp_server` | MCP service over stdio. |

Configuration is validated as `key=value` data, never as shell code.

Any installer or consumer that integrates this repository must materialize it
as a single implementation source.

## Configuration and lifecycle

Configuration allows selecting `worktrees_dir`, `state_dir`, `backup_dir`,
`backup_ref_prefix`, `branch_prefix`, and `lock_dir`. Parent-only supports
`create`, `complete`, `cleanup`, `recover`, `prune`, and `list`, with locks,
journals, recovery, and explicit preservation.

`complete` preserves resources in the presence of conflicts or drift.
`cleanup` does not integrate; removing unintegrated changes requires
`--discard`. Preservation requires opt-in, and restoration conflicts are left
for human intervention.

## Target-direct

Target-direct operates on the specified submodule repository: it does not
create a parent worktree or modify its `HEAD`. It requires explicit
target/parent identity, the submodule path, and `--link-parent staged-only`.
`create` prepares the target worktree; `link-parent` records only the gitlink;
`abort`, `complete`, and `recover` preserve the snapshot and journal and stop
on ambiguous drift. It requires exactly Git 2.54.0.

## Usage

```text
worktree.sh [--repo ABS] [--config ABS] create <id> [--base BRANCH]
worktree.sh [global options] complete <id> [--preserve-dirty]
worktree.sh [global options] cleanup <id> [--discard]
worktree.sh [global options] recover [<transaction-id>]
worktree.sh [global options] prune | list
```

The target-direct interface and JSON output contract are documented in
[`docs/cli-contract-v1.md`](docs/cli-contract-v1.md). Executable tests are in
`tests/`.

## Distribution

This repository contains the manager's complete implementation and
documentation, including the CLI contract and executable tests.
