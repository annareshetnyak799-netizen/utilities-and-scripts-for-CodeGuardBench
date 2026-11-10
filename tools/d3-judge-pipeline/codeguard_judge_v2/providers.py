"""Async provider boundary. HTTPX has no implicit request retries here."""
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from .common import dumps


class TransportError(Exception):
    def __init__(self, code='network', retry_after=None, retryable=True):
        super().__init__(str(code))
        self.code, self.retry_after, self.retryable = code, retry_after, retryable


@dataclass
class Response:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    model: str | None = None


def retry_after(value):
    if not value:
        return None
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return None


class HTTPProvider:
    def __init__(self, config):
        self.config = config
        c = config.inference
        url = urlsplit(c.base_url)
        if url.username or url.password or url.query or url.fragment or url.scheme not in ('http', 'https'):
            raise ValueError('endpoint must not contain credentials/query/fragment')
        if url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('remote endpoint requires HTTPS')
        key = os.environ.get(c.api_key_env)
        if not key:
            raise ValueError('configured credentials environment variable is missing')
        self.client = httpx.AsyncClient(timeout=config.pipeline.request_timeout_seconds,
                                       headers={'Authorization': 'Bearer ' + key}, follow_redirects=False)

    async def complete(self, stage, data, messages, schema, max_tokens):
        c = self.config.inference
        body = {'model': c.model_id, 'messages': messages, c.completion_token_parameter: max_tokens}
        for k in ('reasoning_effort', 'temperature', 'seed'):
            v = getattr(c, k)
            if v is not None:
                body[k] = v
        if c.structured_output == 'json_schema':
            body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': f'stage{stage}', 'strict': True, 'schema': schema}}
        elif c.structured_output == 'json_object':
            body['response_format'] = {'type': 'json_object'}
        try:
            r = await self.client.post(c.base_url.rstrip('/') + '/chat/completions', json=body)
        except (httpx.TransportError, TimeoutError) as exc:
            raise TransportError(type(exc).__name__) from None
        if r.status_code != 200:
            raise TransportError(r.status_code, retry_after(r.headers.get('Retry-After')), r.status_code == 429 or 500 <= r.status_code < 600)
        try:
            obj = r.json()
            usage = obj.get('usage') or {}
            content = obj['choices'][0]['message']['content']
            if not isinstance(content, str):
                content = ''
            def count(k):
                n = usage.get(k)
                return n if type(n) is int and n >= 0 else None
            return Response(content, count('prompt_tokens'), count('completion_tokens'),
                            (usage.get('completion_tokens_details') or {}).get('reasoning_tokens', 0),
                            (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0), obj.get('model'))
        except (ValueError, KeyError, IndexError, TypeError):
            raise TransportError('invalid_provider_envelope') from None

    async def close(self):
        await self.client.aclose()


class MockProvider:
    """Exact authored fixtures ONLY, not a semantic classifier or accuracy evidence.

    Unknown inputs yield unresolved. Never use candidate labels or regex guessing.
    Tests may inject exceptions/strings as an ordered script per (command, stage).
    """
    def __init__(self, latency=0.005, faults=None, fixtures=None):
        self.latency = latency
        self.faults = faults or {}
        self.fixtures = fixtures if fixtures is not None else json.loads((Path(__file__).parent / 'fixtures/mock.json').read_text())
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.stage_overlap = False
        self.active_stages = {1: 0, 2: 0}

    async def complete(self, stage, data, messages, schema, max_tokens):
        self.calls.append((data['command'], stage))
        self.active += 1
        self.active_stages[stage] += 1
        self.max_active = max(self.max_active, self.active)
        self.stage_overlap |= all(self.active_stages.values())
        try:
            await asyncio.sleep(self.latency)
            script = self.faults.get((data['command'], stage), [])
            if script:
                event = script.pop(0)
                if isinstance(event, BaseException):
                    raise event
                if isinstance(event, str):
                    return Response(event, 20, 10)
            fixture = self.fixtures.get(data['command'])
            if stage == 1:
                raw = fixture['stage1'] if fixture else {'actions': [{'effect': 'unknown', 'target': 'unknown', 'risks': [], 'unresolved': 'unsupported_syntax'}]}
            else:
                decisions = []
                for index, a in enumerate(data['actions']):
                    wanted = (fixture or {}).get('rules', [])
                    rid = wanted[index] if index < len(wanted) else None
                    if rid == 'G-3.1-DESTROY' and data['context'].get('environment_tier') == 'prod':
                        rid = 'G-3.1-PROD'
                    allowed = {r['id'] for r in data['approved_rules_by_action'][a['action_id']]}
                    # Replay only the explicitly authored rule if it was offered.
                    # Unknown runtime details do not veto a known mechanism.
                    chosen = rid if rid in allowed else None
                    decisions.append(dict(action_id=a['action_id'], rule_id=chosen,
                                          review_reason=None if chosen else ('missing_context' if a['unresolved'] else 'policy_gap'),
                                          note='Authored offline fixture; not human gold.'))
                raw = {'decisions': decisions}
            content = dumps(raw)
            return Response(content, len(dumps(messages).encode()) // 4 + 1, len(content.encode()) // 4 + 1, model='mock-fixtures-v1')
        finally:
            self.active -= 1
            self.active_stages[stage] -= 1

    async def close(self):
        pass
