# CLI output contract

The default presentation is human-readable. `--json` explicitly selects one JSON document on stdout; diagnostics remain on stderr. JSON objects contain `contract_version` (integer, currently `1`), `tool_version` (string, currently `1.0.0`), `operation`, `result`, `data`, `warnings`, and `error`. `data` is an object whose fields depend on the operation and result; examples include `path`, `branch`, `worktree`, `pruned`, and `recovered`. There is no general `data.output` field: the dispatcher’s human-readable text is not included in the JSON data object.

`result` is `success`, `failure`, `pending_intervention`, or `no_pending_work`. Errors are objects with stable `code`, human `message`, and public `exit_code`. Exit codes are 0 success/no pending work, 2 usage, 3 invalid configuration/identity, 4 resource lock, 5 conflict/intervention, and 6 access/dependency. The legacy entrypoint and its codes remain unchanged when `--json` is absent. Errors whose legacy text does not provide a reliable subtype are reported as `operation_failed` (exit 5); clients should rely on the stable code, not parse the message.

`--version` prints the tool version. The contract version describes the JSON schema and is independent from the tool version. Breaking schema changes require a new contract version. Legacy invocations do not opt into JSON implicitly; `list` retains Git porcelain output without `--json`. JSON changes presentation only and does not authorize, suppress, or alter lifecycle effects, locks, journals, backups, consent, or recovery.

## Protocol requests

`--request-json <file|->` reads one canonical request document and publishes the same nine-key envelope as the MCP transport, with or without `--json`: `contract_version`, `tool_version`, `operation`, `repository`, `result`, `data`, `warnings`, `error` and `transaction_id`. The request must not be combined with a subcommand or with any other flag; `--json` is accepted and does not change the published document. `operation` names the tool (`worktree_create`, `worktree_list`, …), `repository` is the absolute repository path, `error` carries `code`, `message` and `exit_code`, and `transaction_id` is `null` when no transaction exists. Accepted and rejected requests publish the same shape, so a client never has to parse two document formats.

## Create options

`create` accepts `--init-submodules`, `--prepare` and `--verify`; they are off by default, so a repository without that configuration behaves exactly as before. The reported states are the observed ones: `init_submodules_result` is `not_requested` or `initialized`, and `prepare` and `verify` are `skipped`, `passed` or `failed`. `--prepare` and `--verify` require `prepare_command` and `verify_command` in the configuration; without them the request is rejected as `invalid_configuration` before any worktree or branch exists. A failing step keeps the worktree and its branch for inspection instead of discarding them.

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
```

The usage suite parses each pre-dispatch usage failure, including the unknown option, the unknown or missing command, the missing global value and an invalid `--version` arity, checks the stable exit code `2`, and checks the help syntax of the target-direct `complete` and `recover` actions. The compatibility suite is independent of any orchestration worktree path. Every publication records the date, the commit and the output of these commands, and it does not cite a suite that no longer exists.

## Mensaje de cierre

`complete` acepta `--title TEXTO` y `--body TEXTO` opcionales. El gestor
compone el asunto y el cuerpo de forma determinista: normaliza el titulo a una
sola linea, normaliza CRLF a LF en el cuerpo y garantiza que el `work_id`
aparezca en el asunto (lo agrega como ` [work_id]` si falta). Si no se pasa
titulo, el asunto es `Complete <work_id> (generic closure)` y el cuerpo es
`No delivery description was available at closure time.` El cuerpo solo se
escribe si no esta vacio. Ambos valores quedan en `meta.json` como
`commit_subject` y `commit_body`, y el dry-run los publica. Un cambio de
titulo o cuerpo entre preflight y execute provoca `plan_mismatch`.
