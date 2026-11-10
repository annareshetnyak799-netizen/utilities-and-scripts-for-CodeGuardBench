import csv
import json
from contextlib import ExitStack
from pathlib import Path
from .common import atomic_file, dumps, digest, now

COLUMNS = ['command', 'description', 'util', 'severity', 'category', 'risk', 'source', 'seed', 'class']


def csv_row(result, human=None):
    item = result['input']
    verdict = human or result
    risk = verdict.get('primary_risk')
    if not all((risk, verdict.get('proposed_final_class'), verdict.get('severity'))):
        return None
    metadata = item.get('metadata', {})
    source = metadata.get('source')
    seed = metadata.get('seed') or ('-' if source != 'synthetic' else '')
    if not source or not seed:
        return None  # missing provenance is never invented for a nine-column export
    actions = (result.get('stage1') or {}).get('result', {}).get('actions', [])
    description = human.get('description') if human else '; '.join(f"{a['effect']}: {a['target']}" for a in actions)
    # Use AST facts for util; do not copy label-associated input description.
    utilities = sorted({n['argv'][0] for n in (result.get('parser') or {}).get('nodes', []) if n.get('argv')})
    return dict(zip(COLUMNS, [item['command'], description or 'Human reviewed', ','.join(utilities),
                             verdict['severity'], risk.split('.')[0], risk,
                             source, seed,
                             verdict['proposed_final_class']]))


def export(store, run, output, status='proposed'):
    output = Path(output)
    for sub in ('proposals', 'needs_review', 'human_approved', 'reports'):
        (output / sub).mkdir(parents=True, exist_ok=True)
    count = review_count = csv_count = proposal_count = 0
    stem = 'human_approved' if status == 'human_approved' else 'proposals'
    csv_name = 'commands.csv' if status == 'human_approved' else 'commands_NOT_GOLD.csv'
    with ExitStack() as stack:
        all_results = stack.enter_context(atomic_file(output / 'reports/results.jsonl')) if status == 'proposed' else None
        trace = stack.enter_context(atomic_file(output / stem / 'results.jsonl'))
        csvfile = stack.enter_context(atomic_file(output / stem / csv_name))
        writer = csv.DictWriter(csvfile, fieldnames=COLUMNS)
        writer.writeheader()
        reviews = stack.enter_context(atomic_file(output / 'needs_review/results.jsonl')) if status == 'proposed' else None
        for result in store.results(run):
            human = None
            if status == 'human_approved':
                saved = store.db.execute('SELECT decision FROM human_reviews WHERE run_id=? AND input_id=?', (run, result['id'])).fetchone()
                if not saved:
                    continue
                human = json.loads(saved[0])
                result['human_review'] = human
            if all_results:
                all_results.write(dumps(result) + '\n')
            if human or result['review_status'] == 'proposed':
                trace.write(dumps(result) + '\n')
                proposal_count += 1
            count += 1
            if reviews and result['review_status'] != 'proposed':
                reviews.write(dumps(result) + '\n')
                review_count += 1
            row = csv_row(result, human)
            if row is not None and (human or result['review_status'] == 'proposed'):
                writer.writerow(row)
                csv_count += 1
    manifest = {'run_id': run, 'status': status, 'traces': count, 'review': review_count,
                'proposal_rows': proposal_count, 'csv_rows': csv_count, 'gold': status == 'human_approved', 'columns': COLUMNS}
    with store.db:
        store.db.execute('INSERT OR REPLACE INTO exports VALUES(?,?,?,?)', (run, status, dumps(manifest), now()))
    return manifest
