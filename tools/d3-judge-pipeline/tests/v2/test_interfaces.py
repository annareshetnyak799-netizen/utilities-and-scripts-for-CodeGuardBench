import asyncio
import csv
import json
from datetime import datetime, timezone
from unittest.mock import patch
import httpx
import pytest
from codeguard_judge_v2.common import digest
from codeguard_judge_v2.config import Config
from codeguard_judge_v2.cli import main
from codeguard_judge_v2.records import read_records
from codeguard_judge_v2.providers import HTTPProvider, TransportError, retry_after
from codeguard_judge_v2.evaluation import evaluate, check_leakage
from codeguard_judge_v2.review import import_decisions
from codeguard_judge_v2.export import export
from codeguard_judge_v2.pipeline import Pipeline
from codeguard_judge_v2.providers import MockProvider
from codeguard_judge_v2.limits import InflightGate
from .test_pipeline import setup


def test_config_no_implicit_network():
    for raw in ({'inference': {'provider': 'openai_compatible'}}, {'pipeline': {'max_format_retries': 3}},
                {'pipeline': {'queue_capacity': 0}}, {'inference': {'base_url': 'https://name:secret@example.org'}},
                {'run': {'max_spend': float('nan')}}):
        with pytest.raises(ValueError): Config.model_validate(raw)


@pytest.mark.asyncio
async def test_http_adapter_fake_transport(monkeypatch):
    monkeypatch.setenv('TEST_KEY', 'never-log-me')
    config = Config(inference={'provider': 'openai_compatible', 'api_key_env': 'TEST_KEY', 'base_url': 'https://mock.invalid/v1',
                               'allow_network': True, 'input_price_per_million': 1, 'output_price_per_million': 1},
                    run={'max_spend': 1})
    provider = HTTPProvider(config)
    await provider.client.aclose()
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1: return httpx.Response(429, headers={'Retry-After': '3'})
        return httpx.Response(200, json={'choices': [{'message': {'content': '{}', 'reasoning_content': 'DO_NOT_STORE'}}],
                                        'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'completion_tokens_details': {'reasoning_tokens': 15}}, 'model': 'fake'})
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(TransportError) as e: await provider.complete(1, {}, [], {'type': 'object'}, 99)
        assert e.value.code == 429 and e.value.retry_after == 3
        result = await provider.complete(1, {}, [], {'type': 'object'}, 99)
        assert result.reasoning_tokens == 15 and result.output_tokens == 20
        assert 'DO_NOT_STORE' not in str(result)
        assert requests[0]['response_format']['json_schema']['strict'] is True
        assert requests[0]['max_completion_tokens'] == 99
    finally: await provider.close()


def test_retry_after_header():
    assert retry_after('5') == 5 and retry_after('nonsense') is None
    assert retry_after('Thu, 01 Jan 1970 00:00:00 GMT') == 0


def test_csv_raw_and_context(tmp_path):
    path = tmp_path/'input.csv'
    command = 'echo "two\nlines"'
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['command', 'source', 'seed', 'class']); w.writeheader()
        w.writerow(dict(command=command, source='synthetic', seed='source seed', **{'class': 'deny'}))
    r = list(read_records(path))[0]
    assert r['command'] == command and r['metadata']['class'] == 'deny'
    path = tmp_path/'bad.jsonl'
    path.write_text(json.dumps({'id': 'x', 'command': 'git status', 'context': {'class': 'deny'}}))
    with pytest.raises(ValueError): list(read_records(path))


@pytest.mark.asyncio
async def test_duplicate_delivery_idempotent(tmp_path):
    store, cfg, reg = setup(tmp_path, ['git status'])
    class DuplicatePipeline(Pipeline):
        async def producer(self):
            row = next(store.items('test'))
            await self.q1.put(row.copy()); await self.q1.put(row.copy())
            for _ in range(cfg.pipeline.stage1_concurrency): await self.q1.put(None)
    try:
        await DuplicatePipeline(store, 'test', cfg, reg, MockProvider(.001)).run()
        assert len(list(store.results('test'))) == 1
        assert store.db.execute('SELECT COUNT(*) FROM stage_results').fetchone()[0] == 2
    finally: store.close()


@pytest.mark.asyncio
async def test_out_of_order_and_durable_s1(tmp_path, active_registry):
    store, cfg, reg = setup(tmp_path, ['git status', 'rm -rf .git'], registry=active_registry)
    class OutOfOrder(MockProvider):
        async def complete(self, stage, data, *args):
            if stage == 1 and data['command'] == 'git status': await asyncio.sleep(.03)
            if stage == 2:
                identifier = '0' if data['command'] == 'git status' else '1'
                assert store.stage('test', identifier, 1)['status'] == 'success'
            return await super().complete(stage, data, *args)
    try:
        provider = OutOfOrder(0)
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert provider.calls[0] == ('rm -rf .git', 1)
        assert [r['id'] for r in store.results('test')] == ['0', '1']
    finally: store.close()


@pytest.mark.asyncio
async def test_fair_inflight_gate():
    gate = InflightGate(1)
    order = []
    async def worker(stage):
        async with gate.slot(stage, lambda: True):
            order.append(stage)
            await asyncio.sleep(0)
    async with gate.slot(1):
        tasks = [asyncio.create_task(worker(2)) for _ in range(10)] + [asyncio.create_task(worker(1)) for _ in range(5)]
        await asyncio.sleep(0)
    await asyncio.gather(*tasks)
    assert order[:4] == [2, 2, 2, 1] and gate.peak == 1


@pytest.mark.asyncio
async def test_human_import_explicit_and_bound(tmp_path, active_registry):
    store, cfg, reg = setup(tmp_path, ['rm -rf .git'], registry=active_registry)
    try:
        await Pipeline(store, 'test', cfg, reg, MockProvider(0)).run()
        record = dict(id='0', command_sha256=digest('rm -rf .git'), policy_sha256=reg.sha, reviewer='TEST_HUMAN',
                      adjudicated_at='2026-11-09T00:00:00Z', evidence='Test-only explicit review', independent=True,
                      primary_risk='CAT-2.4', proposed_final_class='deny', severity='high', rule_id='G-2.4-METADATA-DELETE', description='fixture')
        with pytest.raises(ValueError): import_decisions(store, 'test', reg, [{**record, 'independent': False}])
        with pytest.raises(ValueError): import_decisions(store, 'test', reg, [{**record, 'command_sha256': '0'*64}])
        assert export(store, 'test', tmp_path, 'human_approved')['csv_rows'] == 0
        import_decisions(store, 'test', reg, [record])
        assert export(store, 'test', tmp_path, 'human_approved')['csv_rows'] == 1
    finally: store.close()


def gold():
    return dict(id='g', command='git status', gold_class='allow', gold_risk='CAT-0.0', gold_severity='low',
                semantic_family='independent-family', adjudication_status='human_approved', independent=True,
                split='locked_test', reviewer='TEST_HUMAN', adjudicated_at='2026-11-09', evidence='fixture', locked_at='2026-11-09', policy_sha256='a'*64)


def prediction():
    return dict(id='g', input={'command': 'git status'}, policy_sha256='a'*64, proposed_final_class='allow',
                primary_risk='CAT-0.0', severity='low', review_status='proposed')


def test_eval_proposals_rejected_and_population():
    p, g = prediction(), gold()
    assert evaluate([g], [p], [])['class_accuracy'] == 1
    for changed in ({**g, 'independent': False}, {**g, 'adjudication_status': 'proposed'}, {**g, 'split': 'development'}):
        with pytest.raises(ValueError): evaluate([changed], [p], [])
    with pytest.raises(ValueError): evaluate([g, g], [p], [])
    with pytest.raises(ValueError): evaluate([g], [p, p], [])
    with pytest.raises(ValueError): evaluate([g], [], [])
    with pytest.raises(ValueError): evaluate([g], [{**p, 'policy_sha256': 'b'*64}], [])


@pytest.mark.parametrize('dev', [dict(command='different text', semantic_family='independent-family'),
                                dict(command='git status', semantic_family='another-family'),
                                dict(command='git status ', semantic_family='third-family')])
def test_family_near_leakage(dev):
    with pytest.raises(ValueError): check_leakage([gold()], [dev])


def test_cli_crash_resume_export(tmp_path):
    input_file = tmp_path/'input.jsonl'; input_file.write_text('{"id":"one","command":"git status"}\n')
    out = tmp_path/'run'
    assert main(['run', '--mock', '--input', str(input_file), '--output-dir', str(out), '--run-id', 'demo', '--crash-after-stage1']) == 2
    assert main(['resume', '--run-id', 'demo', '--output-dir', str(out)]) == 0
    assert main(['export', '--run-id', 'demo', '--output-dir', str(out), '--status', 'human_approved']) == 0
    assert main(['run', '--mock', '--input', str(input_file), '--output-dir', str(out)]) == 2
