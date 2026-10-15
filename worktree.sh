#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# This repository is the sole owner of the implementation.
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/worktree-manager-core.sh"

worktree_manager_main "$@"
