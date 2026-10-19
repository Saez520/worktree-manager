"""Strict reader for persisted target-direct descriptors."""
from __future__ import annotations
import re
from pathlib import Path
import hashlib, os, shutil, subprocess, tempfile
import signal
from .models import ManagerError, TargetDirectIdentity

_KEYS=frozenset({'descriptor_version','operation','target_kind','target_repo','target_common_dir','parent_repo','parent_common_dir','submodule_path','gitlink_sha','target_head','base','base_sha','branch','worktree_path','link_parent','owner','phase','tx_id','index_snapshot_ref'})
_SHA=re.compile(r'^[0-9a-fA-F]{40}$')
_PHASES=frozenset('initial descriptor_written validated worktree_created ready snapshot_captured staged_started staged verified complete_validated remove_started removed closed reconciled index_reconcile_started index_restored recovered aborted blocked'.split())
def load_descriptor(path: str|Path)->tuple[dict[str,str],TargetDirectIdentity]:
    try: lines=Path(path).read_text(encoding='utf-8').splitlines()
    except OSError as exc: raise ManagerError('invalid_descriptor','Target descriptor is unavailable',3) from exc
    values={}
    for line in lines:
        if not line or '=' not in line or '\r' in line: raise ManagerError('invalid_descriptor','Malformed target descriptor',3)
        key,value=line.split('=',1)
        if key not in _KEYS or key in values or not value or '\n' in value: raise ManagerError('invalid_descriptor','Unknown, duplicate, or empty descriptor field',3)
        values[key]=value
    if values.keys()!=_KEYS: raise ManagerError('invalid_descriptor','Target descriptor is incomplete',3)
    if values['descriptor_version']!='1' or values['target_kind']!='submodule' or values['link_parent']!='staged-only': raise ManagerError('invalid_descriptor','Unsupported target descriptor contract',3)
    for key in ('target_repo','target_common_dir','parent_repo','parent_common_dir','worktree_path','index_snapshot_ref'):
        if not Path(values[key]).is_absolute(): raise ManagerError('invalid_descriptor','Descriptor paths must be absolute',3)
    if not re.fullmatch(r'[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*',values['submodule_path']) or any(p in ('.','..') for p in values['submodule_path'].split('/')): raise ManagerError('invalid_descriptor','Invalid submodule path',3)
    for key in ('gitlink_sha','target_head','base_sha'):
        if not _SHA.fullmatch(values[key]): raise ManagerError('invalid_descriptor','Invalid descriptor object ID',3)
    if values['phase'] not in _PHASES: raise ManagerError('invalid_descriptor','Unknown target descriptor phase',3)
    if values['operation'] not in {'create','link-parent','abort','complete'}: raise ManagerError('invalid_descriptor','Unknown target operation',3)
    identity=TargetDirectIdentity(values['target_repo'],values['parent_repo'],values['submodule_path'],values['link_parent'])
    return values,identity

class TargetDirectAdapter:
    """Operate on persisted submodule identity without deriving paths from cwd."""
    def __init__(self, descriptor_path: str|Path):
        self.path=Path(descriptor_path).resolve(); self.values,self.identity=load_descriptor(self.path)
        self.parent=Path(self.values['parent_repo']); self.target=Path(self.values['target_repo'])
        self.snapshot=Path(self.values['index_snapshot_ref'])
        if self.values['link_parent']!='staged-only': raise ManagerError('invalid_descriptor','Only staged-only parent linking is supported',3)
    @classmethod
    def create(cls, descriptor_path: str|Path, target_repo: str|Path, parent_repo: str|Path,
               submodule_path: str, work_id: str, base: str='main'):
        """Create a target worktree and persist its complete recovery identity."""
        target=Path(target_repo).resolve(); parent=Path(parent_repo).resolve()
        def git(root,*args):
            r=subprocess.run(['git','-C',str(root),*args],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            if r.returncode: raise ManagerError('operation_failed',r.stderr.strip() or 'Git operation failed',5)
            return r.stdout.strip()
        if not re.fullmatch(r'[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*',submodule_path) or any(x in ('.','..') for x in submodule_path.split('/')):
            raise ManagerError('invalid_identity','Invalid submodule path',3)
        for root in (target,parent): git(root,'rev-parse','--show-toplevel')
        base_sha=git(target,'rev-parse',f'refs/heads/{base}')
        branch=f'worktree/{work_id}'; worktree=target/'.worktrees'/work_id
        if worktree.exists() or subprocess.run(['git','-C',str(target),'show-ref','--verify','--quiet',f'refs/heads/{branch}']).returncode==0:
            raise ManagerError('operation_failed','Target worktree or branch already exists',5)
        git(target,'worktree','add','-b',branch,str(worktree),base)
        head=git(worktree,'rev-parse','HEAD')
        target_common=Path(git(target,'rev-parse','--git-common-dir')); target_common=(target/target_common).resolve() if not target_common.is_absolute() else target_common
        parent_common=Path(git(parent,'rev-parse','--git-common-dir')); parent_common=(parent/parent_common).resolve() if not parent_common.is_absolute() else parent_common
        parent_gitdir=Path(git(parent,'rev-parse','--git-dir')); parent_gitdir=(parent/parent_gitdir).resolve() if not parent_gitdir.is_absolute() else parent_gitdir
        index=Path(git(parent,'rev-parse','--git-path','index')); index=index if index.is_absolute() else parent/index
        tx='wt-'+work_id; snapshot=target_common/'worktree-manager'/'target-direct'/hashlib.sha256(work_id.encode()).hexdigest()/'snapshot'
        values={'descriptor_version':'1','operation':'create','target_kind':'submodule','target_repo':str(target),'target_common_dir':str(target_common),'parent_repo':str(parent),'parent_common_dir':str(parent_common),'submodule_path':submodule_path,'gitlink_sha':git(parent,'rev-parse','HEAD'),'target_head':head,'base':base,'base_sha':base_sha,'branch':branch,'worktree_path':str(worktree),'link_parent':'staged-only','owner':'python','phase':'ready','tx_id':tx,'index_snapshot_ref':str(snapshot)}
        path=Path(descriptor_path).resolve(); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(''.join(f'{k}={v}\n' for k,v in values.items()),encoding='utf-8'); path.chmod(0o600)
        return cls(path)
    def _git(self,root,*args,check=True):
        result=subprocess.run(['git','-C',str(root),*args],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if check and result.returncode: raise ManagerError('operation_failed',result.stderr.strip() or 'Git operation failed',5)
        return result
    def link_parent(self):
        """Stage the submodule commit as a gitlink and do not commit the parent."""
        if self.values['phase'] not in {'ready','snapshot_captured','staged_started'}: raise ManagerError('invalid_descriptor','Descriptor phase does not permit parent linking',4)
        worktree=Path(self.values['worktree_path'])
        if worktree.is_dir():
            self.values['target_head']=self._git(worktree,'rev-parse','HEAD').stdout.strip()
        index=Path(self._git(self.parent,'rev-parse','--git-path','index').stdout.strip()); index=index if index.is_absolute() else self.parent/index
        self.snapshot.mkdir(parents=True,exist_ok=True)
        shutil.copy2(index,self.snapshot/'index.bytes')
        (self.snapshot/'head.sha').write_text(self._git(self.parent,'rev-parse','HEAD').stdout.strip()+'\n')
        (self.snapshot/'index.sha256').write_text(hashlib.sha256((self.snapshot/'index.bytes').read_bytes()).hexdigest()+'\n')
        (self.snapshot/'entry').write_bytes(self._git(self.parent,'ls-files','--stage','--',self.identity.submodule_path).stdout.encode())
        (self.snapshot/'entries').write_bytes(self._git(self.parent,'ls-files','--stage').stdout.encode())
        self.values['phase']='snapshot_captured'; self._write_descriptor()
        self.values['phase']='staged_started'; self._write_descriptor()
        self._git(self.parent,'update-index','--add','--cacheinfo',f"160000,{self.values['target_head']},{self.identity.submodule_path}")
        got=self._git(self.parent,'ls-files','--stage','--',self.identity.submodule_path).stdout.strip()
        expected=f"160000 {self.values['target_head']} 0\t{self.identity.submodule_path}"
        if got!=expected: self.abort(); raise ManagerError('operation_failed','Staged parent entry is not the expected gitlink',5)
        self.values['gitlink_sha']=self.values['target_head']
        index_path=Path(self._git(self.parent,'rev-parse','--git-path','index').stdout.strip()); index_path=index_path if index_path.is_absolute() else self.parent/index_path
        (self.snapshot/'staged-index.sha256').write_text(hashlib.sha256(index_path.read_bytes()).hexdigest()+'\n')
        self.values['phase']='staged'; self._write_descriptor()
        return {'link_parent':'staged-only','gitlink':got,'parent_committed':False}
    def abort(self):
        if not (self.snapshot/'index.bytes').is_file(): raise ManagerError('invalid_descriptor','Index snapshot is unavailable',4)
        expected=(self.snapshot/'index.sha256').read_text().strip()
        index=Path(self._git(self.parent,'rev-parse','--git-path','index').stdout.strip()); index=index if index.is_absolute() else self.parent/index
        actual=hashlib.sha256(index.read_bytes()).hexdigest()
        head=self._git(self.parent,'rev-parse','HEAD').stdout.strip()
        original=(self.snapshot/'head.sha').read_text().strip()
        if head!=original or actual!=expected:
            entry=(self.snapshot/'entry').read_text()
            staged=self._git(self.parent,'ls-files','--stage','--',self.identity.submodule_path).stdout
            staged_hash=(self.snapshot/'staged-index.sha256').read_text().strip() if (self.snapshot/'staged-index.sha256').exists() else ''
            saved_entries=(self.snapshot/'entries').read_text().splitlines()
            current_entries=self._git(self.parent,'ls-files','--stage').stdout.splitlines()
            unchanged=sorted(current_entries)==sorted(saved_entries)
            staged_gitlink=staged.strip()==f"160000 {self.values['target_head']} 0\t{self.identity.submodule_path}" and actual==staged_hash
            if head!=original or not (unchanged or staged_gitlink):
                raise ManagerError('intervention_required','Parent index drift is ambiguous; snapshot retained',5)
        tmp=index.with_name(index.name+'.restore-'+os.urandom(4).hex())
        shutil.copy2(self.snapshot/'index.bytes',tmp); os.replace(tmp,index)
        self.values['phase']='aborted'; self._write_descriptor()
        return {'aborted':True,'parent_commit_unchanged':True}
    def complete(self):
        if self.values['phase'] not in {'staged','verified','complete_validated','remove_started','removed','closed'}: raise ManagerError('invalid_descriptor','Descriptor phase does not permit complete',4)
        staged=self._git(self.parent,'ls-files','--stage','--',self.identity.submodule_path).stdout.strip()
        if staged!=f"160000 {self.values['target_head']} 0\t{self.identity.submodule_path}": raise ManagerError('intervention_required','Parent gitlink differs from the recorded target commit',5)
        path=Path(self.values['worktree_path']); branch=self.values['branch']; head=self.values['target_head']
        if path.exists():
            if self._git(path,'status','--porcelain').stdout: raise ManagerError('intervention_required','Target worktree is dirty and was retained',5)
            self._git(self.target,'worktree','remove',str(path))
        if self._git(self.target,'show-ref','--verify','--quiet',f'refs/heads/{branch}',check=False).returncode==0:
            self._git(self.target,'update-ref','-d',f'refs/heads/{branch}',head)
        self.values['phase']='closed'; self._write_descriptor()
        return {'completed':True,'parent_worktree':None}
    def recover(self):
        """Reconcile observed resources after interruption; repeated calls are safe."""
        phase=self.values['phase']
        if phase in {'aborted','blocked','closed','recovered'}:
            return {'recovered':True,'classification':'A','phase':phase}
        if phase in {'verified','staged','staged_started','snapshot_captured','descriptor_written','reconciled','index_reconcile_started'}:
            # An interrupted descriptor transition is not proof that parent
            # reconciliation completed. Persist a terminal blocked marker once;
            # subsequent calls are idempotent and retain all recovery evidence.
            if phase in {'descriptor_written','reconciled','index_reconcile_started','snapshot_captured','staged_started'}:
                self.values['phase']='blocked'; self._write_descriptor()
                raise ManagerError('intervention_required','Target recovery evidence is incomplete or ambiguous; descriptor and snapshot retained',6)
            if not (self.snapshot/'index.bytes').is_file() or not (self.snapshot/'entries').is_file() or not (self.snapshot/'head.sha').is_file():
                self.values['phase']='blocked'; self._write_descriptor()
                raise ManagerError('intervention_required','Target recovery snapshot is incomplete; evidence retained',6)
            if (self.snapshot/'index.bytes').exists():
                original=(self.snapshot/'entries').read_text().splitlines()
                current=self._git(self.parent,'ls-files','--stage').stdout.splitlines()
                wanted=f"160000 {self.values['target_head']} 0\t{self.identity.submodule_path}"
                original_target=[line for line in original if line.split('\t',1)[-1]==self.identity.submodule_path]
                current_target=[line for line in current if line.split('\t',1)[-1]==self.identity.submodule_path]
                # A completed link-parent is our intentional index mutation, not
                # proof of arbitrary drift. Compare the full logical index while
                # allowing only that exact gitlink delta; raw index bytes include
                # Git's refreshable stat cache and are not a semantic snapshot.
                expected=[line for line in original if line.split('\t',1)[-1]!=self.identity.submodule_path]
                expected.append(wanted)
                unchanged = sorted(current) == sorted(original)
                if phase == 'staged':
                    if current_target == [wanted] and sorted(current) == sorted(expected):
                        raise ManagerError('intervention_required','Parent gitlink is intentionally staged; snapshot retained',6)
                    raise ManagerError('intervention_required','Parent index drift is ambiguous; snapshot retained',6)
                if unchanged:
                    self.abort()
                elif current_target == [wanted] and sorted(current) == sorted(expected):
                    self.abort()
                else:
                    raise ManagerError('intervention_required','Parent index drift is ambiguous; snapshot retained',6)
            self.values['phase']='recovered'; self._write_descriptor()
            return {'recovered':True,'classification':'A','phase':'recovered'}
        if phase in {'complete_validated','remove_started','removed'}:
            path=Path(self.values['worktree_path'])
            registered=str(path) in [line[9:] for line in self._git(self.target,'worktree','list','--porcelain').stdout.splitlines() if line.startswith('worktree ')]
            if registered:
                if phase not in {'complete_validated','remove_started'} or not path.exists(): raise ManagerError('intervention_required','Target worktree registration drifted; retained',5)
                if self._git(path,'status','--porcelain').stdout: raise ManagerError('intervention_required','Target worktree is dirty; retained',5)
                if phase=='complete_validated': self.values['phase']='remove_started'; self._write_descriptor()
                self._git(self.target,'worktree','remove',str(path))
            if path.exists(): raise ManagerError('intervention_required','Target worktree removal is incomplete',5)
            self.values['phase']='removed'; self._write_descriptor()
            branch=f"refs/heads/{self.values['branch']}"; current=self._git(self.target,'rev-parse',branch,check=False)
            if current.returncode==0:
                if current.stdout.strip()!=self.values['target_head']: raise ManagerError('intervention_required','Target branch drifted; retained',5)
                self._git(self.target,'update-ref','-d',branch,self.values['target_head'])
            self.values['phase']='closed'; self._write_descriptor()
            return {'recovered':True,'classification':'A','phase':'closed'}
        raise ManagerError('recovery_requires_intervention','Descriptor phase requires manual intervention',5)
    def _write_descriptor(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        text=''.join(f'{k}={v}\n' for k,v in self.values.items())
        fd,tmp=tempfile.mkstemp(dir=self.path.parent,prefix='.descriptor-')
        try:
            with os.fdopen(fd,'w') as out: out.write(text); out.flush(); os.fsync(out.fileno())
            os.chmod(tmp,0o600); os.replace(tmp,self.path)
            # Test-only barrier models process death after a durable descriptor
            # transition and before the next Git side effect.
            if os.environ.get('WORKTREE_MANAGER_TEST_CRASH_AFTER_DESCRIPTOR_PHASE') == self.values['phase']:
                os.kill(os.getpid(), signal.SIGKILL)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
