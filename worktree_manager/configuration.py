"""Validated configuration matching the standalone key=value configuration."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from .models import ManagerError

@dataclass(frozen=True)
class Configuration:
    repo_root: Path
    worktrees_dir: str = '.worktrees'
    branch_prefix: str = 'worktree/'
    state_dir: str = 'worktree-manager'
    backup_dir: str = 'backups'
    backup_ref_prefix: str = 'worktree-manager/backups'
    lock_dir: str = 'locks'
    prepare_command: str = ''
    verify_command: str = ''
    prepare_enabled: bool = False
    verify_enabled: bool = False
    preserve_dirty: bool = False

    @classmethod
    def load(cls, repo_root: str|Path, config_path: str|Path|None=None, environ: dict[str,str]|None=None)->'Configuration':
        root=Path(repo_root).expanduser()
        if not root.is_absolute() or not root.is_dir(): raise ManagerError('invalid_repository','Repository root must be an existing absolute directory',3)
        path=Path(config_path).expanduser() if config_path is not None else root/'.worktree-manager.conf'
        values={}
        if config_path is not None and (not path.is_absolute() or not path.is_file()): raise ManagerError('invalid_configuration','Configuration must be an existing absolute file',3)
        if path.is_file():
            try: lines=path.read_text(encoding='utf-8').splitlines()
            except OSError as exc: raise ManagerError('invalid_configuration','Cannot read configuration',3) from exc
            for line in lines:
                if not line or line.startswith('#'): continue
                if '=' not in line: raise ManagerError('invalid_configuration','Configuration lines must use key=value',3)
                key,value=line.split('=',1)
                if key in values: raise ManagerError('invalid_configuration',f'Duplicate configuration key: {key}',3)
                values[key]=value
        allowed={'worktrees_dir','branch_prefix','state_dir','backup_dir','backup_ref_prefix','lock_dir','prepare_command','verify_command','prepare_enabled','verify_enabled','preserve_dirty'}
        if set(values)-allowed: raise ManagerError('invalid_configuration','Configuration contains unknown keys',3)
        env=os.environ if environ is None else environ
        for key in allowed:
            name='WORKTREE_MANAGER_'+key.upper()
            if name in env: values[key]=env[name]
        for key,value in values.items():
            if '\x00' in value or '\n' in value or '\r' in value: raise ManagerError('invalid_configuration',f'Invalid value for {key}',3)
        for key in ('state_dir','lock_dir'):
            value=values.get(key,'')
            if value and (Path(value).is_absolute() or '..' in Path(value).parts or value in ('.','')): raise ManagerError('invalid_configuration',f'Unsafe relative path for {key}',3)
        for key in ('worktrees_dir','backup_dir'):
            value=values.get(key,'')
            if value and (value.startswith('-') or (key=='backup_dir' and (Path(value).is_absolute() or '..' in Path(value).parts))): raise ManagerError('invalid_configuration',f'Invalid path for {key}',3)
        if values.get('backup_ref_prefix','').find('..')>=0: raise ManagerError('invalid_configuration','Invalid backup ref prefix',3)
        bools={'prepare_enabled','verify_enabled','preserve_dirty'}
        for key in bools:
            if key in values:
                if values[key] not in ('true','false'): raise ManagerError('invalid_configuration',f'{key} must be true or false',3)
                values[key]=values[key]=='true'
        if values.get('prepare_enabled') and not values.get('prepare_command'): raise ManagerError('invalid_configuration','prepare_enabled requires prepare_command',3)
        if values.get('verify_enabled') and not values.get('verify_command'): raise ManagerError('invalid_configuration','verify_enabled requires verify_command',3)
        return cls(repo_root=root.resolve(),**values)
