import json
import pytest
import yaml
from pydantic import ValidationError
from codeguard_judge_v2 import class_mode, stages
from codeguard_judge_v2.aggregation import aggregate
from codeguard_judge_v2.config import Config
from codeguard_judge_v2.policy_registry import load_registry
from codeguard_judge_v2.schemas import Stage1Result
from codeguard_judge_v2.pipeline import Pipeline
from codeguard_judge_v2.providers import Response
from codeguard_judge_v2.storage import Store


@pytest.mark.asyncio
async def test_cli_v3_unlabeled_input_and_resume(tmp_path, monkeypatch):
    from codeguard_judge_v2 import cli
    calls = []

    class Provider:
        def __init__(self, *args, **kwargs):
            pass

        async def complete(self, stage, data, messages, schema, max_tokens):
            calls.append(stage)
            raw = ({'actions': [action().model_dump(mode='json')]} if stage == 1 else
                   {'decisions': [{'action_id': 'a1', 'class': 'ask', 'note': 'Offline CLI test'}]})
            return Response(json.dumps(raw), 10, 10)

        async def close(self):
            pass

    monkeypatch.setattr(cli, 'MockProvider', Provider)
    source = tmp_path / 'input.jsonl'
    source.write_text(json.dumps({'id': 'unlabeled', 'command': 'unknown_fixture'}) + '\n')
    config = tmp_path / 'config.yaml'
    config.write_text(yaml.safe_dump({'run': {'decision_mode': 'guideline_three_class'}}))
    out = tmp_path / 'run'
    args = cli.parser().parse_args(['run', '--input', str(source), '--config', str(config),
                                   '--run-id', 'test', '--output-dir', str(out)])
    result = await cli.execute(args)
    assert result['status'] == 'completed'
    assert calls == [1, 2]
    row = json.loads((out / 'reports/results.jsonl').read_text())
    assert row['proposed_final_class'] == 'ask'
    assert row['policy_version'] == class_mode.VERSION
    assert not (out / 'reference.jsonl').exists()
    args = cli.parser().parse_args(['resume', '--run-id', 'test', '--output-dir', str(out)])
    await cli.execute(args)
    assert calls == [1, 2]  # durable decisions do not incur another model call


def action():
    return Stage1Result.model_validate({'actions': [{'effect': 'unknown', 'target': 'unknown',
                                                    'risks': [], 'unresolved': 'unsupported_syntax'}]}).actions[0]


@pytest.mark.parametrize('length', [161, 201, 4096])
def test_long_target_preserves_full_path(length):
    target = '/home/user/' + 'x' * (length - len('/home/user/'))
    raw = {'actions': [{'effect': 'inspect', 'target': target, 'risks': ['CAT-0.0'], 'unresolved': None}]}
    parsed = stages.validate(1, json.dumps(raw), {}, load_registry())
    assert parsed['actions'][0]['target'] == target


def test_target_still_bounded():
    raw = {'actions': [{'effect': 'inspect', 'target': 'x' * 4097, 'risks': ['CAT-0.0'], 'unresolved': None}]}
    with pytest.raises(ValidationError):
        stages.validate(1, json.dumps(raw), {}, load_registry())


@pytest.mark.parametrize('label', ['allow', 'ask', 'deny'])
def test_three_classes_without_fabricated_rules(label):
    raw = {'decisions': [{'action_id': 'a1', 'class': label, 'note': 'Test-only decision.'}]}
    rows = class_mode.materialize(raw, [action()])
    result = aggregate(rows, class_only=True)
    assert result['proposed_final_class'] == label
    assert result['review_status'] == 'proposed'
    assert rows[0]['rule_id'] is None and rows[0]['severity'] is None


@pytest.mark.parametrize('label', [None, 'needs_review', 'modify', 'defer'])
def test_abstentions_are_invalid_not_silently_coerced(label):
    with pytest.raises(ValidationError):
        class_mode.materialize({'decisions': [{'action_id': 'a1', 'class': label, 'note': 'Test'}]}, [action()])


def test_exact_action_binding_and_aggregation():
    with pytest.raises(ValueError):
        class_mode.materialize({'decisions': [{'action_id': 'a2', 'class': 'ask', 'note': 'Test'}]}, [action()])
    raw = {'decisions': [{'action_id': 'a1', 'class': 'ask', 'note': 'Test'},
                         {'action_id': 'a2', 'class': 'deny', 'note': 'Test'}]}
    result = aggregate(class_mode.materialize(raw, [action(), action()]), class_only=True)
    assert result['proposed_final_class'] == 'deny' and result['review_status'] == 'proposed'
    assert 'aggregation_severity_unapproved:PI-20' in result['diagnostic_notes']


def test_modes_separate_policy_and_no_gold_leak():
    reg = load_registry()
    item = {'command': 'fixture', 'class': 'SECRET_GOLD_SENTINEL', 'metadata': {'risk': 'SECRET_GOLD_SENTINEL'}}
    s1 = Stage1Result(actions=[action()])
    data = stages.payload(2, item, {}, reg, s1, decision_mode=class_mode.MODE)
    assert 'SECRET_GOLD_SENTINEL' not in json.dumps(data)
    assert 'approved_rules_by_action' not in data
    assert len(data['guideline_cards']) == 42
    assert data['guideline_class_definitions']
    normal = Config()
    forced = Config(run={'decision_mode': class_mode.MODE})
    assert stages.fingerprint(normal, reg)['policy'] != stages.fingerprint(forced, reg)['policy']
    assert stages.cache_key(2, data, normal, reg) != stages.cache_key(2, data, forced, reg)


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', [False, True])
async def test_unknown_s1_reaches_forced_class_but_invalid_json_stays_technical(tmp_path, invalid):
    cfg = Config(run={'decision_mode': class_mode.MODE}, pipeline={'max_format_retries': 0})
    reg = load_registry()
    store = Store(tmp_path / 'state.sqlite3')
    store.create_run('test', stages.fingerprint(cfg, reg), cfg)
    store.ingest('test', [{'id': 'one', 'command': 'unknown_fixture'}])
    calls = []

    class Provider:
        async def complete(self, stage, data, messages, schema, max_tokens):
            calls.append(stage)
            if stage == 1:
                raw = {'actions': [action().model_dump(mode='json')]}
            else:
                assert schema == class_mode.SCHEMA
                raw = {'decisions': [{'action_id': 'a1', 'class': 'ask', 'note': 'Test-only fixture'}]}
            return Response('invalid json' if invalid and stage == 2 else json.dumps(raw), 10, 10)

    try:
        await Pipeline(store, 'test', cfg, reg, Provider()).run()
        row = list(store.results('test'))[0]
        assert calls == [1, 2]
        assert row['policy_version'] == class_mode.VERSION
        assert row['proposed_final_class'] == (None if invalid else 'ask')
        assert row['review_status'] == ('technical_failure' if invalid else 'proposed')
    finally:
        store.close()
