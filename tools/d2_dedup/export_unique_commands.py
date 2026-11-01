#!/usr/bin/env python3
"""Export exact unique command texts and lossless masked provenance, offline."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    path.chmod(0o600)


def write_jsonl(path, rows):
    with path.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    path.chmod(0o600)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def export(input_path, output):
    require(not output.exists() and not output.is_symlink(), 'output_already_exists')
    raw = input_path.read_bytes()
    rows = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
    grouped = defaultdict(list)
    origin_ids, source_ids = set(), set()
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get('command'), str) and bool(row['command']), 'invalid_input_row')
        require(row.get('source') == 'local' and row.get('seed') == '-' and row.get('annotation_status') == 'unlabeled', 'unexpected_source_or_annotation')
        require(row.get('bash_parse') == 'passed' and row.get('privacy_status') == 'automatic_filters_passed_owner_review_required', 'input_not_filtered')
        require(row['record_id'] not in source_ids, 'duplicate_source_record_id')
        require(row['occurrence_count'] == len(row['origin_ids']) == len(row['origin_observations']), 'invalid_origin_count')
        require(set(row['origin_ids']) == {o['origin_id'] for o in row['origin_observations']}, 'origin_observation_mismatch')
        require(len(set(row['origin_ids'])) == len(row['origin_ids']) and not origin_ids.intersection(row['origin_ids']), 'duplicate_native_origin')
        require(sum(row['observations'].values()) == row['occurrence_count'], 'invalid_result_counts')
        source_ids.add(row['record_id'])
        origin_ids.update(row['origin_ids'])
        grouped[row['command']].append(row)

    commands, provenance = [], []
    for command, originals in grouped.items():
        digest = sha(command.encode('utf-8'))
        record_id = 'D2_' + digest
        commands.append({
            'record_id': record_id, 'command': command, 'command_sha256': digest,
            'source': 'local', 'seed': '-', 'annotation_status': 'unlabeled',
            'privacy_status': 'automatic_filters_passed_owner_review_required',
            'providers': sorted({r['provider'] for r in originals}),
            'source_record_count': len(originals),
            'occurrence_count': sum(r['occurrence_count'] for r in originals),
        })
        provenance.append({
            'record_id': record_id, 'command_sha256': digest,
            'source_records': [{k: v for k, v in r.items() if k != 'command'}
                               for r in sorted(originals, key=lambda r: r['record_id'])],
        })
    commands.sort(key=lambda r: r['record_id'])
    provenance.sort(key=lambda r: r['record_id'])
    require(len({r['record_id'] for r in commands}) == len(commands), 'command_hash_collision')

    output.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    write_jsonl(output / 'commands.jsonl', commands)
    write_jsonl(output / 'provenance.jsonl', provenance)

    # Verify serialized artifacts by reconstructing every original record.
    saved_commands = read_jsonl(output / 'commands.jsonl')
    saved_provenance = read_jsonl(output / 'provenance.jsonl')
    by_id = {r['record_id']: r for r in saved_commands}
    reconstructed = []
    for item in saved_provenance:
        command = by_id[item['record_id']]['command']
        require(item['command_sha256'] == sha(command.encode('utf-8')), 'command_hash_mismatch')
        reconstructed.extend(dict(r, command=command) for r in item['source_records'])
    require(sorted(reconstructed, key=lambda r: r['record_id']) == sorted(rows, key=lambda r: r['record_id']), 'provenance_reconstruction_failed')
    require(len(saved_commands) == len({r['command'] for r in saved_commands}) == len(grouped), 'duplicate_export_command')
    require({r['command'] for r in saved_commands} == set(grouped), 'command_text_changed')
    require(sum(r['occurrence_count'] for r in saved_commands) == len(origin_ids), 'export_origin_count_mismatch')

    statuses, decisions = Counter(), Counter()
    for row in reconstructed:
        for origin in row['origin_observations']:
            observations = origin['source_observations']
            statuses.update({item['tool_status'] for item in observations})
            decisions.update({item['user_decision'] for item in observations})
    report = {
        'schema': 'd2-unique-commands-1', 'stage': 'exact_deduplicated_unlabeled_local_dataset',
        'input_sha256': sha(raw), 'exporter_sha256': sha(Path(__file__).read_bytes()),
        'input_records': len(rows), 'unique_commands': len(commands),
        'duplicate_records_merged': len(rows) - len(commands),
        'duplicate_text_groups': sum(len(group) > 1 for group in grouped.values()),
        'native_origins_preserved': len(origin_ids),
        'unique_commands_by_provider_inclusive': dict(Counter(p for r in commands for p in r['providers'])),
        'cursor_origins_by_source_status': dict(statuses),
        'cursor_origins_by_user_decision': dict(decisions),
        'checks': {'unique_exact_text': True, 'command_text_unchanged': True,
                   'full_source_records_reconstructed': True, 'all_native_origins_preserved': True},
        'deduplication': 'Exact command string equality, no whitespace, quoting or Unicode normalization.',
        'source': 'local', 'seed': '-', 'annotation_status': 'unlabeled', 'training_ready': False,
        'open_gates': ['final_privacy_review', 'near_duplicate_and_test_seed_fewshot_family_review', 'D3_annotation_and_split'],
        'commands_executed': False,
    }
    write_json(output / 'report.json', report)
    readme = (
        '# D2, уникальные локальные команды\n\n'
        f'{len(commands)} различных текстов команд из {len(rows)} записей, '
        f'сохранено происхождение {len(origin_ids)} исходных вызовов.\n\n'
        '`commands.jsonl` — неразмеченный датасет, одна запись на точный текст команды. '
        '`provenance.jsonl` — все исходные записи без повторения команды, связь по `record_id`. '
        'Контексты, инструменты, shell и статусы сохраняются отдельно для каждого исходного вызова. '
        'Для модели, получающей только команду, входом служит поле `command`.\n\n'
        'Текст команд не нормализован. Исходный пакет сохранён. '
        'Отчёт и контрольные суммы — `report.json` и `MANIFEST.json`.\n\n'
        'Перед разбиением D3 учитывает все связанные группы происхождения. '
        'Окончательная проверка приватности, близких повторов и пересечений с test, seeds и few-shot остаётся открытой. '
        'Финальная разметка относится к D3. `training_ready=false`.\n'
    )
    (output / 'README.md').write_text(readme, encoding='utf-8')
    (output / 'README.md').chmod(0o600)
    names = ['commands.jsonl', 'provenance.jsonl', 'report.json', 'README.md']
    write_json(output / 'MANIFEST.json', {'schema': report['schema'], 'files': {
        name: sha((output / name).read_bytes()) for name in names}})
    with zipfile.ZipFile(output / 'dataset.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names + ['MANIFEST.json']:
            archive.write(output / name, name)
    (output / 'dataset.zip').chmod(0o600)
    with zipfile.ZipFile(output / 'dataset.zip') as archive:
        require(archive.testzip() is None and set(archive.namelist()) == set(names + ['MANIFEST.json']), 'invalid_archive')
        for name in archive.namelist():
            require(archive.read(name) == (output / name).read_bytes(), 'archive_content_mismatch')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = export(args.input, args.output)
    print(json.dumps({key: result[key] for key in [
        'input_records', 'unique_commands', 'duplicate_records_merged', 'native_origins_preserved', 'checks']}))
