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

A rejected call publishes the same nine-key envelope as an accepted one, with
`result` set to `failure` or `pending_intervention` and `error` carrying
`code`, `message` and `exit_code`. The command line publishes that identical
envelope for `--request-json`, so both transports can be read by one client.

`worktree_create` accepts the optional booleans `init_submodules`, `prepare`
and `verify`. They are off by default and report the observed state of each
step; `prepare` and `verify` require the matching configured command and are
rejected as `invalid_configuration` before any worktree or branch is created.

Mutating dry runs do not invoke lifecycle operations. Complete, cleanup,
recover and prune require per-call `authorization: "I_AUTHORIZE_THIS_CALL"`;
cleanup with discard additionally requires the separate boolean
`discard_consent: true`.
Authorization is not retained across requests. Do not expose this local service
to untrusted clients. CLI JSON v1 and its entrypoint remain unchanged.

## End-to-end verification

Run the real stdio client tests from the repository root:

```sh
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_mcp*.py' -v
MCP_E2E_EVIDENCE_DIR=/private/tmp/worktree-mcp-evidence \
  PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_mcp_e2e.py' -v
```

`test_mcp_e2e.py` uses isolated temporary Git repositories and launches the
stdio server as a subprocess. It exercises discovery and every public tool,
dry-run immutability, authorization and separate discard consent, transaction
recovery, worktree/ref/index/status effects, plus MCP-vs-Python-CLI completion
on independent equivalent repositories. When `MCP_E2E_EVIDENCE_DIR` is set,
each test writes its request/response trace there as JSON. No evidence or Git
fixture is written into the checked-out repository by default.
