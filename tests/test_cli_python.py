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
    def test_request_json_uses_mcp_contract_and_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(['git','init','-q',d],check=True)
            subprocess.run(['git','-C',d,'-c','user.name=test','-c','user.email=test@example.invalid','commit','--allow-empty','-m','init'],check=True,capture_output=True)
            request={'operation':'list','repo':d}
            cli=self.run_cli('--request-json','-','--json')
            cli=subprocess.run([sys.executable,'-m','worktree_manager','--request-json','-','--json'],input=json.dumps(request),text=True,capture_output=True)
            self.assertEqual(cli.returncode,0,cli.stderr)
            doc=json.loads(cli.stdout)
            self.assertEqual(doc['operation'],'worktree_list')
            self.assertEqual(doc['result'],'success')
            bad=dict(request,unexpected=True)
            rejected=subprocess.run([sys.executable,'-m','worktree_manager','--request-json','-','--json'],input=json.dumps(bad),text=True,capture_output=True)
            self.assertEqual(rejected.returncode,3)
            self.assertEqual(json.loads(rejected.stdout)['error']['code'],'invalid_request')
if __name__=='__main__': unittest.main()
