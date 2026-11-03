# Worktree manager

Standalone manager to create, complete, clean up, and recover worktrees of a
Git repository. The project does not know FlowTask and does not depend on its paths, legacy
refs, or coordination mechanisms.

## Requirements

- **Python 3.9 or later.** The entrypoint only checks that `python3` is
  available on the `PATH`; the 3.9 floor is validated by the package postinstall
  and `node <package>/setup.mjs`. The package uses only the standard library.
- **Git 2.17.0 or later**, for `git worktree remove`, which is the most
  recent command used by the manager. The test baseline is Git 2.54.0. The
  manager does not check the Git version at runtime.
- **Node 18 or later** for the `mcp-server.mjs`, `worktree.mjs`
  and `setup.mjs` launchers.
- **`bash`** to run the test suites.

## Installation

The manager is distributed as the npm package `worktree-for-agents`, version
`1.0.0`, with no bin or `npx`:

```sh
npm install -g worktree-for-agents@latest
pnpm add -g worktree-for-agents@latest
```

Check the installation diagnostics:

```sh
node <package>/setup.mjs
```

The repository clone is for development only. There is no `pip install` and no
dependencies to resolve: the manager uses only the Python standard
library. Once installed, the manager works without a network.

## Quick start

Global options go before the subcommand and `--repo` requires an absolute
path.

```text
worktree.sh [--repo ABS] [--config ABS] [--json] create <id> [--base BRANCH] [--init-submodules] [--prepare] [--verify]
worktree.sh [globals] complete <id> [--preserve-dirty] [--title TEXT] [--body TEXT]
worktree.sh [globals] cleanup <id> [--discard]
worktree.sh [globals] recover [<transaction-id>]
worktree.sh [globals] prune
worktree.sh [globals] list
```

Target-direct operates on the repository given in `--repo` and does not create a
parent worktree nor modify its `HEAD`. Its syntax places `--parent-repo`
after the action and requires `--submodule-path` in `create`:

```text
worktree.sh [--repo ABS] target-direct <action> <id> --parent-repo <parent> [--target submodule] [--submodule-path <REL>] [--base BRANCH] [--link-parent staged-only] [--descriptor PATH]
```

The actions are `create`, `link-parent`, `abort`, `complete` and `recover`, and the
only supported link mode is `--link-parent staged-only`.

`--json` publishes a single JSON document. `--request-json <file|->` publishes
the same nine-key envelope used by the MCP transport, and optionally accepts `--json`.
A dry run of `create` publishes `planned: true` and creates no
worktree or branch.

The MCP service is published over stdio. From the installed package it is launched without
bin:

```sh
node <package>/mcp-server.mjs
```

The CLI is used the same way:

```sh
node <package>/worktree.mjs --version
```

The MCP `initialize` publishes the guide in `instructions`:

```text
You are going to implement a change, run a spec, or start a flow. Do you want to create a worktree to work in isolation?
```

For development, the transport also starts from the checkout:

```sh
PYTHONPATH=. python3 -m worktree_manager.mcp_transport
```

## Configuration

The configuration is an optional `key=value` file, selected with
`--config` or taken from `.worktree-manager.conf` at the repository root.
The eleven keys and their default values are:

| Key | Default | Restriction |
|---|---|---|
| `worktrees_dir` | `.worktrees` | Must not start with `-` |
| `branch_prefix` | `worktree/` | — |
| `state_dir` | `worktree-manager` | Safe relative path |
| `backup_dir` | `backups` | Not an absolute path and contains no `..` |
| `backup_ref_prefix` | `worktree-manager/backups` | No `..` |
| `lock_dir` | `locks` | Safe relative path |
| `prepare_command` | `''` (empty) | Required when `prepare_enabled=true` |
| `verify_command` | `''` (empty) | Required when `verify_enabled=true` |
| `prepare_enabled` | `false` | `true` or `false` |
| `verify_enabled` | `false` | `true` or `false` |
| `preserve_dirty` | `false` | `true` or `false` |

Each key may appear only once. Unknown keys, malformed lines, invalid booleans, and unsafe paths are rejected as
`invalid_configuration` with exit code `3`. The environment variable
`WORKTREE_MANAGER_<KEY>`, with the key in uppercase, overrides the value
read from the file.

## Architecture

`worktree.sh` is the entrypoint and delegates the lifecycle to the Python
package `worktree_manager`, which runs with `python3 -m worktree_manager`. The package
is the only lifecycle implementation: there is no alternative shell engine.

The package is organized in modules with one responsibility each:

| Module | Responsibility |
| --- | --- |
| `worktree_manager.cli` | Command dispatcher, target-direct dispatch, and output contract. |
| `worktree_manager.configuration` | Reading and validating the `key=value` configuration. |
| `worktree_manager.models` | Shared domain values: results, errors, and identities. |
| `worktree_manager.output` | Publishing the result as readable text or as JSON. |
| `worktree_manager.git_repository` | Shared Git access for the lifecycle modules. |
| `worktree_manager.worktree_lifecycle` | `create`, `complete`, `cleanup`, and `prune` operations. |
| `worktree_manager.commit_message` | Deterministic closing message composition and neutral fallback. |
| `worktree_manager.target_direct_adapter` | Target-direct operations on a submodule. |
| `worktree_manager.recovery_manager` | Recovery of pending transactions. |
| `worktree_manager.transaction_journal` | Durable transaction and link journal. |
| `worktree_manager.backup_store` | Retained backup references. |
| `worktree_manager.lock_manager` | Mutual exclusion between processes. |
| `worktree_manager.state_digest` | Canonical digest of the repository state and of a plan. |
| `worktree_manager.mcp_server` | MCP service published over stdio. |
| `worktree_manager.mcp_contract` | Strict versioned request and envelope contracts. |
| `worktree_manager.mcp_operations` | Facade over the lifecycle and recovery services. |
| `worktree_manager.mcp_transport` | Stdio transport entrypoint. |

The package also contains the package marker `__init__.py` and the
entrypoint `__main__.py`, which is what `python3 -m worktree_manager` runs.

## Tests

```sh
bash tests/cli-usage.sh
bash tests/cli-json.sh
bash tests/compatibility.sh
bash tests/smoke.sh
bash tests/parity.sh
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_mcp*.py' -v
```

## Documentation

- [CLI output contract](docs/cli-contract-v1.md) — contract.
- [MCP service contract](docs/mcp-contract.md) — contract.
- [Installation and usage guide](docs/installation.md) — guide.
- [History bash → Python](docs/history-bash-to-python.md) — notes, not a contract.

Contracts pin the verifiable behavior. The guide explains how to use it.
The history records the transition and does not replace the contracts.

## Source and distribution

This repository is the source of truth for the implementation, the contracts,
the installation, and the manager history.

The consumer that integrates this repository documents the adapter, the bridge, and
the submodule boundary: **that integration documentation lives in the
consumer repository**. The manager does not keep a vendored copy of itself
and does not know the consumer.
