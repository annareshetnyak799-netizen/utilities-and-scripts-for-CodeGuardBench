"""Two bounded worker pools; durable hand-off; finite, stage-local retries."""
import asyncio
import json
import random
import time
from pathlib import Path
from pydantic import ValidationError
from judge.static import SECRET  # Reuse only the tested secret-shape detector, never analyze().
from . import stages
from .aggregation import aggregate
from .common import digest, dumps, atomic_write
from .limits import InflightGate, RateLimiter, LimitExceeded
from .metrics import report
from .parser import parse, MAX_BYTES
from .policy_registry import materialize
from .providers import TransportError
from .schemas import Stage1Result
from .storage import BudgetExhausted


class InjectedCrash(RuntimeError):
    pass


class Pipeline:
    def __init__(self, store, run_id, config, registry, provider, *, crash_hook=None, limiter=None, sleep=asyncio.sleep):
        self.store, self.run_id, self.config, self.registry, self.provider = store, run_id, config, registry, provider
        self.crash_hook, self.sleep = crash_hook, sleep
        p = config.pipeline
        self.q1, self.q2 = asyncio.Queue(p.queue_capacity), asyncio.Queue(p.queue_capacity)
        self.gate = InflightGate(p.max_inflight_total, p.prefer_stage2_when_backlogged)
        self.limiter = limiter or RateLimiter(config.rate_limit)
        # Restore recent quota reservations conservatively across a process restart.
        if limiter is None:
            for row in store.db.execute('SELECT * FROM stage_attempts WHERE started>? ORDER BY started', (time.time()-60,)):
                pin = row['input_tokens'] if row['input_tokens'] is not None else row['estimated_input']
                pout = row['output_tokens'] if row['output_tokens'] is not None else row['estimated_output']
                self.limiter.entries.append([self.limiter.clock()-(time.time()-row['started']), 1, pin, pout, pin+pout])
        self.paused = False
        self.stats = dict(cache_hits=0, format_retries=0, transport_retries=0, peak_queue1=0, peak_queue2=0)
        self.done = asyncio.Event()
        self.elapsed_prior = store.run(run_id)['elapsed_seconds']
        self.started = time.monotonic()
        self.output = None

    def runtime_stats(self):
        return {**self.stats, 'peak_inflight': self.gate.peak, 'inflight': self.gate.active,
                'queue1': self.q1.qsize(), 'queue2': self.q2.qsize(),
                'throttled_seconds': self.limiter.throttled_seconds,
                'provider_stage_overlap': getattr(self.provider, 'stage_overlap', None)}

    def hook(self, location, item, stage):
        if self.crash_hook:
            self.crash_hook(location, item['id'], stage)

    async def put(self, q, value, stage):
        await q.put(value)
        self.stats[f'peak_queue{stage}'] = max(self.stats[f'peak_queue{stage}'], q.qsize())

    def terminal(self, item, reason, status='technical_failure', facts=None):
        self.store.commit_decision(self.run_id, item['id'], dict(
            id=item['id'], operational_verdict=None, proposed_final_class=None, primary_risk=None,
            severity=None, review_status=status, review_reasons=[reason], human_status='unreviewed',
            parser=facts, stage1=self.store.stage(self.run_id, item['id'], 1),
            stage2=self.store.stage(self.run_id, item['id'], 2),
            policy_version=self.registry.policy_version, policy_sha256=self.registry.sha))

    async def call_stage(self, stage, item, data):
        store, run, cfg = self.store, self.run_id, self.config
        prior = store.stage(run, item['id'], stage)
        if prior:
            return prior
        key = stages.cache_key(stage, data, cfg, self.registry)
        if cfg.run.cache_policy == 'exact':
            cached = store.cached(key)
            if cached:
                result = stages.validate(stage, cached['result'], data, self.registry)
                meta = {'cache_hit': True, 'origin_run': cached['origin_run'], 'origin_input': cached['origin_input']}
                store.commit_stage(run, item['id'], stage, 'success', result, key, meta)
                self.stats['cache_hits'] += 1
                return store.stage(run, item['id'], stage)
        p, inf = cfg.pipeline, cfg.inference
        counts = store.counters(run, item['id'], stage)
        formats, transports = counts['format_errors'], counts['transport_errors']
        feedback = counts['last_error'] if formats else None
        error = feedback or 'provider_error'
        format_retry_pending = bool(formats)
        transport_retry_pending = bool(transports)
        maximum = getattr(inf, f'reserved_output_tokens_stage{stage}')
        while formats <= p.max_format_retries and transports <= p.max_transport_retries:
            if self.paused:
                store.state(run, item['id'], 'budget_paused')
                return None
            msg = stages.messages(stage, data, feedback)
            # UTF-8 bytes + framing/schema is a conservative tokenizer-independent bound.
            pin = len(dumps({'messages': msg, 'schema': stages.SCHEMAS[stage]}).encode()) + 512
            if pin > inf.max_input_tokens:
                error = 'input_token_limit_no_truncation'
                break
            async with self.gate.slot(stage, lambda: self.q2.qsize() >= max(1, p.queue_capacity // 2)):
                if self.paused:
                    store.state(run, item['id'], 'budget_paused')
                    return None
                try:
                    reservation = await self.limiter.reserve(pin, maximum)
                except LimitExceeded:
                    error = 'single_request_exceeds_quota'
                    break
                if self.paused:
                    store.state(run, item['id'], 'budget_paused')
                    return None
                cost = (pin * inf.input_price_per_million + maximum * inf.output_price_per_million) / 1e6
                try:
                    attempt = store.reserve(run, item['id'], stage, pin, maximum, cost)
                except BudgetExhausted:
                    self.paused = True
                    store.state(run, item['id'], 'budget_paused')
                    return None
                if format_retry_pending:
                    self.stats['format_retries'] += 1
                    format_retry_pending = False
                if transport_retry_pending:
                    self.stats['transport_retries'] += 1
                    transport_retry_pending = False
                store.state(run, item['id'], f'stage{stage}_running')
                start = time.monotonic()
                try:
                    async with asyncio.timeout(p.request_timeout_seconds):
                        response = await self.provider.complete(stage, data, msg, stages.SCHEMAS[stage], maximum)
                except (TransportError, TimeoutError) as exc:
                    code = str(exc.code) if isinstance(exc, TransportError) else 'timeout'
                    store.attempt_status(attempt, 'transport_error', code, time.monotonic()-start)
                    transports += 1
                    transport_retry_pending = True
                    error = 'provider_error:' + code
                    retryable = not isinstance(exc, TransportError) or exc.retryable
                    delay = exc.retry_after if isinstance(exc, TransportError) else None
                    if delay is None:
                        delay = p.backoff_base_seconds * 2**(transports-1) + random.random()*p.backoff_base_seconds
                    # Never shorten Retry-After. Excessive provider delay exhausts this job.
                    self.limiter.block(delay)
                    if not retryable or transports > p.max_transport_retries or delay > p.max_retry_wait_seconds:
                        break
                    store.state(run, item['id'], 'retry_wait')
                    continue
                store.settle(attempt, response, time.monotonic()-start, inf)
                self.limiter.settle(reservation, response)
                self.hook('after_response_before_commit', item, stage)
                try:
                    result = stages.validate(stage, response.content, data, self.registry)
                except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
                    # Do not echo model text or Pydantic input_value into logs/next prompts.
                    try:
                        json.loads(response.content)
                        error = 'schema_or_reference_validation'
                    except (ValueError, TypeError):
                        error = 'invalid_json'
                    store.attempt_status(attempt, 'format_error', error)
                    formats += 1
                    format_retry_pending = True
                    feedback = error
                    continue
                store.attempt_status(attempt, 'success')
                store.commit_stage(run, item['id'], stage, 'success', result, key,
                                   {'cache_hit': False, 'attempts': store.counters(run, item['id'], stage)['calls'],
                                    'prompt_sha256': digest(stages.PROMPTS[stage]), 'model_id': inf.model_id,
                                    'model_revision': inf.model_revision, 'schema_sha256': digest(stages.SCHEMAS[stage])})
                self.hook('after_stage_commit', item, stage)
                return store.stage(run, item['id'], stage)
        store.commit_stage(run, item['id'], stage, 'failure', {'reason': error}, key,
                           {'attempts': store.counters(run, item['id'], stage)['calls']})
        return store.stage(run, item['id'], stage)

    async def producer(self):
        for item in self.store.items(self.run_id, pending=True):
            item['_queued_at'] = time.monotonic()
            await self.put(self.q1, item, 1)
        for _ in range(self.config.pipeline.stage1_concurrency):
            await self.q1.put(None)

    async def stage1_worker(self):
        while True:
            item = await self.q1.get()
            try:
                if item is None:
                    return
                start = item.pop('_queued_at', time.monotonic())
                command = item['command']
                if not isinstance(command, str) or not command.strip() or '\x00' in command or len(command.encode()) > MAX_BYTES:
                    self.terminal(item, 'invalid_or_oversize_input', 'invalid_input')
                    continue
                if SECRET.search(command) or SECRET.search(dumps(item.get('context', {}))):
                    self.terminal(item, 'possible_secret', 'needs_review')
                    continue
                facts = parse(command)
                s1 = await self.call_stage(1, item, stages.payload(1, item, facts, self.registry))
                if s1 is None:
                    continue
                if s1['status'] != 'success':
                    self.terminal(item, s1['result']['reason'], facts=facts)
                    continue
                parsed = Stage1Result.model_validate(s1['result'])
                # Only skip Stage 2 when no action has an identified CAT.
                # Known risks with unknown payload/variable still require policy
                # evaluation (e.g. encoded code execution with unknown content).
                if all(not a.risks for a in parsed.actions):
                    self.store.commit_stage(self.run_id, item['id'], 2, 'skipped', {'skip_reason': 'no_identified_risk'}, '', {})
                    self.terminal(item, 'no_identified_risk', 'needs_review', facts)
                    continue
                await self.put(self.q2, (item, facts, s1, start), 2)
            finally:
                self.q1.task_done()

    async def stage2_worker(self):
        while True:
            job = await self.q2.get()
            try:
                if job is None:
                    return
                item, facts, s1, start = job
                parsed = Stage1Result.model_validate(s1['result'])
                data = stages.payload(2, item, facts, self.registry, parsed)
                s2 = await self.call_stage(2, item, data)
                if s2 is None:
                    continue
                if s2['status'] != 'success':
                    self.terminal(item, s2['result']['reason'], facts=facts)
                    continue
                decisions = materialize(s2['result'], parsed.actions, data['approved_rules_by_action'], self.registry)
                result = dict(id=item['id'], **aggregate(decisions), decisions=decisions,
                              stage1=s1, stage2=s2, parser=facts,
                              command_sha256=digest(item['command']), context_sha256=digest(item.get('context', {})),
                              policy_version=self.registry.policy_version, policy_sha256=self.registry.sha,
                              elapsed_seconds=time.monotonic()-start)
                self.store.commit_decision(self.run_id, item['id'], result)
            finally:
                self.q2.task_done()

    async def periodic_metrics(self):
        while not self.done.is_set():
            try:
                await asyncio.wait_for(self.done.wait(), timeout=self.config.run.metrics_interval_seconds)
            except TimeoutError:
                if self.output:
                    atomic_write(self.output / 'reports/metrics.json', dumps(report(self.store, self.run_id, self.elapsed_prior + time.monotonic()-self.started, self.runtime_stats())))

    async def run(self, output=None):
        self.output = Path(output) if output else None
        self.store.set_status(self.run_id, 'running')
        try:
            async with asyncio.TaskGroup() as tg:
                producer = tg.create_task(self.producer())
                first = [tg.create_task(self.stage1_worker()) for _ in range(self.config.pipeline.stage1_concurrency)]
                second = [tg.create_task(self.stage2_worker()) for _ in range(self.config.pipeline.stage2_concurrency)]
                tg.create_task(self.periodic_metrics())
                await producer
                await asyncio.gather(*first)
                for _ in second:
                    await self.q2.put(None)
                await asyncio.gather(*second)
                self.done.set()
        except BaseException:
            self.done.set()
            self.store.set_status(self.run_id, 'interrupted')
            with self.store.db:
                self.store.db.execute('UPDATE runs SET elapsed_seconds=? WHERE run_id=?', (self.elapsed_prior+time.monotonic()-self.started, self.run_id))
            raise
        with self.store.db:
            self.store.db.execute('UPDATE runs SET elapsed_seconds=? WHERE run_id=?', (self.elapsed_prior+time.monotonic()-self.started, self.run_id))
        self.store.set_status(self.run_id, 'budget_paused' if self.paused else 'completed')
        metrics = report(self.store, self.run_id, self.elapsed_prior + time.monotonic()-self.started, self.runtime_stats())
        if self.output:
            atomic_write(self.output / 'reports/metrics.json', dumps(metrics) + '\n')
        return metrics
