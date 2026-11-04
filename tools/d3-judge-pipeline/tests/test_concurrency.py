import json,os,subprocess,sys
from pathlib import Path
from judge.io import write_jsonl
ROOT=Path(__file__).resolve().parents[1]
def test_two_processes_cannot_reserve_same_budget(tmp_path):
 script='from codeguard_judge.providers import Budget; import sys; Budget(sys.argv[1],1).reserve(.7)'
 env=dict(os.environ,PYTHONPATH=str(ROOT))
 ps=[subprocess.Popen([sys.executable,'-c',script,str(tmp_path/'budget.json')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
 codes=[]
 for p in ps:p.communicate(timeout=15);codes.append(p.returncode)
 assert sorted(codes)==[0,1]
 assert len(json.loads((tmp_path/'budget.json').read_text())['entries'])==1

def test_two_batch_writers_resume_without_duplicate_ids(tmp_path):
 inp=tmp_path/'input.jsonl';write_jsonl(inp,[{'record_id':'one','command':'git clean -n'},{'record_id':'two','command':'git reset --hard'}])
 script="from codeguard_judge.batch import run; import sys; run(sys.argv[1],sys.argv[2],{'architecture':'rules'},resume=True)"
 env=dict(os.environ,PYTHONPATH=str(ROOT))
 ps=[subprocess.Popen([sys.executable,'-c',script,str(inp),str(tmp_path/'run')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
 for p in ps:
  _,err=p.communicate(timeout=15);assert p.returncode==0,err.decode()
 ids=[json.loads(line)['record_id'] for line in (tmp_path/'run/results.jsonl').read_text().splitlines()];assert ids==['one','two']
