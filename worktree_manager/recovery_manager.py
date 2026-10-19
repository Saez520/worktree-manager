"""Conservative transaction recovery: never interprets recovery as discard."""
from __future__ import annotations
from pathlib import Path
import json
from .models import ManagerError, ResultKind
from .transaction_journal import TransactionJournal
from .git_repository import GitRepository
from .lock_manager import LockManager
import hashlib
class RecoveryManager:
    def __init__(self,state_root: str|Path,repo_root: str|Path|None=None): self.journal=TransactionJournal(state_root); self.repo=GitRepository(repo_root) if repo_root else None
    def recover(self,transaction_id: str|None=None):
        if transaction_id is None:
            pending=[]
            for path in self.journal.root.glob('*/journal'):
                try:
                    if path.read_text(encoding='utf-8').strip() not in ('restored',): pending.append(path.parent.name)
                except OSError: continue
            if not pending: return ResultKind.NO_PENDING_WORK,None
            transaction_id=sorted(pending)[-1]
        phase=self.journal.read_phase(transaction_id)
        if phase in {'restored','closed','aborted'}: return ResultKind.NO_PENDING_WORK,{'transaction_id':transaction_id,'phase':phase}
        if self.repo is not None:
            # Validate transaction existence before marking/acquiring the lock.
            key=hashlib.sha256(str(self.repo.root.resolve()).encode()).hexdigest()
            locks=LockManager(self.journal.root.parent/'locks')
            with locks:
                locks.acquire([f'repository-{key}'],'recover')
                phase=self.journal.read_phase(transaction_id)
                return self._recover_locked(transaction_id,phase)
        return self._recover_locked(transaction_id,phase)

    def _recover_locked(self,transaction_id,phase):
        if phase=='pending_manual':
            if self.repo is None: return ResultKind.PENDING_INTERVENTION,{'transaction_id':transaction_id,'phase':phase}
            try: meta=json.loads((self.journal.directory(transaction_id)/'meta.json').read_text(encoding='utf-8'))
            except (OSError,ValueError) as exc: raise ManagerError('invalid_journal','Recovery metadata is corrupt; backups were retained',5) from exc
            lifecycle=__import__('worktree_manager.worktree_lifecycle',fromlist=['WorktreeLifecycle']).WorktreeLifecycle.__new__(__import__('worktree_manager.worktree_lifecycle',fromlist=['WorktreeLifecycle']).WorktreeLifecycle)
            lifecycle.config=type('RecoveryConfig',(),{'repo_root':self.repo.root,'backup_ref_prefix':meta.get('backup_ref_prefix','worktree-manager/backups')})()
            lifecycle.git=self.repo; lifecycle.journal=self.journal
            lifecycle._restore_saved(transaction_id,meta)
            self.journal.write_phase(transaction_id,'restored')
            return ResultKind.SUCCESS,{'transaction_id':transaction_id,'phase':'restored'}
        if phase=='restored': return ResultKind.NO_PENDING_WORK,{'transaction_id':transaction_id,'phase':phase}
        if phase in {'captured','merge_started','merged','remove_started','removed'}:
            if self.repo is None: raise ManagerError('recovery_requires_intervention','Repository context is required; no effects were changed',5)
            try: meta=json.loads((self.journal.directory(transaction_id)/'meta.json').read_text(encoding='utf-8'))
            except (OSError,ValueError) as exc: raise ManagerError('invalid_journal','Recovery metadata is corrupt; backups were retained',5) from exc
            if meta.get('base') is None or meta.get('branch') is None or meta.get('path') is None: raise ManagerError('invalid_journal','Transaction identity is incomplete',5)
            # Preserve-dirty captures are a separate recovery contract from a
            # durable squash. A crash can leave captured parent state that
            # must not be silently classified as a completed close, regardless
            # of whether HEAD advanced. Keep every artifact for intervention.
            if meta.get('preserve_dirty'):
                raise ManagerError('intervention_required','Preserved changes require explicit validated recovery; resources retained',5)
            head=self.repo.head(); before=meta.get('before'); branch=meta['branch']; path=Path(meta['path']); registered={line[9:] for line in self.repo.worktrees().splitlines() if line.startswith('worktree ')}
            # A durable squash interrupted before the close journal advances is
            # not a transaction recovery. Confirm the complete identity before
            # reporting no pending work; ambiguous movement remains actionable.
            if phase == 'merge_started' and head != before:
                base_tip=self.repo.run(('rev-parse',f"refs/heads/{meta['base']}"),check=False)
                worktree_head=self.repo.run(('-C',str(path),'rev-parse','HEAD'),check=False)
                symbolic=self.repo.run(('-C',str(path),'symbolic-ref','-q','HEAD'),check=False)
                branch_tip=self.repo.run(('rev-parse',f'refs/heads/{branch}'),check=False)
                parents=self.repo.run(('rev-list','--parents','-n','1',head),check=False).stdout.split()
                registered_paths={str(Path(item).resolve()) for item in registered}
                if (base_tip.returncode or base_tip.stdout.strip()!=head or
                    str(path.resolve()) not in registered_paths or
                    worktree_head.returncode or worktree_head.stdout.strip()!=meta.get('origin') or
                    symbolic.returncode or symbolic.stdout.strip()!=f'refs/heads/{branch}' or
                    branch_tip.returncode or branch_tip.stdout.strip()!=meta.get('origin') or
                    len(parents)!=2 or parents[0]!=head or parents[1]!=before):
                    raise ManagerError('intervention_required','Durable squash evidence is incomplete or ambiguous; resources retained',5)
                return ResultKind.NO_PENDING_WORK, None
            if phase in {'captured','merge_started'} and head==before:
                # The squash commit did not happen. Restore captured destination state once.
                if meta.get('preserve_dirty'):
                    from .worktree_lifecycle import WorktreeLifecycle
                    lifecycle=WorktreeLifecycle.__new__(WorktreeLifecycle); lifecycle.config=type('RecoveryConfig',(),{'repo_root':self.repo.root,'backup_ref_prefix':meta.get('backup_ref_prefix','worktree-manager/backups')})(); lifecycle.git=self.repo; lifecycle.journal=self.journal
                    lifecycle._restore_saved(transaction_id,meta)
                self.journal.write_phase(transaction_id,'restored')
                return ResultKind.SUCCESS,{'transaction_id':transaction_id,'phase':'restored','integrated':False}
            squash=meta.get('squash')
            if phase in {'merged','remove_started','removed'} and (not squash or head!=squash): raise ManagerError('intervention_required','Repository HEAD drifted from the recorded squash commit; resources retained',5)
            if path.exists() or str(path) in registered:
                if phase not in {'merged','remove_started'}: raise ManagerError('intervention_required','Worktree state is ambiguous; resources retained',5)
                if self.repo.run(('-C',str(path),'status','--porcelain')).stdout: raise ManagerError('intervention_required','Worktree is dirty; resources retained',5)
                self.journal.write_phase(transaction_id,'remove_started'); self.repo.run(('worktree','remove','--force','--',str(path)))
            self.journal.write_phase(transaction_id,'removed')
            ref=f"refs/heads/{branch}"; current=self.repo.run(('rev-parse',ref),check=False)
            if current.returncode==0:
                if current.stdout.strip()!=meta.get('origin'): raise ManagerError('intervention_required','Branch drifted; it was retained',5)
                self.repo.run(('update-ref','-d',ref,meta['origin']))
            if meta.get('preserve_dirty'):
                from .worktree_lifecycle import WorktreeLifecycle
                lifecycle=WorktreeLifecycle.__new__(WorktreeLifecycle); lifecycle.config=type('RecoveryConfig',(),{'repo_root':self.repo.root,'backup_ref_prefix':meta.get('backup_ref_prefix','worktree-manager/backups')})(); lifecycle.git=self.repo; lifecycle.journal=self.journal
                lifecycle._restore_saved(transaction_id,meta)
            self.journal.write_phase(transaction_id,'restored' if meta.get('preserve_dirty') else 'closed')
            return ResultKind.SUCCESS,{'transaction_id':transaction_id,'phase':self.journal.read_phase(transaction_id),'integrated':True}
        raise ManagerError('recovery_requires_intervention','Transaction requires its validated operation context; no effects were changed',5)
