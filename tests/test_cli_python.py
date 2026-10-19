import json, subprocess, sys, tempfile, unittest
from pathlib import Path
class PythonCliTests(unittest.TestCase):
    def run_cli(self,*args): return subprocess.run([sys.executable,'-m','worktree_manager',*args],text=True,capture_output=True)
    def test_help_and_version_outside_repository(self):
        help_result=self.run_cli('--help'); version=self.run_cli('--version')
        self.assertEqual(help_result.returncode,0); self.assertEqual(version.stdout.strip(),'1.0.0')
    def test_usage_error_is_single_json_document(self):
        result=self.run_cli('--json','not-a-command')
        self.assertEqual(result.returncode,2); doc=json.loads(result.stdout)
        self.assertEqual(doc['contract_version'],1); self.assertEqual(doc['error']['code'],'usage_error')
    def test_list_json_validates_contract(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(['git','init','-q',d],check=True)
            subprocess.run(['git','-C',d,'-c','user.name=test','-c','user.email=test@example.invalid','commit','--allow-empty','-m','init'],check=True,capture_output=True)
            result=self.run_cli('--json','--repo',d,'list')
            self.assertEqual(result.returncode,0,result.stderr); doc=json.loads(result.stdout)
            self.assertEqual(doc['operation'],'list'); self.assertEqual(doc['result'],'success'); self.assertEqual(doc['data']['worktrees'][0]['branch'],'refs/heads/master')
if __name__=='__main__': unittest.main()
