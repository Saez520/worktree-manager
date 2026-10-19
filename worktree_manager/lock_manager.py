"""Process-safe directory locks acquired in deterministic order."""
from __future__ import annotations
import os, socket, json, tempfile
from pathlib import Path
from .models import ManagerError
class LockManager:
    def __init__(self,lock_root: str|Path): self.root=Path(lock_root).resolve(); self.held=[]; self.barrier=os.environ.get('WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR')
    def _mark(self, phase):
        if not self.barrier: return
        root=Path(self.barrier); root.mkdir(parents=True,exist_ok=True)
        path=root/phase; fd,name=tempfile.mkstemp(prefix='.tmp-',dir=root)
        try:
            with os.fdopen(fd,'w') as stream: json.dump({'phase':phase,'pid':os.getpid()},stream); stream.flush(); os.fsync(stream.fileno())
            os.replace(name,path)
        finally:
            if os.path.exists(name): os.unlink(name)
    def acquire(self,names: list[str],operation: str)->None:
        if self.held: raise ManagerError('resource_locked','Lock manager already owns locks',4)
        self._mark('pre_lock_validation')
        for name in sorted(set(names)):
            if not name or name.startswith('/') or '..' in Path(name).parts:
                self.release(); raise ManagerError('invalid_identity','Invalid lock name',3)
            path=self.root/name; path.parent.mkdir(parents=True,exist_ok=True)
            try: path.mkdir()
            except FileExistsError as exc:
                self.release(); raise ManagerError('resource_locked',f"Resource '{name}' is locked",5) from exc
            self.held.append(path); (path/'owner').write_text(f'{os.getpid()}\n{socket.gethostname()}\n{operation}\n',encoding='utf-8')
        self._mark('lock_acquired')
    def release(self)->None:
        for path in reversed(self.held):
            try: (path/'owner').unlink(missing_ok=True); path.rmdir()
            except OSError: pass
        self.held.clear()
    def __enter__(self): return self
    def __exit__(self,*_): self.release()
