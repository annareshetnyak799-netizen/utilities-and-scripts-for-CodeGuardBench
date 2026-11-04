"""Real-model diagnostic coverage across 42 authored mechanisms; no accuracy claims."""
from pathlib import Path
import json,collections
from judge.io import read_records,write_jsonl,dump,digest
from codeguard_judge.batch import run
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/cascade_2026-11-05';dest=OUT/'taxonomy_probe';dest.mkdir(exist_ok=True)
rows=[r for r in read_records(ROOT/'tests/fixtures/all_taxonomy.jsonl') if r['kind']=='mechanism']
write_jsonl(dest/'blind_inputs.jsonl',[{'record_id':r['record_id'],'command':r['command']} for r in rows]);dump(dest/'freeze.json',{'input_sha':digest((dest/'blind_inputs.jsonl').read_bytes()),'ids':[r['record_id'] for r in rows],'n':len(rows),'role':'independently_authored_diagnostic_NOT_HUMAN_GOLD'})
cfg=json.loads((OUT/'experiments/configs/reasoning_single.json').read_text());rs=run(dest/'blind_inputs.jsonl',dest/'run',cfg,resume=(dest/'run').exists())
dump(dest/'summary.json',{'n':len(rs),'model_calls':sum(len(r['judges']) for r in rs),'nonabstain':sum(r['predicted_class'] is not None for r in rs),'human_gold':0,'semantic_accuracy':'NOT_AVAILABLE','estimated_cost_rub':sum(j.get('usage',{}).get('estimated_rub',0) for r in rs for j in r['judges'])})
print((dest/'summary.json').read_text(),flush=True)
