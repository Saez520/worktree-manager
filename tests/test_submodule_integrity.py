"""Regression tests for the submodule integrity guard in worktree creation.

The guard fingerprints the module dirs of submodules already initialized in
the main worktree before ``git worktree add`` and compares them again after
``git submodule update``. Gap coverage:

- G1: a healthy ``create --init-submodules`` must leave the main module dir
  untouched and initialize the submodule inside the new worktree.
- G2: an incomplete main module dir must fail closed before any worktree or
  branch exists.
- G3: the fingerprint comparison must report a vanished module dir, missing
  ``objects`` and any change in object count, object bytes or ``HEAD``.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from worktree_manager.worktree_lifecycle import WorktreeLifecycle

CONFIG = ('state_dir=state\nbackup_dir=backups\nbackup_ref_prefix=manager/backups\n'
          'branch_prefix=worktree/\nlock_dir=locks\n')
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUBMODULE_PATH = 'modules/target'


class SubmoduleIntegrityGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='submodule-integrity-')
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.env = dict(os.environ, GIT_CONFIG_COUNT='1',
                        GIT_CONFIG_KEY_0='protocol.file.allow',
                        GIT_CONFIG_VALUE_0='always')

    def git(self, repo, *args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env).stdout.strip()

    def repository(self, directory):
        directory.mkdir(parents=True)
        self.git(directory, 'init', '-q', '-b', 'main')
        self.git(directory, 'config', 'user.name', 'test')
        self.git(directory, 'config', 'user.email', 'test@example.invalid')
        return directory

    def parent_with_initialized_submodule(self):
        target = self.repository(self.root / 'target')
        (target / 'target.txt').write_text('target\n')
        self.git(target, 'add', '.')
        self.git(target, 'commit', '-qm', 'target initial commit')
        parent = self.repository(self.root / 'parent')
        (parent / '.gitignore').write_text('.worktrees/\n')
        (parent / '.worktree-manager.conf').write_text(CONFIG)
        self.git(parent, 'add', '.')
        self.git(parent, 'commit', '-qm', 'init')
        self.git(parent, 'submodule', 'add', '-q', str(target), SUBMODULE_PATH)
        self.git(parent, 'commit', '-qm', 'add submodule')
        self.git(parent, 'submodule', 'update', '--init')
        module_dir = Path(self.git(parent, 'rev-parse', '--git-path', f'modules/{SUBMODULE_PATH}'))
        if not module_dir.is_absolute():
            module_dir = parent / module_dir
        return parent, module_dir.resolve()

    def fingerprint(self, module_dir):
        objects = module_dir / 'objects'
        files = [entry for entry in objects.rglob('*') if entry.is_file()] if objects.is_dir() else []
        return {
            'objects': objects.is_dir(),
            'object_files': len(files),
            'object_bytes': sum(entry.stat().st_size for entry in files),
            'head': (module_dir / 'HEAD').read_text(encoding='utf-8'),
        }

    def run_cli(self, repo, *args):
        return subprocess.run([sys.executable, '-m', 'worktree_manager', '--repo', str(repo), *args],
                              cwd=str(PROJECT_ROOT), text=True, capture_output=True, env=self.env)

    def ref_exists(self, repo, ref):
        completed = subprocess.run(['git', '-C', str(repo), 'show-ref', '--verify', '--quiet', ref],
                                   env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return completed.returncode == 0

    # gap: G1 — init_submodules muta el module dir principal o no inicializa el submódulo del worktree nuevo
    def test_create_preserves_main_module_dir_and_initializes_worktree_submodule(self):
        parent, module_dir = self.parent_with_initialized_submodule()
        before = self.fingerprint(module_dir)

        created = self.run_cli(parent, '--json', 'create', 'wt', '--init-submodules')

        self.assertEqual(created.returncode, 0, created.stderr)
        data = json.loads(created.stdout)['data']
        self.assertEqual(data['init_submodules'], 'true')
        self.assertEqual(data['init_submodules_result'], 'initialized')
        self.assertEqual(self.fingerprint(module_dir), before)
        worktree = parent / '.worktrees' / 'wt'
        self.assertTrue((worktree / SUBMODULE_PATH / 'target.txt').is_file())
        status = self.git(worktree, 'submodule', 'status')
        self.assertFalse(status.startswith('-'), status)

    # gap: G2 — un module dir principal incompleto se acepta y se crea worktree/branch
    def test_create_rejects_incomplete_main_module_dir_before_mutating(self):
        parent, module_dir = self.parent_with_initialized_submodule()
        shutil.rmtree(module_dir / 'objects')

        rejected = self.run_cli(parent, '--json', 'create', 'wt', '--init-submodules')

        self.assertEqual(rejected.returncode, 5, rejected.stderr)
        document = json.loads(rejected.stdout)
        self.assertEqual(document['result'], 'failure')
        self.assertEqual(document['error']['code'], 'operation_failed')
        self.assertEqual(document['error']['exit_code'], 5)
        self.assertIn(str(module_dir), document['error']['message'])
        self.assertFalse((parent / '.worktrees' / 'wt').exists())
        self.assertFalse(self.ref_exists(parent, 'refs/heads/worktree/wt'))

    # gap: G3 — la comparación de fingerprints no detecta desaparición, objects ausente o cambios de conteo/bytes/HEAD
    def test_submodule_integrity_mutations_detects_every_fingerprint_change(self):
        path = str(self.root / '.git' / 'modules' / SUBMODULE_PATH)
        recorded = {'objects': True, 'object_files': 3, 'object_bytes': 30,
                    'head': 'ref: refs/heads/main\n'}
        cases = {
            'no mutation': ({path: dict(recorded)}, {path: dict(recorded)}, []),
            'module dir disappeared': ({path: dict(recorded)}, {}, [path]),
            'objects missing': ({path: dict(recorded)}, {path: dict(recorded, objects=False)}, [path]),
            'object count changed': ({path: dict(recorded)}, {path: dict(recorded, object_files=4)}, [path]),
            'object bytes changed': ({path: dict(recorded)}, {path: dict(recorded, object_bytes=31)}, [path]),
            'HEAD changed': ({path: dict(recorded)}, {path: dict(recorded, head='ref: refs/heads/other\n')}, [path]),
        }
        for name, (before, after, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(WorktreeLifecycle._submodule_integrity_mutations(before, after), expected)


if __name__ == '__main__':
    unittest.main()
