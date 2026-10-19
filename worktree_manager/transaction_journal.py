"""Atomic transaction journal storage."""
from __future__ import annotations
import os, tempfile
from pathlib import Path
from .models import ManagerError
PHASES = frozenset({'captured','merge_started','merged','pending_manual','restored','created','removed','closed','remove_started','captured_dirty','restoring'})
class TransactionJournal:
    def __init__(self, state_root: str | Path): self.root = Path(state_root).resolve() / 'transactions'
    def directory(self, tx: str) -> Path:
        if not tx or '/' in tx or tx.startswith(('.', '-')): raise ManagerError('invalid_identity','Invalid transaction identifier',3)
        return self.root / tx
    @staticmethod
    def _atomic(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(prefix='.tmp-',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream: stream.write(text); stream.flush(); os.fsync(stream.fileno())
            os.chmod(name,0o600); os.replace(name,path)
        finally:
            if os.path.exists(name): os.unlink(name)
    def write_phase(self,tx: str,phase: str) -> None:
        if phase not in PHASES: raise ManagerError('invalid_journal','Unknown transaction phase',3)
        self._atomic(self.directory(tx)/'journal',phase+'\n')
    def read_phase(self,tx: str) -> str:
        try: value=(self.directory(tx)/'journal').read_text(encoding='utf-8')
        except OSError as exc: raise ManagerError('invalid_journal','Transaction journal is unavailable',3) from exc
        phase=value.removesuffix('\n')
        if phase not in PHASES or '\n' in phase: raise ManagerError('invalid_journal','Transaction journal is corrupt',3)
        return phase
