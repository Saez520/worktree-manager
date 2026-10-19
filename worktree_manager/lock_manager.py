"""Process-safe directory locks acquired in deterministic order."""
from __future__ import annotations
import os, socket
from pathlib import Path
from .models import ManagerError
class LockManager:
    def __init__(self,lock_root: str|Path): self.root=Path(lock_root).resolve(); self.held=[]
    def acquire(self,names: list[str],operation: str)->None:
        if self.held: raise ManagerError('resource_locked','Lock manager already owns locks',4)
        for name in sorted(set(names)):
            if not name or name.startswith('/') or '..' in Path(name).parts:
                self.release(); raise ManagerError('invalid_identity','Invalid lock name',3)
            path=self.root/name; path.parent.mkdir(parents=True,exist_ok=True)
            try: path.mkdir()
            except FileExistsError as exc:
                self.release(); raise ManagerError('resource_locked',f"Resource '{name}' is locked",5) from exc
            self.held.append(path); (path/'owner').write_text(f'{os.getpid()}\n{socket.gethostname()}\n{operation}\n',encoding='utf-8')
    def release(self)->None:
        for path in reversed(self.held):
            try: (path/'owner').unlink(missing_ok=True); path.rmdir()
            except OSError: pass
        self.held.clear()
    def __enter__(self): return self
    def __exit__(self,*_): self.release()
