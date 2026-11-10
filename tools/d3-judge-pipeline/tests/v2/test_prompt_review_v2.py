"""Review of v0 prompt integration and contract behavior; mock calls only."""
import json
import pytest
from codeguard_judge_v2.schemas import Stage1Result, validate_stage1
from codeguard_judge_v2 import stages
from codeguard_judge_v2.parser import parse
from codeguard_judge_v2.policy_registry import materialize
from codeguard_judge_v2.providers import MockProvider
from codeguard_judge_v2.pipeline import Pipeline
from .test_pipeline import setup


def test_only_v0_taxonomy_is_sent_and_validated():
    assert len(stages.V0_RISK_CODES) == 30
    assert all(int(x.split('-')[1].split('.')[0]) <= 6 for x in stages.V0_RISK_CODES)
    payload = stages.payload(1, {'command': 'git status', 'context': {}}, parse('git status'), None)
    assert len(payload['taxonomy']['cards']) == 30
    assert 'CAT-9.1' not in json.dumps(payload['taxonomy'])
    assert 'potential' in stages.PROMPTS[1].lower()
    assert 'POTENTIAL' in stages.PROMPTS[2]
    with pytest.raises(ValueError, match='unknown taxonomy'):
        validate_stage1({'actions': [{'effect': 'install', 'target': 'package',
                      'risks': ['CAT-9.1'], 'unresolved': None}]}, stages.V0_RISK_CODES)


def test_known_effect_unknown_target_is_valid_but_not_safe():
    result = Stage1Result.model_validate({'actions': [{
        'effect': 'delete', 'target': '$TARGET (unresolved)',
        'risks': [], 'unresolved': 'unknown_variable'}]})
    assert not result.actions[0].risks
    with pytest.raises(ValueError):
        Stage1Result.model_validate({'actions': [{
            'effect': 'delete', 'target': '$TARGET',
            'risks': [], 'unresolved': None}]})


def test_opaque_payload_preserves_visible_risk():
    out = validate_stage1({'actions': [{
        'effect': 'execute', 'target': 'encoded payload from payload.b64',
        'risks': ['CAT-6.1'], 'unresolved': 'unknown_payload'}]}, stages.V0_RISK_CODES)
    assert out.actions[0].risks == ['CAT-6.1']


@pytest.mark.asyncio
async def test_known_risk_with_unresolved_value_reaches_stage2(tmp_path, active_registry):
    command = 'rm -rf .git'
    stage1 = json.dumps({'actions': [{
        'effect': 'delete', 'target': '.git',
        'risks': ['CAT-2.4'], 'unresolved': 'runtime_context'}]})
    store, cfg, reg = setup(tmp_path, [command], registry=active_registry)
    try:
        provider = MockProvider(latency=0, faults={(command, 1): [stage1]})
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert provider.calls == [(command, 1), (command, 2)]
        row = list(store.results('test'))[0]
        assert row['proposed_final_class'] == 'deny'
    finally:
        store.close()


@pytest.mark.asyncio
async def test_unidentified_risk_is_never_assumed_allow(tmp_path):
    cmd = '"$ACTION" .'
    store, cfg, reg = setup(tmp_path, [cmd])
    try:
        provider = MockProvider(latency=0)
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert provider.calls == [(cmd, 1)]
        result = list(store.results('test'))[0]
        assert result['review_status'] == 'needs_review'
        assert result['proposed_final_class'] is None
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('review_reason', ['missing_context', 'policy_gap'])
async def test_known_risk_respects_stage2_review(tmp_path, active_registry, review_reason):
    command = 'rm -rf .git'
    stage1 = {'actions': [{'effect': 'delete', 'target': '.git',
                          'risks': ['CAT-2.4'], 'unresolved': 'runtime_context'}]}
    stage2 = {'decisions': [{'action_id': 'a1', 'rule_id': None,
                            'review_reason': review_reason, 'note': 'Explicit review fixture.'}]}
    store, cfg, reg = setup(tmp_path, [command], registry=active_registry)
    try:
        provider = MockProvider(0, faults={(command, 1): [json.dumps(stage1)],
                                           (command, 2): [json.dumps(stage2)]})
        await Pipeline(store, 'test', cfg, reg, provider).run()
        row = list(store.results('test'))[0]
        assert provider.calls == [(command, 1), (command, 2)]
        assert row['proposed_final_class'] is None
        assert row['review_reasons'] == [review_reason]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_known_effect_without_risk_skips_stage2(tmp_path):
    command = 'rm -- "$TARGET"'
    stage1 = {'actions': [{'effect': 'delete', 'target': '$TARGET',
                          'risks': [], 'unresolved': 'unknown_variable'}]}
    store, cfg, reg = setup(tmp_path, [command])
    try:
        provider = MockProvider(0, faults={(command, 1): [json.dumps(stage1)]})
        await Pipeline(store, 'test', cfg, reg, provider).run()
        row = list(store.results('test'))[0]
        assert provider.calls == [(command, 1)]
        assert row['stage2']['status'] == 'skipped'
        assert row['review_reasons'] == ['no_identified_risk']
        assert row['proposed_final_class'] is None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_mixed_identified_and_unknown_actions_remain_review(tmp_path, active_registry):
    command = 'rm -rf .git; "$ACTION" .'
    stage1 = {'actions': [
        {'effect': 'delete', 'target': '.git', 'risks': ['CAT-2.4'], 'unresolved': 'runtime_context'},
        {'effect': 'unknown', 'target': '.', 'risks': [], 'unresolved': 'unknown_variable'}]}
    fixtures = {command: {'stage1': stage1, 'rules': ['G-2.4-METADATA-DELETE', None]}}
    store, cfg, reg = setup(tmp_path, [command], registry=active_registry)
    try:
        provider = MockProvider(0, fixtures=fixtures)
        await Pipeline(store, 'test', cfg, reg, provider).run()
        row = list(store.results('test'))[0]
        assert provider.calls == [(command, 1), (command, 2)]
        assert row['operational_verdict'] == 'deny'
        assert row['proposed_final_class'] is None
        assert 'missing_context' in row['review_reasons']
        assert row['review_status'] == 'needs_review'
    finally:
        store.close()


@pytest.mark.asyncio
async def test_out_of_scope_risk_exhausts_bounded_format_retries(tmp_path):
    command = 'pip install example-package'
    stage1 = json.dumps({'actions': [{'effect': 'install', 'target': 'package',
                                     'risks': ['CAT-9.1'], 'unresolved': None}]})
    store, cfg, reg = setup(tmp_path, [command])
    try:
        provider = MockProvider(0, faults={(command, 1): [stage1] * 3})
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert provider.calls == [(command, 1)] * 3
        row = list(store.results('test'))[0]
        assert row['review_status'] == 'technical_failure'
        assert row['proposed_final_class'] is None
    finally:
        store.close()
