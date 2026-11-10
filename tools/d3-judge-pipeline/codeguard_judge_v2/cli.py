import argparse
import asyncio
import json
import re
import sys
import sqlite3
import uuid
from pathlib import Path
import yaml
from pydantic import ValidationError
from .common import atomic_write, dumps, digest
from .config import Config
from .evaluation import evaluate
from .export import export
from .pipeline import Pipeline, InjectedCrash
from .policy_registry import load_registry, approve, Registry
from .providers import MockProvider, HTTPProvider
from .records import read_records
from .review import import_decisions
from .stages import fingerprint
from .storage import Store


def jsonl(path):
    with Path(path).open() as f:
        return [json.loads(line) for line in f if line.strip()]


async def execute(args):
    out = Path(args.output_dir)
    if args.cmd == 'run' and (out / 'state.sqlite3').exists():
        raise ValueError('run requires a fresh output directory; use resume')
    out.mkdir(parents=True, exist_ok=True)
    store = Store(out / 'state.sqlite3')
    provider = None
    try:
        if args.cmd == 'run':
            raw_config = yaml.safe_load(Path(args.config).read_text()) if args.config else {}
            if args.mock:
                raw_config.setdefault('inference', {}).update(provider='mock', allow_network=False)
            config = Config.model_validate(raw_config)
            registry = load_registry(args.policy)
            run_id = args.run_id or 'run-' + uuid.uuid4().hex[:12]
            manifest = fingerprint(config, registry)
            atomic_write(out / f'{run_id}.policy.json', dumps(registry.model_dump(mode='json', by_alias=True)))
            store.create_run(run_id, manifest, config)
            store.ingest(run_id, read_records(args.input))
            atomic_write(out / 'run_manifest.json', dumps({'run_id': run_id, 'versions': manifest, 'config': config.model_dump(mode='json')}))
        else:
            run_id = args.run_id
            saved = store.run(run_id)
            config = Config.model_validate(json.loads(saved['config']))
            registry = Registry.model_validate_json((out / f'{run_id}.policy.json').read_text())
            if digest(fingerprint(config, registry)) != saved['fingerprint']:
                raise ValueError('resume fingerprint mismatch: start a new run')
            if saved['status'] == 'ingesting':
                raise ValueError('input ingest incomplete: start a new run with the source input')
            if args.max_spend is not None:
                store.raise_budget(run_id, args.max_spend)
        if args.crash_after_stage1 and config.inference.provider != 'mock':
            raise ValueError('fault injection is mock-only')
        provider = MockProvider(config.inference.mock_latency_seconds) if config.inference.provider == 'mock' else HTTPProvider(config)
        fired = False
        def hook(location, item_id, stage):
            nonlocal fired
            if args.crash_after_stage1 and not fired and location == 'after_stage_commit' and stage == 1:
                fired = True
                raise InjectedCrash('injected crash after durable Stage 1')
        pipeline = Pipeline(store, run_id, config, registry, provider, crash_hook=hook)
        metrics = await pipeline.run(out)
        exported = export(store, run_id, out)
        return {'run_id': run_id, 'status': store.run(run_id)['status'], 'metrics': metrics, 'export': exported}
    finally:
        if provider:
            await provider.close()
        store.close()


def parser():
    p = argparse.ArgumentParser(prog='judge-v2', description='Offline two-stage preliminary annotation; no corpus execution.')
    sub = p.add_subparsers(dest='cmd', required=True)
    policy = sub.add_parser('policy').add_subparsers(dest='policy_cmd', required=True)
    for name in ('validate', 'report-gaps'):
        q = policy.add_parser(name)
        q.add_argument('--registry')
    q = policy.add_parser('approve')
    for arg in ('registry', 'output', 'reviewer', 'evidence', 'version'):
        q.add_argument('--' + arg, required=True)
    q.add_argument('--rule-id', action='append', required=True)
    for cmd in ('run', 'resume'):
        q = sub.add_parser(cmd)
        q.add_argument('--output-dir', required=True)
        q.add_argument('--run-id', required=cmd == 'resume')
        q.add_argument('--crash-after-stage1', action='store_true', help='offline fault injection')
        if cmd == 'run':
            q.add_argument('--input', required=True)
            q.add_argument('--config')
            q.add_argument('--policy')
            q.add_argument('--mock', action='store_true')
        else:
            q.add_argument('--max-spend', type=float)
    q = sub.add_parser('export')
    q.add_argument('--output-dir', required=True)
    q.add_argument('--run-id', required=True)
    q.add_argument('--status', choices=['proposed', 'human_approved'], default='proposed')
    q = sub.add_parser('review-import')
    q.add_argument('--output-dir', required=True)
    q.add_argument('--run-id', required=True)
    q.add_argument('--decisions', required=True)
    q = sub.add_parser('evaluate')
    for arg in ('gold', 'predictions', 'development', 'output'):
        q.add_argument('--' + arg, required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if getattr(args, 'run_id', None) and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', args.run_id):
            raise ValueError('invalid run_id')
        if args.cmd in ('run', 'resume'):
            result = asyncio.run(execute(args))
        elif args.cmd == 'policy':
            if args.policy_cmd == 'approve':
                reg = approve(args.registry, args.output, args.rule_id, args.reviewer, args.evidence, args.version)
            else:
                reg = load_registry(args.registry)
            result = reg.gaps() if args.policy_cmd == 'report-gaps' else {'valid': True, 'policy_sha256': reg.sha, 'active_rules': reg.gaps()['active_rules']}
        elif args.cmd in ('export', 'review-import'):
            out = Path(args.output_dir)
            store = Store(out / 'state.sqlite3')
            try:
                store.run(args.run_id)
                if args.cmd == 'export':
                    result = export(store, args.run_id, out, args.status)
                else:
                    reg = Registry.model_validate_json((out / f'{args.run_id}.policy.json').read_text())
                    result = import_decisions(store, args.run_id, reg, jsonl(args.decisions))
            finally:
                store.close()
        else:
            result = evaluate(jsonl(args.gold), jsonl(args.predictions), jsonl(args.development))
            atomic_write(args.output, dumps(result) + '\n')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error, ExceptionGroup) as exc:
        # ValidationError string includes original input; never print it unfiltered.
        error = type(exc).__name__
        if isinstance(exc, ExceptionGroup):
            error = 'interrupted_or_injected_crash; durable stages can be resumed'
        elif isinstance(exc, ValueError) and not isinstance(exc, ValidationError):
            error = 'configuration_or_data_error'  # detailed private records remain in SQLite
        print(dumps({'error': error}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
