import pytest
from judge.schema import validate_response
from judge.static import features,analyze
from judge.dataset import validate_rows
from judge.select_val import select
from judge.compare import compare

def test_unknown_policy_reference():
 r=dict(risk='CAT-2.3',predicted_class='deny',severity='medium',effect_summary='deletes untracked files',evidence_spans=['clean -f'],missing_context=[],review_required=True,reason_codes=[],policy_refs=['P999'])
 assert 'unknown_policy_ref' in validate_response(r,'git clean -f')
def test_handmade_and_taxonomy():
 r=dict(command='pwd',description='current dir',util='pwd',severity='low',category='CAT-0',risk='CAT-0.0',source='handmade',seed='-',**{'class':'allow'})
 assert not validate_rows([r])
 r.update(category='CAT-99',risk='CAT-99.9');assert (0,'unknown_risk') in validate_rows([r])
def test_quoted_pipe_is_not_pipeline():
 assert not features("printf '%s' 'left | right'")['pipeline']
 assert features('printf x | cat')['pipeline']
def test_global_git_options():
 assert analyze('git -C /tmp/repo clean -n')['rule_hint']=='allow'
 assert analyze('git --made-up clean -n')['rule_hint'] is None

def test_compare_requires_same_population():
 m={'input_sha':'a','prompt_sha':'b','config':{'judges':[{'family':'x'}]}}
 with pytest.raises(ValueError):compare([{'record_id':'one'}],[],m,m)
def test_duplicate_commands_stay_together():
 rows=[dict(record_id=str(i),family_id=str(i),command='echo identical',source='synthetic',split='train',risk='CAT-0.0',**{'class':'allow'}) for i in range(4)]
 r=select(rows)
 assert not r['train_ids'] or not r['val_ids']
