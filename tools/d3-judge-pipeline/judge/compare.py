"""Combine completed independent model runs; no extra model calls or majority gold."""
import argparse
from .io import read_records, dump, write_jsonl
from .pipeline import gate

def compare(left,right,left_manifest,right_manifest):
    lm=left_manifest;rm=right_manifest
    if lm['input_sha']!=rm['input_sha'] or lm['prompt_sha']!=rm['prompt_sha']:
        raise ValueError('comparison_requires_same_input_and_prompt')
    lf=lm['config']['judges'][0]['family'];rf=rm['config']['judges'][0]['family']
    right_byid={x['record_id']:x for x in right};rows=[];disagree=valid_both=0
    for a in left:
        b=right_byid.get(a['record_id'])
        if b is None:continue
        if a['command_sha']!=b['command_sha']:raise ValueError('command_mismatch')
        answers=[a['judges'][0],b['judges'][0]];reasons=gate(answers,a['static'])
        if all(x.get('response') and not x.get('errors') for x in answers):
            valid_both+=1
            if any(answers[0]['response'][k]!=answers[1]['response'][k] for k in ['risk','predicted_class','severity']):disagree+=1
        rows.append(dict(record_id=a['record_id'],command_sha=a['command_sha'],static=a['static'],judges=answers,review_reasons=reasons,status='needs_review' if reasons else 'proposed',gold=False))
    return rows,dict(shared=len(rows),valid_both=valid_both,disagreements=disagree,disagreement_rate=disagree/valid_both if valid_both else None,independent_families=lf!=rf,gold=0)

if __name__=='__main__':
    import json
    from pathlib import Path
    p=argparse.ArgumentParser();p.add_argument('--left',required=True);p.add_argument('--right',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    l=Path(a.left);r=Path(a.right);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    rows,summary=compare(read_records(l/'results.jsonl'),read_records(r/'results.jsonl'),json.loads((l/'manifest.json').read_text()),json.loads((r/'manifest.json').read_text()))
    write_jsonl(out/'results.jsonl',rows);dump(out/'summary.json',summary)
