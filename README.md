# Worktree Manager

Standalone Bash manager for creating, completing, cleaning up, and recovering
worktrees in a Git repository.

## Architecture

`worktree.sh` is the entrypoint and delegates the parent-only lifecycle to
`lib/worktree-manager-core.sh`; the core loads
`lib/worktree-manager-target-direct.sh` to operate directly on a
submodule. Configuration is validated as `key=value` data, never as shell
code.

The manager maintains a single implementation of the core and the
target-direct module; alternative copies of either must not be maintained.

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
