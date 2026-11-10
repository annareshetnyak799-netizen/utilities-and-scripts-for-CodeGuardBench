import json
import pytest
from codeguard_judge_v2.config import Config, RateConfig
from codeguard_judge_v2.storage import Store
from codeguard_judge_v2.stages import fingerprint
from codeguard_judge_v2.pipeline import Pipeline, InjectedCrash
from codeguard_judge_v2.providers import MockProvider, TransportError, Response
from codeguard_judge_v2.policy_registry import load_registry
from codeguard_judge_v2.limits import RateLimiter, LimitExceeded
from codeguard_judge_v2.export import export, COLUMNS


def setup(path, commands, cfg=None, registry=None, run='test'):
    cfg, registry = cfg or Config(), registry or load_registry()
    store = Store(path/'state.sqlite3')
    store.create_run(run, fingerprint(cfg, registry), cfg)
    store.ingest(run, ({'id': str(i), 'command': c, 'context': {}, 'metadata': {'source': 'test_fixture', 'seed': '-'}} for i, c in enumerate(commands)))
    return store, cfg, registry


def projection(results):
    return [{k: r[k] for k in ('id', 'operational_verdict', 'proposed_final_class', 'severity', 'primary_risk', 'review_status', 'review_reasons')} for r in results]


@pytest.mark.asyncio
async def test_default_policy_review(tmp_path):
    store, cfg, reg = setup(tmp_path, ['git status', 'rm -rf .git'])
    try:
        provider = MockProvider(0)
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert len(provider.calls) == 4
        assert all(r['review_status'] == 'needs_review' and r['proposed_final_class'] is None for r in store.results('test'))
    finally: store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', [1, 2])
@pytest.mark.parametrize('bad_count', [2, 3])
async def test_format_retry_bound(tmp_path, stage, bad_count, active_registry):
    store, cfg, reg = setup(tmp_path, ['rm -rf .git'], registry=active_registry)
    try:
        provider = MockProvider(0, {('rm -rf .git', stage): ['not json']*bad_count})
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert provider.calls.count(('rm -rf .git', stage)) == 3
        if stage == 2: assert provider.calls.count(('rm -rf .git', 1)) == 1
        assert list(store.results('test'))[0]['review_status'] == ('technical_failure' if bad_count == 3 else 'proposed')
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert provider.calls.count(('rm -rf .git', stage)) == 3
    finally: store.close()


@pytest.mark.asyncio
async def test_semantic_review_no_retry(tmp_path, active_registry):
    store, cfg, reg = setup(tmp_path, ['rm -rf .git'], registry=active_registry)
    raw = {'decisions': [{'action_id': 'a1', 'rule_id': None, 'review_reason': 'semantic_mismatch', 'note': 'fixture mismatch'}]}
    try:
        provider = MockProvider(0, {('rm -rf .git', 2): [json.dumps(raw)]})
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert len(provider.calls) == 2
        assert list(store.results('test'))[0]['review_reasons'] == ['semantic_mismatch']
    finally: store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('where', ['after_stage_commit', 'after_response_before_commit'])
async def test_crash_resume(tmp_path, where, active_registry):
    store, cfg, reg = setup(tmp_path, ['rm -rf .git'], registry=active_registry)
    provider = MockProvider(0)
    def crash(location, item, stage):
        if location == where and stage == 1: raise InjectedCrash('fixture')
    with pytest.raises(ExceptionGroup): await Pipeline(store, 'test', cfg, reg, provider, crash_hook=crash).run()
    assert store.run('test')['status'] == 'interrupted'
    store.close()
    store = Store(tmp_path/'state.sqlite3')
    try:
        second = MockProvider(0)
        await Pipeline(store, 'test', cfg, reg, second).run()
        assert second.calls.count(('rm -rf .git', 1)) == (0 if where == 'after_stage_commit' else 1)
        assert len(list(store.results('test'))) == 1
        calls = len(second.calls)
        await Pipeline(store, 'test', cfg, reg, second).run()
        assert len(second.calls) == calls
    finally: store.close()


@pytest.mark.asyncio
async def test_retries_persist_on_crash(tmp_path):
    store, cfg, reg = setup(tmp_path, ['git status'])
    provider = MockProvider(0, {('git status', 1): ['invalid']*3})
    def crash(location, item, stage):
        if location == 'after_response_before_commit' and len(provider.calls) == 2: raise InjectedCrash('fixture')
    try:
        with pytest.raises(ExceptionGroup): await Pipeline(store, 'test', cfg, reg, provider, crash_hook=crash).run()
        second = MockProvider(0, {('git status', 1): ['invalid']*5})
        await Pipeline(store, 'test', cfg, reg, second).run()
        assert len(second.calls) == 2
        assert store.counters('test', '0', 1)['format_errors'] == 3
    finally: store.close()


@pytest.mark.asyncio
async def test_transports_timeout(tmp_path, active_registry):
    store, cfg, reg = setup(tmp_path, ['rm -rf .git'], registry=active_registry)
    cfg.pipeline.backoff_base_seconds = .001
    provider = MockProvider(0, {('rm -rf .git', 1): [TransportError(429, .003), TransportError(503, .001), TimeoutError()]})
    try:
        report = await Pipeline(store, 'test', cfg, reg, provider).run()
        assert len(provider.calls) == 5
        assert report['count_429'] == 1 and report['transport_errors'] == 3
        assert report['runtime']['throttled_seconds'] >= .001
        assert list(store.results('test'))[0]['operational_verdict'] == 'deny'
    finally: store.close()


@pytest.mark.asyncio
async def test_transport_bound(tmp_path):
    store, cfg, reg = setup(tmp_path, ['git status'])
    cfg.pipeline.backoff_base_seconds = .001
    provider = MockProvider(0, {('git status', 1): [TransportError(503, .001)]*6})
    try:
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert len(provider.calls) == 4
        assert list(store.results('test'))[0]['review_status'] == 'technical_failure'
    finally: store.close()


@pytest.mark.asyncio
async def test_thousand_bounded_pipeline(tmp_path, active_registry):
    cfg = Config(pipeline={'queue_capacity': 2})
    store, cfg, reg = setup(tmp_path, ['git status', 'rm -rf .git']*500, cfg, active_registry)
    try:
        provider = MockProvider(.0001)
        report = await Pipeline(store, 'test', cfg, reg, provider).run()
        assert [r['id'] for r in store.results('test')] == list(map(str, range(1000)))
        assert len(provider.calls) == 2000
        assert report['runtime']['peak_queue1'] <= 2 and report['runtime']['peak_queue2'] <= 2
        assert 1 < provider.max_active <= 16 and provider.stage_overlap
        assert store.db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert store.db.execute('SELECT COUNT(*) FROM stage_results').fetchone()[0] == 2000
    finally: store.close()


@pytest.mark.asyncio
async def test_concurrency_results_stable(tmp_path, active_registry):
    commands = ['git status', 'cat /etc/shadow', 'terraform destroy -auto-approve; rm -rf .git']*10
    outputs = []
    for n in (1, 16):
        cfg = Config(pipeline={'stage1_concurrency': n, 'stage2_concurrency': n, 'max_inflight_total': n})
        store, cfg, reg = setup(tmp_path/str(n), commands, cfg, active_registry)
        try:
            await Pipeline(store, 'test', cfg, reg, MockProvider(.001)).run()
            outputs.append(projection(store.results('test')))
        finally: store.close()
    assert outputs[0] == outputs[1]


@pytest.mark.asyncio
async def test_budget_resume(tmp_path, active_registry):
    cfg = Config(pipeline={'stage1_concurrency': 1, 'stage2_concurrency': 1, 'max_inflight_total': 1},
                 inference={'input_price_per_million': 1, 'output_price_per_million': 1}, run={'max_spend': .001})
    store, cfg, reg = setup(tmp_path, ['rm -rf .git'], cfg, active_registry)
    try:
        provider = MockProvider(0)
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert store.run('test')['status'] == 'budget_paused' and not provider.calls
        store.raise_budget('test', 10)
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert store.run('test')['status'] == 'completed' and len(list(store.results('test'))) == 1
        assert store.cost('test')['conservative_spend'] > 0
    finally: store.close()


@pytest.mark.asyncio
async def test_exact_cache(tmp_path, active_registry):
    cfg = Config(run={'cache_policy': 'exact'}, pipeline={'stage1_concurrency': 1, 'stage2_concurrency': 1, 'max_inflight_total': 1})
    store, cfg, reg = setup(tmp_path, ['git status']*4, cfg, active_registry)
    try:
        provider = MockProvider(.001)
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert len(provider.calls) < 8
        store.create_run('two', fingerprint(cfg, reg), cfg)
        store.ingest('two', [{'id': 'z', 'command': 'git status', 'context': {}, 'metadata': {'class': 'deny'}}])
        second = MockProvider(0)
        await Pipeline(store, 'two', cfg, reg, second).run()
        assert not second.calls and list(store.results('two'))[0]['id'] == 'z'
    finally: store.close()


@pytest.mark.asyncio
async def test_secret_oversize_no_calls(tmp_path):
    store, cfg, reg = setup(tmp_path, ['echo sk-'+'a'*30, 'x'*33000, '', '\x00'])
    try:
        p = MockProvider(0)
        await Pipeline(store, 'test', cfg, reg, p).run()
        assert not p.calls and len(list(store.results('test'))) == 4
    finally: store.close()


@pytest.mark.asyncio
async def test_exports(tmp_path, active_registry):
    import csv
    store, cfg, reg = setup(tmp_path, ['git status', 'rm -rf .git', '"$ACTION" .'], registry=active_registry)
    try:
        await Pipeline(store, 'test', cfg, reg, MockProvider(0)).run()
        r = export(store, 'test', tmp_path)
        assert r['traces'] == 3 and r['csv_rows'] == 2 and not r['gold']
        first = (tmp_path/'proposals/results.jsonl').read_bytes()
        export(store, 'test', tmp_path)
        assert first == (tmp_path/'proposals/results.jsonl').read_bytes()
        with (tmp_path/'proposals/commands_NOT_GOLD.csv').open() as f: assert csv.DictReader(f).fieldnames == COLUMNS
        assert export(store, 'test', tmp_path, 'human_approved')['csv_rows'] == 0
    finally: store.close()


class FakeClock:
    def __init__(self): self.t = 0; self.waits = []
    def clock(self): return self.t
    async def sleep(self, n): self.waits.append(n); self.t += n


@pytest.mark.asyncio
async def test_shared_rate_limiter():
    clock = FakeClock()
    limiter = RateLimiter(RateConfig(requests_per_minute=2, input_tokens_per_minute=100, output_tokens_per_minute=100,
                                     combined_tokens_per_minute=120, utilization_target=1), clock.clock, clock.sleep)
    r = await limiter.reserve(50, 50)
    limiter.settle(r, Response('{}', 10, 10))
    await limiter.reserve(50, 50)
    assert clock.t == 0
    await limiter.reserve(1, 1)
    assert clock.t == 60
    limiter.block(7)
    await limiter.reserve(1, 1)
    assert clock.t == 67
    with pytest.raises(LimitExceeded): await limiter.reserve(101, 1)


@pytest.mark.asyncio
async def test_budget_paused_after_durable_stage1(tmp_path):
    cfg = Config(pipeline={'stage1_concurrency': 1, 'stage2_concurrency': 1, 'max_inflight_total': 1},
                 inference={'input_price_per_million': 1, 'output_price_per_million': 1}, run={'max_spend': 10})
    store, cfg, reg = setup(tmp_path, ['git status'], cfg)
    def lower_budget(location, item, stage):
        if location == 'after_stage_commit' and stage == 1:
            with store.db:
                store.db.execute('UPDATE runs SET ceiling=?', (store.cost('test')['conservative_spend']+.000001,))
    try:
        provider = MockProvider(0)
        await Pipeline(store, 'test', cfg, reg, provider, crash_hook=lower_budget).run()
        assert store.run('test')['status'] == 'budget_paused'
        assert store.stage('test', '0', 1)['status'] == 'success'
        assert provider.calls == [('git status', 1)]
        store.raise_budget('test', 20)
        await Pipeline(store, 'test', cfg, reg, provider).run()
        assert provider.calls == [('git status', 1), ('git status', 2)]
        for amount in (float('nan'), float('inf'), -1):
            with pytest.raises(ValueError): store.raise_budget('test', amount)
    finally: store.close()


@pytest.mark.asyncio
async def test_pydantic_error_retry_and_unknown_trace(tmp_path):
    store, cfg, reg = setup(tmp_path, ['git status', '"$ACTION" .'])
    provider = MockProvider(0, {('git status', 2): ['{"decisions":[]}']*3})
    try:
        await Pipeline(store, 'test', cfg, reg, provider).run()
        rows = list(store.results('test'))
        assert rows[0]['review_status'] == 'technical_failure'
        assert rows[0]['stage1']['status'] == 'success'
        assert rows[0]['stage2']['metadata']['attempts'] == 3
        assert rows[1]['stage1']['result']['actions'][0]['unresolved'] == 'unknown_variable'
        assert rows[1]['stage2']['status'] == 'skipped'
        raw = store.db.execute('SELECT response_content FROM stage_attempts WHERE stage=2').fetchall()
        assert all(r[0] == '{"decisions":[]}' for r in raw)
    finally: store.close()
