"""Stable digest of repository and transaction state used by preflight plans."""
import hashlib
import json
from pathlib import Path


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def repository_state(repo_root, state_root):
    import subprocess
    root, state = Path(repo_root).resolve(), Path(state_root)
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()
    refs = git("for-each-ref", "--format=%(refname) %(objectname)").splitlines()
    worktrees = git("worktree", "list", "--porcelain").splitlines()
    index = Path(git("rev-parse", "--git-path", "index"))
    if not index.is_absolute(): index = root / index
    journal = []
    transactions = state / "transactions"
    if transactions.exists():
        for entry in sorted(transactions.iterdir()):
            if not entry.is_dir(): continue
            phase_path = entry / "journal"
            phase = phase_path.read_text().strip() if phase_path.is_file() else None
            meta = (entry / "meta.json").read_bytes() if (entry / "meta.json").is_file() else b""
            binding = (entry / "binding.json").read_bytes() if (entry / "binding.json").is_file() else b""
            journal.append([entry.name, phase, hashlib.sha256(meta).hexdigest(), hashlib.sha256(binding).hexdigest()])
    descriptors=[]
    common=Path(git("rev-parse", "--git-common-dir"))
    if not common.is_absolute(): common=root/common
    directory=common/"worktree-manager"/"target-direct"
    if directory.exists(): descriptors=sorted((p.relative_to(directory).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()) for p in directory.rglob("descriptor") if p.is_file())
    state_obj={"head":git("rev-parse", "HEAD"),"index_sha256":hashlib.sha256(index.read_bytes()).hexdigest() if index.exists() else None,"refs":refs,"worktrees":worktrees,"journal":journal,"descriptors":descriptors}
    return state_obj


def _declares_work_id(raw, work_id):
    if not raw:
        return False
    try:
        value = json.loads(raw)
    except ValueError:
        return False
    return isinstance(value, dict) and value.get("work_id") == work_id


def complete_state(repo_root, state_root, base, branch, worktree_path, work_id):
    """Closure state: only the base, branch, worktree, index and work transactions."""
    import subprocess
    root, state = Path(repo_root).resolve(), Path(state_root)

    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

    def ref(name):
        value = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", name],
                               check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return value.stdout.strip() if value.returncode == 0 else None

    index = Path(git("rev-parse", "--git-path", "index"))
    if not index.is_absolute(): index = root / index
    transactions = []
    directory = state / "transactions"
    if directory.exists():
        for entry in sorted(directory.iterdir()):
            if not entry.is_dir(): continue
            meta_path = entry / "meta.json"
            binding_path = entry / "binding.json"
            meta = meta_path.read_bytes() if meta_path.is_file() else b""
            binding = binding_path.read_bytes() if binding_path.is_file() else b""
            if not any(_declares_work_id(raw, work_id) for raw in (meta, binding)): continue
            phase_path = entry / "journal"
            phase = phase_path.read_text().strip() if phase_path.is_file() else None
            transactions.append([entry.name, phase, hashlib.sha256(meta).hexdigest(), hashlib.sha256(binding).hexdigest()])
    worktree_head = worktree_status = None
    path = Path(worktree_path) if worktree_path else None
    if path and path.is_dir():
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], check=False, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        worktree_head = head.stdout.strip() if head.returncode == 0 else None
        status = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=all"],
                                check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        worktree_status = status.stdout if status.returncode == 0 else None
    return {"base_ref": ref(f"refs/heads/{base}"), "branch_ref": ref(f"refs/heads/{branch}"),
            "worktree_head": worktree_head, "worktree_status": worktree_status,
            "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest() if index.exists() else None,
            "transactions": transactions}


def complete_state_digest(repo_root, state_root, base, branch, worktree_path, work_id):
    return canonical_hash(complete_state(repo_root, state_root, base, branch, worktree_path, work_id))


def state_digest(repo_root, state_root):
    return canonical_hash(repository_state(repo_root, state_root))
