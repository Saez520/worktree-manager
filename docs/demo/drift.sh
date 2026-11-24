#!/usr/bin/env bash
# Base-drift demo: main moves after `create`, then `complete` runs.
#
#   docs/demo/drift.sh [REF]
#
# Without REF it runs the checkout this script lives in. With REF (a tag,
# branch or commit, e.g. demo/pre-fix) it exports that ref with `git archive`
# into a temporary directory and runs the scenario against it, so the same
# script reproduces the bug and the fix. Everything is created in a temporary
# directory that is removed on exit; no real repository is touched.
set -uo pipefail

HERE="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/wm-drift-demo.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

if [[ $# -ge 1 ]]; then
  SRC="$WORK/src"; mkdir -p "$SRC"
  git -C "$HERE" archive "$1" | tar -x -C "$SRC" || { echo "cannot export ref '$1'" >&2; exit 3; }
  LABEL="$1 ($(git -C "$HERE" rev-parse --short "$1"))"
else
  SRC="$HERE"; LABEL="working tree ($(git -C "$HERE" rev-parse --short HEAD))"
fi
export PYTHONPATH="$SRC"
export GIT_AUTHOR_NAME=Demo GIT_AUTHOR_EMAIL=demo@example.invalid
export GIT_COMMITTER_NAME=Demo GIT_COMMITTER_EMAIL=demo@example.invalid
# Run from a neutral directory: `python3 -m` puts the current directory ahead of
# PYTHONPATH, which would silently load another checkout of the package.
wm() { (cd "$WORK" && python3 -m worktree_manager --json --repo "$REPO" "$@"); }
field() { python3 -c 'import json,sys; d=json.load(sys.stdin); e=d.get("error") or {}; print(e.get("code") or d["result"])'; }

REPO="$WORK/repo"; mkdir "$REPO"
git -C "$REPO" init -q -b main
printf 'worktrees/\n' > "$REPO/.gitignore"; echo base > "$REPO/app.txt"
printf 'state_dir=state\nbranch_prefix=worktree/\n' > "$REPO/.worktree-manager.conf"
git -C "$REPO" add . && git -C "$REPO" commit -qm base
sed -i.bak 's#^worktrees/#.worktrees/#' "$REPO/.gitignore" && rm "$REPO/.gitignore.bak"
git -C "$REPO" commit -qam "ignore .worktrees"

echo "== subject:  $LABEL"
echo "== code under test: $(cd "$WORK" && python3 -c 'import worktree_manager as m; print(m.__file__.replace("'"$WORK"'", "<tmp>").replace("'"$HERE"'", "<checkout>"), m.__version__)')"
echo "== 1. create worktree 'feat' from main"
WT="$(wm create feat | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["path"])')"
echo feature > "$WT/feature.txt"; git -C "$WT" add . && git -C "$WT" commit -qm "feature"
VALIDATED_TREE="$(git -C "$REPO" rev-parse worktree/feat^{tree})"
echo "   validated branch tree : $VALIDATED_TREE"

echo "== 2. main moves on (drift.txt), after the branch was built"
echo drift > "$REPO/drift.txt"; git -C "$REPO" add drift.txt; git -C "$REPO" commit -qm "drift on main"
MAIN_BEFORE="$(git -C "$REPO" rev-parse main)"

echo "== 3. complete feat (squash)"
OUT="$(wm complete feat 2>&1)"; RC=$?
echo "   exit code             : $RC"
echo "   outcome               : $(printf '%s' "$OUT" | field)"
FINAL_TREE="$(git -C "$REPO" rev-parse main^{tree})"
echo "   final main tree       : $FINAL_TREE"
echo "== verdict"
if [[ "$(git -C "$REPO" rev-parse main)" != "$MAIN_BEFORE" ]]; then
  if [[ "$FINAL_TREE" != "$VALIDATED_TREE" ]]; then
    echo "   INTEGRATED SILENTLY: final tree differs from the validated branch tree (extra: $(git -C "$REPO" diff --name-only "$VALIDATED_TREE" "$FINAL_TREE" | tr '\n' ' '))"
  else
    echo "   integrated, final tree == validated branch tree"
  fi
else
  echo "   REJECTED: main untouched, branch and worktree kept ($(git -C "$REPO" branch --list 'worktree/feat' | tr -d ' *+'))"
fi
