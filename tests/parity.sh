#!/usr/bin/env bash
# Check that the canonical Python CLI resolves identically from unrelated cwd values.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENTRY="$ROOT/tests/cli_entrypoint.sh"
TMP="${PARITY_TMPDIR:-$(mktemp -d)}"
mkdir -p "$TMP/repo" "$TMP/elsewhere"
cleanup() { [[ ${KEEP_PARITY_TRACES:-0} == 1 ]] || rm -rf "$TMP"; }
trap cleanup EXIT
git -C "$TMP/repo" init -q -b main
git -C "$TMP/repo" config user.name Parity
git -C "$TMP/repo" config user.email parity@example.invalid
printf 'base\n' > "$TMP/repo/base"
printf '.worktrees/\n' > "$TMP/repo/.gitignore"
git -C "$TMP/repo" add . && git -C "$TMP/repo" commit -qm base
for cwd in "$TMP/repo" "$TMP/elsewhere"; do
  (cd "$cwd" && "$ENTRY" --repo "$TMP/repo" --json list) > "$TMP/$(basename "$cwd").json"
done
diff -u "$TMP/repo.json" "$TMP/elsewhere.json"
missing="$TMP/missing"
if WORKTREE_MANAGER_SNAPSHOT="$missing" "$ENTRY" --repo "$TMP/repo" list >"$TMP/missing.out" 2>"$TMP/missing.err"; then
  echo 'parity unexpectedly accepted a missing canonical CLI' >&2; exit 1
fi
grep -q 'missing canonical snapshot CLI' "$TMP/missing.err"
echo 'Canonical Python CLI cwd-resolution parity passed.'
