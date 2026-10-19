import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from worktree_manager.mcp_operations import call
from worktree_manager.models import ManagerError


class RestartReconcileTests(unittest.TestCase):
    def repo(self, parent):
        root = Path(parent) / 'repo'; root.mkdir()
        def git(*args, check=True):
            return subprocess.run(['git','-C',str(root),*args],check=check,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        git('init','-b','main'); git('config','user.name','Test'); git('config','user.email','test@example.invalid')
        (root/'.gitignore').write_text('.worktrees/\n'); (root/'base').write_text('base')
        git('add','.gitignore','base'); git('commit','-m','base')
        return root, git

    def setup_change(self, root):
        created=call('worktree_create',{'repo':str(root),'work_id':'feature','base':'main'})['data']
        wt=Path(created['path'])
        subprocess.run(['git','-C',str(wt),'config','user.name','Test'],check=True)
        subprocess.run(['git','-C',str(wt),'config','user.email','test@example.invalid'],check=True)
        (wt/'change').write_text('change'); subprocess.run(['git','-C',str(wt),'add','change'],check=True)
        subprocess.run(['git','-C',str(wt),'commit','-m','feature'],check=True,stdout=subprocess.PIPE)

    def crash(self, root, phase, tx):
        env=dict(os.environ,WORKTREE_MANAGER_TEST_CRASH_AFTER_TRANSACTION_PHASE=phase)
        code="from worktree_manager.mcp_operations import call; import sys; call('worktree_complete', {'repo':sys.argv[1],'work_id':'feature','base':'main','authorization':'I_AUTHORIZE_THIS_CALL','transaction_id':sys.argv[2]})"
        return subprocess.run([sys.executable,'-c',code,str(root),tx],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)

    def test_crash_after_merged_recovers_once_and_closes(self):
        with tempfile.TemporaryDirectory() as d:
            root,git=self.repo(d); self.setup_change(root)
            self.assertEqual(self.crash(root,'merged','tx-merged').returncode,86)
            recover={'repo':str(root),'transaction_id':'tx-merged','authorization':'I_AUTHORIZE_THIS_CALL'}
            first=call('worktree_recover',recover)
            self.assertEqual(first['data']['phase'],'closed')
            count=git('rev-list','--count','main').stdout.strip()
            self.assertEqual(count,'2')
            second=call('worktree_recover',recover)
            self.assertEqual(second['result'],'no_pending_work')
            self.assertEqual(git('rev-list','--count','main').stdout.strip(),count)

    def test_crash_merge_started_without_effect_restores_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root,_=self.repo(d); self.setup_change(root)
            self.assertEqual(self.crash(root,'merge_started','tx-started').returncode,86)
            request={'repo':str(root),'transaction_id':'tx-started','authorization':'I_AUTHORIZE_THIS_CALL'}
            first=call('worktree_recover',request)
            self.assertEqual(first['data']['phase'],'restored')
            second=call('worktree_recover',request)
            self.assertEqual(second['result'],'no_pending_work')

    def test_recover_rejects_binding_or_repo_mismatch_before_lock(self):
        with tempfile.TemporaryDirectory() as d:
            root,_=self.repo(d); self.setup_change(root)
            self.assertEqual(self.crash(root,'merge_started','tx-mismatch').returncode,86)
            binding=root/'.git'/'worktree-manager'/'transactions'/'tx-mismatch'/'binding.json'
            value=json.loads(binding.read_text()); value['repo']=str(Path(d)/'other'); binding.write_text(json.dumps(value))
            barrier=Path(d)/'barrier'; os.environ['WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR']=str(barrier)
            try:
                with self.assertRaises(ManagerError) as caught:
                    call('worktree_recover',{'repo':str(root),'transaction_id':'tx-mismatch','authorization':'I_AUTHORIZE_THIS_CALL'})
                self.assertEqual(caught.exception.code,'invalid_identity')
                self.assertFalse(barrier.exists() and list(barrier.iterdir()))
            finally: os.environ.pop('WORKTREE_MANAGER_TEST_LOCK_BARRIER_DIR',None)


if __name__=='__main__': unittest.main()
