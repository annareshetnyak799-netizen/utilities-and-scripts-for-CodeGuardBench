import argparse
import json
import time
from pathlib import Path
from .adapters import make_adapter
from .io import read_records, digest, dump, append, completed
from .schema import validate_response
from .static import analyze, SECRET
from .version import implementation_sha

PROMPTS = Path(__file__).parent/'prompts'

def gate(responses, static):
    reasons=[]
    if not static['bash_valid']: reasons.append('invalid_bash')
    reasons += static['flags']
    valid=[x['response'] for x in responses if not x.get('errors') and x.get('response')]
    if len(valid) != len(responses): reasons.append('invalid_or_failed_response')
    if any(x['review_required'] or x['predicted_class'] is None for x in valid): reasons.append('model_requests_review')
    if len({(x['risk'],x['predicted_class'],x['severity']) for x in valid})>1: reasons.append('judge_disagreement')
    if any(static['rule_hint'] and x['predicted_class']!=static['rule_hint'] for x in valid): reasons.append('rule_disagreement')
    if any(static['rule_hint'] and static['rule_risk'] and x['risk']!=static['rule_risk'] for x in valid): reasons.append('rule_risk_disagreement')
    if any(x['risk'] and not x['risk'].startswith('CAT-2.') for x in valid): reasons.append('outside_specialized_rubric')
    return sorted(set(reasons))

def run(input_path, output, config, limit=None, resume=False, dry_run=False):
    records=read_records(input_path)
    # Reject duplicate IDs so resume cannot silently skip distinct commands.
    for r in records:
        r.setdefault('record_id',r.get('id',digest(r['command'])[:20]))
    if len({r['record_id'] for r in records})!=len(records): raise ValueError('duplicate_record_id')
    system=(PROMPTS/'system_v1.md').read_text(); template=(PROMPTS/'user_template_v1.md').read_text()
    fingerprint=digest({'records':records,'config':config,'system':system,'template':template,'dry_run':dry_run,'implementation_sha':implementation_sha()})
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    manifest_path=output/'manifest.json'
    if manifest_path.exists():
        if not resume: raise ValueError('output_exists_use_resume')
        if json.loads(manifest_path.read_text())['fingerprint']!=fingerprint: raise ValueError('resume_fingerprint_mismatch')
    else:
        dump(manifest_path,dict(implementation_sha=implementation_sha(),fingerprint=fingerprint,config=config,prompt_sha=digest(system),input_sha=digest(records),dry_run=dry_run,policy_version='v0-2026-11-01',gold=False))
    configs=config.get('judges',[{'provider':'mock','model_id':'mock','family':'mock'}])
    if config.get('independent_dual') and (len(configs)!=2 or len({x['family'] for x in configs})!=2):
        raise ValueError('independent_dual_requires_distinct_families')
    adapters=[make_adapter({'provider':'mock'}) if dry_run else make_adapter(c) for c in configs]
    previous=completed(output/'results.jsonl');done={x['record_id'] for x in previous}
    processed=0
    for record in records:
        if record['record_id'] in done:continue
        if limit is not None and processed>=limit:break
        command=record['command'];static=analyze(command);answers=[]
        # Labels, descriptions, pair IDs, source URLs and metadata never enter prompt.
        messages=[{'role':'system','content':system},{'role':'user','content':template.replace('{payload}',json.dumps({'command':command},ensure_ascii=False))}]
        if static['bash_valid'] and 'possible_secret' not in static['flags']:
            for c,adapter in zip(configs,adapters):
                start=time.monotonic();entry={'model_id':c['model_id'],'response':None,'errors':[]}
                try:
                    raw,usage=adapter.complete(messages)
                    if SECRET.search(raw):raise ValueError('possible_secret_in_response')
                    entry.update(raw=raw,usage=usage)
                    response=json.loads(raw)
                    entry['errors']=validate_response(response,command)
                    if not entry['errors']:entry['response']=response
                except Exception as exc:
                    entry['errors']=[type(exc).__name__] # sanitized; never dump provider bodies
                entry['latency_s']=round(time.monotonic()-start,4);answers.append(entry)
        else:
            answers=[dict(model_id='not_called',response=None,errors=['static_rejected'])]
        reasons=gate(answers,static)
        row=dict(record_id=record['record_id'],command_sha=digest(command),static=static,judges=answers,
                 review_reasons=reasons,status='needs_review' if reasons else 'proposed',gold=False)
        append(output/'results.jsonl',row)
        # Every proposal requires human lock; uncertainty is a prioritization queue.
        processed+=1
    all_rows=completed(output/'results.jsonl')
    dump(output/'summary.json',dict(records=len(all_rows),proposed=sum(x['status']=='proposed' for x in all_rows),needs_review=sum(x['status']=='needs_review' for x in all_rows),gold=0,dry_run=dry_run))
    return all_rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    p.add_argument('--config',required=True);p.add_argument('--limit',type=int);p.add_argument('--resume',action='store_true');p.add_argument('--dry-run',action='store_true')
    a=p.parse_args();run(a.input,a.output,json.loads(Path(a.config).read_text()),a.limit,a.resume,a.dry_run)
if __name__=='__main__':main()
