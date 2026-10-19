import tempfile
import unittest
import subprocess
from pathlib import Path
from worktree_manager.lock_manager import LockManager
from worktree_manager.models import ManagerError
from worktree_manager.transaction_journal import TransactionJournal
from worktree_manager.worktree_lifecycle import validate_work_id
from worktree_manager.configuration import Configuration
from worktree_manager.worktree_lifecycle import WorktreeLifecycle
from worktree_manager.recovery_manager import RecoveryManager
import json

class BackendTests(unittest.TestCase):
    def test_preserve_dirty_crash_stays_pending_intervention_idempotently(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'repo'; root.mkdir()
            subprocess.run(['git','-C',str(root),'init','-q','-b','main'],check=True)
            subprocess.run(['git','-C',str(root),'config','user.name','Test'],check=True)
            subprocess.run(['git','-C',str(root),'config','user.email','test@example.invalid'],check=True)
            (root/'base').write_text('base'); subprocess.run(['git','-C',str(root),'add','base'],check=True)
            subprocess.run(['git','-C',str(root),'commit','-qm','base'],check=True)
            before=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],check=True,text=True,stdout=subprocess.PIPE).stdout.strip()
            state=root/'.git'/'state'; journal=TransactionJournal(state); tx='preserve-crash'
            journal.directory(tx).mkdir(parents=True)
            meta={'base':'main','branch':'worktree/feature','path':str(root/'missing'),
                  'before':before,'origin':before,'preserve_dirty':True}
            (journal.directory(tx)/'meta.json').write_text(json.dumps(meta))
            journal.write_phase(tx,'merge_started')
            (journal.directory(tx)/'lock').write_text('owned')
            for _ in range(2):
                with self.assertRaises(ManagerError) as caught:
                    RecoveryManager(state,root).recover(tx)
                self.assertEqual(caught.exception.exit_code,5)
                self.assertEqual(journal.read_phase(tx),'merge_started')
                self.assertTrue((journal.directory(tx)/'lock').exists())
                self.assertEqual(subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],check=True,text=True,stdout=subprocess.PIPE).stdout.strip(),before)

    def test_journal_phase_atomic_roundtrip_and_rejects_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            journal=TransactionJournal(d); journal.write_phase('tx-1','captured')
            self.assertEqual(journal.read_phase('tx-1'),'captured')
            with self.assertRaises(ManagerError): journal.write_phase('tx-1','discarded')
    def test_locks_sort_and_release_and_contention_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            first=LockManager(d); first.acquire(['z','a'],'test')
            self.assertEqual([p.name for p in first.held],['a','z'])
            second=LockManager(d)
            with self.assertRaises(ManagerError): second.acquire(['a'],'other')
            first.release(); second.acquire(['a'],'other'); second.release()
    def test_work_id_validation(self):
        self.assertEqual(validate_work_id('team/task-1'),'team/task-1')
        for value in ('../x','-x','a//b','a/..','a/--bad'):
            with self.subTest(value=value),self.assertRaises(ManagerError): validate_work_id(value)

    def test_relative_git_dir_state_is_resolved_against_repo_not_process_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'repo'; root.mkdir()
            subprocess.run(['git','-C',str(root),'init','-q','-b','main'],check=True)
            subprocess.run(['git','-C',str(root),'config','user.name','Test'],check=True)
            subprocess.run(['git','-C',str(root),'config','user.email','test@example.invalid'],check=True)
            (root/'.gitignore').write_text('.worktrees/\n')
            subprocess.run(['git','-C',str(root),'add','.gitignore'],check=True)
            (root/'file').write_text('base'); subprocess.run(['git','-C',str(root),'add','file'],check=True)
            subprocess.run(['git','-C',str(root),'commit','-qm','base'],check=True)
            outside=Path(d)/'standalone'; outside.mkdir()
            cfg=Configuration.load(root,environ={'WORKTREE_MANAGER_STATE_DIR':'state','WORKTREE_MANAGER_LOCK_DIR':'locks'})
            import os
            old=os.getcwd()
            try:
                os.chdir(outside)
                lifecycle=WorktreeLifecycle(cfg)
                lifecycle.create('crash-create','main')
            finally:
                os.chdir(old)
            self.assertEqual(lifecycle.state_root,root.resolve()/'.git/state')
            self.assertEqual(lifecycle.journal.root,root.resolve()/'.git/state/transactions')
            self.assertFalse((outside/'.git').exists())

    def test_complete_squashes_then_removes_worktree_and_branch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'repo'; root.mkdir()
            def git(*args): return subprocess.run(['git','-C',str(root),*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout.strip()
            git('init','-b','main'); git('config','user.name','Test'); git('config','user.email','test@example.invalid')
            (root/'base').write_text('base'); git('add','base'); git('commit','-m','base')
            cfg=Configuration(repo_root=root,worktrees_dir=str(Path(d)/'trees'),branch_prefix='worktree/',state_dir='state')
            lifecycle=WorktreeLifecycle(cfg); created=lifecycle.create('feature','main')
            subprocess.run(['git','-C',created['path'],'config','user.name','Test'],check=True)
            subprocess.run(['git','-C',created['path'],'config','user.email','test@example.invalid'],check=True)
            (Path(created['path'])/'feature').write_text('change')
            subprocess.run(['git','-C',created['path'],'add','feature'],check=True)
            subprocess.run(['git','-C',created['path'],'commit','-m','feature'],check=True,stdout=subprocess.PIPE)
            result=lifecycle.complete('feature','main')
            self.assertEqual(result['completed'],'feature')
            self.assertFalse(Path(created['path']).exists())
            self.assertNotEqual(subprocess.run(['git','-C',str(root),'show-ref','--verify','--quiet','refs/heads/worktree/feature']).returncode,0)
            self.assertTrue((root/'feature').is_file())

    def test_complete_preserve_dirty_restores_staged_unstaged_and_untracked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'repo'; root.mkdir()
            def git(*args): return subprocess.run(['git','-C',str(root),*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout.strip()
            git('init','-b','main'); git('config','user.name','Test'); git('config','user.email','test@example.invalid')
            (root/'tracked').write_text('base\n'); git('add','tracked'); git('commit','-m','base')
            cfg=Configuration(repo_root=root,worktrees_dir=str(Path(d)/'trees'),branch_prefix='worktree/',state_dir='state')
            lifecycle=WorktreeLifecycle(cfg); created=lifecycle.create('feature','main')
            subprocess.run(['git','-C',created['path'],'config','user.name','Test'],check=True)
            subprocess.run(['git','-C',created['path'],'config','user.email','test@example.invalid'],check=True)
            (Path(created['path'])/'feature').write_text('change'); subprocess.run(['git','-C',created['path'],'add','feature'],check=True)
            subprocess.run(['git','-C',created['path'],'commit','-m','feature'],check=True,stdout=subprocess.PIPE)
            (root/'tracked').write_text('staged\n'); git('add','tracked')
            (root/'tracked').write_text('unstaged\n'); (root/'new-file').write_text('untracked\n')
            result=lifecycle.complete('feature','main',True)
            self.assertEqual((root/'tracked').read_text(),'unstaged\n')
            self.assertEqual((root/'new-file').read_text(),'untracked\n')
            self.assertIn('M ',git('status','--porcelain'))
            self.assertEqual(lifecycle.journal.read_phase(result['transaction_id']),'restored')

    def test_recover_merge_started_after_durable_squash_is_noop_and_repeat(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'repo'; root.mkdir()
            def git(*args):
                return subprocess.run(['git','-C',str(root),*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout.strip()
            git('init','-b','main'); git('config','user.name','Test'); git('config','user.email','test@example.invalid')
            (root/'base').write_text('base'); git('add','base'); git('commit','-m','base'); before=git('rev-parse','HEAD')
            trees=Path(d)/'trees'; wt=trees/'feature'
            git('worktree','add','-b','worktree/feature',str(wt),'main')
            subprocess.run(['git','-C',str(wt),'config','user.name','Test'],check=True)
            subprocess.run(['git','-C',str(wt),'config','user.email','test@example.invalid'],check=True)
            (wt/'change').write_text('feature'); subprocess.run(['git','-C',str(wt),'add','change'],check=True)
            subprocess.run(['git','-C',str(wt),'commit','-m','feature'],check=True,stdout=subprocess.PIPE)
            origin=git('rev-parse','refs/heads/worktree/feature')
            git('merge','--squash','worktree/feature'); git('commit','-m','squash')
            squash=git('rev-parse','HEAD'); tx='durable-squash'
            state=root/'.git'/'state'; journal=TransactionJournal(state)
            journal.directory(tx).mkdir(parents=True)
            (journal.directory(tx)/'meta.json').write_text(json.dumps({
                'work_id':'feature','base':'main','branch':'worktree/feature','path':str(wt),
                'before':before,'origin':origin,'preserve_dirty':False,
                'backup_ref_prefix':'worktree-manager/backups'}))
            journal.write_phase(tx,'merge_started')
            manager=RecoveryManager(state,root)
            result,data=manager.recover(tx)
            self.assertEqual(result.value,'no_pending_work'); self.assertIsNone(data)
            self.assertEqual(git('rev-parse','HEAD'),squash)
            self.assertTrue(wt.exists()); self.assertEqual(git('rev-parse','refs/heads/worktree/feature'),origin)
            self.assertEqual(journal.read_phase(tx),'merge_started')
            self.assertTrue((wt/'change').is_file())
            result,data=manager.recover(tx)
            self.assertEqual(result.value,'no_pending_work')
            self.assertIsNone(data)
            self.assertEqual(journal.read_phase(tx),'merge_started')

    def test_recover_merge_started_ambiguous_evidence_preserves_journal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'repo'; root.mkdir()
            subprocess.run(['git','-C',str(root),'init','-q','-b','main'],check=True)
            subprocess.run(['git','-C',str(root),'config','user.name','Test'],check=True)
            subprocess.run(['git','-C',str(root),'config','user.email','test@example.invalid'],check=True)
            (root/'base').write_text('base'); subprocess.run(['git','-C',str(root),'add','base'],check=True)
            subprocess.run(['git','-C',str(root),'commit','-qm','base'],check=True)
            before=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],check=True,text=True,stdout=subprocess.PIPE).stdout.strip()
            # HEAD movement without a recorded, registered feature worktree is not recoverable.
            subprocess.run(['git','-C',str(root),'commit','--allow-empty','-qm','unrelated'],check=True)
            state=root/'.git'/'state'; journal=TransactionJournal(state); tx='ambiguous'
            journal.directory(tx).mkdir(parents=True)
            (journal.directory(tx)/'meta.json').write_text(json.dumps({'base':'main','branch':'worktree/missing','path':str(root/'missing'),
                'before':before,'origin':before,'preserve_dirty':False}))
            journal.write_phase(tx,'merge_started')
            with self.assertRaises(ManagerError) as caught: RecoveryManager(state,root).recover(tx)
            self.assertEqual(caught.exception.exit_code,5)
            self.assertEqual(journal.read_phase(tx),'merge_started')
