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
! grep -R -E 'refs/flowtask/backups|\.flowtask/backups|runner-constructor-target-direct|target-direct-transport' "$ROOT"/worktree.sh "$ROOT"/lib
echo 'standalone smoke tests passed'
