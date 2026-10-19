#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/worktree-compat.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
mkdir -p "$tmp/repo with spaces"
git -C "$tmp/repo with spaces" init -q
git -C "$tmp/repo with spaces" -c user.name=Test -c user.email=test@example.invalid commit --allow-empty -qm initial

for args in '--version' 'list --json' 'list' 'recover' 'prune --json'; do
    set +e
    (cd "$tmp" && "$root/worktree.sh" --repo "$tmp/repo with spaces" $args) >"$tmp/shim.out" 2>"$tmp/shim.err"
    shim_status=$?
    (cd "$tmp" && PYTHONPATH="$root${PYTHONPATH+:$PYTHONPATH}" python3 -m worktree_manager --repo "$tmp/repo with spaces" $args) >"$tmp/direct.out" 2>"$tmp/direct.err"
    direct_status=$?
    set -e
    [ "$shim_status" -eq "$direct_status" ] || { echo "status mismatch for: $args" >&2; exit 1; }
    cmp "$tmp/shim.out" "$tmp/direct.out" || { echo "stdout mismatch for: $args" >&2; exit 1; }
    cmp "$tmp/shim.err" "$tmp/direct.err" || { echo "stderr mismatch for: $args" >&2; exit 1; }
done

mkdir "$tmp/no-python"
ln -s "$(command -v sh)" "$tmp/no-python/sh"
ln -s "$(command -v dirname)" "$tmp/no-python/dirname"
set +e
PATH="$tmp/no-python" "$root/worktree.sh" list >"$tmp/missing.out" 2>"$tmp/missing.err"
status=$?
set -e
[ "$status" -eq 127 ] || { echo "expected missing-python status 127, got $status" >&2; exit 1; }
grep -q 'requires Python 3' "$tmp/missing.err"
[ ! -s "$tmp/missing.out" ]

echo 'worktree compatibility checks passed'
