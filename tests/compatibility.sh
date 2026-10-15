#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# All scenarios below use private temporary repositories and remain independent
# of any orchestration checkout or worktree naming.
# Keep the historical shell fixture, but do not treat it as the compatibility
# suite: exercise public legacy output, JSON side-effect parity, and target
# transaction states independently below.
bash "$ROOT/tests/smoke.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
init_repo() {
  local path="$1"
  mkdir -p "$path"
  git -C "$path" init -q -b main
  git -C "$path" config user.name compatibility
  git -C "$path" config user.email compatibility@example.invalid
  printf base > "$path/file"
  printf '.worktrees/\n' > "$path/.gitignore"
  git -C "$path" add file .gitignore
  git -C "$path" commit -qm base
}

# Legacy `list` is still exactly Git porcelain, and choosing JSON does not
# change the registry/worktree state.
repo="$tmp/legacy"
init_repo "$repo"
legacy_out="$("$ROOT/worktree.sh" --repo "$repo" list)"
expected="$(git -C "$repo" worktree list --porcelain)"
[[ "$legacy_out" == "$expected" ]]
before="$(git -C "$repo" worktree list --porcelain)"
json_out="$("$ROOT/worktree.sh" --json --repo "$repo" list)"
printf '%s' "$json_out" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["contract_version"] == 1 and d["operation"] == "list"'
after="$(git -C "$repo" worktree list --porcelain)"
[[ "$before" == "$after" ]]

# Target-direct lifecycle: create and staged-only link are exercised against a
# real submodule checkout. A modified parent index is detected as drift by
# abort and must be left intact for explicit recovery.
target="$tmp/target"
parent="$tmp/parent"
init_repo "$target"
init_repo "$parent"
git -C "$parent" -c protocol.file.allow=always submodule add -q "$target" modules/target
git -C "$parent" commit -qam 'add target submodule'
target="$parent/modules/target"
args=(--repo "$target" --parent-repo "$parent")
"$ROOT/worktree.sh" "${args[@]}" create td-abort --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
parent_index_before="$(git -C "$parent" ls-files --stage)"
"$ROOT/worktree.sh" "${args[@]}" link-parent td-abort --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
git -C "$parent" ls-files --stage -- modules/target | grep -q '^160000 '
set +e
"$ROOT/worktree.sh" "${args[@]}" abort td-abort --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null 2>&1
abort_status=$?
set -e
[[ $abort_status -eq 6 ]]
[[ "$(git -C "$parent" ls-files --stage)" == "$parent_index_before" ]]

# Successful target-direct recovery restores the staged-only parent index from
# its recorded snapshot, and successful complete removes the target worktree.
"$ROOT/worktree.sh" "${args[@]}" create td-recover --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
recover_index_before="$(git -C "$parent" ls-files --stage)"
"$ROOT/worktree.sh" "${args[@]}" link-parent td-recover --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
recover_tx="wt-td-recover"
"$ROOT/worktree.sh" "${args[@]}" recover "$recover_tx" >/dev/null
[[ "$(git -C "$parent" ls-files --stage)" == "$recover_index_before" ]]

"$ROOT/worktree.sh" "${args[@]}" create td-complete --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
"$ROOT/worktree.sh" "${args[@]}" complete td-complete --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
[[ ! -e "$target/.worktrees/td-complete" ]]

# Refuse dirty destination without changing it or creating a stash; JSON must
# report a failure rather than making the consent implicit.
"$ROOT/worktree.sh" --repo "$repo" create dirty --base main >/dev/null
printf dirty >> "$repo/.worktrees/dirty/file"
set +e
"$ROOT/worktree.sh" --json --repo "$repo" complete dirty --base main >"$tmp/out.json" 2>"$tmp/err"
dirty_status=$?
set -e
[[ $dirty_status -ne 0 ]]
python3 - "$tmp/out.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1])); assert d['result'] in ('failure','pending_intervention')
PY
git -C "$repo/.worktrees/dirty" status --porcelain | grep -q 'file'
[[ -z "$(git -C "$repo" stash list)" ]]

# Preserve-dirty success restores staged, unstaged and untracked destination
# changes after the merge without creating a stash.
preserve_repo="$tmp/preserve"
init_repo "$preserve_repo"
"$ROOT/worktree.sh" --repo "$preserve_repo" create preserve --base main >/dev/null
printf 'feature\n' > "$preserve_repo/.worktrees/preserve/feature"
git -C "$preserve_repo/.worktrees/preserve" add feature
git -C "$preserve_repo/.worktrees/preserve" -c user.name=compatibility -c user.email=compatibility@example.invalid commit -qm feature
"$ROOT/worktree.sh" --repo "$preserve_repo" complete preserve --base main >/dev/null
printf 'staged\n' >> "$preserve_repo/file"
git -C "$preserve_repo" add file
printf 'unstaged\n' >> "$preserve_repo/file"
printf 'untracked\n' > "$preserve_repo/local.txt"
"$ROOT/worktree.sh" --repo "$preserve_repo" complete preserve --base main --preserve-dirty >/dev/null
git -C "$preserve_repo" diff --cached --quiet && { echo 'expected staged changes restored' >&2; exit 1; }
git -C "$preserve_repo" diff --quiet && { echo 'expected unstaged changes restored' >&2; exit 1; }
[[ -f "$preserve_repo/local.txt" ]]
[[ -z "$(git -C "$preserve_repo" stash list)" ]]

# Locks are not stolen while their recorded owner is alive.
lock="$tmp/held.lock"
mkdir "$lock"; echo "$$" > "$lock/owner_pid"
! (source "$ROOT/lib/worktree-manager-target-direct.sh"; TD_LOCKS=(); target_direct_lock_one "$lock" test)
rm -rf "$lock"

# The version guard is exact and must reject a different advertised version.
PATH="$tmp/no-git:$PATH"
mkdir -p "$tmp/no-git"
cat > "$tmp/no-git/git" <<'SH'
#!/bin/sh
if [ "$1" = --version ]; then echo 'git version 2.53.0'; exit 0; fi
exec /usr/bin/git "$@"
SH
chmod +x "$tmp/no-git/git"
set +e
PATH="$tmp/no-git:$PATH" "$ROOT/worktree.sh" "${args[@]}" create rejected --target submodule --submodule-path modules/rejected --link-parent staged-only >/dev/null 2>&1
version_status=$?
set -e
[[ $version_status -eq 7 ]]
[[ ! -e "$target/.worktrees/rejected" ]]

echo 'compatibility tests passed'
