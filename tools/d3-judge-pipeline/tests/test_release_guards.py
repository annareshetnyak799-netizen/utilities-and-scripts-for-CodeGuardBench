import json
import pytest
from jsonschema import ValidationError,validate
from judge.static import analyze
from judge.generate import GENERATION_SCHEMA
from codeguard_judge.providers import API,Budget,ProviderError

def test_single_candidate_is_not_a_minimal_pair():
 c={'command':'echo fixture','description':'fictional','util':'echo','class':'allow','severity':'low'}
 with pytest.raises(ValidationError):validate({'candidates':[c]},GENERATION_SCHEMA)
def test_oversize_rejected_before_ast_features(monkeypatch):
 import judge.static as static
 monkeypatch.setattr(static,'features',lambda c: (_ for _ in ()).throw(AssertionError('oversize AST must not run')))
 assert 'invalid_or_oversize_input' in static.analyze('a'*32769)['flags']
@pytest.mark.parametrize('secret',['sk-'+'a'*30,'xoxb-'+'a'*20,'-----BEGIN EC PRIVATE KEY-----'])
def test_extended_secret_shapes_never_reach_parser(secret):
 assert 'possible_secret' in analyze('printf '+secret)['flags']
def test_api_parameters_cannot_override_budgeted_limit(tmp_path):
 c={'base_url':'https://api.proxyapi.ru/v1','allow_network':True,'model_id':'priced','rub_per_million':{'input':1,'output':1},'parameters':{'max_tokens':1000000000}}
 with pytest.raises(ProviderError,match='reserved_request_parameter'):API(c,Budget(tmp_path/'ledger',1))
