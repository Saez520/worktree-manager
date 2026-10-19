#!/usr/bin/env bash
# Differential behavior matrix; every implementation gets an independent Git fixture.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BASH_CLI="${BASH_CLI:-$ROOT/worktree.sh}"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"; export PYTHONPATH
TMP="${PARITY_TMPDIR:-$(mktemp -d)}"
mkdir -p "$TMP"
cleanup() {
  if [[ ${KEEP_PARITY_TRACES:-0} == 1 || ${PARITY_FAILED:-0} == 1 ]]; then
    echo "parity traces retained: $TMP" >&2
  else
    rm -rf "$TMP"
  fi
}
trap cleanup EXIT
mkdir -p "$TMP/traces"
fail() { PARITY_FAILED=1; echo "parity: $*" >&2; exit 1; }
init_repo() {
  local r="$1"; mkdir -p "$r"; git -C "$r" init -q -b main
  git -C "$r" config user.name Parity; git -C "$r" config user.email parity@example.invalid
  printf 'base\n' > "$r/file"; printf '.worktrees/\nstate/\nbackups/\nlocks/\n' > "$r/.gitignore"
  cat > "$r/.worktree-manager.conf" <<'EOF'
state_dir=state
backup_dir=backups
backup_ref_prefix=manager/backups
branch_prefix=worktree/
lock_dir=locks
EOF
  git -C "$r" add file .gitignore .worktree-manager.conf; git -C "$r" commit -qm base
}
run_pair() {
  local label="$1"; shift; local bash_repo="$TMP/$label/bash" py_repo="$TMP/$label/python"
  init_repo "$bash_repo"; init_repo "$py_repo"
  local -a command=("$@")
  set +e
  "$BASH_CLI" --repo "$bash_repo" "${command[@]}" >"$TMP/traces/$label.bash.out" 2>"$TMP/traces/$label.bash.err"; local bs=$?
  python3 -m worktree_manager --repo "$py_repo" "${command[@]}" >"$TMP/traces/$label.python.out" 2>"$TMP/traces/$label.python.err"; local ps=$?
  set -e
  printf '%s\n' "$bs" > "$TMP/traces/$label.bash.status"; printf '%s\n' "$ps" > "$TMP/traces/$label.python.status"
  [[ $bs == "$ps" ]] || fail "$label exit status: bash=$bs python=$ps (traces: $TMP/traces)"
  if [[ " ${command[*]} " == *" --json "* ]]; then
    jq -e . "$TMP/traces/$label.bash.out" >/dev/null || fail "$label Bash emitted invalid JSON"
    jq -e . "$TMP/traces/$label.python.out" >/dev/null || fail "$label Python emitted invalid JSON"
    jq -S 'del(.error.message) | if (.data.worktrees|type)=="array" then del(.data.worktrees[].path) else . end | if .operation=="create" then del(.data.path) else . end' "$TMP/traces/$label.bash.out" > "$TMP/a"
    jq -S 'del(.error.message) | if (.data.worktrees|type)=="array" then del(.data.worktrees[].path) else . end | if .operation=="create" then del(.data.path) else . end' "$TMP/traces/$label.python.out" > "$TMP/b"
    diff -u "$TMP/a" "$TMP/b" || fail "$label JSON contract differs"
  fi
  git -C "$bash_repo" status --porcelain=v2 --untracked-files=all > "$TMP/a"
  git -C "$py_repo" status --porcelain=v2 --untracked-files=all > "$TMP/b"
  diff -u "$TMP/a" "$TMP/b" || fail "$label base repository status differs"
}
# Envelope, empty-state semantics, and both output modes.
run_pair list-json --json list
run_pair list-human list
for impl in bash python; do
  out="$TMP/traces/list-human.$impl.out"
  if [[ $impl == bash ]]; then grep -q '^worktree ' "$out" || fail 'Bash legacy list is not porcelain'; else grep -q '^worktree ' "$out" || fail 'Python legacy list is not porcelain'; fi
done
run_pair recover-empty --json recover
run_pair prune-empty --json prune
# Strict input failures must be side-effect free and agree on public status.
run_pair unknown-command --json not-a-command
run_pair unknown-option --not-an-option list
# Lifecycle fixture: create then compare the resulting worktree and branch.
run_pair create --json create parity-create --base main
for impl in bash python; do
  repo="$TMP/create/$impl"; git -C "$repo" worktree list --porcelain | sed -E "s#$repo#<repo>#g; s/^HEAD .*/HEAD <sha>/" > "$TMP/$impl-created"
done
diff -u "$TMP/bash-created" "$TMP/python-created" || fail 'create worktree/branch effects differ'
# Complete a committed feature in each isolated fixture and compare integration/removal.
for impl in bash python; do
  repo="$TMP/create/$impl"; wt="$repo/.worktrees/parity-create"
  git -C "$wt" config user.name Parity; git -C "$wt" config user.email parity@example.invalid
  printf 'feature\n' > "$wt/feature"; git -C "$wt" add feature; git -C "$wt" commit -qm feature
  if [[ $impl == bash ]]; then "$BASH_CLI" --repo "$repo" --json complete parity-create --base main > "$TMP/complete.$impl"; else python3 -m worktree_manager --repo "$repo" --json complete parity-create --base main > "$TMP/complete.$impl"; fi
  [[ ! -e "$wt" ]] || fail "$impl complete retained worktree"
  git -C "$repo" show main:feature > "$TMP/feature.$impl" || fail "$impl complete did not integrate feature"
done
jq -S 'del(.data.path,.data.worktree,.data.squash_commit,.data.transaction_id)' "$TMP/complete.bash" > "$TMP/a"
jq -S 'del(.data.path,.data.worktree,.data.squash_commit,.data.transaction_id)' "$TMP/complete.python" > "$TMP/b"
diff -u "$TMP/a" "$TMP/b" || fail 'complete JSON contract differs'
diff -u "$TMP/feature.bash" "$TMP/feature.python" || fail 'complete integration differs'
# Cleanup success, list after create, and prune are independently compared.
# Each backend performs cleanup only on its own fixture; compare the public result and effects.
for impl in bash python; do
  repo="$TMP/cleanup/$impl"; init_repo "$repo"
  if [[ $impl == bash ]]; then "$BASH_CLI" --repo "$repo" create parity-cleanup --base main >/dev/null; "$BASH_CLI" --repo "$repo" --json cleanup parity-cleanup >"$TMP/cleanup.$impl"; else python3 -m worktree_manager --repo "$repo" create parity-cleanup --base main >/dev/null; python3 -m worktree_manager --repo "$repo" --json cleanup parity-cleanup >"$TMP/cleanup.$impl"; fi
  [[ ! -e "$repo/.worktrees/parity-cleanup" ]] || fail "$impl cleanup retained worktree"
  if [[ $impl == bash ]]; then "$BASH_CLI" --repo "$repo" --json list >"$TMP/final-list.$impl"; else python3 -m worktree_manager --repo "$repo" --json list >"$TMP/final-list.$impl"; fi
done
jq -S 'del(.data)' "$TMP/cleanup.bash" > "$TMP/a"; jq -S 'del(.data)' "$TMP/cleanup.python" > "$TMP/b"; diff -u "$TMP/a" "$TMP/b" || fail 'cleanup contract differs'
jq -S 'del(.data.worktrees[].path)' "$TMP/final-list.bash" > "$TMP/a"; jq -S 'del(.data.worktrees[].path)' "$TMP/final-list.python" > "$TMP/b"; diff -u "$TMP/a" "$TMP/b" || fail 'list after cleanup differs'
# Contract-level negative checks against the live implementations.
for impl in bash python; do
  repo="$TMP/create/$impl"
  if [[ $impl == bash ]]; then "$BASH_CLI" --repo "$repo" --json prune >"$TMP/prune.$impl"; else python3 -m worktree_manager --repo "$repo" --json prune >"$TMP/prune.$impl"; fi
done
jq -S 'del(.data)' "$TMP/prune.bash" > "$TMP/a"; jq -S 'del(.data)' "$TMP/prune.python" > "$TMP/b"; diff -u "$TMP/a" "$TMP/b" || fail 'prune contract differs'
# Preserve-dirty is exercised on both backends with real staged, unstaged and
# untracked parent changes. Compare the resulting index and complete tree state.
for impl in bash python; do
  repo="$TMP/preserve-dirty/$impl"; init_repo "$repo"
  if [[ $impl == bash ]]; then cli=("$BASH_CLI" --repo "$repo"); else cli=(python3 -m worktree_manager --repo "$repo"); fi
  "${cli[@]}" create parity-dirty --base main >/dev/null
  wt="$repo/.worktrees/parity-dirty"
  git -C "$wt" config user.name Parity; git -C "$wt" config user.email parity@example.invalid
  printf 'feature\n' > "$wt/feature"; git -C "$wt" add feature; git -C "$wt" commit -qm feature
  printf 'staged\n' > "$repo/file"; git -C "$repo" add file
  printf 'unstaged\n' > "$repo/file"; printf 'untracked\n' > "$repo/new-file"
  "${cli[@]}" --json complete parity-dirty --base main --preserve-dirty > "$TMP/preserve-dirty.$impl.out" 2>"$TMP/preserve-dirty.$impl.err" || fail "$impl preserve-dirty complete failed"
  git -C "$repo" status --porcelain=v2 --untracked-files=all > "$TMP/preserve-dirty.$impl.status"
  git -C "$repo" diff --cached --binary > "$TMP/preserve-dirty.$impl.index"
  git -C "$repo" diff --binary > "$TMP/preserve-dirty.$impl.worktree"
  git -C "$repo" ls-files --others --exclude-standard -z | xargs -0 -I{} sh -c 'printf "%s\0" "$1"; cat "$2/$1"' _ {} "$repo" > "$TMP/preserve-dirty.$impl.untracked"
done
for suffix in status index worktree untracked; do diff -u "$TMP/preserve-dirty.bash.$suffix" "$TMP/preserve-dirty.python.$suffix" || fail "preserve-dirty $suffix differs"; done
jq -S 'del(.data.path,.data.worktree,.data.squash_commit,.data.transaction_id,.data.preserve,.data.merge)' "$TMP/preserve-dirty.bash.out" > "$TMP/a"
jq -S 'del(.data.path,.data.worktree,.data.squash_commit,.data.transaction_id,.data.preserve_dirty,.data.merge)' "$TMP/preserve-dirty.python.out" > "$TMP/b"
diff -u "$TMP/a" "$TMP/b" || fail 'preserve-dirty JSON differs'
# Lock contention: inject a live lock artifact into equivalent isolated repos.
for impl in bash python; do
  repo="$TMP/lock-contention/$impl"; init_repo "$repo"
  # State is rooted in Git's common dir; work IDs are UTF-8 hex-encoded before
  # becoming path components.
  lock_id="$(printf '%s' parity-lock | od -An -tx1 | tr -d ' \n')"
  mkdir -p "$repo/.git/state/locks/work/$lock_id"
  if [[ $impl == bash ]]; then
    printf 'held\n' > "$repo/.git/state/locks/work/$lock_id/pid"
    cli=("$BASH_CLI" --repo "$repo")
  else
    printf 'held\n' > "$repo/.git/state/locks/work/$lock_id/owner"
    cli=(python3 -m worktree_manager --repo "$repo")
  fi
  set +e; "${cli[@]}" --json create parity-lock --base main > "$TMP/lock.$impl.out" 2>"$TMP/lock.$impl.err"; status=$?; set -e
  printf '%s\n' "$status" > "$TMP/lock.$impl.status"
done
diff -u "$TMP/lock.bash.status" "$TMP/lock.python.status" || fail 'lock contention exit differs'
diff -u <(jq -S 'del(.error.message)' "$TMP/lock.bash.out") <(jq -S 'del(.error.message)' "$TMP/lock.python.out") || fail 'lock contention JSON differs'
# Journal lifecycle/recovery produces actual persisted transaction state; recover
# twice against each implementation and compare the idempotent terminal result.
for impl in bash python; do
  repo="$TMP/recovery/$impl"; init_repo "$repo"
  if [[ $impl == bash ]]; then cli=("$BASH_CLI" --repo "$repo"); else cli=(python3 -m worktree_manager --repo "$repo"); fi
  "${cli[@]}" --json recover > "$TMP/recovery-empty.$impl"
  "${cli[@]}" --json recover > "$TMP/recovery-second.$impl"
done
diff -u <(jq -S . "$TMP/recovery-empty.bash") <(jq -S . "$TMP/recovery-empty.python") || fail 'empty journal recovery differs'
diff -u <(jq -S . "$TMP/recovery-second.bash") <(jq -S . "$TMP/recovery-second.python") || fail 'idempotent recovery differs'
# Target-direct differential tests use real parent repositories with local submodules.
init_target_parent() {
  local parent="$1" target="$2"
  init_repo "$target"; init_repo "$parent"
  git -C "$parent" -c protocol.file.allow=always submodule add -q "$target" modules/target
  git -C "$parent" commit -qam 'add target submodule'
}
for impl in bash python; do
  parent="$TMP/td-abort/$impl/parent"; target="$TMP/td-abort/$impl/target"
  mkdir -p "$(dirname "$parent")"; init_target_parent "$parent" "$target"; target="$parent/modules/target"
  git -C "$parent" ls-files --stage > "$TMP/td-abort.$impl.before-index"
  git -C "$parent" rev-parse HEAD > "$TMP/td-abort.$impl.before-head"
  if [[ $impl == bash ]]; then cli=("$BASH_CLI" --repo "$target" --parent-repo "$parent")
    "${cli[@]}" create td-abort --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
    "${cli[@]}" link-parent td-abort --target submodule --submodule-path modules/target --link-parent staged-only >"$TMP/td-abort.$impl.link" 2>"$TMP/td-abort.$impl.err"
    set +e; "${cli[@]}" abort td-abort --target submodule --submodule-path modules/target --link-parent staged-only >"$TMP/td-abort.$impl.out" 2>"$TMP/td-abort.$impl.abort.err"; s=$?; set -e
  else cli=(python3 -m worktree_manager --repo "$target")
    "${cli[@]}" target-direct create td-abort --parent-repo "$parent" --submodule-path modules/target >/dev/null
    "${cli[@]}" target-direct link-parent td-abort --parent-repo "$parent" >"$TMP/td-abort.$impl.link" 2>"$TMP/td-abort.$impl.err"
    set +e; "${cli[@]}" target-direct abort td-abort --parent-repo "$parent" >"$TMP/td-abort.$impl.out" 2>"$TMP/td-abort.$impl.abort.err"; s=$?; set -e
  fi
  printf '%s\n' "$s" > "$TMP/td-abort.$impl.status"
  git -C "$parent" status --porcelain=v2 --untracked-files=all > "$TMP/td-abort.$impl.parent-status"
  git -C "$parent" ls-files --stage > "$TMP/td-abort.$impl.index"
  git -C "$parent" rev-parse HEAD > "$TMP/td-abort.$impl.head"
done
for impl in bash python; do
  diff -u "$TMP/td-abort.$impl.before-index" "$TMP/td-abort.$impl.index" || fail "$impl abort failed to restore parent index"
  diff -u "$TMP/td-abort.$impl.before-head" "$TMP/td-abort.$impl.head" || fail "$impl abort changed parent HEAD"
  [[ $(cat "$TMP/td-abort.$impl.status") == 6 ]] || fail "$impl abort public status mismatch"
done
# A staged parent-index change after link must be preserved and abort blocked.
for impl in bash python; do
  parent="$TMP/td-drift/$impl/parent"; target="$TMP/td-drift/$impl/target"
  mkdir -p "$(dirname "$parent")"; init_target_parent "$parent" "$target"; target="$parent/modules/target"
  if [[ $impl == bash ]]; then cli=("$BASH_CLI" --repo "$target" --parent-repo "$parent")
    "${cli[@]}" create td-drift --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
    "${cli[@]}" link-parent td-drift --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
    printf 'keep\n' > "$parent/keep"; git -C "$parent" add keep
  git -C "$parent" ls-files --stage > "$TMP/td-drift.$impl.before-index"
    set +e; "${cli[@]}" abort td-drift --target submodule --submodule-path modules/target --link-parent staged-only >"$TMP/td-drift.$impl.out" 2>"$TMP/td-drift.$impl.err"; s=$?; set -e
  else cli=(python3 -m worktree_manager --repo "$target")
    "${cli[@]}" target-direct create td-drift --parent-repo "$parent" --submodule-path modules/target >/dev/null
    "${cli[@]}" target-direct link-parent td-drift --parent-repo "$parent" >/dev/null
    printf 'keep\n' > "$parent/keep"; git -C "$parent" add keep
  git -C "$parent" ls-files --stage > "$TMP/td-drift.$impl.before-index"
    set +e; "${cli[@]}" target-direct abort td-drift --parent-repo "$parent" >"$TMP/td-drift.$impl.out" 2>"$TMP/td-drift.$impl.err"; s=$?; set -e
  fi
  printf '%s\n' "$s" > "$TMP/td-drift.$impl.status"
  git -C "$parent" ls-files --stage > "$TMP/td-drift.$impl.index"
  git -C "$parent" status --porcelain=v2 --untracked-files=all > "$TMP/td-drift.$impl.parent-status"
  [[ -f "$parent/keep" ]] || fail "$impl drift abort lost staged developer file"
done
for impl in bash python; do
  diff -u "$TMP/td-drift.$impl.before-index" "$TMP/td-drift.$impl.index" || fail "$impl drift abort overwrote staged index"
  [[ $(cat "$TMP/td-drift.$impl.status") == 5 || $(cat "$TMP/td-drift.$impl.status") == 6 ]] || fail "$impl drift abort unexpectedly succeeded"
done
# A successful link-parent is not an interruption: the parent index now contains
# the intentional gitlink, so recovery cannot safely classify it as pre-stage or
# recoverable partial state. Both implementations must fail closed (status 6)
# and retain the staged index rather than claiming successful rollback.
for impl in bash python; do
  parent="$TMP/td-recover/$impl/parent"; target="$TMP/td-recover/$impl/target"
  mkdir -p "$(dirname "$parent")"; init_target_parent "$parent" "$target"; target="$parent/modules/target"
  git -C "$parent" ls-files --stage > "$TMP/td-recover.$impl.before-index"
  if [[ $impl == bash ]]; then cli=("$BASH_CLI" --repo "$target" --parent-repo "$parent")
    "${cli[@]}" create td-recover --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
    "${cli[@]}" link-parent td-recover --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
    set +e; "${cli[@]}" recover wt-td-recover --target submodule --submodule-path modules/target --link-parent staged-only > "$TMP/td-recover.$impl.first" 2>"$TMP/td-recover.$impl.err"; rs=$?; set -e
    [[ $rs == 6 ]] || { cat "$TMP/td-recover.$impl.err" "$TMP/td-recover.$impl.first" >&2; fail "Bash target recovery returned $rs instead of fail-closed status 6"; }
  else cli=(python3 -m worktree_manager --repo "$target")
    "${cli[@]}" target-direct create td-recover --parent-repo "$parent" --submodule-path modules/target >/dev/null
    "${cli[@]}" target-direct link-parent td-recover --parent-repo "$parent" >/dev/null
    set +e; "${cli[@]}" target-direct recover td-recover --parent-repo "$parent" > "$TMP/td-recover.$impl.first" 2>"$TMP/td-recover.$impl.err"; rs=$?; set -e
    [[ $rs == 6 ]] || { cat "$TMP/td-recover.$impl.err" "$TMP/td-recover.$impl.first" >&2; fail "Python target recovery returned $rs instead of fail-closed status 6"; }
  fi
  git -C "$parent" ls-files --stage > "$TMP/td-recover.$impl.after-index"
  git -C "$parent" ls-files --stage -- modules/target | grep -q '^160000 ' || fail "$impl recovery discarded the staged gitlink"
done
# Interrupt target-direct after the durable descriptor reaches staged_started,
# before update-index. Compare retained descriptor/journal/lock and parent index,
# then require recovery to be idempotent in both implementations.
for impl in bash python; do
  parent="$TMP/td-descriptor-crash/$impl/parent"; target="$TMP/td-descriptor-crash/$impl/target"
  mkdir -p "$(dirname "$parent")"; init_target_parent "$parent" "$target"; target="$parent/modules/target"
  git -C "$parent" ls-files --stage > "$TMP/td-descriptor-crash.$impl.before-index"
  if [[ $impl == bash ]]; then
    cli=("$BASH_CLI" --repo "$target" --parent-repo "$parent")
    "${cli[@]}" create td-descriptor-crash --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
    set +e
    ( WORKTREE_MANAGER_TEST_MODE=1 WORKTREE_MANAGER_TEST_TARGET_CRASH_AFTER=staged_started "${cli[@]}" link-parent td-descriptor-crash --target submodule --submodule-path modules/target --link-parent staged-only >"$TMP/td-descriptor-crash.$impl.crash.out" 2>"$TMP/td-descriptor-crash.$impl.crash.err" ) &
    crash_pid=$!; printf '%s\n' "$crash_pid" > "$TMP/td-descriptor-crash.$impl.crash.pid"; wait "$crash_pid"; crash_status=$?; set -e
    [[ $crash_status == 99 ]] || fail "Bash target descriptor barrier returned $crash_status"
    state_dir="$target/.git/worktree-manager/target-direct/$(printf '%s' td-descriptor-crash | shasum -a 256 | awk '{print $1}')"
    # Worktree common-dir indirection is resolved from the descriptor itself.
    descriptor=$(find "$target/.git" -path '*/target-direct/*/descriptor' -type f -print -quit)
    [[ -n $descriptor ]] || descriptor=$(find "$(git -C "$target" rev-parse --git-common-dir)" -path '*/target-direct/*/descriptor' -type f -print -quit)
    state_dir="$(dirname "$descriptor")"
    recover=("${cli[@]}" recover wt-td-descriptor-crash --target submodule --submodule-path modules/target --link-parent staged-only)
  else
    cli=(python3 -m worktree_manager --repo "$target")
    "${cli[@]}" target-direct create td-descriptor-crash --parent-repo "$parent" --submodule-path modules/target >/dev/null
    set +e
    ( WORKTREE_MANAGER_TEST_CRASH_AFTER_DESCRIPTOR_PHASE=staged_started "${cli[@]}" target-direct link-parent td-descriptor-crash --parent-repo "$parent" >"$TMP/td-descriptor-crash.$impl.crash.out" 2>"$TMP/td-descriptor-crash.$impl.crash.err" ) &
    crash_pid=$!; printf '%s\n' "$crash_pid" > "$TMP/td-descriptor-crash.$impl.crash.pid"; wait "$crash_pid"; crash_status=$?; set -e
    [[ $crash_status == 137 || $crash_status == 9 ]] || fail "Python target descriptor barrier returned $crash_status"
    state_dir=$(find "$(git -C "$target" rev-parse --git-common-dir)" -path '*/target-direct/*/descriptor' -type f -print -quit | xargs dirname)
    descriptor="$state_dir/descriptor"
    recover=("${cli[@]}" target-direct recover td-descriptor-crash --parent-repo "$parent")
  fi
  [[ -n ${descriptor:-} && -f "$descriptor" ]] || fail "$impl target descriptor was not retained"
  grep -q '^phase=staged_started$' "$descriptor" || fail "$impl target descriptor phase was not durable"
  git -C "$parent" ls-files --stage > "$TMP/td-descriptor-crash.$impl.pre-recover-index"
  diff -u "$TMP/td-descriptor-crash.$impl.before-index" "$TMP/td-descriptor-crash.$impl.pre-recover-index" || fail "$impl target crash changed parent index before staging"
  set +e; "${recover[@]}" >"$TMP/td-descriptor-crash.$impl.recover1.out" 2>"$TMP/td-descriptor-crash.$impl.recover1.err"; r1=$?; "${recover[@]}" >"$TMP/td-descriptor-crash.$impl.recover2.out" 2>"$TMP/td-descriptor-crash.$impl.recover2.err"; r2=$?; set -e
  printf '%s %s\n' "$r1" "$r2" > "$TMP/td-descriptor-crash.$impl.codes"
  git -C "$parent" ls-files --stage > "$TMP/td-descriptor-crash.$impl.index"
  # Independent target repositories necessarily have different object IDs and
  # local URLs. Compare the observable gitlink structure and logical config,
  # while retaining per-fixture checks that each implementation staged a real
  # gitlink with a valid object ID.
  git -C "$parent" ls-files --stage -- modules/target > "$TMP/td-descriptor-crash.$impl.gitlink.raw"
  if [[ -s "$TMP/td-descriptor-crash.$impl.gitlink.raw" ]]; then
    grep -Eq '^160000 [0-9a-f]{40} 0[[:space:]]+modules/target$' "$TMP/td-descriptor-crash.$impl.gitlink.raw" || fail "$impl target crash has invalid staged gitlink"
  fi
  awk '{print $1, $3, $4}' "$TMP/td-descriptor-crash.$impl.gitlink.raw" > "$TMP/td-descriptor-crash.$impl.gitlink"
  if [[ -f "$parent/.gitmodules" ]]; then
    sed "s#${TMP}/td-descriptor-crash/${impl}/target#<target-repo>#g; s#${TMP}/td-descriptor-crash/${impl}/parent#<parent-repo>#g" "$parent/.gitmodules" > "$TMP/td-descriptor-crash.$impl.gitmodules"
  else
    : > "$TMP/td-descriptor-crash.$impl.gitmodules"
  fi
  git -C "$parent" status --porcelain=v2 --untracked-files=all > "$TMP/td-descriptor-crash.$impl.status"
  sed -n 's/^phase=//p' "$descriptor" > "$TMP/td-descriptor-crash.$impl.phase"
  find "$state_dir" -type f -maxdepth 3 -print | sed "s#^$state_dir/##" | sort > "$TMP/td-descriptor-crash.$impl.artifacts"
  # Assert the semantic recovery contract per backend. SIGKILL happens only
  # after the durable staged_started descriptor write; recovery must therefore
  # retain evidence, report blocked once, then be idempotent.
  [[ $(cat "$TMP/td-descriptor-crash.$impl.codes") == '6 0' ]] || fail "$impl target crash recovery sequence is not (6, 0)"
  [[ $(cat "$TMP/td-descriptor-crash.$impl.phase") == blocked ]] || fail "$impl target crash did not persist blocked phase"
  [[ -f "$state_dir/descriptor" && -f "$state_dir/snapshot/head.sha" && -f "$state_dir/snapshot/index.bytes" && -f "$state_dir/snapshot/index.sha256" ]] || fail "$impl target crash lost required descriptor/snapshot evidence"
  expected_index_hash=$(cat "$state_dir/snapshot/index.sha256")
  actual_index_hash=$(shasum -a 256 "$state_dir/snapshot/index.bytes" | awk '{print $1}')
  [[ "$expected_index_hash" == "$actual_index_hash" ]] || fail "$impl target crash snapshot index hash is invalid"
done
# Physical journal/meta/snapshot filenames are implementation-specific. Compare
# the persisted contract above and the logical state below, never inventories.
for suffix in codes status phase gitlink gitmodules; do
  diff -u "$TMP/td-descriptor-crash.bash.$suffix" "$TMP/td-descriptor-crash.python.$suffix" || fail "target descriptor crash $suffix differs"
done
# Successful target-direct completion must retain staged-only parent linkage and
# remove the target worktree without making a parent commit.
for impl in bash python; do
  parent="$TMP/td-complete/$impl/parent"; target="$TMP/td-complete/$impl/target"
  mkdir -p "$(dirname "$parent")"; init_target_parent "$parent" "$target"; target="$parent/modules/target"
  head_before=$(git -C "$parent" rev-parse HEAD)
  if [[ $impl == bash ]]; then cli=("$BASH_CLI" --repo "$target" --parent-repo "$parent")
    "${cli[@]}" create td-complete --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
    printf 'completed target change\n' > "$target/.worktrees/td-complete/completed"
    git -C "$target/.worktrees/td-complete" add completed
    git -C "$target/.worktrees/td-complete" commit -qm 'complete target change'
    "${cli[@]}" link-parent td-complete --target submodule --submodule-path modules/target --link-parent staged-only >/dev/null
    "${cli[@]}" complete td-complete --target submodule --submodule-path modules/target --link-parent staged-only >"$TMP/td-complete.$impl.out" 2>"$TMP/td-complete.$impl.err"
  else cli=(python3 -m worktree_manager --repo "$target")
    "${cli[@]}" target-direct create td-complete --parent-repo "$parent" --submodule-path modules/target >/dev/null
    printf 'completed target change\n' > "$target/.worktrees/td-complete/completed"
    git -C "$target/.worktrees/td-complete" add completed
    git -C "$target/.worktrees/td-complete" commit -qm 'complete target change'
    "${cli[@]}" target-direct link-parent td-complete --parent-repo "$parent" >/dev/null
    "${cli[@]}" target-direct complete td-complete --parent-repo "$parent" >"$TMP/td-complete.$impl.out" 2>"$TMP/td-complete.$impl.err"
  fi
  [[ ! -e "$target/.worktrees/td-complete" ]] || fail "$impl target complete retained worktree"
  [[ $(git -C "$parent" rev-parse HEAD) == "$head_before" ]] || fail "$impl target complete committed parent"
  git -C "$parent" ls-files --stage -- modules/target | grep -q '^160000 ' || fail "$impl target complete lost staged gitlink"
done
# Crash injection: a PATH shim runs the real Git command, then SIGKILLs the
# Bash CLI (and its operation subshell) after the selected durable operation. This is an
# actual process death (not a recover call against a normally closed operation).
mkdir -p "$TMP/crash-bin"
REAL_GIT="$(command -v git)"
cat > "$TMP/crash-bin/git" <<'SHIM'
#!/bin/sh
"$REAL_GIT" "$@"
  rc=$?
  if [ "$rc" -eq 0 ] && [ -n "${CRASH_AFTER_GIT:-}" ]; then
    # Match the exact squash commit operation, not any argument containing
    # "commit" (for example rev-parse's ^{commit} type peel during validation).
    case "$*" in
    *"$CRASH_AFTER_GIT"*)
      cli_pid="$PPID"
      cli_parent="$(ps -o ppid= -p "$cli_pid" | tr -d ' ')"
      cli_parent_args="$(ps -o args= -p "$cli_parent" 2>/dev/null || true)"
      kill -KILL "$cli_pid" 2>/dev/null || :
      # worktree.sh isolates lifecycle execution in a child shell; kill the
      # entrypoint too, otherwise it converts the child death into status 5.
      case "$cli_parent_args" in *worktree.sh*) kill -KILL "$cli_parent" 2>/dev/null || : ;; esac
      sleep 1 ;;
  esac
fi
exit "$rc"
SHIM
chmod +x "$TMP/crash-bin/git"
run_crashed() {
  local impl="$1" repo="$2" trigger="$3"; shift 3
  set +e
  if [[ $impl == python ]]; then
    WORKTREE_MANAGER_TEST_CRASH_AFTER_GIT="$trigger" \
      "$@" >"$TMP/crash-$impl.out" 2>"$TMP/crash-$impl.err"
  else
    PATH="$TMP/crash-bin:$PATH" REAL_GIT="$REAL_GIT" CRASH_AFTER_GIT="$trigger" \
      "$@" >"$TMP/crash-$impl.out" 2>"$TMP/crash-$impl.err"
  fi
  local rc=$?
  set -e
  [[ $rc == 137 || $rc == 128 ]] || fail "$impl did not die at durable Git barrier ($trigger, status $rc)"
}

# create: die after Git has registered and materialized the worktree. Check the
# persisted worktree/branch and that a subsequent create fails rather than
# silently replacing that state.
for impl in bash python; do
  repo="$TMP/crash-create/$impl"; init_repo "$repo"
  if [[ $impl == bash ]]; then cli=("$BASH_CLI" --repo "$repo"); else cli=(python3 -m worktree_manager --repo "$repo"); fi
  run_crashed "$impl" "$repo" 'worktree add' "${cli[@]}" create crash-create --base main
  git -C "$repo" worktree list --porcelain | grep -q "$repo/.worktrees/crash-create" || fail "$impl create crash lost registered worktree"
  git -C "$repo" show-ref --verify --quiet refs/heads/worktree/crash-create || fail "$impl create crash lost branch"
  set +e; "${cli[@]}" --json create crash-create --base main >"$TMP/retry.$impl.out" 2>/dev/null; rc=$?; set -e
  [[ $rc != 0 ]] || fail "$impl retried create over crash residue"
done

# complete/preserve-dirty: terminate after the squash commit is durable but
# before the next journal transition. Compare recover outcome, persisted refs,
# worktree/branch state, destination index/tree, and a second idempotent recover.
for scenario in complete preserve-dirty; do
  for impl in bash python; do
    repo="$TMP/crash-$scenario/$impl"; init_repo "$repo"
    if [[ $impl == bash ]]; then cli=("$BASH_CLI" --repo "$repo"); else cli=(python3 -m worktree_manager --repo "$repo"); fi
    "${cli[@]}" create crash-feature --base main >/dev/null
    wt="$repo/.worktrees/crash-feature"
    git -C "$wt" config user.name Parity; git -C "$wt" config user.email parity@example.invalid
    echo feature > "$wt/change"; git -C "$wt" add change; git -C "$wt" commit -qm feature
    if [[ $scenario == preserve-dirty ]]; then echo staged > "$repo/file"; git -C "$repo" add file; echo unstaged > "$repo/file"; echo extra > "$repo/extra"; fi
    run_crashed "$impl" "$repo" 'commit -m squash merge' "${cli[@]}" --json complete crash-feature --base main $([[ $scenario == preserve-dirty ]] && echo --preserve-dirty)
    if [[ $impl == bash ]]; then
      close_id="$(printf '%s' crash-feature | od -An -tx1 | tr -d ' \n')"
      journal="$repo/.git/state/close/$close_id/journal"
      [[ -f "$journal" && $(cat "$journal") == merge_started ]] || fail "$scenario Bash crash did not stop between durable squash commit and journal transition"
      before_head="$(sed -n 's/^before_head=//p' "${journal%/journal}/meta")"
      [[ -n "$before_head" && $(git -C "$repo" rev-parse HEAD) != "$before_head" ]] || fail "$scenario Bash crash did not advance destination HEAD"
    fi
    set +e; "${cli[@]}" --json recover >"$TMP/recover.$scenario.$impl.1" 2>"$TMP/recover.$scenario.$impl.err"; r1=$?; "${cli[@]}" --json recover >"$TMP/recover.$scenario.$impl.2" 2>>"$TMP/recover.$scenario.$impl.err"; r2=$?; set -e
    printf '%s %s\n' "$r1" "$r2" > "$TMP/recover.$scenario.$impl.codes"
    git -C "$repo" status --porcelain=v2 --untracked-files=all > "$TMP/recover.$scenario.$impl.status"
    git -C "$repo" ls-files --stage > "$TMP/recover.$scenario.$impl.index"
    git -C "$repo" worktree list --porcelain \
      | sed -E -e "s#$(printf '%s' "$repo" | sed 's#[.[\*^$()+?{|]#\\&#g')#<repo>#g" \
          -e 's/^(HEAD )[0-9a-f]{40}$/\1<sha>/' \
      > "$TMP/recover.$scenario.$impl.worktrees"
    git -C "$repo" for-each-ref --format='%(refname) %(objectname)' refs/worktree-manager-backups > "$TMP/recover.$scenario.$impl.refs"
    # Journal storage is intentionally implementation-specific: Bash closes
    # live in state/close/<work-id-hex>, Python transactions in
    # state/transactions/<transaction-id>. Compare logical phases, not paths.
    journal_out="$TMP/recover.$scenario.$impl.journal"
    : > "$journal_out"
    if [[ $impl == bash ]]; then
      while IFS= read -r -d '' journal; do
        work_id="$(basename "$(dirname "$journal")")"
        phase="$(tr -d '\n' < "$journal")"
        printf 'complete %s\n' "$phase" >> "$journal_out"
      done < <(find "$repo/.git/state/close" -name journal -print0 2>/dev/null)
    else
      while IFS= read -r -d '' journal; do
        phase="$(tr -d '\n' < "$journal")"
        printf 'complete %s\n' "$phase" >> "$journal_out"
      done < <(find "$repo/.git/state/transactions" -name journal -print0 2>/dev/null)
    fi
    sort -o "$journal_out" "$journal_out"
  done
  for suffix in codes status index worktrees refs journal; do
    diff -u "$TMP/recover.$scenario.bash.$suffix" "$TMP/recover.$scenario.python.$suffix" || fail "$scenario crash recovery $suffix differs"
  done
done

# Record intentional nondeterminism explicitly; case traces are retained on failure.
cat <<'EOF'
Parity matrix passed: JSON/human list, empty recover/prune, invalid command/option,
create, complete/integration/removal, cleanup, preserve-dirty index/worktree/untracked
restoration, lock contention, repeated recovery, post-lifecycle list, and prune across
isolated Git fixtures, including real target-direct abort, staged-index drift, recovery, and completion.
Real SIGKILL fixtures cover create and complete/preserve-dirty at durable Git
barriers, including twice-recovery state comparisons. Target-direct descriptor
phase interruption and twice-recovery state are compared differentially.
EOF
