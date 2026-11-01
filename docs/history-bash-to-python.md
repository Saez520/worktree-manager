# History: from shell backend to Python backend

This document is project memory, not a contract. It does not repeat the current
contracts and contains no shell instructions. The verifiable behavior
lives in [cli-contract-v1.md](cli-contract-v1.md) and in
[mcp-contract.md](mcp-contract.md).

## What there was

The manager implemented its lifecycle in shell. That backend lived in `worktree.sh`
and in two modules under the `lib/` directory:
`lib/worktree-manager-core.sh` for the parent-only cycle and
`lib/worktree-manager-target-direct.sh` for the target-direct path. The same
repository maintained the Python implementation in parallel, and the harness
`tests/parity.sh` compared both backends against each other: it started an independent
test repository for each implementation and required them to publish the
same exit state, the same JSON output, and the same repository state.

## What there is

`worktree.sh` validates that `python3` is available and that the entrypoint
`worktree_manager/__main__.py` exists, and then runs
`python3 -m worktree_manager`. The `worktree_manager` package is the only
lifecycle implementation: there is no alternative shell engine. It consists of
16 modules, plus the package marker `__init__.py` and the entrypoint
`__main__.py`. The MCP service is published over stdio.

## Why

A single implementation avoids two divergent behaviors for the same
operation. The harness compared equivalence between the two backends, not the
correctness of each one: it showed that one path replicated the other, not that
either one was wrong. The package uses only the Python standard
library, with no external dependencies.

## Real status of `tests/parity.sh`

`tests/parity.sh` is 25 lines long. It does not compare backends: it runs `list --json`
from two different working directories and requires both JSON documents
to be identical, and checks that invocation without the canonical CLI available is
rejected. Its name keeps the parity reference; its content verifies
working-directory resolution.

## Where the evidence lives

The evidence of the retired phases remains in tags `phase-3-4`
(`8c7a569`) and `phase-5` (`671effb`). The commit that purges the evidence from the active
tree traces it in its own message. Tags are not re-published and
history is not rewritten; previous content is inspected with `git show`.

## What it is not

This document is not a contract, does not duplicate the contracts, and gives no
shell instructions. For current behavior, see
[cli-contract-v1.md](cli-contract-v1.md) and [mcp-contract.md](mcp-contract.md).
