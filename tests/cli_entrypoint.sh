#!/usr/bin/env bash
set -euo pipefail
ROOT="${WORKTREE_MANAGER_SNAPSHOT:-/private/tmp/worktree-manager-phase-4-snapshot-final}"
[[ "$ROOT" = /* ]] || { echo 'snapshot root must be absolute' >&2; exit 3; }
[[ -f "$ROOT/worktree_manager/cli.py" ]] || { echo 'missing canonical snapshot CLI' >&2; exit 3; }
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m worktree_manager "$@"
