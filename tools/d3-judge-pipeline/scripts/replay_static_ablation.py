"""Isolate deterministic static gate using exactly the same saved classifier responses."""
import copy,json
from pathlib import Path
from judge.io import read_records,write_jsonl,dump,digest
from codeguard_judge.evaluation import evaluate
ROOT=Path(__file__).resolve().parents[1];EXP=ROOT/'reports/cascade_2026-11-05/experiments';src=EXP/'single';dest=EXP/'static_replay';dest.mkdir(exist_ok=True)
rs=read_records(src/'results.jsonl');changed=[]
for r in rs:
 r['architecture']='static_replay'
 if r['static']['rule_hint'] and r['predicted_class'] is not None and r['predicted_class']!=r['static']['rule_hint']:
  changed.append(r['record_id']);r.update(predicted_class=None,predicted_primary_risk=None,severity=None,safety_label=None,risk_identifiable=False)
  r['review_reasons']=sorted(set(r['review_reasons']+['static_model_conflict']))
m=json.loads((src/'run_manifest.json').read_text());m['config']['architecture']='static_replay';m['parent_fingerprint']=m['fingerprint'];m['fingerprint']=digest(m);m['replay_analysis_sha']=digest(Path(__file__).read_bytes());m['replay_no_new_inference']=True
write_jsonl(dest/'results.jsonl',rs);dump(dest/'run_manifest.json',m);evaluate(dest,EXP/'pilot_references.jsonl');dump(dest/'replay_receipt.json',{'same_classifier_outputs':True,'new_calls':0,'incremental_cost_rub':0,'changed_ids':changed,'usage_fields_refer_to_parent_calls':True});print('changed_ids',len(changed))
