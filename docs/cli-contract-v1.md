# CLI output contract

The default presentation is human-readable. `--json` explicitly selects one JSON document on stdout; diagnostics remain on stderr. JSON objects contain `contract_version` (integer, currently `1`), `tool_version` (string, currently `1.2.3`), `operation`, `result`, `data`, `warnings`, and `error`. `data` is an object whose fields depend on the operation and result; examples include `path`, `branch`, `worktree`, `pruned`, and `recovered`. There is no general `data.output` field: the dispatcher’s human-readable text is not included in the JSON data object.

`result` is `success`, `failure`, `pending_intervention`, or `no_pending_work`. Errors are objects with stable `code`, human `message`, and public `exit_code`, plus an optional `details` object published only by errors that carry structured fields (currently `base_changed`). Exit codes are 0 success/no pending work, 2 usage, 3 invalid configuration/identity, 4 resource lock, 5 conflict/intervention, and 6 access/dependency. The legacy entrypoint and its codes remain unchanged when `--json` is absent. Errors whose legacy text does not provide a reliable subtype are reported as `operation_failed` (exit 5); clients should rely on the stable code, not parse the message.

`--version` prints the tool version. The contract version describes the JSON schema and is independent from the tool version. Breaking schema changes require a new contract version. Legacy invocations do not opt into JSON implicitly; `list` retains Git porcelain output without `--json`. JSON changes presentation only and does not authorize, suppress, or alter lifecycle effects, locks, journals, backups, consent, or recovery.

## Protocol requests

`--request-json <file|->` reads one canonical request document and publishes the same nine-key envelope as the MCP transport, with or without `--json`: `contract_version`, `tool_version`, `operation`, `repository`, `result`, `data`, `warnings`, `error` and `transaction_id`. The request must not be combined with a subcommand or with any other flag; `--json` is accepted and does not change the published document. `operation` names the tool (`worktree_create`, `worktree_list`, …), `repository` is the absolute repository path, `error` carries `code`, `message` and `exit_code`, and `transaction_id` is `null` when no transaction exists. Accepted and rejected requests publish the same shape, so a client never has to parse two document formats.

## Create options

`create` accepts `--init-submodules`, `--prepare` and `--verify`; they are off by default, so a repository without that configuration behaves exactly as before. The reported states are the observed ones: `init_submodules_result` is `not_requested` or `initialized`, and `prepare` and `verify` are `skipped`, `passed` or `failed`. `--prepare` and `--verify` require `prepare_command` and `verify_command` in the configuration; without them the request is rejected as `invalid_configuration` before any worktree or branch exists. A failing step keeps the worktree and its branch for inspection instead of discarding them.

With `--init-submodules`, the manager fingerprints the module directories of the submodules already initialized in the main worktree before adding the worktree. An existing module directory without `objects` or `HEAD` is rejected as `operation_failed` with exit code 5 before any worktree or branch exists. After the update, on success or failure, a module directory that changed, disappeared or lost `objects` is reported as `operation_failed` with the affected paths and the worktree and its branch are retained. The guard is read-only: it does not restore or delete module directories, and a healthy run still reports `initialized`.

A dry run of `create` publishes `data.planned` as `true` and creates no worktree, no branch and no other mutation. Its reported states are the planned ones: `init_submodules_result` is `planned` or `not_requested`, and `prepare` and `verify` are `planned` or `skipped`. In an execution the states are the observed ones: `init_submodules_result` is `initialized` or `not_requested`, and `prepare` and `verify` are `passed`, `failed` or `skipped`.

## Compatibility and recovery

The standalone commands are `create`, `complete`, `cleanup`, `recover`, `list`, and `prune`; target-direct operations include `create`, `link-parent`, `abort`, `complete`, and `recover`. In the target-direct syntax `--parent-repo` is placed after the action, and `--submodule-path` is required by `create`. Existing legacy invocations remain human-readable and preserve their legacy exit codes and `list` porcelain format. A failed destination-state restoration is reported as `pending_intervention`; preserve-dirty backups and transaction evidence are retained for human intervention. Invalid descriptor/drift, lock contention, absent dependencies, and access failures are failures, not successful recovery. A recover request does not discard state.

## Verification commands

The suites that gate a publication of this repository are:

```sh
bash tests/cli-usage.sh
bash tests/cli-json.sh
bash tests/compatibility.sh
bash tests/smoke.sh
bash tests/parity.sh
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_mcp*.py' -v
PYTHONPATH=. python3 -m unittest tests.test_npm_launchers tests.test_npm_setup tests.test_npm_package -v
node scripts/verify-package.mjs
```

The usage suite parses each pre-dispatch usage failure, including the unknown option, the unknown or missing command, the missing global value and an invalid `--version` arity, checks the stable exit code `2`, and checks the help syntax of the target-direct `complete` and `recover` actions. The compatibility suite is independent of any orchestration worktree path. Every publication records the date, the commit and the output of these commands, and it does not cite a suite that no longer exists.

## Closing message

`complete` accepts optional `--title TEXT` and `--body TEXT`. The manager
composes the subject and body deterministically: it normalizes the title to a
single line, normalizes CRLF to LF in the body, and guarantees that `work_id`
appears in the subject (appending it as ` [work_id]` when missing). When no
title is passed, the subject is `Complete <work_id> (generic closure)` and the body is
`No delivery description was available at closure time.` The body is only
written when non-empty. Both values are stored in `meta.json` as
`commit_subject` and `commit_body`, and the dry run publishes them. A
title or body change between preflight and execute causes `plan_mismatch`.

## Base drift

`complete` integrates only when the current tip of the base branch is an
ancestor of the worktree branch tip (`git merge-base --is-ancestor <base>
<branch>`). In that case the integrated tree is identical to the branch tree,
which is the tree that was built and validated. Otherwise the base moved after
the branch was built and `complete` fails closed:

- `error.code` is `base_changed`, `result` is `failure` and the exit code is `5`.
- `error.message` is `Base branch '<base>' moved after the worktree branch was
  built (current base <sha12>, branch built on <sha12>); merge or rebase
  '<base>' into the branch, commit, and retry. Nothing was changed`.
- `error.details` carries `base_branch`, `current_base` (the tip of the base
  now), `expected_base` (the merge base: the base commit the branch was built
  on) and `branch_head`.
- Nothing is mutated: no commit, no journal entry, no backup, no lock residue;
  the base, the branch, the worktree and any destination changes kept with
  `--preserve-dirty` are untouched.

The check runs before any mutation and again under the repository lock. The
way forward is the orchestrator's: merge or rebase the base into the worktree
branch, commit, and run `complete` again; the base tip is then an ancestor and
the integration proceeds. A base that moved only by being reset backwards still
satisfies the rule and integrates the validated branch tree. A base that gained
commits whose patches the branch carries by cherry-pick is rejected too: the
rule is conservative and never integrates a tree other than the branch tree.

## Merge strategy

`complete` accepts `--merge-strategy` with the values `squash` (default) and
`preserve-history`. Squash integrates the branch as one new commit on the base
branch and keeps the existing verification. Preserve-history integrates it with
a merge commit whose first parent is the base position before completion and
whose second parent is the branch tip, so the branch commits remain reachable.

Both strategies land the commit the same way: the manager writes a commit whose
tree is the verified branch tree (`git commit-tree`, parented on the verified
base tip) and publishes it with `git merge --ff-only`. This is a
compare-and-swap: if the base moves between the verification and the write,
Git refuses the fast-forward and `complete` fails with `base_changed` instead of
integrating. The branch itself is not fast-forwarded and its commits stay
separate in squash. Before the worktree and the branch are removed, the
integrated commit is verified: its parents, its tree (equal to the branch tree)
and a clean tracked state. The commit is written without running commit hooks.

The result publishes `merge_strategy` and `integrated_commit` in both cases;
`squash_commit` is published only for squash and equals `integrated_commit`.
The transaction `meta.json` records `merge_strategy` and `integrated` (plus
`squash` for squash), and `binding.json` records `merge_strategy`. Recovery
validates the parent shape recorded by the strategy and that the integrated
tree equals the branch tree; a landed commit with the right parents and any
other tree, or a base that moved after the landing, is reported as
`intervention_required` with exit code 5 and every resource is retained. A
transaction without a recorded strategy is read as squash, and an unknown value
is reported as `invalid_journal` with exit code 5 while retaining the evidence.
A failed fast-forward leaves the transaction in `pending_manual`; `recover`
restores any captured destination state and closes it as `restored`.

An invalid `--merge-strategy` value is rejected by the parser with
`usage_error` and exit code 2 before any mutation. With `preserve-history`,
a branch with no commits ahead of the base is rejected as `operation_failed`
with exit code 5 before the transaction journal or locks are created, so the
worktree and branch are retained. A destination with uncommitted changes keeps
requiring `--preserve-dirty`, which captures and restores the destination state
around either strategy.
