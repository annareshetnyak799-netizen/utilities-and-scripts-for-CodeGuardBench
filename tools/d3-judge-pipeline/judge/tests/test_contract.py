import json
from pathlib import Path
import pytest
from judge.static import analyze, clean_hint
from judge.schema import validate_response
from judge.pipeline import run, gate
from judge.dataset import split_collisions, export_reviewed
from judge.generate import run as generate
from judge.select_val import select
from judge.evaluate import score
from judge.io import completed, write_jsonl

def answer(**kwargs):
    value=dict(risk='CAT-2.3',predicted_class='allow',severity='medium',effect_summary='Preview',evidence_spans=['-n'],missing_context=[],review_required=False,reason_codes=[],policy_refs=['P4'])
    value.update(kwargs);return value

@pytest.mark.parametrize('args,expected',[
    (['-dfe','--dry-run'],'deny'),(['-dne','--force'],'allow'),
    (['--exclude','--dry-run','-f'],'deny'),(['-fen'],'deny'),
    (['-n','-f'],'allow'),(['--','--dry-run','-f'],None),
    (['--interactive'],None),(['--unknown','-n'],None),(['-e'],None),
])
def test_option_consumption(args,expected):assert clean_hint(args)==expected

def test_parse_does_not_execute(tmp_path):
    marker=tmp_path/'executed'
    assert analyze(f'echo $(touch {marker})')['bash_valid']
    assert not marker.exists()

@pytest.mark.parametrize('command',[
    "printf '%s' 'git clean -f'", 'echo git clean -f',
    'git clean -n > important', 'git clean -n; git clean -f',
    'git clean -n $(printf x)',
])
def test_no_keyword_or_compound_oracle(command):assert analyze(command)['rule_hint'] is None

def test_schema_enum_evidence_and_abstention():
    assert not validate_response(answer(),'git clean -n')
    assert validate_response(answer(predicted_class='modify'),'git clean -n')
    assert validate_response(answer(evidence_spans=['not in command']),'git clean -n')
    assert validate_response(answer(predicted_class=None),'git clean -n')
    assert validate_response(answer(risk='CAT-99.9'),'git clean -n')

def test_resume_and_label_blinding(tmp_path,monkeypatch):
    from judge import pipeline
    calls=[]
    class Fake:
        def complete(self,messages):calls.append(messages);return json.dumps(answer()),{}
    monkeypatch.setattr(pipeline,'make_adapter',lambda c:Fake())
    source=tmp_path/'in.jsonl';write_jsonl(source,[{'record_id':'one','command':'git clean -n','class':'SECRET_LABEL','description':'HIDDEN_DESC','source_url':'HIDDEN_URL'}])
    config={'judges':[{'provider':'mock','model_id':'fake'}]};out=tmp_path/'out'
    run(source,out,config);run(source,out,config,resume=True)
    assert len(calls)==1
    assert all(x not in json.dumps(calls) for x in ['SECRET_LABEL','HIDDEN_DESC','HIDDEN_URL'])
    with pytest.raises(ValueError):run(source,out,dict(config,new=1),resume=True)

def test_secret_never_reaches_adapter(tmp_path,monkeypatch):
    from judge import pipeline
    class Fake:
        def complete(self,messages):raise AssertionError('must not call')
    monkeypatch.setattr(pipeline,'make_adapter',lambda c:Fake())
    p=tmp_path/'input.jsonl';write_jsonl(p,[{'command':'echo ghp_'+'a'*30}])
    result=run(p,tmp_path/'out',{'judges':[{'provider':'mock','model_id':'fake'}]})
    assert result[0]['judges'][0]['model_id']=='not_called'
    assert 'ghp_' not in (tmp_path/'out/results.jsonl').read_text()

def test_disagreement_gate():
    responses=[{'response':answer(),'errors':[]},{'response':answer(predicted_class='deny'),'errors':[]}]
    assert 'judge_disagreement' in gate(responses,analyze('git clean -n'))

def test_partial_resume(tmp_path):
    p=tmp_path/'log.jsonl';p.write_text('{"a":1}\n{"a":')
    assert completed(p)==[{'a':1}]
    assert p.with_suffix('.interrupted-tail').read_text()=='{"a":'

def test_lineage_not_just_text():
    a={'seed_id':'test','family_id':'same','prompt':'one'}
    b={'seed_id':'train','family_id':'same','prompt':'unrelated words'}
    assert split_collisions([a],[b])[0]['same_family']

def test_train_and_test_rejected_in_same_generation(tmp_path):
    p=tmp_path/'seeds.jsonl';write_jsonl(p,[dict(split='test',source_kind='abstract_synthetic_spec')])
    with pytest.raises(ValueError):generate(p,tmp_path/'out','train',{'provider':'mock'},dry_run=True)

def test_model_does_not_approve_itself(tmp_path):
    candidate={'record_id':'x','command':'git clean -n'}
    export_reviewed([candidate],[{'record_id':'x','status':'accepted','human_reviewed':False}],tmp_path/'export')
    assert len((tmp_path/'export/commands.csv').read_text().splitlines())==1

def test_gold_guard():
    with pytest.raises(ValueError):score([], [{'record_id':'x','class':'allow','risk':'CAT-2.3'}])

def test_family_split_and_no_test_contamination():
    rows=[dict(record_id=str(n),family_id=f'f{n//2}',command='echo safe',risk='CAT-2.2',source='synthetic',split='train',**{'class':'allow'}) for n in range(12)]
    r=select(rows);byid={x['record_id']:x['family_id'] for x in rows}
    assert not {byid[x] for x in r['train_ids']} & {byid[x] for x in r['val_ids']}
    rows[0]['split']='test'
    with pytest.raises(ValueError):select(rows)

def test_reset_incompatible_option_not_oracle():
    assert analyze('git reset --hard -p')['rule_hint'] is None

def test_non_string_input():
    assert not analyze(None)['bash_valid']

def test_independent_family_gate(tmp_path):
    path=tmp_path/'in.jsonl';write_jsonl(path,[{'command':'echo sample'}])
    c={'independent_dual':True,'judges':[{'provider':'mock','model_id':'a','family':'qwen'},{'provider':'mock','model_id':'b','family':'qwen'}]}
    with pytest.raises(ValueError):run(path,tmp_path/'out',c)

def test_network_requires_explicit_enable():
    from judge.adapters import OpenAICompatible
    with pytest.raises(ValueError):OpenAICompatible({'base_url':'https://remote.example/v1'})

def test_http_retry(monkeypatch):
    import urllib.error
    from judge import adapters
    calls=[]
    class Reply:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return b'{"choices":[{"message":{"content":"{}"}}],"usage":{}}'
    def fetch(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:raise urllib.error.HTTPError('http://localhost',429,'limited',{},None)
        return Reply()
    monkeypatch.setattr(adapters.urllib.request,'urlopen',fetch)
    monkeypatch.setattr(adapters.time,'sleep',lambda t:None)
    a=adapters.OpenAICompatible({'base_url':'http://127.0.0.1:8000/v1','model_id':'fixture'})
    assert a.complete([])[0]=='{}' and len(calls)==2

def test_generation_actual_adapter_path(tmp_path,monkeypatch):
    from judge import generate as module
    class Fake:
        def complete(self,messages):
            assert 'source_url' not in json.dumps(messages)
            return json.dumps({'candidates':[{'command':'echo fixture','description':'fixture','util':'echo','class':'allow','severity':'low'}]}),{}
    monkeypatch.setattr(module,'make_adapter',lambda c:Fake())
    p=tmp_path/'seeds.jsonl';write_jsonl(p,[dict(seed_id='T1',split='test',risk='CAT-2.1',family_id='fiction',source_kind='abstract_synthetic_spec',status='approved_for_generation',prompt='fictional instruction')])
    c={'provider':'mock','experimental_only':True}
    rows=generate(p,tmp_path/'out','test',c)
    assert rows[0]['status']=='generated_unreviewed'
    assert rows[0]['candidates'][0]['human_reviewed'] is False
    assert len(generate(p,tmp_path/'out','test',c,resume=True))==1

@pytest.mark.parametrize('mutation', [{'class':'modify'}, {'severity':'unknown'}, {'command':''}, {'extra':'field'}])
def test_generation_schema_rejects_invalid(mutation):
    from judge.generate import GENERATION_SCHEMA
    from jsonschema import validate, ValidationError
    candidate=dict(command='echo fixture',description='fixture',util='echo',severity='low',**{'class':'allow'})
    candidate.update(mutation)
    with pytest.raises(ValidationError):validate({'candidates':[candidate]},GENERATION_SCHEMA)

def test_implementation_fingerprint_blocks_resume(tmp_path,monkeypatch):
    from judge import pipeline
    path=tmp_path/'input.jsonl';write_jsonl(path,[{'command':'echo fixture'}])
    run(path,tmp_path/'run',{},dry_run=True)
    monkeypatch.setattr(pipeline,'implementation_sha',lambda:'changed')
    with pytest.raises(ValueError,match='resume_fingerprint'):run(path,tmp_path/'run',{},resume=True,dry_run=True)

def test_export_source_enum():
    from judge.dataset import validate_rows
    row=dict(command='echo fixture',description='fixture',util='echo',severity='low',category='CAT-2',risk='CAT-2.1',source='invented',seed='-',**{'class':'allow'})
    assert (0,'invalid_source') in validate_rows([row])
