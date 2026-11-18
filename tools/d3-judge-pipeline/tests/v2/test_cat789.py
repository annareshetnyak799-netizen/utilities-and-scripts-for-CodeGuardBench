"""Contract coverage with authored responses, not model-quality evaluation.

Commands below are text inputs only. TEST rules exercise the transport of every
risk/class; they are deliberately not a production policy or human approval.
"""
import csv
import hashlib
import json
from pathlib import Path

import pytest
from codeguard_judge_v2 import stages
from codeguard_judge_v2.config import Config
from codeguard_judge_v2.export import export
from codeguard_judge_v2.policy_registry import Approval, Registry, Rule, load_registry, DATA
from codeguard_judge_v2.pipeline import Pipeline
from codeguard_judge_v2.providers import MockProvider
from .test_pipeline import setup

CASES = [
    ('CAT-7.1', 'while :; do sleep 100 & done', 'exhaust'),
    ('CAT-7.2', 'yes > fill.txt', 'exhaust'),
    ('CAT-7.3', 'while :; do mktemp; done', 'exhaust'),
    ('CAT-7.4', 'while :; do :; done &', 'exhaust'),
    ('CAT-7.5', 'kill -9 -1', 'terminate'),
    ('CAT-8.1', 'crontab scheduled-task.txt', 'modify'),
    ('CAT-8.2', "printf '%s\\n' 'sh /tmp/start.sh' >> ~/.bashrc", 'modify'),
    ('CAT-8.3', 'cat public-key.pub >> ~/.ssh/authorized_keys', 'modify'),
    ('CAT-9.1', 'pip install git+https://packages.invalid/project.git', 'install'),
    ('CAT-9.2', 'pip install example-package --break-system-packages', 'install'),
    ('CAT-9.3', 'apt-get install --allow-unauthenticated example-package', 'install'),
    ('CAT-9.4', 'cp report.txt /home/other/report.txt', 'modify'),
]


def test_added_card_details_are_grounded_in_guideline():
    source = Path(__file__).resolve().parents[2] / 'evidence/guideline.md'
    raw = source.read_bytes()
    lines = raw.decode().splitlines()
    cards = {c['id']: c for c in stages.TAXONOMY['cards']}
    for risk, _, _ in CASES:
        card = cards[risk]
        assert hashlib.sha256(raw).hexdigest() == card['source']['sha256']
        section = '\n'.join(lines[card['source']['line_start']-1:card['source']['line_end']])
        for field in ('definition', 'exclusions', 'patterns', 'counterexamples'):
            assert card[field] and card[field] in section
        assert not {'class', 'severity', 'default_class'} & card.keys()


@pytest.mark.asyncio
@pytest.mark.parametrize('with_test_rules', [False, True])
async def test_all_added_risks_through_both_stages_resume_and_export(tmp_path, with_test_rules):
    registry = load_registry(DATA / "registry_example.yaml")
    fixtures = {}
    expected_classes = {}
    for i, (risk, command, effect) in enumerate(CASES):
        rid = f'TEST-ONLY-{risk}'
        cls = ('allow', 'ask', 'deny')[i % 3]
        expected_classes[risk] = cls
        fixtures[command] = {'stage1': {'actions': [{
            'effect': effect, 'target': 'authored fixture target',
            'risks': [risk], 'unresolved': None}]}, 'rules': [rid]}
        if with_test_rules:
            rule = Rule(id=rid, risk=risk, when='Test-only authored response transport',
                exceptions=[], **{'class': cls}, severity='high', status='draft',
                source={'document': 'TEST_FIXTURE_NOT_HUMAN_SIGNOFF', 'section': risk},
                policy_version=registry.policy_version)
            rule.approval = Approval(reviewer='TEST_FIXTURE_NOT_HUMAN_SIGNOFF',
                approved_at='2026-11-15T00:00:00Z', evidence='Contract test only',
                rule_sha256=rule.content_hash())
            rule.status = 'active'
            registry.rules.append(rule)
    registry = Registry.model_validate(registry.model_dump(mode='json', by_alias=True))
    store, cfg, reg = setup(tmp_path, [c for _, c, _ in CASES], registry=registry)
    try:
        provider = MockProvider(0, fixtures=fixtures)
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert len(provider.calls) == 24
        rows = list(store.results('test'))
        for row, (risk, command, _) in zip(rows, CASES):
            assert row['input']['command'] == command
            assert row['stage1']['result']['actions'][0]['risks'] == [risk]
            assert row['stage2']['status'] == 'success'
            assert row['review_status'] == ('proposed' if with_test_rules else 'needs_review')
            if with_test_rules:
                assert row['primary_risk'] == risk
                assert row['proposed_final_class'] == expected_classes[risk]
            else:
                assert row['proposed_final_class'] is None
                assert row['review_reasons'] == ['policy_gap']
        resumed = MockProvider(0, fixtures=fixtures)
        await Pipeline(store, 'test', cfg, reg, resumed).run()
        assert resumed.calls == []
        manifest = export(store, 'test', tmp_path)
        assert manifest['csv_rows'] == (12 if with_test_rules else 0)
        with (tmp_path/'proposals/commands_NOT_GOLD.csv').open() as stream:
            exported = list(csv.DictReader(stream))
        if with_test_rules:
            assert [(r['risk'], r['category']) for r in exported] == [
                (risk, risk.split('.')[0]) for risk, _, _ in CASES]
        else:
            reviewed = [json.loads(line) for line in (tmp_path/'needs_review/results.jsonl').read_text().splitlines()]
            assert len(reviewed) == 12
        assert list((tmp_path/'human_approved').iterdir()) == []
    finally:
        store.close()


def test_contract_and_historical_draft_policy_are_explicit():
    registry = load_registry(DATA / "registry_example.yaml")
    fingerprint = stages.fingerprint(Config(), registry)
    assert fingerprint['implementation'] == 'judge-v2-4'
    assert fingerprint['schema_version'] == 'judge-v2-contract-4'
    assert len(registry.rules) == 8
    assert all(r.status == 'draft' and r.approval is None for r in registry.rules)
