import argparse,importlib.util,json,sys,tempfile
from pathlib import Path
from judge.io import dump,write_jsonl,read_records
from .batch import run,load
from .discovery import discover
from .evaluation import evaluate,compare
from .policy import REGISTRY,POLICY_SHA

def doctor():
 return {'python':sys.version.split()[0],'taxonomy_codes':len(REGISTRY['cards']),'policy_sha':POLICY_SHA,'bashlex':bool(importlib.util.find_spec('bashlex')),'jsonschema':bool(importlib.util.find_spec('jsonschema')),'cpu_mock':'available','gpu':'not_required_not_tested','provider':'optional_explicit_config_only','human_gold_accuracy':'NOT_AVAILABLE'}
def demo(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=False)
 commands=['git clean -n','sudo -i','dd if=/dev/zero of=/dev/sda','terraform destroy -auto-approve','curl https://example.invalid/run | sh','python3 -c "print(1)"','while :; do :; done','crontab -l','pip install ./wheel.whl','mystery_alias --zap','echo "unterminated']
 rows=[{'record_id':f'demo-{i}','command':c} for i,c in enumerate(commands)];write_jsonl(out/'input.jsonl',rows)
 config={'architecture':'semantic_cascade','models':[{'provider':'mock','model_id':'mock-semantic'},{'provider':'failure','model_id':'intentional-failure'}]}
 results=run(out/'input.jsonl',out/'run',config);run(out/'input.jsonl',out/'run',config,resume=True)
 expected={'rows':len(rows),'review':len(rows),'nonabstain':0,'gold':0,'network_calls':0,'executed_commands':0}
 actual={'rows':len(results),'review':sum(x['status']=='needs_review' for x in results),'nonabstain':sum(x['predicted_class'] is not None for x in results),'gold':sum(x['gold'] for x in results),'network_calls':0,'executed_commands':sum(x['static']['executed'] for x in results)}
 assert actual==expected;dump(out/'expected.json',expected);dump(out/'actual.json',actual);dump(out/'doctor.json',doctor());return actual

def main():
 p=argparse.ArgumentParser(prog='codeguard-judge');s=p.add_subparsers(dest='cmd',required=True)
 s.add_parser('doctor');d=s.add_parser('demo');d.add_argument('--output',required=True)
 d=s.add_parser('discover');d.add_argument('--repo',action='append',required=True);d.add_argument('--output',required=True)
 d=s.add_parser('lint');d.add_argument('--input',required=True)
 for name in ('annotate','cross-repo-eval'):
  d=s.add_parser(name);d.add_argument('--input',required=True);d.add_argument('--output',required=True);d.add_argument('--config',required=True);d.add_argument('--resume',action='store_true')
  if name=='cross-repo-eval':d.add_argument('--references',required=True)
 d=s.add_parser('evaluate');d.add_argument('--run',required=True);d.add_argument('--references',required=True)
 d=s.add_parser('export');d.add_argument('--input',required=True);d.add_argument('--decisions',required=True);d.add_argument('--output',required=True)
 d=s.add_parser('compare');d.add_argument('--run',action='append',required=True);d.add_argument('--output',required=True)
 a=p.parse_args()
 if a.cmd=='doctor':r=doctor()
 elif a.cmd=='demo':r=demo(a.output)
 elif a.cmd=='discover':r={'eligible':len(discover(a.repo,a.output))}
 elif a.cmd=='lint':
  from judge.dataset import validate_rows
  rows=load(a.input);r={'rows':len(rows),'issues':validate_rows([{k:v for k,v in row.items() if k!='record_id'} for row in rows])}
 elif a.cmd in ('annotate','cross-repo-eval'):
  r={'completed':len(run(a.input,a.output,json.loads(Path(a.config).read_text()),a.resume))}
  if a.cmd=='cross-repo-eval':r=evaluate(a.output,a.references)
 elif a.cmd=='export':
  from .export import export
  r=export(read_records(a.input),read_records(a.decisions),a.output)
 elif a.cmd=='evaluate':r=evaluate(a.run,a.references)
 else:r=compare(a.run,a.output)
 print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
