# CLI output contract

The default presentation is human-readable. `--json` explicitly selects one JSON document on stdout; diagnostics remain on stderr. JSON objects contain `contract_version` (integer, currently `1`), `tool_version` (string, currently `1.0.0`), `operation`, `result`, `data`, `warnings`, and `error`. `data` is an object whose fields depend on the operation and result; examples include `path`, `branch`, `worktree`, `pruned`, and `recovered`. There is no general `data.output` field: the dispatcher’s human-readable text is not included in the JSON data object.

`result` is `success`, `failure`, `pending_intervention`, or `no_pending_work`. Errors are objects with stable `code`, human `message`, and public `exit_code`. Exit codes are 0 success/no pending work, 2 usage, 3 invalid configuration/identity, 4 resource lock, 5 conflict/intervention, and 6 access/dependency. The legacy entrypoint and its codes remain unchanged when `--json` is absent. Errors whose legacy text does not provide a reliable subtype are reported as `operation_failed` (exit 5); clients should rely on the stable code, not parse the message.

`--version` prints the tool version. The contract version describes the JSON schema and is independent from the tool version. Breaking schema changes require a new contract version. Legacy invocations do not opt into JSON implicitly; `list` retains Git porcelain output without `--json`. JSON changes presentation only and does not authorize, suppress, or alter lifecycle effects, locks, journals, backups, consent, or recovery.

## Protocol requests

`--request-json <file|->` reads one canonical request document and publishes the same nine-key envelope as the MCP transport, with or without `--json`: `contract_version`, `tool_version`, `operation`, `repository`, `result`, `data`, `warnings`, `error` and `transaction_id`. The request must not be combined with a subcommand or with any other flag; `--json` is accepted and does not change the published document. `operation` names the tool (`worktree_create`, `worktree_list`, …), `repository` is the absolute repository path, `error` carries `code`, `message` and `exit_code`, and `transaction_id` is `null` when no transaction exists. Accepted and rejected requests publish the same shape, so a client never has to parse two document formats.

## Create options

`create` accepts `--init-submodules`, `--prepare` and `--verify`; they are off by default, so a repository without that configuration behaves exactly as before. The reported states are the observed ones: `init_submodules_result` is `not_requested` or `initialized`, and `prepare` and `verify` are `skipped`, `passed` or `failed`. `--prepare` and `--verify` require `prepare_command` and `verify_command` in the configuration; without them the request is rejected as `invalid_configuration` before any worktree or branch exists. A failing step keeps the worktree and its branch for inspection instead of discarding them.

## Compatibility and recovery

The standalone commands are `create`, `complete`, `cleanup`, `recover`, `list`, and `prune`; target-direct operations include `link-parent`, `abort`, `complete`, and `recover`. Existing legacy invocations remain human-readable and preserve their legacy exit codes and `list` porcelain format. A failed destination-state restoration is reported as `pending_intervention`; preserve-dirty backups and transaction evidence are retained for human intervention. Invalid descriptor/drift, lock contention, absent dependencies, and access failures are failures, not successful recovery. A recover request does not discard state.

## Verification record

Re-executed from the standalone checkout on 2026-10-14 after the usage/help/fixture fixes (working tree based at `85500ce6a7f5bab76ad8ff969328242bcde047ed`):

| Command | Result |
|---|---|
| `bash tests/cli-usage.sh` | passed |
| `bash tests/cli-json.sh` | passed |
| `bash tests/compatibility.sh` | passed |
| `bash tests/snapshot-and-contract.sh` | passed after snapshot-gate hardening |
| `bash tests/smoke.sh` | passed |

The usage suite additionally parses each `--json` pre-dispatch usage failure (unknown option, unknown/missing command, missing global value, and invalid `--version` arity), checks stable exit code 2, and checks help syntax for target-direct `complete` and `recover`. The compatibility suite is independent of any orchestration worktree path. Snapshot SHA-256 manifest validation and source HEAD/branch/index plus exact porcelain-status checks were executed by `tests/snapshot-and-contract.sh`; all reported `OK`. The snapshot is a manifest, raw index, patches, path inventory and metadata sufficient to reconstruct the recorded dirty state; it is not itself a checked-out working tree. This suite verifies recorded artifact integrity and source identity, not a fresh end-to-end reconstruction. This execution confirms the source identity and recorded status match the snapshot at test time; it does not certify every aspect of Phase 1 or perform a fresh checkout/reconstruction. No merge, complete, cleanup, discard, or other lifecycle operation was run on Phase 1. The source worktree remains outside the functional target. No claim is made here that the snapshot alone reconstructs submodule object stores unavailable locally.
