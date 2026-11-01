"""Clean local-model context for TRAIN seed drafting. No test data inputs.

Only abstract taxonomy definitions below are sent. No workspace/RAG/tools,
source commands, test seeds or previous conversation are exposed to the model.
Output is outside the test repository and quarantined pending independent QA.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from judge.adapters import HuggingFace
from judge.io import dump, append, digest, completed

DEFINITIONS={
 'CAT-2.1':'Git remote reference updates that can replace previously published history, contrasted with guarded updates.',
 'CAT-2.2':'Git operations discarding tracked working edits or saved work, contrasted with preserving changes.',
 'CAT-2.3':'Git removal of untracked or ignored work, contrasted with inspection without deletion.',
 'CAT-2.4':'Git repository metadata references and object reachability loss, contrasted with recovery and inspection.'}
SYSTEM='''Draft concrete synthetic TRAIN seed specifications for a Bash safety classifier.
You have only taxonomy definitions. Do not recall or quote examples, source code, commands, websites or logs.
Return JSON {"seeds":[{"mechanism":"short identifier", "prompt":"abstract instruction in prose, describing a scenario and a safe counterpart"}]}.
Create 5 meaningfully distinct mechanisms, not changes of filenames. Mention actual Git subcommand/option names as separate prose terms, explain what observable flags determine loss versus preservation, and require all values needed to infer behavior to be visible. Each prompt must be actionable for a generator and have a specific causal distinction. Avoid vague frameworks, generic history protection, imaginary approval systems, or contradictory 'deletion without deleting'. NO literal Bash command strings or few-shot examples. All drafts require later isolation and human review. JSON only.'''

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--config',required=True);a=p.parse_args()
 out=Path(a.output).resolve();repo=Path(__file__).resolve().parents[1]
 if out==repo or repo in out.parents:raise SystemExit('TRAIN artifacts must stay outside test repository')
 out.mkdir(parents=True,exist_ok=True)
 c=json.loads(Path(a.config).read_text())['judges'][0];c=dict(c,max_new_tokens=1600)
 dump(out/'author_manifest.json',dict(model=c,system_prompt=SYSTEM,definitions=DEFINITIONS,source_commands_provided=0,test_seeds_provided=0,context='fresh local model messages only',author_code_sha=digest(Path(__file__).read_bytes())))
 adapter=HuggingFace(c);done={r['risk'] for r in completed(out/'author_runs.jsonl')}
 for risk,definition in DEFINITIONS.items():
  if risk in done:continue
  try:
   raw,usage=adapter.complete([{'role':'system','content':SYSTEM},{'role':'user','content':definition}])
   obj=json.loads(raw);seeds=[]
   for i,s in enumerate(obj['seeds']):
    seeds.append(dict(seed_id=f'TRAIN-{risk}-{i+1:02d}',split='train',risk=risk,family_id=f'{risk}/'+s['mechanism'],prompt=s['prompt'],source_kind='abstract_synthetic_spec',status='quarantine_pending_cross_split_review',model_family_blocklist=[],ancestors=[],author_model=c['model_id'],version='1'))
   append(out/'author_runs.jsonl',dict(risk=risk,raw=raw,usage=usage,seeds=seeds,status='draft'))
  except Exception as exc:append(out/'author_runs.jsonl',dict(risk=risk,status='failed',error=type(exc).__name__))
 rows=[s for r in completed(out/'author_runs.jsonl') for s in r.get('seeds',[])]
 (out/'train_seeds.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
 print(json.dumps({'draft_seeds':len(rows),'approved':0}))
