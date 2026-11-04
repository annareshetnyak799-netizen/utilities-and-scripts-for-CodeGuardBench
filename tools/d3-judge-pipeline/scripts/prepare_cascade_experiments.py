"""Freeze held-out diagnostic IDs BEFORE model calls; no prompt tuning on them."""
from pathlib import Path
import collections,json
from judge.io import digest,dump,read_records,write_jsonl
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/cascade_2026-11-05';EXP=OUT/'experiments';EXP.mkdir(exist_ok=True)
rows=read_records(OUT/'discovery_v2/eligible_references.jsonl');groups=collections.defaultdict(list)
for r in rows:
 if r['partition']=='holdout_diagnostic':groups[r['risk']].append(r)
selected=[]
for risk,rr in sorted(groups.items()):
 ordered=sorted(rr,key=lambda r:digest(['frozen-pilot-v1',r['record_id']]))
 chosen=[]
 # At most two labels per risk for budget; not a representative population estimate.
 for r in ordered:
  if len(chosen)<2 and (not chosen or r['class']!=chosen[0]['class']):chosen.append(r)
 if len(chosen)<2:chosen=ordered[:2]
 selected.extend(chosen)
write_jsonl(EXP/'pilot_references.jsonl',selected);write_jsonl(EXP/'pilot_blind.jsonl',[{'record_id':r['record_id'],'command':r['command']} for r in selected])
dump(EXP/'freeze.json',{'rows':len(selected),'ids':[r['record_id'] for r in selected],'input_sha':digest((EXP/'pilot_blind.jsonl').read_bytes()),'selection':'two per observed risk; differing labels if available; fixed hash order; holdout_diagnostic','contamination':'prior project familiarity; not pristine holdout','prompt_tuning_after_freeze':False,'human_gold':0})
config_dir=EXP/'configs';config_dir.mkdir(exist_ok=True)
common={'provider':'api','base_url':'https://api.proxyapi.ru/v1','allow_network':True,'credential_file':'/Users/dekovaleva/GigaChat/.proxyapi/access_token.py','timeout':60,'retries':0,'max_tokens':1800,'price_source':'https://proxyapi.ru/models/browse','price_checked':'2026-11-05'}
qwen=dict(common,model_id='qwen/qwen3-32b',family='Qwen',rub_per_million={'input':11.58,'output':37.89})
oss=dict(common,model_id='openai/gpt-oss-120b',family='gpt-oss',rub_per_million={'input':7.79,'output':35.79},parameters={'reasoning':{'effort':'low'}})
configs={'rules':{'architecture':'rules'},'mock':{'architecture':'semantic_cascade','models':[{'provider':'mock','model_id':'mock-a'},{'provider':'mock','model_id':'mock-b'}]},'single':{'architecture':'single','models':[qwen]},'static_single':{'architecture':'static_single','models':[qwen]},'reasoning_single':{'architecture':'single','models':[oss]},'critic_cascade':{'architecture':'critic_cascade','models':[qwen,oss]},'specialists':{'architecture':'specialists','models':[qwen,oss]},'semantic_cascade':{'architecture':'semantic_cascade','models':[qwen,oss]}}
for name,c in configs.items():
 c.update(budget_rub=60,budget_file=str(OUT/'budget_ledger.json'))
 dump(config_dir/(name+'.json'),c)
print({'frozen_pilot_rows':len(selected),'risks':sorted(groups),'budget_cap':60,'reserve_unallocated_rub':6})
