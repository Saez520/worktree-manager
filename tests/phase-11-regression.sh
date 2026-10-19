#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

run_section() {
  local label="$1" script="$2"
  printf '== %s ==\n' "$label"
  bash "$ROOT/tests/$script"
  printf 'PASS %s\n' "$label"
}

run_section inventory english-inventory.sh
run_section usage cli-usage.sh
run_section json cli-json.sh
run_section compatibility compatibility.sh
run_section smoke smoke.sh
printf '%s\n' 'MCP: absent/not verified; no Worktree Manager MCP surface is claimed.'
printf '%s\n' 'Phase 11 regression passed.'
