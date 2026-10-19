"""MCP façade over the canonical Python lifecycle and recovery services."""
from pathlib import Path
from .configuration import Configuration
from .git_repository import GitRepository
from .models import ManagerError
from .worktree_lifecycle import WorktreeLifecycle
from .recovery_manager import RecoveryManager
from .mcp_contract import validate_request, envelope
from .worktree_lifecycle import validate_work_id
from .target_direct_adapter import TargetDirectAdapter
from .state_digest import state_digest, canonical_hash
import hashlib
import subprocess

DESTRUCTIVE = {"worktree_complete", "worktree_cleanup", "worktree_recover", "worktree_prune"}

def call(tool, request):
    req = validate_request(tool, request)
    root = Path(req["repo"]).resolve(strict=True)
    git = GitRepository(root)
    if root != git.root:
        raise ManagerError("invalid_repository", "Repository identity mismatch", 3)
    dry = req.get("dry_run", False)
    if tool in DESTRUCTIVE and not dry and req.get("authorization") != "I_AUTHORIZE_THIS_CALL":
        raise ManagerError("authorization_required", "Explicit authorization for this call is required", 3)
    lifecycle = WorktreeLifecycle(Configuration.load(root))
    if tool in {"worktree_create", "worktree_complete", "worktree_cleanup", "worktree_prune"}:
        if dry:
            if tool == "worktree_complete" and not req.get("transaction_id"):
                req["transaction_id"] = __import__("uuid").uuid4().hex
            digest = state_digest(root, lifecycle.state_root)
            fields = ("operation", "repo", "work_id", "confirm", "transaction_id", "base", "preserve_dirty", "discard", "discard_consent", "target_direct", "parent_repo", "submodule_path", "state_digest")
            plan = {key: (tool if key == "operation" else digest if key == "state_digest" else bool(req.get("authorization")) if key == "confirm" else req.get(key)) for key in fields}
            req["_computed_plan_hash"] = canonical_hash(plan)
        elif req.get("plan_hash"):
            digest = state_digest(root, lifecycle.state_root)
            fields = ("operation", "repo", "work_id", "confirm", "transaction_id", "base", "preserve_dirty", "discard", "discard_consent", "target_direct", "parent_repo", "submodule_path", "state_digest")
            plan = {key: (tool if key == "operation" else digest if key == "state_digest" else bool(req.get("authorization")) if key == "confirm" else req.get(key)) for key in fields}
            if req["plan_hash"] != canonical_hash(plan):
                raise ManagerError("plan_mismatch", "Repository state or request changed since preflight", 5)
    if "work_id" in req:
        validate_work_id(req["work_id"])
    def target_adapter(identity):
        common = Path(git.run(("rev-parse", "--git-common-dir")).stdout.strip())
        if not common.is_absolute(): common = (root / common).resolve()
        work_id = identity[3:] if identity.startswith("wt-") else identity
        descriptor = common / "worktree-manager" / "target-direct" / hashlib.sha256(work_id.encode()).hexdigest() / "descriptor"
        adapter = TargetDirectAdapter(descriptor)
        if adapter.values["target_repo"] != str(root) or adapter.values["parent_repo"] != str(Path(req["parent_repo"]).resolve()):
            raise ManagerError("invalid_descriptor", "Target descriptor identity does not match this request", 3)
        return adapter
    if tool == "worktree_create" and req.get("parent_repo"):
        if dry: raise ManagerError("unsupported_dry_run", "Target-direct creation cannot be simulated safely", 3)
        common = Path(git.run(("rev-parse", "--git-common-dir")).stdout.strip())
        if not common.is_absolute(): common = (root / common).resolve()
        descriptor = common / "worktree-manager" / "target-direct" / hashlib.sha256(req["work_id"].encode()).hexdigest() / "descriptor"
        adapter = TargetDirectAdapter.create(descriptor, root, req["parent_repo"], req["submodule_path"], req["work_id"], req.get("base", "main"))
        return envelope(tool, str(root), data={"target_direct": True, "worktree": adapter.values["worktree_path"], "descriptor": str(adapter.path), "phase": adapter.values["phase"]}, transaction_id=adapter.values["tx_id"])
    if tool == "worktree_complete" and req.get("target_direct"):
        if dry: raise ManagerError("unsupported_dry_run", "Target-direct completion cannot be simulated safely", 3)
        data = target_adapter(req["work_id"]).complete()
        return envelope(tool, str(root), data=data, transaction_id="wt-" + req["work_id"])
    if tool == "worktree_recover" and req.get("target_direct"):
        if dry: raise ManagerError("unsupported_dry_run", "Target-direct recovery cannot be simulated safely", 3)
        tx = req.get("transaction_id")
        if not tx: raise ManagerError("transaction_id_required", "Target-direct recovery requires transaction_id", 3)
        data = target_adapter(tx).recover()
        return envelope(tool, str(root), data=data, transaction_id=tx)
    if tool == "worktree_status":
        matches = [item for item in lifecycle.list() if item["path"] == str(lifecycle._path(req["work_id"]))]
        journal = []
        if lifecycle.journal.root.exists():
            for entry in sorted(lifecycle.journal.root.iterdir()):
                if entry.is_dir():
                    phase = lifecycle.journal.read_phase(entry.name)
                    meta_path = entry / "meta.json"
                    meta = __import__("json").loads(meta_path.read_text()) if meta_path.is_file() else {}
                    if meta.get("work_id") == req["work_id"]:
                        journal.append({"transaction_id": entry.name, "phase": phase, "metadata": meta})
        data = {"worktree": matches[0] if matches else None, "identity_exists": bool(matches), "transactions": journal,
                "pending_intervention": any(item["phase"] == "pending_manual" for item in journal),
                "locks_directory": str(lifecycle.state_root / lifecycle.config.lock_dir)}
    elif tool == "worktree_list":
        data = {"worktrees": lifecycle.list()}
    elif tool == "worktree_create":
        base = req.get("base") or next((b for b in ("development", "main", "trunk") if lifecycle.git.run(("show-ref", "--verify", "--quiet", f"refs/heads/{b}"), check=False).returncode == 0), "main")
        if dry:
            lifecycle._base(base)
            branch, path = lifecycle._branch(req["work_id"]), lifecycle._path(req["work_id"])
            if path.exists() or lifecycle.git.run(("show-ref", "--verify", "--quiet", f"refs/heads/{branch}"), check=False).returncode == 0:
                raise ManagerError("operation_failed", "Worktree branch or path already exists", 5)
            if not Path(lifecycle.config.worktrees_dir).is_absolute():
                rel = path.relative_to(root).as_posix()
                if lifecycle.git.run(("check-ignore", "-q", "--", rel), check=False).returncode:
                    raise ManagerError("invalid_configuration", "Worktree path is not ignored", 3)
            data = {"planned": True, "work_id": req["work_id"], "base": base, "path": str(path), "branch": branch, "preflight": "passed", "mutations": [], "plan_hash":req.get("_computed_plan_hash"), "state_digest":digest}
        else:
            data = lifecycle.create(req["work_id"], base)
            data.update({"init_submodules":"false", "init_submodules_result":"not_requested", "prepare":"skipped", "verify":"skipped"})
    elif tool == "worktree_complete":
        if dry:
            base=req.get("base", "main"); lifecycle._base(base)
            path=lifecycle._path(req["work_id"])
            if str(path) not in {item["path"] for item in lifecycle.list()} or not path.is_dir(): raise ManagerError("invalid_identity", "Worktree identity does not match registration", 3)
            if lifecycle.git.run(("symbolic-ref", "--short", "HEAD")).stdout.strip()!=base: raise ManagerError("invalid_identity", f"Current branch must be '{base}'", 3)
            if lifecycle.git.run(("-C", str(path), "status", "--porcelain", "--untracked-files=all")).stdout: raise ManagerError("intervention_required", "Worktree has uncommitted changes; it was retained", 5)
            data = {"planned": True, "work_id": req["work_id"], "transaction_id":req.get("transaction_id"), "preflight": "passed", "mutations": ["squash_merge", "remove_worktree", "delete_branch"], "plan_hash":req.get("_computed_plan_hash"), "state_digest":digest}
        else: data = lifecycle.complete(req["work_id"], req.get("base", "main"), req.get("preserve_dirty", False), req.get("transaction_id"))
    elif tool == "worktree_cleanup":
        if req.get("discard") and req.get("discard_consent") is not True:
            raise ManagerError("discard_consent_required", "Separate explicit discard consent is required", 3)
        if dry:
            path=lifecycle._path(req["work_id"])
            if str(path) not in {item["path"] for item in lifecycle.list()} or not path.exists(): raise ManagerError("invalid_identity", "Worktree identity does not match registration", 3)
            lifecycle._base(req.get("base", "main"))
            changed=bool(lifecycle.git.run(("-C", str(path), "status", "--porcelain", "--untracked-files=all")).stdout)
            if changed and not req.get("discard"): raise ManagerError("intervention_required", "Worktree has changes; discard is required", 5)
            data = {"planned": True, "work_id": req["work_id"], "discard": req.get("discard", False), "dirty": changed, "preflight": "passed", "mutations": ["remove_worktree", "delete_branch"], "plan_hash":req.get("_computed_plan_hash"), "state_digest":digest}
        else: data = lifecycle.cleanup(req["work_id"], req.get("discard", False), req.get("base", "main"))
    elif tool == "worktree_prune":
        if dry:
            # Git's dry-run reports exactly which stale administrative records
            # would be removed, without changing them.
            preview = lifecycle.git.run(("worktree", "prune", "--dry-run", "--verbose"))
            eligible = [line for line in (preview.stdout + preview.stderr).splitlines() if line.strip()]
            worktrees = lifecycle.list()
            locks_dir = lifecycle.state_root / lifecycle.config.lock_dir
            locks = sorted(p.name for p in locks_dir.iterdir()) if locks_dir.is_dir() else []
            interventions = []
            if lifecycle.journal.root.exists():
                for entry in sorted(lifecycle.journal.root.iterdir()):
                    if entry.is_dir() and lifecycle.journal.read_phase(entry.name) == "pending_manual":
                        interventions.append(entry.name)
            pending = bool(eligible)
            data = {"planned": pending, "preflight": "passed" if pending else "no_pending_work",
                    "worktrees": worktrees, "eligible_orphans": eligible, "locks": locks,
                    "pending_interventions": interventions,
                    "mutations": ["git_worktree_prune"] if pending else []}
            if not pending:
                return envelope(tool, str(root), "no_pending_work", data, transaction_id=None)
        else:
            data = lifecycle.prune()
            if data.get("pruned", 0) == 0:
                return envelope(tool, str(root), "no_pending_work", data, transaction_id=None)
    else:
        if dry:
            entries=[]
            if lifecycle.journal.directory.exists():
                entries=[entry.name for entry in lifecycle.journal.directory.iterdir() if entry.is_dir()]
            tx=req.get("transaction_id")
            if tx and tx not in entries: raise ManagerError("invalid_identity", "Transaction does not exist", 3)
            data = {"planned": True, "transaction_id": tx, "transactions": entries, "preflight": "passed", "mutations": ["recover_transaction"] if entries else []}
        else:
            git_dir = Path(git.run(("rev-parse", "--git-dir")).stdout.strip())
            if not git_dir.is_absolute(): git_dir = (root / git_dir).resolve()
            kind, data = RecoveryManager(git_dir / lifecycle.config.state_dir, root).recover(req.get("transaction_id"))
            return envelope(tool, str(root), kind, data, transaction_id=(data or {}).get("transaction_id"))
    return envelope(tool, str(root), data=data, transaction_id=data.get("transaction_id"))
