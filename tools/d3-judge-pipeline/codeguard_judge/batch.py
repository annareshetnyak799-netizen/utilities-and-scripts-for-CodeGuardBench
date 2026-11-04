import csv,importlib.metadata,json,platform,sys
from pathlib import Path
from judge.io import append,completed,digest,dump,read_records,write_jsonl
from .cascade import Cascade,TASKS,INSTRUCTION
from .contracts import SCHEMA,SEMANTIC_SCHEMA,CRITIC_SCHEMA,SCHEMA_VERSION
from .policy import POLICY_SHA,REGISTRY
from .providers import lock

def implementation_sha():
 root=Path(__file__).resolve().parents[1]
 files=list((root/'codeguard_judge').rglob('*.py'))+list((root/'judge').glob('*.py'))
 return digest({str(p.relative_to(root)):digest(p.read_bytes()) for p in sorted(files)})
def load(path):
 path=Path(path);file_sha=digest(path.read_bytes())
 if path.suffix=='.csv':
  rows=read_records(path)
 else:
  rows=[]
  for i,line in enumerate(path.read_text().splitlines()):
   if not line.strip():continue
   try:r=json.loads(line)
   except ValueError:r={'command':None,'input_error':'malformed_json_line'}
   rows.append(r if isinstance(r,dict) else {'command':None,'input_error':'nonobject_row'})
 for i,r in enumerate(rows):r.setdefault('record_id',digest({'file_sha':file_sha,'row':i,'command':r.get('command')}))
 ids=[r['record_id'] for r in rows]
 if any(not isinstance(i,str) or not i for i in ids) or len(ids)!=len(set(ids)):raise ValueError('duplicate_or_invalid_record_id')
 return rows

def run(input_path,output,config,resume=False):
 rows=load(input_path);out=Path(output);out.mkdir(parents=True,exist_ok=True)
 version={'input_sha':digest(Path(input_path).read_bytes()),'policy_sha':POLICY_SHA,'policy_version':REGISTRY['version'],'schema_sha':digest([SCHEMA,SEMANTIC_SCHEMA,CRITIC_SCHEMA]),'prompt_sha':digest([TASKS,INSTRUCTION]),'implementation_sha':implementation_sha(),'parser_version':importlib.metadata.version('bashlex'),'config':config,'mode':'command_only','expected_ids':[r['record_id'] for r in rows]}
 fingerprint=digest(version)
 with lock(out/'.run.lock'):
  manifest_path=out/'run_manifest.json'
  if manifest_path.exists():
   if not resume:raise ValueError('existing_run_requires_resume')
   if json.loads(manifest_path.read_text())['fingerprint']!=fingerprint:raise ValueError('resume_fingerprint_mismatch')
  else:dump(manifest_path,dict(version,fingerprint=fingerprint,python=sys.version,platform=platform.platform(),human_gold_available=False))
  results=completed(out/'results.jsonl');ids=[r['record_id'] for r in results]
  if len(set(ids))!=len(ids) or not set(ids)<=set(version['expected_ids']):raise ValueError('corrupt_result_population')
  done=set(ids);cascade=Cascade(config)
  for row in rows:
   if row['record_id'] in done:continue
   result=cascade.annotate(row)
   append(out/'results.jsonl',result);results.append(result)
  # Review output deliberately contains IDs/diagnostics, not private commands.
  write_jsonl(out/'review_queue.jsonl',[{k:r[k] for k in ('record_id','predicted_class','predicted_primary_risk','review_reasons','status')} for r in results])
  dump(out/'pipeline_health.json',{'rows':len(rows),'completed':len(results),'review':len(results),'nonabstain':sum(r['predicted_class'] is not None for r in results),'human_gold_accuracy':'NOT_AVAILABLE','complete':len(results)==len(rows)})
 return results
