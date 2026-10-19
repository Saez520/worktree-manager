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


def state_digest(repo_root, state_root):
    return canonical_hash(repository_state(repo_root, state_root))
