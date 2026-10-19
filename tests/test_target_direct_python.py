import subprocess
import tempfile
import unittest
import os
from pathlib import Path

from worktree_manager.models import ManagerError
from worktree_manager.target_direct_adapter import TargetDirectAdapter


class TargetDirectTests(unittest.TestCase):
    def git(self, root, *args, check=True):
        return subprocess.run(['git', '-C', str(root), *args], check=check,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

    def repo(self, path):
        path.mkdir()
        self.git(path, 'init', '-b', 'main')
        self.git(path, 'config', 'user.name', 'Test')
        self.git(path, 'config', 'user.email', 'test@example.invalid')
        (path/'base').write_text('base')
        self.git(path, 'add', 'base'); self.git(path, 'commit', '-m', 'base')

    def test_descriptor_rejects_unknown_or_duplicate_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'descriptor'; p.write_text('unknown=x\n')
            with self.assertRaises(ManagerError): TargetDirectAdapter(p)

    def test_create_link_abort_and_recover_are_safe(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/'target'; parent=root/'parent'
            self.repo(target); self.repo(parent)
            descriptor=root/'state'/'descriptor'
            adapter=TargetDirectAdapter.create(descriptor,target,parent,'module','sample')
            self.assertEqual(adapter.values['phase'],'ready')
            adapter.link_parent()
            self.assertEqual(adapter.values['phase'],'staged')
            entry=self.git(parent,'ls-files','--stage','--','module')
            self.assertTrue(entry.startswith('160000 '+adapter.values['target_head']))
            adapter.abort()
            self.assertEqual(self.git(parent,'ls-files','--stage','--','module'),'')
            self.assertEqual(adapter.recover()['recovered'],True)
            self.assertEqual(adapter.recover()['recovered'],True)

    def test_parent_index_drift_blocks_abort_without_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/'target'; parent=root/'parent'
            self.repo(target); self.repo(parent)
            adapter=TargetDirectAdapter.create(root/'descriptor',target,parent,'module','sample')
            adapter.link_parent()
            (parent/'new').write_text('preserve')
            self.git(parent,'add','new')
            with self.assertRaises(ManagerError): adapter.abort()
            self.assertTrue((parent/'new').exists())

    def test_recover_recognizes_own_gitlink_but_rejects_other_index_drift(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/'target'; parent=root/'parent'
            self.repo(target); self.repo(parent)
            adapter=TargetDirectAdapter.create(root/'descriptor',target,parent,'module','sample')
            adapter.link_parent()
            before=self.git(parent,'ls-files','--stage')
            with self.assertRaisesRegex(ManagerError,'intentionally staged'):
                adapter.recover()
            self.assertEqual(self.git(parent,'ls-files','--stage'),before)
            (parent/'external').write_text('external')
            self.git(parent,'add','external')
            with self.assertRaisesRegex(ManagerError,'drift is ambiguous'):
                adapter.recover()
            self.assertTrue((parent/'external').exists())

    def test_recover_after_gitlink_staged_before_descriptor_advance_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/'target'; parent=root/'parent'
            self.repo(target); self.repo(parent)
            descriptor=root/'descriptor'
            adapter=TargetDirectAdapter.create(descriptor,target,parent,'module','sample')
            adapter.link_parent()
            # Model process death after update-index became durable, before the
            # descriptor could advance staged_started -> staged.
            text=descriptor.read_text().replace('phase=staged\n','phase=staged_started\n')
            descriptor.write_text(text)
            resumed=TargetDirectAdapter(descriptor)
            with self.assertRaises(ManagerError) as blocked:
                resumed.recover()
            self.assertEqual(blocked.exception.exit_code,6)
            self.assertEqual(TargetDirectAdapter(descriptor).values['phase'],'blocked')
            self.assertTrue(self.git(parent,'ls-files','--stage','--','module').startswith('160000 '))
            self.assertEqual(TargetDirectAdapter(descriptor).recover()['phase'],'blocked')

    def test_recover_after_descriptor_staged_started_crash_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/'target'; parent=root/'parent'
            self.repo(target); self.repo(parent)
            descriptor=root/'descriptor'
            adapter=TargetDirectAdapter.create(descriptor,target,parent,'module','sample')
            adapter.link_parent()
            # Reproduce the durable descriptor state immediately before
            # update-index; the parent index must be restored without guessing.
            text=descriptor.read_text().replace('phase=staged\n','phase=staged_started\n')
            descriptor.write_text(text)
            resumed=TargetDirectAdapter(descriptor)
            with self.assertRaises(ManagerError) as blocked:
                resumed.recover()
            self.assertEqual(blocked.exception.exit_code,6)
            self.assertEqual(TargetDirectAdapter(descriptor).values['phase'],'blocked')
            self.assertTrue(self.git(parent,'ls-files','--stage','--','module').startswith('160000 '))
            self.assertEqual(TargetDirectAdapter(descriptor).recover()['phase'],'blocked')

    def test_actual_process_death_after_staged_started_recovers_twice(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/'target'; parent=root/'parent'
            self.repo(target); self.repo(parent)
            descriptor=root/'descriptor'
            TargetDirectAdapter.create(descriptor,target,parent,'module','sample')
            code=('from worktree_manager.target_direct_adapter import TargetDirectAdapter; '
                  f'TargetDirectAdapter({str(descriptor)!r}).link_parent()')
            env={**os.environ,'WORKTREE_MANAGER_TEST_CRASH_AFTER_DESCRIPTOR_PHASE':'staged_started'}
            crashed=subprocess.run(['python3','-c',code],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(crashed.returncode,-9)
            self.assertIn('phase=staged_started',descriptor.read_text())
            self.assertEqual(self.git(parent,'ls-files','--stage','--','module'),'')
            resumed=TargetDirectAdapter(descriptor)
            with self.assertRaises(ManagerError) as blocked:
                resumed.recover()
            self.assertEqual(blocked.exception.exit_code,6)
            self.assertEqual(TargetDirectAdapter(descriptor).values['phase'],'blocked')
            self.assertEqual(TargetDirectAdapter(descriptor).recover()['phase'],'blocked')

    def test_complete_and_recover_resume_after_remove_phase(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/'target'; parent=root/'parent'
            self.repo(target); self.repo(parent)
            adapter=TargetDirectAdapter.create(root/'descriptor',target,parent,'module','sample')
            adapter.link_parent()
            result=adapter.complete()
            self.assertTrue(result['completed'])
            self.assertFalse(Path(adapter.values['worktree_path']).exists())
            self.assertEqual(adapter.recover()['phase'],'closed')


if __name__ == '__main__': unittest.main()
