"""Human approval is necessary; model agreement alone cannot authorize export."""
import csv
from pathlib import Path
from judge.dataset import validate_rows
from judge.io import FIELDS,digest,dump,write_jsonl
from .contracts import safety

def export(candidates,decisions,output):
 for rows in (candidates,decisions):
  ids=[r['record_id'] for r in rows]
  if len(ids)!=len(set(ids)):raise ValueError('duplicate_export_id')
 by={r['record_id']:r for r in candidates};selected=[];sidecar=[];rejected=[]
 for d in decisions:
  r=by.get(d['record_id']);why=[]
  if r is None:raise ValueError('unknown_export_id')
  if not (d.get('human_lock') is True and d.get('human_reviewed') is True and d.get('reviewer') and d.get('reviewed_at') and d.get('evidence') and d.get('policy_version')):why.append('missing_human_approval_metadata')
  if d.get('command_sha')!=digest(r['command']):why.append('approval_command_mismatch')
  if d.get('status')!='accepted' or d.get('unresolved_policy') or d.get('missing_context'):why.append('unresolved_review')
  if r.get('source') in ('real','local') and not (r.get('source_verified') and r.get('source_url') and r.get('rights_status')=='verified'):why.append('unverified_provenance')
  row={k:r.get(k,'') for k in FIELDS}
  for k in ('class','risk','severity'):row[k]=d.get(k)
  row['category']=str(row['risk']).split('.')[0]
  if validate_rows([row]):why.append('invalid_csv_contract')
  if why:rejected.append({'record_id':d['record_id'],'reasons':why});continue
  selected.append(row);sidecar.append({'record_id':d['record_id'],'human_lock':True,'reviewer':d['reviewer'],'reviewed_at':d['reviewed_at'],'evidence':d['evidence'],'policy_version':d['policy_version'],'command_sha':d['command_sha'],'safety_label':safety(row['class']),'mapping':'unconditional-v1-proposed'})
 if validate_rows(selected):raise ValueError('invalid_export_batch')
 out=Path(output);out.mkdir(parents=True,exist_ok=False)
 with (out/'commands.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(selected)
 write_jsonl(out/'human_lock.jsonl',sidecar);write_jsonl(out/'rejected.jsonl',rejected);dump(out/'manifest.json',{'accepted':len(selected),'rejected':len(rejected),'commands_sha':digest((out/'commands.csv').read_bytes())})
 return {'accepted':len(selected),'rejected':len(rejected)}
