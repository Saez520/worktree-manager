#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
(cd "$tmp" && "$ROOT/worktree.sh" --version) | grep -qx '1.0.0'
help="$(cd "$tmp" && "$ROOT/worktree.sh" --help)"
printf '%s\n' "$help" | grep -q 'target-direct'
printf '%s\n' "$help" | grep -q 'complete <work-id> --target submodule'
printf '%s\n' "$help" | grep -q 'recover \[<transaction-id>\].*--target submodule'
for args in '--json --wat' '--json bogus' '--json' '--json --repo' '--json --version extra'; do
  set +e
  (cd "$tmp" && "$ROOT/worktree.sh" $args) >"$tmp/out" 2>"$tmp/err"
  status=$?
  set -e
  test "$status" -eq 2 || { echo "expected usage exit 2 for: $args (got $status)" >&2; exit 1; }
  python3 - "$tmp/out" <<'PYJSON'
import json,sys
obj=json.load(open(sys.argv[1]))
assert obj['contract_version']==1 and obj['result']=='failure'
assert obj['error']['code']=='usage_error' and obj['error']['exit_code']==2
PYJSON
done
for args in '--wat' 'bogus' '--repo'; do
  set +e
  (cd "$tmp" && "$ROOT/worktree.sh" $args) >/dev/null 2>&1
  status=$?
  set -e
  test "$status" -eq 2 || { echo "expected usage exit 2 for: $args (got $status)" >&2; exit 1; }
done
if (cd "$tmp" && "$ROOT/worktree.sh" --repo "$tmp" create invalid --unknown) 2>/dev/null; then
  echo 'expected invalid repository to fail' >&2; exit 1
fi
test ! -e "$tmp/.worktrees"
echo 'CLI usage tests passed'
