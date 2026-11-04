# Worktree manager MCP service

The optional stdio service starts independently from the existing CLI:

```sh
python3 -m worktree_manager.mcp_transport
```

It implements JSON-RPC `initialize`, `ping`, `tools/list` and `tools/call` and
publishes exactly `worktree_create`, `worktree_complete`, `worktree_cleanup`,
`worktree_recover`, `worktree_list`, `worktree_prune` and `worktree_status`.
Each call requires an absolute existing Git repository path; the process
working directory is never used as a repository default. Unknown arguments
are rejected. Responses carry contract version 1, operation, repository,
result, data, warnings, structured error and a nullable transaction ID.

The `initialize` result carries `serverInfo.name "worktree-for-agents"` and
an `instructions` field with the literal guide text:

```text
You are going to implement a change, run a spec, or start a flow. Do you want to create a worktree to work in isolation?
```

When installed from npm, the service is launched without a bin entry via:

```sh
node <package>/mcp-server.mjs
```

A rejected call publishes the same nine-key envelope as an accepted one, with
`result` set to `failure` or `pending_intervention` and `error` carrying
`code`, `message` and `exit_code`. The command line publishes that identical
envelope for `--request-json`, so both transports can be read by one client.

`worktree_create` accepts the optional booleans `init_submodules`, `prepare`
and `verify`. They are off by default and report the observed state of each
step; `prepare` and `verify` require the matching configured command and are
rejected as `invalid_configuration` before any worktree or branch is created.

Mutating dry runs do not invoke lifecycle operations. A per-call authorization is
required only in an execution, that is, when `dry_run` is absent or `false`; a
dry run of a destructive operation succeeds without it. A destructive execute
accepts `authorization: "I_AUTHORIZE_THIS_CALL"` directly, or `confirm: true`,
from which that authorization is derived. A `confirm: false` sent together with
the literal is rejected as `authorization_mismatch`. A `cleanup` with a discard
additionally requires the separate boolean `discard_consent: true`. A
target-direct `create`, `complete` or `recover` has no safe simulation and is
rejected as `unsupported_dry_run` with exit code `3` when a dry run is
requested. Authorization is not retained across requests. Do not expose this
local service to untrusted clients. CLI JSON v1 and its entrypoint remain
unchanged.

## End-to-end verification

Run the real stdio client tests from the repository root:

```sh
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_mcp*.py' -v
MCP_E2E_EVIDENCE_DIR=<evidence-dir> \
  PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_mcp_e2e.py' -v
```

`test_mcp_e2e.py` uses isolated temporary Git repositories and launches the
stdio server as a subprocess. It exercises discovery and every public tool,
dry-run immutability, authorization and separate discard consent, transaction
recovery, worktree/ref/index/status effects, plus MCP-vs-Python-CLI completion
on independent equivalent repositories. When `MCP_E2E_EVIDENCE_DIR` is set,
each test writes its request/response trace there as JSON. No evidence or Git
fixture is written into the checked-out repository by default.

## Closing message

`worktree_complete` accepts `commit_title` and `commit_body` (optional strings).
They are validated as strings and included in the plan hash only for this operation.
The dry run publishes the composed `commit_subject` and `commit_body`; execute passes them
to the lifecycle. If missing, the manager uses the neutral fallback
`Complete <work_id> (generic closure)` / `No delivery description was available
at closure time.`.

## Merge strategy

`worktree_complete` accepts the optional string `merge_strategy` with the enum
values `squash` (default) and `preserve-history`. Squash integrates the branch
as one commit; preserve-history records an explicit merge commit that keeps the
branch commits. Neither strategy uses a fast-forward.

The field is validated as a string and against the enum before any mutation; a
value outside the enum is rejected as `invalid_request` with exit code 3. It is
included in the plan hash only for `worktree_complete`, so a preflight for one
strategy cannot execute the other and reports `plan_mismatch` with exit code 5.

A dry run publishes `data.merge_strategy` and the planned `mutations`:
`squash_merge` for squash, or `merge_no_ff` for preserve-history, followed by
`remove_worktree` and `delete_branch` in both cases. Execute returns
`merge_strategy` and `integrated_commit`; `squash_commit` is present only for
squash and equals `integrated_commit`. The transaction records the strategy and
the integrated commit. Recovery validates the parent shape recorded by the
strategy, reads a transaction without the field as squash, and reports an
unknown value as `invalid_journal` with exit code 5 while retaining evidence.
With `preserve-history`, a branch with no commits ahead of the base fails as
`operation_failed` with exit code 5 without a transaction or mutation.
