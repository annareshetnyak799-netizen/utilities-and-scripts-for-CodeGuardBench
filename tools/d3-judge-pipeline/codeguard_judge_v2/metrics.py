import json
import time
from collections import Counter


def quantiles(values):
    values = sorted(values)
    return {f'p{p}': values[min(len(values)-1, int((len(values)-1)*p/100))] if values else None for p in (50, 95, 99)}


def report(store, run, elapsed, runtime=None):
    rows = store.db.execute('SELECT * FROM stage_attempts WHERE run_id=?', (run,)).fetchall()
    results = [json.loads(r[0]) for r in store.db.execute('SELECT result FROM decisions WHERE run_id=?', (run,))]
    completed = len(results)
    tokens = {k: sum(r[k] or 0 for r in rows) for k in ('input_tokens', 'output_tokens', 'reasoning_tokens', 'cached_tokens')}
    minutes = max(elapsed / 60, 1e-9)
    costs = store.cost(run)
    by_risk, by_rule = Counter(), Counter()
    parser_states = Counter()
    for result in results:
        parser_states[(result.get('parser') or {}).get('parse_status', 'not_parsed')] += 1
        for action in ((result.get('stage1') or {}).get('result') or {}).get('actions', []):
            by_risk.update(action['risks'])
        by_rule.update(d['rule_id'] for d in result.get('decisions', []) if d.get('rule_id'))
    cfg = json.loads(store.run(run)['config'])['rate_limit']
    quota = {}
    for key, amount in [('requests_per_minute', len(rows)), ('input_tokens_per_minute', tokens['input_tokens']),
                        ('output_tokens_per_minute', tokens['output_tokens']),
                        ('combined_tokens_per_minute', tokens['input_tokens']+tokens['output_tokens'])]:
        quota[key] = amount/minutes/cfg[key] if cfg.get(key) else None
    by_stage = {}
    for stage in (1, 2):
        subset = [r for r in rows if r['stage'] == stage]
        by_stage[str(stage)] = dict(requests=len(subset), input_tokens=sum(r['input_tokens'] or 0 for r in subset),
                                   output_tokens=sum(r['output_tokens'] or 0 for r in subset),
                                   conservative_cost=sum(r['actual_cost'] if r['actual_cost'] is not None else r['estimated_cost'] for r in subset))
    return dict(run_id=run, completed=completed, elapsed_seconds=elapsed,
                completed_per_minute=completed/minutes, requests=len(rows), requests_per_minute=len(rows)/minutes,
                **tokens, tokens_per_minute=(tokens['input_tokens']+tokens['output_tokens'])/minutes,
                count_429=sum(r['error'] == '429' for r in rows),
                transport_errors=sum(r['status'] == 'transport_error' for r in rows),
                format_errors=sum(r['status'] == 'format_error' for r in rows),
                review_rate=sum(r['review_status'] != 'proposed' for r in results)/completed if completed else None,
                stage_latency_seconds={str(s): quantiles([r['latency'] for r in rows if r['stage'] == s and r['latency'] is not None]) for s in (1, 2)},
                e2e_latency_seconds=quantiles([r['elapsed_seconds'] for r in results if 'elapsed_seconds' in r]),
                review_reasons=dict(Counter(reason for r in results for reason in r['review_reasons'])),
                **costs, cost_per_1000_rows=costs['conservative_spend']*1000/completed if completed else None,
                actual_invoice_cost=None, human_gold_accuracy=None, semantic_validation=False,
                stages=[dict(r) for r in store.db.execute('SELECT stage,status,COUNT(*) AS count FROM stage_results WHERE run_id=? GROUP BY stage,status', (run,))],
                job_states=dict(store.db.execute('SELECT state,COUNT(*) FROM jobs WHERE run_id=? GROUP BY state', (run,)).fetchall()),
                risk_action_counts=dict(by_risk), rule_selection_counts=dict(by_rule), parser_states=dict(parser_states),
                stage_usage=by_stage, quota_utilization=quota,
                runtime=runtime or {}, at=time.time())
