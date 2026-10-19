"""Parent repository worktree lifecycle primitives."""
from __future__ import annotations
import re
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from .configuration import Configuration
from .git_repository import GitRepository
from .models import ManagerError
from .lock_manager import LockManager
from .transaction_journal import TransactionJournal

_WORK_ID = re.compile(r'^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$')
def validate_work_id(value: str) -> str:
    if not value or value.startswith('-') or not _WORK_ID.fullmatch(value) or any(p in ('.','..') or p.startswith('--') for p in value.split('/')):
        raise ManagerError('invalid_identity','Invalid work identifier',3)
    return value

class WorktreeLifecycle:
    def __init__(self, config: Configuration):
        self.config=config
        self.git=GitRepository(config.repo_root)
        self.state_root=self._state_root()
        self.journal=TransactionJournal(self.state_root)
    def _state_root(self)->Path:
        value=Path(self.git.run(('rev-parse','--git-dir')).stdout.strip())
        git_dir=(self.config.repo_root/value).resolve() if not value.is_absolute() else value.resolve()
        return git_dir/self.config.state_dir
    def _branch(self,work_id: str)->str: return self.config.branch_prefix+validate_work_id(work_id)
    def _lock_work_id(self,work_id: str)->str: return validate_work_id(work_id).encode('utf-8').hex()
    def _path(self,work_id: str)->Path:
        part=Path(validate_work_id(work_id)); root=Path(self.config.worktrees_dir)
        return (root/part if root.is_absolute() else self.config.repo_root/root/part).resolve()
    def _base(self,base: str)->str:
        if not base or base.startswith('-') or self.git.run(('check-ref-format','--branch',base),check=False).returncode:
            raise ManagerError('invalid_identity','Invalid base branch',3)
        if self.git.run(('show-ref','--verify','--quiet',f'refs/heads/{base}'),check=False).returncode:
            raise ManagerError('invalid_identity',f"Base branch '{base}' does not exist",3)
        return base
    def list(self)->list[dict[str,str]]:
        result=[]; path=None; branch=''
        for line in self.git.worktrees().splitlines()+['']:
            if line.startswith('worktree '): path=line[9:]; branch=''
            elif line.startswith('branch '): branch=line[7:]
            elif not line and path is not None: result.append({'path':path,'branch':branch}); path=None
        return result
    def create(self,work_id: str,base: str)->dict[str,str]:
        branch=self._branch(work_id); base=self._base(base); path=self._path(work_id)
        if self.git.run(('show-ref','--verify','--quiet',f'refs/heads/{branch}'),check=False).returncode==0 or path.exists():
            raise ManagerError('operation_failed','Worktree branch or path already exists',5)
        if not Path(self.config.worktrees_dir).is_absolute():
            rel=path.relative_to(self.config.repo_root).as_posix()
            if self.git.run(('check-ignore','-q','--',rel),check=False).returncode:
                raise ManagerError('invalid_configuration',f"Worktree path '{rel}' is not ignored",3)
        state=self.state_root
        locks=LockManager(state/self.config.lock_dir)
        with locks:
            locks.acquire([f'work/{self._lock_work_id(work_id)}'],'create')
            # Revalidate after acquiring the operation lock so concurrent create
            # attempts cannot both pass the preflight checks.
            if self.git.run(('show-ref','--verify','--quiet',f'refs/heads/{branch}'),check=False).returncode==0 or path.exists():
                raise ManagerError('operation_failed','Worktree branch or path already exists',5)
            path.parent.mkdir(parents=True,exist_ok=True)
            self.git.run(('worktree','add','-b',branch,str(path),base))
        return {'path':str(path),'branch':branch,'base_branch':base}
    def cleanup(self,work_id: str,discard: bool=False,base: str='main')->dict[str,str]:
        branch=self._branch(work_id); path=self._path(work_id); self._base(base)
        registered={item['path'] for item in self.list()}
        if str(path) not in registered or not path.exists(): raise ManagerError('invalid_identity','Worktree identity does not match registration',3)
        status=self.git.run(('-C',str(path),'status','--porcelain','--untracked-files=all')).stdout
        commits=self.git.run(('rev-list','--count',f'{base}..{branch}'),check=False).stdout.strip() or '0'
        if (status or int(commits)>0) and not discard: raise ManagerError('intervention_required','Worktree has changes or commits; explicit discard consent is required',5)
        self.git.run(('worktree','remove',*(('--force',) if discard else ()),str(path)))
        self.git.run(('branch','-D' if discard else '-d',branch))
        return {'cleaned':work_id,'branch':branch,'worktree':str(path)}
    def complete(self,work_id: str,base: str,preserve_dirty: bool=False)->dict[str,str]:
        """Squash a worktree branch and retire it only after verified success.

        Dirty-destination preservation is intentionally rejected until its capture
        and restoration protocol is available; it must never silently discard data.
        """
        branch=self._branch(work_id); base=self._base(base); path=self._path(work_id)
        registered={item['path'] for item in self.list()}
        if str(path) not in registered or not path.is_dir():
            raise ManagerError('invalid_identity','Worktree identity does not match registration',3)
        current=self.git.run(('symbolic-ref','--short','HEAD')).stdout.strip()
        if current != base: raise ManagerError('invalid_identity',f"Current branch must be '{base}'",3)
        if self.git.run(('show-ref','--verify','--quiet',f'refs/heads/{branch}'),check=False).returncode:
            raise ManagerError('invalid_identity','Worktree branch does not exist',3)
        if self.git.run(('-C',str(path),'status','--porcelain','--untracked-files=all')).stdout:
            raise ManagerError('intervention_required','Worktree has uncommitted changes; it was retained',5)
        status=self.git.run(('status','--porcelain','--untracked-files=all')).stdout
        if status and not preserve_dirty:
            raise ManagerError('intervention_required','Destination has uncommitted changes; use --preserve-dirty to retain them',5)
        state=self.state_root
        locks=LockManager(state/self.config.lock_dir)
        tx=uuid.uuid4().hex
        journal=TransactionJournal(state)
        before=self.git.head(); origin=self.git.run(('rev-parse',f'refs/heads/{branch}')).stdout.strip()
        meta={'work_id':work_id,'base':base,'branch':branch,'path':str(path),'before':before,'origin':origin,
              'preserve_dirty':bool(status),'tracked_ref':None,'untracked_ref':None,
              'backup_ref_prefix':self.config.backup_ref_prefix}
        meta_path=journal.directory(tx)/'meta.json'
        def save_meta(phase):
            journal.write_phase(tx,phase)
            meta['phase']=phase
            meta_path.parent.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(dir=meta_path.parent,prefix='.meta-')
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as stream: json.dump(meta,stream,sort_keys=True); stream.flush(); os.fsync(stream.fileno())
                os.chmod(tmp,0o600); os.replace(tmp,meta_path)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
        key=hashlib.sha256(str(self.config.repo_root).encode()).hexdigest()
        with locks:
            locks.acquire([f'repository-{key}',f'work/{self._lock_work_id(work_id)}'],'complete')
            try:
                if status:
                    # Keep the original index/worktree as a Git stash commit and
                    # separately retain untracked files in a private tree ref.
                    tracked=self.git.run(('stash','create',f'worktree-manager-backup {tx}'),check=False).stdout.strip()
                    if not tracked:
                        raise ManagerError('operation_failed','Could not capture destination changes; nothing was modified',5)
                    tracked_ref=f'refs/{self.config.backup_ref_prefix.strip("/")}/{tx}'
                    self.git.run(('update-ref',tracked_ref,tracked)); meta['tracked_ref']=tracked_ref
                    untracked=self.git.run(('ls-files','--others','--exclude-standard','-z')).stdout
                    names=[x for x in untracked.split('\0') if x]
                    if names:
                        with tempfile.TemporaryDirectory(prefix='wt-index-') as td:
                            index=Path(td)/'index'; env={'GIT_INDEX_FILE':str(index)}
                            import subprocess
                            subprocess.run(['git','-C',str(self.config.repo_root),'read-tree','--empty'],env={**os.environ,**env},check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                            subprocess.run(['git','-C',str(self.config.repo_root),'add','-f','--',*names],env={**os.environ,**env},check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                            tree=subprocess.run(['git','-C',str(self.config.repo_root),'write-tree'],env={**os.environ,**env},check=True,text=True,stdout=subprocess.PIPE).stdout.strip()
                        oid=self.git.run(('commit-tree',tree,'-m',f'worktree-manager-backup-untracked {tx}')).stdout.strip()
                        untracked_ref=f'refs/{self.config.backup_ref_prefix.strip("/")}/{tx}-untracked'
                        self.git.run(('update-ref',untracked_ref,oid)); meta['untracked_ref']=untracked_ref
                    save_meta('captured')
                    # Clear only captured state; backups remain until recovery succeeds.
                    self.git.run(('restore','--source=HEAD','--staged','--worktree','--','.'),check=False)
                    for name in names if 'names' in locals() else []:
                        candidate=self.config.repo_root/name
                        if candidate.is_file() or candidate.is_symlink(): candidate.unlink()
                save_meta('merge_started')
                merged=self.git.run(('merge','--squash',branch),check=False)
                if merged.returncode or self.git.run(('diff','--cached','--quiet'),check=False).returncode==0:
                    self.git.run(('reset','--merge'),check=False)
                    save_meta('pending_manual')
                    raise ManagerError('operation_failed','Squash merge failed or produced no changes; worktree and branch retained',5)
                self.git.run(('commit','-m',f'squash merge {branch}'))
                after=self.git.head()
                if after==before or len(self.git.run(('rev-list','--parents','-n','1',after)).stdout.split())!=2:
                    save_meta('pending_manual'); raise ManagerError('operation_failed','Squash commit verification failed; resources retained',5)
                meta['squash']=after; save_meta('merged')
                self.git.run(('worktree','remove','--force','--',str(path)))
                if path.exists() or str(path) in {item['path'] for item in self.list()}:
                    save_meta('pending_manual'); raise ManagerError('operation_failed','Worktree removal could not be verified',5)
                save_meta('removed')
                if self.git.run(('rev-parse',f'refs/heads/{branch}')).stdout.strip()!=origin:
                    save_meta('pending_manual'); raise ManagerError('operation_failed','Branch changed; it was retained',5)
                self.git.run(('update-ref','-d',f'refs/heads/{branch}',origin)); save_meta('closed')
                if status:
                    meta['squash']=after; save_meta('merged')
                    self._restore_saved(tx,meta)
                    save_meta('restored')
                return {'completed':work_id,'branch':branch,'base_branch':base,'worktree':str(path),'squash_commit':after,'transaction_id':tx}
            finally: locks.release()

    def _restore_saved(self,tx,meta):
        try:
            if meta.get('tracked_ref'):
                self.git.run(('stash','apply','--index',meta['tracked_ref']))
            ref=meta.get('untracked_ref')
            if ref:
                entries=self.git.run(('ls-tree','-r','--name-only','-z',ref)).stdout.split('\0')
                for name in filter(None,entries):
                    dest=self.config.repo_root/name
                    if dest.exists() or dest.is_symlink(): raise ManagerError('intervention_required','Untracked restore collides with a file created after completion; backup retained',5)
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    self.git.run(('restore',f'--source={ref}','--worktree','--',f'./{name}'))
        except ManagerError as exc:
            self.journal.write_phase(tx,'pending_manual')
            raise ManagerError('intervention_required',f"Restore requires manual intervention; transaction {tx} and backups are retained",5) from exc
    def prune(self)->dict[str,int]:
        self.git.run(('worktree','prune'))
        return {'pruned':0}
