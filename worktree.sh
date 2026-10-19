#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'worktree manager requires Python 3 (python3) on PATH; install Python 3 and retry.' >&2
    exit 127
fi

if [ ! -f "$script_dir/worktree_manager/__main__.py" ]; then
    printf '%s\n' "worktree manager Python entry point is missing: $script_dir/worktree_manager/__main__.py" >&2
    exit 126
fi

PYTHONPATH="$script_dir${PYTHONPATH+:$PYTHONPATH}"
export PYTHONPATH
exec python3 -m worktree_manager "$@"
