"""Retained Git refs; pending backups are never automatically pruned."""
from __future__ import annotations
from .git_repository import GitRepository
from .models import ManagerError
class BackupStore:
    def __init__(self,repository: GitRepository,backup_ref_prefix: str):
        self.repository,self.prefix=repository,backup_ref_prefix.strip('/')
        if not self.prefix or '..' in self.prefix.split('/'): raise ManagerError('invalid_configuration','Unsafe backup ref prefix',3)
    def ref(self,tx: str,suffix: str='')->str:
        if not tx or '/' in tx: raise ManagerError('invalid_identity','Invalid transaction identifier',3)
        return f'refs/{self.prefix}/{tx}{suffix}'
    def retain(self,tx: str,oid: str,suffix: str='')->None: self.repository.run(('update-ref',self.ref(tx,suffix),oid))
    def resolve(self,tx: str,suffix: str='')->str|None:
        result=self.repository.run(('rev-parse','--verify','--quiet',self.ref(tx,suffix)),check=False)
        return result.stdout.strip() if result.returncode==0 else None
    def delete(self,tx: str,suffix: str='')->None: self.repository.run(('update-ref','-d',self.ref(tx,suffix)),check=False)
