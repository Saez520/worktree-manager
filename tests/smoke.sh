#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
repo="$tmp/repo"
mkdir -p "$repo"
git -C "$repo" init -q -b main
git -C "$repo" config user.name test
git -C "$repo" config user.email test@example.invalid
printf base > "$repo/file"
printf '.worktrees/\n' > "$repo/.gitignore"
cat > "$repo/.worktree-manager.conf" <<EOF
state_dir=state
backup_dir=backups
backup_ref_prefix=manager/backups
branch_prefix=worktree/
lock_dir=locks
EOF
git -C "$repo" add file .gitignore .worktree-manager.conf
git -C "$repo" commit -qm base
"$ROOT/worktree.sh" --repo "$repo" create smoke --base main >/dev/null
test -d "$repo/.worktrees/smoke"
git -C "$repo/.worktrees/smoke" config user.name test
git -C "$repo/.worktrees/smoke" config user.email test@example.invalid
printf changed >> "$repo/.worktrees/smoke/file"
git -C "$repo/.worktrees/smoke" add file
git -C "$repo/.worktrees/smoke" commit -qm change
"$ROOT/worktree.sh" --repo "$repo" complete smoke --base main >/dev/null
test ! -e "$repo/.worktrees/smoke"
git -C "$repo" show main:file | grep -q changed

# The package worktree_manager is the only lifecycle. The retired shell engine
# must be absent and must not be referenced by the active tree. The forbidden
# names are written with a character-class break so that this test does not
# reintroduce them into the tree it scans.
engine_prefix='worktree-manager-'
for retired in "${engine_prefix}core.sh" "${engine_prefix}target-direct.sh"; do
  if [ -e "$ROOT/lib/$retired" ]; then
    printf 'retired shell engine file is present: %s\n' "$ROOT/lib/$retired" >&2
    exit 1
  fi
done
# The transition history records the retired surfaces as memory; it is the only
# file excluded from the scan of the active guide.
forbidden_pattern="${engine_prefix}[a-z-]*[.]sh|worktree[_]manager[_]main[_]legacy|target[-]direct[-]transport|refs[/]flowtask[/]backups|[.]flowtask[/]backups|runner[-]constructor[-]target[-]direct"
if grep -R -E -n "$forbidden_pattern" \
    "$ROOT/worktree.sh" "$ROOT/worktree_manager" "$ROOT/tests" "$ROOT/docs" \
    --exclude=history-bash-to-python.md; then
  printf '%s\n' 'the active tree references a forbidden identifier' >&2
  exit 1
fi
echo 'standalone smoke tests passed'
