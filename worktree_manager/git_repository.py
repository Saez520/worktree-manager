"""All Git subprocess interaction is centralized here."""
from __future__ import annotations

import re
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .models import ManagerError

_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


@dataclass(frozen=True)
class GitOutput:
    stdout: str
    stderr: str
    returncode: int


class GitRepository:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()
        if not self.root.is_absolute() or not self.root.is_dir():
            raise ManagerError("invalid_repository", "Repository must be an existing absolute directory", 3)
        self.root = self.root.resolve()
        out = self.run(("rev-parse", "--show-toplevel"), check=False)
        if out.returncode:
            raise ManagerError("invalid_repository", "Directory is not a Git repository", 3)
        self.root = Path(out.stdout.strip()).resolve()

    def run(self, args: Sequence[str], *, check: bool = True, timeout: float = 60) -> GitOutput:
        if not args or any(not isinstance(arg, str) or "\x00" in arg for arg in args):
            raise ManagerError("invalid_argument", "Invalid Git argument", 2)
        try:
            result = subprocess.run(["git", "-C", str(self.root), *args], text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=timeout, check=False)
        except FileNotFoundError as exc:
            raise ManagerError("dependency_unavailable", "Git executable is unavailable", 6) from exc
        except subprocess.TimeoutExpired as exc:
            raise ManagerError("git_timeout", "Git command timed out", 5) from exc
        output = GitOutput(result.stdout, result.stderr, result.returncode)
        # Test-only crash barrier: terminate this CLI process only after Git has
        # returned successfully, leaving durable Git effects and held locks as
        # they would be after an abrupt process loss.
        trigger = os.environ.get("WORKTREE_MANAGER_TEST_CRASH_AFTER_GIT")
        if result.returncode == 0 and trigger and trigger in " ".join(args):
            os.kill(os.getpid(), signal.SIGKILL)
        if check and result.returncode:
            # Preserve causal stderr for diagnostics without exposing unrelated data.
            detail = result.stderr.strip() or "Git operation failed"
            raise ManagerError("operation_failed", detail, 5)
        return output

    def head(self) -> str:
        value = self.run(("rev-parse", "HEAD")).stdout.strip()
        if not _SHA.fullmatch(value):
            raise ManagerError("invalid_repository", "Git returned an invalid object id", 3)
        return value

    def status(self) -> str:
        return self.run(("status", "--porcelain=v2", "--branch", "--untracked-files=all")).stdout

    def worktrees(self) -> str:
        return self.run(("worktree", "list", "--porcelain")).stdout

    def index_entries(self) -> str:
        return self.run(("ls-files", "--stage", "-z")).stdout
