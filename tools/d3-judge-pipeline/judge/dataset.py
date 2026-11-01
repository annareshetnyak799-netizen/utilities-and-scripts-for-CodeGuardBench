"""Validation/export and split leakage gates. No automatic safety labels."""
import argparse
import collections
import csv
import difflib
import json
import re
from pathlib import Path
from .io import FIELDS, read_records, dump, digest, write_jsonl
from .static import analyze, SECRET

def validate_rows(rows):
    issues=[];seen=set()
    for n,r in enumerate(rows):
        if set(r)!=set(FIELDS) or any(not isinstance(r.get(f),str) or not r[f].strip() for f in FIELDS):
            issues.append((n,'schema_or_empty'));continue
        if r['source'] not in {'real','local','synthetic'}:issues.append((n,'invalid_source'))
        if r['class'] not in {'allow','ask','deny'}:issues.append((n,'invalid_class'))
        if r['severity'] not in {'low','medium','high','critical'}:issues.append((n,'invalid_severity'))
        if r['source']!='synthetic' and r['seed']!='-':issues.append((n,'non_synthetic_seed'))
        if r['source']=='synthetic' and r['seed']=='-':issues.append((n,'missing_generation_prompt'))
        if r['risk'].split()[0].rsplit('.',1)[0]!=r['category'].split()[0]:issues.append((n,'category_mismatch'))
        if r['command'] in seen:issues.append((n,'exact_duplicate'))
        seen.add(r['command'])
        a=analyze(r['command'])
        if not a['bash_valid']:issues.append((n,'invalid_bash_or_secret'))
    return issues

def normalize(command):
    # Deliberately preserve quoted contents/flags. String similarity is only a signal.
    return command.strip()

def split_collisions(test, train, threshold=.90):
    findings=[]
    for a in test:
        for b in train:
            samefamily=a.get('family_id') and a.get('family_id')==b.get('family_id')
            lineage=set(a.get('ancestors',[])+[a.get('seed_id','')]) & set(b.get('ancestors',[])+[b.get('seed_id','')]);lineage.discard('')
            x=normalize(a.get('command',a.get('prompt','')));y=normalize(b.get('command',b.get('prompt','')))
            ratio=difflib.SequenceMatcher(None,x,y,autojunk=False).ratio()
            if samefamily or lineage or x==y or ratio>=threshold:
                findings.append(dict(test_id=a.get('seed_id',a.get('record_id')),train_id=b.get('seed_id',b.get('record_id')),same_family=bool(samefamily),shared_lineage=sorted(lineage),exact=x==y,similarity=ratio))
    return findings

def export_reviewed(candidates, decisions, output):
    """Require human identity and source evidence; never promote LLM self-approval."""
    approved={x['record_id']:x for x in decisions if x.get('human_reviewed') is True and x.get('human_reviewer')}
    selected=[];review=[]
    for candidate in candidates:
        d=approved.get(candidate['record_id'])
        if not d or d.get('status')!='accepted':review.append(candidate);continue
        if candidate.get('source') in ('real','local') and not (candidate.get('source_url') and candidate.get('source_verified') and candidate.get('rights_status')=='verified'):
            review.append(dict(candidate,export_error='source_or_rights_unverified'));continue
        row={f:candidate.get(f,'') for f in FIELDS}
        row.update({f:d[f] for f in ['class','risk','severity']})
        problems=validate_rows([row])
        if problems:review.append(dict(candidate,export_error=problems));continue
        selected.append(row)
    issues=validate_rows(selected)
    if issues:raise ValueError(issues)
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    with (out/'commands.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader();writer.writerows(selected)
    write_jsonl(out/'review.jsonl',review)
    dump(out/'manifest.json',dict(selected=len(selected),review=len(review),commands_sha=digest((out/'commands.csv').read_bytes())))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    rows=read_records(a.input);issues=validate_rows(rows);dump(a.output,dict(rows=len(rows),issues=issues,passed=not issues));raise SystemExit(bool(issues))
