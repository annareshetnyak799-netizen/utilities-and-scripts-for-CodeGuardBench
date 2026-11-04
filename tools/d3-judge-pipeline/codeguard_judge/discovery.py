"""Read Git blobs without checkout. Selection and exclusions have an audit trail."""
import collections,csv,io,json,re,subprocess
from pathlib import Path
from judge.io import digest,dump,write_jsonl,FIELDS
from .policy import TAXONOMY

def git(repo,*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL)
def discover(repos,output):
 out=Path(output);out.mkdir(parents=True,exist_ok=False);snap=out/'snapshots';snap.mkdir()
 inventory=[];records=[];seen_blobs={};excluded=[]
 for repo in repos:
  repo=Path(repo)
  refs=git(repo,'for-each-ref','--format=%(refname:short)','refs/remotes/origin').decode().splitlines()
  for ref in refs:
   sha=git(repo,'rev-parse',ref).decode().strip();paths=git(repo,'ls-tree','-r','--name-only',sha).decode().splitlines()
   entry={'repository':repo.name,'branch':ref,'commit':sha,'csv_files':[]};inventory.append(entry)
   for path in paths:
    if not path.endswith('.csv'):continue
    blob=git(repo,'show',sha+':'+path);blob_sha=digest(blob)
    try:reader=csv.DictReader(io.StringIO(blob.decode('utf-8-sig')));fields=set(reader.fieldnames or [])
    except (UnicodeError,csv.Error):continue
    if not {'command','class','risk'}<=fields:continue
    # Canonical datasets, not audit snapshots/reserve/changelog copies.
    canonical=bool(re.fullmatch(r'CAT-[^/]+/(?:commands(?:_test|_train)?|test|train)(?:_commands)?\.csv',path) or re.fullmatch(r'(?:data/)?(?:train|test)[^/]*\.csv',path) or re.fullmatch(r'CAT-[^/]+/(?:test|train)/commands\.csv',path))
    info={'path':path,'blob_sha':blob_sha,'canonical':canonical,'rows':0};entry['csv_files'].append(info)
    if not canonical:info['exclusion']='noncanonical_snapshot_or_auxiliary';continue
    if blob_sha in seen_blobs:info['exclusion']='identical_blob';info['duplicate_of']=seen_blobs[blob_sha];continue
    seen_blobs[blob_sha]=f'{ref}:{path}'
    (snap/(blob_sha+'.csv')).write_bytes(blob)
    for n,row in enumerate(reader,2):
     info['rows']+=1;command=row.get('command','');risk=row.get('risk','').split()[0] if row.get('risk') else ''
     record_id=digest([repo.name,sha,path,n,command]);issues=[]
     if row.get('class') not in ('allow','ask','deny'):issues.append('incompatible_v0_class')
     if risk not in TAXONOMY:issues.append('unknown_risk')
     if set(row)!=set(FIELDS):issues.append('csv_schema')
     if row.get('source') not in ('real','local','handmade','synthetic'):issues.append('invalid_source')
     category=row.get('category','').split()[0] if row.get('category') else ''
     if category!=risk.split('.')[0]:issues.append('category_mismatch')
     if row.get('severity') not in ('low','medium','high','critical'):issues.append('invalid_severity')
     if not command.strip():issues.append('empty_command')
     if row.get('source')!='synthetic' and row.get('seed')!='-':issues.append('invalid_seed')
     record=dict(row,record_id=record_id,risk=risk,category=category,provenance={'repository':repo.name,'branch':ref,'commit':sha,'path':path,'row':n,'snapshot_sha':blob_sha},human_reviewed=False,contamination='historical_diagnostic_not_pristine_holdout',split='train' if 'train' in path.lower() else 'test',ingest_issues=issues)
     records.append(record)
     if issues:excluded.append({'record_id':record_id,'issues':issues})
 eligible=[r for r in records if not (set(r['ingest_issues'])-{'invalid_source'}) and r['split']=='test']
 # Exact commands stay in same partition; deterministic freeze before inference.
 for r in records:r['partition']='dev' if int(digest(r['command'])[:8],16)%5==0 else 'holdout_diagnostic'
 write_jsonl(out/'references.jsonl',records);write_jsonl(out/'eligible_references.jsonl',eligible)
 write_jsonl(out/'blind_inputs.jsonl',[{'record_id':r['record_id'],'command':r['command']} for r in eligible])
 counts=collections.Counter(r['risk'] for r in eligible)
 dump(out/'inventory.json',{'repositories':inventory,'total_rows':len(records),'eligible_test_rows':len(eligible),'excluded':excluded,'taxonomy_counts':{k:counts[k] for k in sorted(TAXONOMY)},'blind_fields':['record_id','command'],'human_gold':0})
 return eligible
