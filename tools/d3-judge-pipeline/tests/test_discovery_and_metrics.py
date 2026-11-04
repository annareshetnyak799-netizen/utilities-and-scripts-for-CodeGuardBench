import csv,io,json,subprocess
from pathlib import Path
import pytest
from codeguard_judge.discovery import discover
from codeguard_judge.evaluation import evaluate,compare
from codeguard_judge.batch import run
from judge.io import FIELDS,write_jsonl,digest

def test_git_discovery_read_only_with_explicit_exclusions(tmp_path):
 repo=tmp_path/'peer';repo.mkdir()
 def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL)
 git('init');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
 folder=repo/'CAT-4';folder.mkdir();p=folder/'commands_test.csv'
 row=dict(command='sudo -i',description='fixture',util='sudo',severity='high',category='CAT-4',risk='CAT-4.1',source='real',seed='-',**{'class':'deny'})
 with p.open('w') as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows([row,dict(row,**{'class':'modify'})])
 git('add','.');git('commit','-m','fixture');git('update-ref','refs/remotes/origin/feat/data_CAT-4','HEAD');before=digest(p.read_bytes());head=git('rev-parse','HEAD')
 records=discover([repo],tmp_path/'out');assert len(records)==1
 inv=json.load(open(tmp_path/'out/inventory.json'));assert inv['total_rows']==2 and inv['excluded'][0]['issues']==['incompatible_v0_class']
 assert digest(p.read_bytes())==before and git('rev-parse','HEAD')==head and git('status','--porcelain')==b''

def test_metrics_reject_missing_ids_and_mismatched_reference_command(tmp_path):
 inp=tmp_path/'in.jsonl';refs=tmp_path/'refs.jsonl';write_jsonl(inp,[{'record_id':'one','command':'git clean -n'}]);cfg={'architecture':'rules'}
 run(inp,tmp_path/'run',cfg);write_jsonl(refs,[{'record_id':'one','command':'different','class':'allow','risk':'CAT-2.3','category':'CAT-2','severity':'medium','source':'real'}])
 with pytest.raises(ValueError,match='command_mismatch'):evaluate(tmp_path/'run',refs)
 (tmp_path/'run/results.jsonl').write_text('')
 with pytest.raises(ValueError,match='population'):evaluate(tmp_path/'run',refs)
