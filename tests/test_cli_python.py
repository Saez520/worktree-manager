import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from worktree_manager.mcp_contract import output_schema
CONFIG='state_dir=state\nbackup_dir=backups\nbackup_ref_prefix=manager/backups\nbranch_prefix=worktree/\nlock_dir=locks\n'
PREPARED_CONFIG=CONFIG+'prepare_command=printf prepared > prepared.txt\nverify_command=test -f prepared.txt\n'
class PythonCliTests(unittest.TestCase):
    def run_cli(self,*args): return subprocess.run([sys.executable,'-m','worktree_manager',*args],text=True,capture_output=True)
    def run_request(self,request,*args):
        return subprocess.run([sys.executable,'-m','worktree_manager','--request-json','-',*args],input=json.dumps(request),text=True,capture_output=True)
    def repository(self,directory,config=None):
        directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
        subprocess.run(['git','init','-q','-b','main',str(directory)],check=True)
        subprocess.run(['git','-C',str(directory),'config','user.name','test'],check=True)
        subprocess.run(['git','-C',str(directory),'config','user.email','test@example.invalid'],check=True)
        (directory/'.gitignore').write_text('.worktrees/\n')
        if config is not None: (directory/'.worktree-manager.conf').write_text(config)
        subprocess.run(['git','-C',str(directory),'add','.'],check=True)
        subprocess.run(['git','-C',str(directory),'commit','-qm','init'],check=True,capture_output=True)
        return directory
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
    def test_request_json_failure_without_json_is_one_contract_document(self):
        with tempfile.TemporaryDirectory() as d:
            repo=self.repository(Path(d)/'repo')
            rejected=self.run_request({'operation':'list','repo':str(repo),'unexpected':True})
            self.assertEqual(rejected.returncode,3,rejected.stderr)
            self.assertEqual(rejected.stderr,'')
            documents=[line for line in rejected.stdout.splitlines() if line.strip()]
            self.assertEqual(len(documents),1,rejected.stdout)
            document=json.loads(documents[0])
            self.assertEqual(set(document),set(output_schema()['required']))
            self.assertEqual(document['operation'],'worktree_list')
            self.assertEqual(document['result'],'failure')
            self.assertEqual(document['error'],{'code':'invalid_request','message':'unknown_fields: unexpected','exit_code':3})
            self.assertEqual(document['transaction_id'],None)
            self.assertEqual(document['repository'],str(repo.resolve()))
    def test_request_json_success_and_failure_publish_the_same_key_set(self):
        with tempfile.TemporaryDirectory() as d:
            repo=self.repository(Path(d)/'repo')
            accepted=self.run_request({'operation':'list','repo':str(repo)})
            rejected=self.run_request({'operation':'list','repo':str(repo),'unexpected':True})
            self.assertEqual(accepted.returncode,0,accepted.stderr); self.assertEqual(rejected.returncode,3,rejected.stderr)
            success=json.loads(accepted.stdout); failure=json.loads(rejected.stdout)
            self.assertEqual(set(success),set(failure))
            self.assertEqual(set(success),set(output_schema()['required']))
            self.assertEqual(success['error'],None); self.assertIsNotNone(failure['error'])
    def test_request_json_usage_failure_publishes_the_contract_envelope(self):
        rejected=self.run_cli('--request-json','-','--json','unexpected-argument')
        self.assertEqual(rejected.returncode,2,rejected.stderr)
        document=json.loads(rejected.stdout)
        self.assertEqual(set(document),set(output_schema()['required']))
        self.assertEqual(document['error']['code'],'usage_error')
        self.assertEqual(document['error']['exit_code'],2)
    def test_request_json_create_reports_the_real_prepare_and_verify_states(self):
        with tempfile.TemporaryDirectory() as d:
            repo=self.repository(Path(d)/'repo',config=PREPARED_CONFIG)
            created=self.run_request({'operation':'create','repo':str(repo),'work_id':'sample','base':'main','prepare':True,'verify':True})
            self.assertEqual(created.returncode,0,created.stderr)
            document=json.loads(created.stdout)
            self.assertEqual(set(document),set(output_schema()['required']))
            self.assertEqual(document['operation'],'worktree_create')
            self.assertEqual(document['data']['prepare'],'passed')
            self.assertEqual(document['data']['verify'],'passed')
            self.assertEqual(document['data']['init_submodules'],'false')
            self.assertEqual(document['data']['init_submodules_result'],'not_requested')
            self.assertTrue((repo/'.worktrees/sample/prepared.txt').is_file())
    def test_create_runs_the_configured_prepare_and_verify_steps(self):
        with tempfile.TemporaryDirectory() as d:
            repo=self.repository(Path(d)/'repo',config=PREPARED_CONFIG)
            created=self.run_cli('--repo',str(repo),'--json','create','sample','--prepare','--verify')
            self.assertEqual(created.returncode,0,created.stderr)
            data=json.loads(created.stdout)['data']
            self.assertEqual(data['prepare'],'passed'); self.assertEqual(data['verify'],'passed')
            self.assertEqual(data['init_submodules'],'false'); self.assertEqual(data['init_submodules_result'],'not_requested')
            self.assertTrue((repo/'.worktrees/sample/prepared.txt').is_file())
    def test_create_without_a_configured_prepare_command_is_rejected_before_mutating(self):
        with tempfile.TemporaryDirectory() as d:
            repo=self.repository(Path(d)/'repo',config=CONFIG)
            created=self.run_cli('--repo',str(repo),'--json','create','sample','--prepare')
            self.assertEqual(created.returncode,3,created.stderr)
            self.assertEqual(json.loads(created.stdout)['error']['code'],'invalid_configuration')
            self.assertFalse((repo/'.worktrees').exists())
    def test_create_initializes_submodules_only_when_requested(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            target=self.repository(root/'target')
            (target/'target.txt').write_text('target\n')
            subprocess.run(['git','-C',str(target),'add','.'],check=True)
            subprocess.run(['git','-C',str(target),'commit','-qm','target'],check=True,capture_output=True)
            parent=self.repository(root/'parent')
            env=dict(os.environ,GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='protocol.file.allow',GIT_CONFIG_VALUE_0='always')
            subprocess.run(['git','-C',str(parent),'submodule','add','-q',str(target),'modules/target'],check=True,env=env)
            subprocess.run(['git','-C',str(parent),'commit','-qm','add submodule'],check=True,env=env)
            created=subprocess.run([sys.executable,'-m','worktree_manager','--repo',str(parent),'--json','create','wt','--init-submodules'],text=True,capture_output=True,env=env)
            self.assertEqual(created.returncode,0,created.stderr)
            data=json.loads(created.stdout)['data']
            self.assertEqual(data['init_submodules'],'true')
            self.assertEqual(data['init_submodules_result'],'initialized')
            self.assertTrue((parent/'.worktrees/wt/modules/target/target.txt').is_file())
if __name__=='__main__': unittest.main()
