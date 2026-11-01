"""Recompute diagnostic reports without inference, executing no corpus commands."""
import csv
import json
from pathlib import Path
from judge.io import read_records, dump, write_jsonl
from judge.evaluate import score
from judge.compare import compare


def main():
    root=Path(__file__).resolve().parents[1]
    refs=read_records(root/'evidence/calibration_draft.jsonl'); byid={x['record_id']:x for x in refs}
    metrics=[]
    for name in ['qwen3_smoke','qwen3_4b_pilot','granite_pilot']:
        folder=root/'reports'/name; rows=read_records(folder/'results.jsonl')
        m=score(rows,refs,diagnostic=True)
        m['per_risk']={risk:score([r for r in rows if byid[r['record_id']]['risk']==risk],refs,diagnostic=True) for risk in sorted({r['risk'] for r in refs})}
        m['joint_class_risk_accuracy']=sum(bool(r['judges'][0].get('response') and r['judges'][0]['response']['predicted_class']==byid[r['record_id']]['class'] and r['judges'][0]['response']['risk']==byid[r['record_id']]['risk']) for r in rows)/len(rows)
        dump(folder/'diagnostic_metrics.json',m)
        metrics.append(dict(run=name,**{k:m[k] for k in ['n','accuracy','macro_f1','risk_accuracy','joint_class_risk_accuracy','schema_valid_rate','false_allow_on_deny','false_deny_on_allow','review_rate']}))
    dump(root/'reports/JUDGE_BENCHMARK.json',dict(kind='diagnostic_NOT_human_gold',runs=metrics,latency_comparable=False))
    with (root/'reports/JUDGE_BENCHMARK.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(metrics[0]),lineterminator="\n");writer.writeheader();writer.writerows(metrics)
    left=root/'reports/qwen3_4b_pilot';right=root/'reports/granite_pilot'
    rows,summary=compare(read_records(left/'results.jsonl'),read_records(right/'results.jsonl'),json.loads((left/'manifest.json').read_text()),json.loads((right/'manifest.json').read_text()))
    write_jsonl(root/'reports/dual_pilot/results.jsonl',rows);dump(root/'reports/dual_pilot/summary.json',summary)
    queue=[]
    for r in rows:
        queue.append(dict(record_id=r['record_id'],command=byid[r['record_id']]['command'],review_reasons=r['review_reasons'],judge_proposals=r['judges'],human_reviewed=False,human_reviewer=None,human_class=None,human_risk=None,status='pending_human_review'))
    write_jsonl(root/'reports/HUMAN_REVIEW_QUEUE.jsonl',queue)
    # Blind worksheet omits all machine/reference labels for independent adjudication.
    with (root/'reports/HUMAN_REVIEW_BLIND.csv').open('w',newline='') as f:
        fields=['record_id','command','class','risk','severity','reason','reviewer'];w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n");w.writeheader()
        w.writerows({k:r[k] for k in ['record_id','command']} for r in queue)

if __name__=='__main__':main()
