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
printf ".worktrees/\n" > "$repo/.gitignore"
cat > "$repo/.worktree-manager.conf" <<EOF
state_dir=state
backup_dir=backups
backup_ref_prefix=manager/backups
branch_prefix=worktree/
lock_dir=locks
EOF
git -C "$repo" add file .gitignore .worktree-manager.conf
git -C "$repo" commit -qm base
"$ROOT/worktree.sh" --json --repo "$repo" list > "$tmp/result.json"
python3 - "$tmp/result.json" <<'PY'
import json, sys
result = json.load(open(sys.argv[1], encoding="utf-8"))
assert result["contract_version"] == 1
assert result["tool_version"] == "1.0.0"
assert result["operation"] == "list"
assert result["result"] == "success"
assert len(result["data"]["worktrees"]) == 1
assert result["data"]["worktrees"][0]["path"].endswith("/repo")
assert "output" not in result["data"]
assert result["warnings"] == [] and result["error"] is None
PY
"$ROOT/worktree.sh" --json --repo "$repo" create sample > "$tmp/create.json"
"$ROOT/worktree.sh" --json --repo "$repo" recover > "$tmp/recover.json"
"$ROOT/worktree.sh" --json --repo "$repo" prune > "$tmp/prune.json"
python3 - "$tmp/create.json" "$tmp/recover.json" "$tmp/prune.json" <<'PY2'
import json, sys
create, recover, prune = [json.load(open(path, encoding="utf-8")) for path in sys.argv[1:]]
assert create["operation"] == "create" and create["result"] == "success"
assert create["data"]["branch"] == "worktree/sample"
assert recover["operation"] == "recover" and recover["result"] == "no_pending_work"
assert prune["operation"] == "prune" and prune["result"] == "no_pending_work"
assert isinstance(prune["data"]["pruned"], int)
PY2
echo 'CLI JSON tests passed' 
