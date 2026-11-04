"""Same frozen inputs, actual legacy v1 prompt. Separate protocol, not pooled comparison."""
import json,sys
from pathlib import Path
from judge import pipeline
from judge.io import read_records,dump
from codeguard_judge.providers import API,Budget
from codeguard_judge.evaluation import metrics
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/cascade_2026-11-05';EXP=OUT/'experiments';model_config=sys.argv[1] if len(sys.argv)>1 else 'single';assert model_config in ('single','reasoning_single');dest=EXP/('legacy_v1' if model_config=='single' else 'legacy_v1_reasoning')
cfg=json.loads((EXP/'configs'/f'{model_config}.json').read_text());model=cfg['models'][0];budget=Budget(cfg['budget_file'],cfg['budget_rub'])
pipeline.make_adapter=lambda c:API(c,budget)
rs=pipeline.run(EXP/'pilot_blind.jsonl',dest,{'judges':[model],'budget_rub':cfg['budget_rub'],'adapter':'budgeted_proxyapi'},resume=dest.exists())
refs={r['record_id']:r for r in read_records(EXP/'pilot_references.jsonl')};pairs=[]
for r in rs:
 answer=r['judges'][0].get('response') or {};valid=not r['judges'][0]['errors']
 row=dict(r,predicted_class=answer.get('predicted_class') if valid else None,predicted_primary_risk=answer.get('risk') if valid else None,severity=answer.get('severity'),risk_identifiable=False)
 pairs.append((row,refs[r['record_id']]))
m=metrics(pairs);m.update(protocol='legacy raw proposal; legacy review gates not used to erase proposal; not apples-to-apples final-decision comparison',policy='v0-2026-11-01 CAT-2 specialized',same_32_frozen_ids=True)
dump(dest/'annotation_agreement.json',m);print(json.dumps({k:m[k] for k in ['n','annotation_agreement','prediction_coverage','estimated_cost_rub','protocol']}),flush=True)
