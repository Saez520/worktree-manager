"""Standalone Python command dispatcher."""
from __future__ import annotations
import argparse,sys,subprocess
from pathlib import Path
from .configuration import Configuration
from .git_repository import GitRepository
from .models import ManagerError,OperationResult,ResultKind
from .output import emit
from .worktree_lifecycle import WorktreeLifecycle
from .recovery_manager import RecoveryManager
from .target_direct_adapter import TargetDirectAdapter
VERSION='1.0.0'
class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ManagerError('usage_error',message,2)
def _parser():
    parser=_Parser(prog='python3 -m worktree_manager'); parser.add_argument('--json',action='store_true'); parser.add_argument('--version',action='version',version=VERSION); parser.add_argument('--repo'); parser.add_argument('--config'); sub=parser.add_subparsers(dest='command',required=True,parser_class=_Parser)
    for name in ('create','complete','cleanup'):
        p=sub.add_parser(name); p.add_argument('work_id'); p.add_argument('--base');
        if name=='cleanup': p.add_argument('--discard',action='store_true')
        if name=='complete': p.add_argument('--preserve-dirty',action='store_true')
    p=sub.add_parser('recover'); p.add_argument('transaction_id',nargs='?')
    sub.add_parser('list'); sub.add_parser('prune')
    td=sub.add_parser('target-direct'); td.add_argument('action',choices=('create','link-parent','abort','complete','recover')); td.add_argument('work_id'); td.add_argument('--parent-repo',required=True); td.add_argument('--target',choices=('submodule',),default='submodule'); td.add_argument('--submodule-path'); td.add_argument('--base',default='main'); td.add_argument('--link-parent',choices=('staged-only',),default='staged-only'); td.add_argument('--descriptor')
    return parser
def main(argv=None)->int:
    operation='usage'; json_mode='--json' in (argv if argv is not None else sys.argv[1:])
    try:
        raw_argv = list(argv if argv is not None else sys.argv[1:])
        if '--version' in raw_argv and any(arg not in {'--version', '--json'} for arg in raw_argv):
            raise ManagerError('usage_error', "unrecognized arguments: extra arguments with --version", 2)
        args=_parser().parse_args(argv); operation=args.command
        if operation=='target-direct':
            target=Path(args.repo).expanduser().resolve() if args.repo else Path.cwd().resolve()
            if not args.descriptor:
                common=Path(subprocess.run(['git','-C',str(target),'rev-parse','--git-common-dir'],check=True,text=True,stdout=subprocess.PIPE).stdout.strip())
                if not common.is_absolute(): common=(target/common).resolve()
                import hashlib
                descriptor_id=args.work_id[3:] if args.action=='recover' and args.work_id.startswith('wt-') else args.work_id
                args.descriptor=str(common/'worktree-manager'/'target-direct'/hashlib.sha256(descriptor_id.encode()).hexdigest()/'descriptor')
            if args.action=='create':
                if not args.submodule_path: raise ManagerError('invalid_identity','--submodule-path is required',2)
                adapter=TargetDirectAdapter.create(args.descriptor,target,args.parent_repo,args.submodule_path,args.work_id,args.base)
                data={'created':True,'worktree':adapter.values['worktree_path'],'branch':adapter.values['branch'],'descriptor':str(adapter.path)}
            else:
                adapter=TargetDirectAdapter(args.descriptor)
                if adapter.values['target_repo']!=str(target) or adapter.values['parent_repo']!=str(Path(args.parent_repo).resolve()) or adapter.values['tx_id'] not in {args.work_id,'wt-'+args.work_id}:
                    raise ManagerError('invalid_descriptor','Target descriptor identity does not match command arguments',3)
                data={'link-parent':adapter.link_parent,'abort':adapter.abort,'complete':adapter.complete,'recover':adapter.recover}[args.action]()
            result=OperationResult('target-direct',data=data); emit(result,args.json)
            # The established target-direct command reports abort through its
            # dedicated public status (6), including a successfully restored
            # index; the result envelope remains success in that case.
            return 6 if args.action=='abort' and result.exit_code==0 else result.exit_code
        root=Path(args.repo).expanduser() if args.repo else Path.cwd()
        if not root.is_absolute(): raise ManagerError('invalid_repository','Repository path must be absolute',3)
        repository=GitRepository(root)
        if operation=='recover':
            config=Configuration.load(repository.root,args.config)
            git_dir=Path(repository.run(('rev-parse','--git-dir')).stdout.strip())
            if not git_dir.is_absolute(): git_dir=(repository.root/git_dir).resolve()
            kind,data=RecoveryManager(git_dir/config.state_dir,repository.root).recover(args.transaction_id)
            result=OperationResult(operation,kind,data or {})
        else:
            config=Configuration.load(repository.root,args.config); lifecycle=WorktreeLifecycle(config)
            if operation=='list': result=OperationResult(operation,data={'worktrees':lifecycle.list()})
            elif operation=='prune':
                data=lifecycle.prune()
                result=OperationResult(operation,ResultKind.NO_PENDING_WORK if data.get('pruned',0)==0 else ResultKind.SUCCESS,data=data)
            elif operation=='create':
                base=args.base or next((b for b in ('development','main','trunk') if repository.run(('show-ref','--verify','--quiet',f'refs/heads/{b}'),check=False).returncode==0),'main')
                data=lifecycle.create(args.work_id,base)
                data.update({'init_submodules':'false','init_submodules_result':'not_requested','prepare':'skipped','verify':'skipped'})
                result=OperationResult(operation,data=data)
            elif operation=='cleanup': result=OperationResult(operation,data=lifecycle.cleanup(args.work_id,args.discard,args.base or 'main'))
            elif operation=='complete':
                data=lifecycle.complete(args.work_id,args.base or 'main',args.preserve_dirty)
                data['merge']='success'
                result=OperationResult(operation,data=data)
        if operation=='list' and not args.json:
            sys.stdout.write(repository.run(('worktree','list','--porcelain')).stdout)
            return result.exit_code
        emit(result,args.json); return result.exit_code
    except ManagerError as exc:
        if exc.code == 'resource_locked':
            exc = ManagerError('operation_failed', exc.message, 5)
        emit(OperationResult(operation,ResultKind.PENDING_INTERVENTION if exc.code=='intervention_required' else ResultKind.FAILURE,error=exc),getattr(locals().get('args',None),'json',json_mode)); return exc.exit_code

def usage(argv=None)->int:
    try: return main(argv)
    except SystemExit as exc: return int(exc.code)
