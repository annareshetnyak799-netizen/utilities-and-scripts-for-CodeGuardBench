"""Reproducible offline throughput/crash demo. Corpus text is never executed."""
import argparse
import asyncio
import json
from pathlib import Path
from codeguard_judge_v2.common import atomic_write, dumps
from codeguard_judge_v2.config import Config
from codeguard_judge_v2.storage import Store
from codeguard_judge_v2.stages import fingerprint
from codeguard_judge_v2.policy_registry import load_registry
from codeguard_judge_v2.providers import MockProvider
from codeguard_judge_v2.pipeline import Pipeline, InjectedCrash
from codeguard_judge_v2.export import export
from codeguard_judge_v2.records import read_records


def projection(store, run):
    return [{k: r[k] for k in ('id', 'operational_verdict', 'proposed_final_class', 'primary_risk', 'severity', 'review_status', 'review_reasons')} for r in store.results(run)]


async def experiment(out, name, records, workers=8, queue=128, latency=.01, crash=False):
    directory = out/name
    directory.mkdir(parents=True, exist_ok=False)
    cfg = Config(pipeline={'stage1_concurrency': workers, 'stage2_concurrency': workers,
                           'max_inflight_total': 1 if workers == 1 else 16, 'queue_capacity': queue},
                 inference={'mock_latency_seconds': latency})
    reg = load_registry()
    store = Store(directory/'state.sqlite3')
    try:
        store.create_run(name, fingerprint(cfg, reg), cfg)
        store.ingest(name, records)
        provider = MockProvider(latency)
        receipt = None
        def hook(location, item, stage):
            if crash and location == 'after_stage_commit' and stage == 1:
                raise InjectedCrash('offline demonstration')
        try:
            metrics = await Pipeline(store, name, cfg, reg, provider, crash_hook=hook).run(directory)
        except ExceptionGroup as group:
            if not all(isinstance(e, InjectedCrash) for e in group.exceptions): raise
            before = len(provider.calls)
            committed = store.db.execute('SELECT COUNT(*) FROM stage_results WHERE stage=1 AND status="success"').fetchone()[0]
            store.close()
            store = Store(directory/'state.sqlite3')
            provider = MockProvider(latency)
            metrics = await Pipeline(store, name, cfg, reg, provider).run(directory)
            receipt = dict(calls_before_crash=before, durable_stage1=committed,
                           stage1_calls_after_resume=sum(s == 1 for _, s in provider.calls),
                           stage2_calls_after_resume=sum(s == 2 for _, s in provider.calls))
            assert receipt['stage1_calls_after_resume'] == 0
        exported = export(store, name, directory)
        before_calls = len(provider.calls)
        await Pipeline(store, name, cfg, reg, provider).run()
        assert len(provider.calls) == before_calls
        return dict(metrics=metrics, export=exported, crash_receipt=receipt, results=projection(store, name))
    finally:
        store.close()


def rows(n):
    commands = ['git status', 'rm -rf .git', 'sudo -i', 'cat /etc/shadow']
    return ({'id': f'row-{i:06d}', 'command': commands[i % 4], 'context': {},
             'metadata': {'source': 'authored_mock_fixture_NOT_GOLD', 'seed': '-'}} for i in range(n))


async def main(args):
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=False)
    serial = await experiment(out, 'serial100', rows(100), workers=1)
    parallel = await experiment(out, 'parallel100', rows(100))
    assert serial['results'] == parallel['results']
    bounded = await experiment(out, 'bounded1000', rows(1000), queue=2, latency=.001)
    crash = await experiment(out, 'crash_resume', rows(1), workers=1, crash=True)
    results = dict(serial100=serial, parallel100=parallel, bounded1000=bounded, crash_resume=crash)
    if args.development_csv:
        results['development3000'] = await experiment(out, 'development3000', read_records(args.development_csv), latency=.001)
        assert results['development3000']['metrics']['completed'] == 3000
    for result in results.values(): result.pop('results')
    summary = dict(runs=results, identical_serial_parallel_results=True,
                   measured_mock_speedup=serial['metrics']['elapsed_seconds']/parallel['metrics']['elapsed_seconds'],
                   network_calls=0, executed_corpus_commands=0, human_gold=0,
                   semantic_validation=False, active_rules=0,
                   note='Mock transport/infrastructure measurement; not model accuracy or provider SLA.')
    atomic_write(out/'benchmark.json', dumps(summary)+'\n')
    print(dumps({k: v for k, v in summary.items() if k != 'runs'}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output-dir', required=True)
    p.add_argument('--development-csv')
    asyncio.run(main(p.parse_args()))
