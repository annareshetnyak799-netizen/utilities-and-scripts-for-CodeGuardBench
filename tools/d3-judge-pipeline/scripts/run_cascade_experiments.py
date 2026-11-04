"""Independent architecture runs on a frozen command-only pilot. Shared hard budget."""
import concurrent.futures,json,sys
from pathlib import Path
from codeguard_judge.batch import run
from codeguard_judge.evaluation import evaluate,compare
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/cascade_2026-11-05';EXP=OUT/'experiments'
def one(name):
 cfg=json.loads((EXP/'configs'/f'{name}.json').read_text());dest=EXP/name
 run(EXP/'pilot_blind.jsonl',dest,cfg,resume=dest.exists())
 m=evaluate(dest,EXP/'pilot_references.jsonl')
 print(json.dumps({'run':name,**{k:m[k] for k in ['n','annotation_agreement','prediction_coverage','calls','provider_failure_calls','schema_failure_calls','estimated_cost_rub']}}),flush=True)
 return dest
if __name__=='__main__':
 names=sys.argv[1:] or ['rules','single','reasoning_single','static_single','critic_cascade','specialists','semantic_cascade']
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:paths=list(pool.map(one,names))
 if len(paths)>1:compare(paths,EXP/'comparison.json')
