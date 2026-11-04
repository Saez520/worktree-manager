# Installation and usage of the worktree manager

This guide explains how to install the manager as an npm package, register the
MCP service in both supported environments, and use it on a test repository.

The examples use `$HOME` because `--repo` requires an absolute path. `<package>`
is the installed package path.

## 1. Requirements

Check the available versions:

```sh
python3 --version
git --version
node --version
```

- **Python 3.9 or later.** The package postinstall checks the
  3.9 floor and fails visibly if it is missing or older. `node
  <package>/setup.mjs` reports the detected interpreter.
- **Git 2.17.0 or later**, for `git worktree remove`. The test baseline is
  Git 2.54.0. The manager does not check the Git version at runtime.
- **Node 18 or later** for the `mcp-server.mjs`, `worktree.mjs`
  and `setup.mjs` launchers.
- **`bash`** to run the test suites.

## 2. Install the package

```sh
npm install -g worktree-for-agents@latest
pnpm add -g worktree-for-agents@latest
```

Check the diagnostics:

```sh
node <package>/setup.mjs
```

The package exposes no bin or `npx`: the MCP is launched with `node
<package>/mcp-server.mjs` and the CLI with `node <package>/worktree.mjs`. The
repository clone is for development only. There is no `pip install` and no
dependencies to resolve: the manager uses only the Python standard
library. Once installed, the manager works without a network.

## 3. Register the MCP service

Both environments launch the same service with Node and the absolute package
path:

```sh
node <package>/mcp-server.mjs
```

### OpenCode

Run the writer from anywhere:

```sh
node <package>/setup.mjs --write-opencode
```

The entry `mcp.worktree-for-agents` is written to the OpenCode configuration
file that the diagnostics report (`~/.config/opencode/opencode.json` on Linux
and macOS by default, or `$XDG_CONFIG_HOME/opencode/opencode.json` when that
variable is set). The writer is idempotent: a second run confirms the entry and
changes nothing. Before writing it copies the existing file to
`opencode.json.bak`, and it refuses to overwrite a different value with exit
code 1 without touching the file.

### Claude Code

Run the writer from the project root:

```sh
cd <project>
node <package>/setup.mjs --write-claude
```

The entry `mcpServers.worktree-for-agents` is written to `<project>/.mcp.json`,
the project configuration file that Claude Code reads. The writer is
idempotent, copies an existing file to `.mcp.json.bak` before writing, and
exits with code 1 without touching the file when the existing entry differs or
the file is not valid JSON.

### Check the registration

From the project root:

```sh
node <package>/setup.mjs
```

The diagnostics report the package version and path, the Python interpreter,
the launch command, the active installation, and each environment's
configuration path with the entries that point to this package. Run it from the
project root so the Claude Code entry of that project is included.

## 4. A test repository

The manager requires the worktree path to be ignored by Git, and
`.worktrees/` in `.gitignore` satisfies that condition.

```sh
mkdir "$HOME/demo" && cd "$HOME/demo"
git init -b main
git config user.name "Demo"
git config user.email "demo@example.invalid"
printf 'base\n' > file
printf '.worktrees/\n' > .gitignore
git add file .gitignore
git commit -m "base"
```

Create the worktree:

```sh
"$HOME/worktree-manager/worktree.sh" --repo "$HOME/demo" create demo --base main
```

What each step leaves behind:

- `git init` creates the repository and its `main` branch.
- The initial commit pins the base on top of which the worktree is built.
- `create` creates the `worktree/demo` branch, the worktree at `$HOME/demo/.worktrees/demo`
  and the transaction journal in the repository state directory.

Check the status:

```sh
"$HOME/worktree-manager/worktree.sh" --repo "$HOME/demo" list
```

Work inside the worktree and then merge it:

```sh
cd "$HOME/demo/.worktrees/demo"
printf 'change\n' >> file
git add file
git commit -m "change"
cd "$HOME/demo"
"$HOME/worktree-manager/worktree.sh" --repo "$HOME/demo" complete demo --base main
```

`complete` requires the repository to be on the base branch, the worktree to have
no uncommitted changes, and the destination to have none either, unless
`--preserve-dirty` is used. When finished, the change is merged as a squash
commit on `main`, and the worktree and its branch are removed.

To leave an expressive closing commit, pass `--title` and optionally
`--body`:

```sh
"$HOME/worktree-manager/worktree.sh" --repo "$HOME/demo" complete demo --base main \
  --title "Demo closing" --body "Delivery: merged change. Reason: verification."
```

If `--title` is not passed, the manager uses the generic fallback:
`Complete <work_id> (generic closure)` with the body
`No delivery description was available at closure time.`.

## 5. Configuration

The configuration is a `key=value` file. The manager reads it from
`.worktree-manager.conf` at the repository root, or from the file passed
with `--config`, which must exist and be an absolute path. If both are
given, `--config` wins. Afterwards, the environment variable
`WORKTREE_MANAGER_<KEY>`, with the key in uppercase, overrides the value
read from the file.

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

Each key may appear only once. An unknown key, a line without
`=`, an invalid boolean, or an unsafe path is rejected as
`invalid_configuration` with exit code `3`, before any effect.

## 6. Output contracts

- `--json` publishes a single JSON document with seven keys: `contract_version`,
  `tool_version`, `operation`, `result`, `data`, `warnings` and `error`.
- `--request-json <file|->` publishes the same nine-key document used by
  the MCP transport: the previous seven plus `repository` and
  `transaction_id`. It optionally accepts `--json` and the published document
  does not change.
- A dry run of `create` publishes `planned: true` and creates no worktree or branch.
  `init_submodules_result` is `planned` or `not_requested`, and `prepare` and
  `verify` are `planned` or `skipped`.
- The MCP service is published over stdio and exposes seven tools. Each
  operation publishes its own description in `tools/list`. From the installed
  package it is launched without bin:

```sh
node <package>/mcp-server.mjs
```

  `initialize` publishes the guide in `instructions`:

```text
Before you touch the main branch, offer to create an isolated worktree: create it with worktree_create, do all the work inside it, and close it with worktree_complete to integrate or worktree_cleanup to discard. If the worktree cannot be created or closed, correct the cause named in the error message before retrying.
```

  For development, the transport also starts from the checkout:

```sh
PYTHONPATH=. python3 -m worktree_manager.mcp_transport
```

## 7. Tests

```sh
bash tests/cli-usage.sh
bash tests/cli-json.sh
bash tests/compatibility.sh
bash tests/smoke.sh
bash tests/parity.sh
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_mcp*.py' -v
```

## 8. Troubleshooting

- **`python3` is not on the `PATH`.** The entrypoint exits with code `127`
  and the message
  `worktree manager requires Python 3 (python3) on PATH; install Python 3 and retry.`
- **The package entrypoint is missing.** The entrypoint exits with
  code `126` and the message
  `worktree manager Python entry point is missing: <path>/worktree_manager/__main__.py`.
- **The repository path is relative.** The operation is rejected with
  code `invalid_repository`, exit code `3`, and the message
  `Repository path must be absolute`.
- **The Python version is older than 3.9.** The package postinstall reports
  it as `python <version> is older than the required 3.9`. The entrypoint
  of this repository does not check the version.
