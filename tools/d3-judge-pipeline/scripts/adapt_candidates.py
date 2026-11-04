"""D1/D2 -> blinded D3 input + separate provenance, without modifying upstream files."""
import argparse
from pathlib import Path
from judge.io import digest,dump,read_records,write_jsonl

def adapt(rows,kind,out):
 ids=[r.get('record_id') for r in rows]
 if any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)):raise ValueError('invalid_upstream_ids')
 blind=[];sidecar=[];quarantine=[]
 for r in rows:
  if not isinstance(r.get('command'),str) or not r['command'].strip():
   quarantine.append({'record_id':r['record_id'],'reason':'invalid_command'});continue
  if kind=='d2' and not r.get('owner_privacy_approved'):
   quarantine.append({'record_id':r['record_id'],'reason':'owner_privacy_review_pending'});continue
  if kind=='d1' and r.get('split') not in ('train','test'):
   quarantine.append({'record_id':r['record_id'],'reason':'missing_split'});continue
  blind.append({'record_id':r['record_id'],'command':r['command']})
  sidecar.append({k:v for k,v in r.items() if k!='command'} | {'command_sha':digest(r['command']),'upstream_kind':kind,'annotation_status':'proposal_not_gold','allowed_split':'test_only' if kind=='d2' else r['split']})
 out=Path(out);out.mkdir(parents=True,exist_ok=False)
 if kind=='d2':out.chmod(0o700)
 write_jsonl(out/'blind_inputs.jsonl',blind);write_jsonl(out/'provenance.jsonl',sidecar);write_jsonl(out/'quarantine.jsonl',quarantine)
 if kind=='d2':
  for p in out.iterdir():p.chmod(0o600)
 result={'input_rows':len(rows),'accepted':len(blind),'quarantine':len(quarantine),'blinded_fields':['record_id','command']};dump(out/'manifest.json',result);return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--kind',choices=['d1','d2'],required=True);p.add_argument('--output',required=True);a=p.parse_args();print(adapt(read_records(a.input),a.kind,a.output))
