from pathlib import Path
from judge.io import read_records,write_jsonl,dump,digest
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/cascade_2026-11-05';dest=OUT/'human_review';dest.mkdir(exist_ok=True)
pilot=read_records(OUT/'experiments/pilot_references.jsonl');fixtures=read_records(ROOT/'tests/fixtures/all_taxonomy.jsonl')
# 32 peer cases plus 20 independently authored cases in absent CAT-0,5..9.
extra=[]
for category in ['CAT-0','CAT-5','CAT-6','CAT-7','CAT-8','CAT-9']:
 group=[r for r in fixtures if r['diagnostic_family'].split('.')[0]==category]
 extra.extend(group[:3] if category in ('CAT-0','CAT-8') else group[:4])
extra=extra[:20];rows=pilot+extra
blind=[];key=[]
for i,r in enumerate(sorted(rows,key=lambda r:digest(['blind-human-order-v1',r['record_id']]))):
 ident=f'HR-{i+1:03d}'
 blind.append({'review_id':ident,'command':r['command'],'action':None,'primary_risk':None,'severity':None,'risk_identifiable_from_command':None,'missing_context':[],'policy_conflict':None,'effect_and_evidence':None,'reviewer':None,'reviewed_at':None,'human_lock':False})
 key.append({'review_id':ident,'record_id':r['record_id'],'origin':'peer_annotation' if 'class' in r else 'independently_authored_diagnostic','curated_class':r.get('class'),'curated_risk':r.get('risk'),'provenance':r.get('provenance')})
write_jsonl(dest/'blind_review.jsonl',blind);write_jsonl(dest/'reference_key_DO_NOT_SHOW_REVIEWER.jsonl',key)
# All 43 historical disputed CAT-2.2 remain separate, rather than claiming 52 covers them.
root=ROOT.parents[2]
refs=read_records(OUT/'discovery_v2/eligible_references.jsonl');cat22=[r for r in refs if r['risk']=='CAT-2.2' and r['class']=='deny']
write_jsonl(dest/'cat22_deny_review_candidates.jsonl',[{'record_id':r['record_id'],'command':r['command'],'reviewer':None,'action':None,'policy_question':'Q02; current deny is not an independent human label'} for r in cat22])
dump(dest/'manifest.json',{'blind_cases':len(blind),'peer_cases':len(pilot),'authored_cases':len(extra),'human_gold':0,'cat22_current_deny_candidates':len(cat22),'historical_disputed_count':43,'historical43_exact_linkage':'see CodeBench collections/cat2_v0_audit_2026-10-31; do not equate all current deny with historical43','instructions':'Review commands before opening reference key. Do not show model proposals first. Record policy ambiguity; do not force a label.'})
print({'review_cases':len(blind),'human_gold':0})
