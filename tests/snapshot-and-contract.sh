#!/usr/bin/env bash
set -euo pipefail
SNAPSHOT="${SNAPSHOT:-/private/tmp/worktree-manager-phase-1-snapshot}"
test -d "$SNAPSHOT"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$(sed -n 's/^source=//p' "$SNAPSHOT/manifest.txt")"
test -n "$SOURCE" && test -d "$SOURCE"
test "$(git -C "$SOURCE" rev-parse HEAD)" = "$(sed -n 's/^head=//p' "$SNAPSHOT/manifest.txt")"
test "$(git -C "$SOURCE" symbolic-ref --short HEAD)" = "$(sed -n 's/^branch=//p' "$SNAPSHOT/manifest.txt")"
test "$(shasum -a 256 "$(sed -n 's/^index_path=//p' "$SNAPSHOT/manifest.txt")" | awk '{print $1}')" = "$(sed -n 's/^index_sha256=//p' "$SNAPSHOT/manifest.txt")"
git -C "$SOURCE" status --porcelain=v2 --branch --untracked-files=all > "${TMPDIR:-/tmp}/worktree-manager-source-status.$$"
trap 'rm -f "${TMPDIR:-/tmp}/worktree-manager-source-status.$$"' EXIT
cmp "$SNAPSHOT/status.porcelain-v2" "${TMPDIR:-/tmp}/worktree-manager-source-status.$$"
(cd "$SNAPSHOT" && shasum -a 256 -c SHA256SUMS)
for artifact in manifest.txt index.bytes index.entries status.porcelain-v2 staged.patch unstaged.patch untracked.paths0 submodules.txt worktrees.txt remotes.txt; do
  test -s "$SNAPSHOT/$artifact" || { echo "snapshot missing $artifact" >&2; exit 1; }
done
test -s "$SNAPSHOT/untracked/.flowtask/scripts/worktree-adapter.sh"
CONTRACT="$ROOT/docs/cli-contract-v1.md"
for term in contract_version tool_version pending_intervention no_pending_work legacy target-direct recovery; do
  grep -qi "$term" "$CONTRACT" || { echo "contract missing $term" >&2; exit 1; }
done
echo "snapshot and contract checks passed (source=$SOURCE head=$(git -C "$SOURCE" rev-parse HEAD))"
