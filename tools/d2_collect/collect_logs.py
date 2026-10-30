#!/usr/bin/env python3
"""Local-only D2 intake, native terminal requests to masked, unlabeled JSONL.

Sources are untrusted data. This program never runs their commands. It does
not read account/config tables, transmit data, infer safety labels or unwrap JS.
"""
import argparse
import csv
import hashlib
import json
import os
import platform
import re
import sqlite3
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

VERSION = '0.2.0'
SCHEMA = 'd2-intake-2'
MAX_LINE = 16 * 1024 * 1024
MAX_COMMAND = 256 * 1024
TERMINAL_NAMES = {'run_terminal_cmd', 'run_terminal_command', 'run_terminal_cmd_v2'}


def sha(content):
    return hashlib.sha256(content).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    path.chmod(0o600)


def dependency_versions():
    wanted = {'tree-sitter': '0.25.2', 'tree-sitter-bash': '0.25.1', 'detect-secrets': '1.5.0'}
    for package, expected in wanted.items():
        if version(package) != expected:
            raise RuntimeError('dependency_version_mismatch')
    return wanted


def walk_files(root, pattern):
    if not root.is_dir() or root.is_symlink():
        return
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if path.match(pattern) and not path.is_symlink() and path.is_file():
                yield path


def cursor_directory(home):
    if sys.platform == 'darwin':
        return home / 'Library/Application Support/Cursor/User'
    if os.name == 'nt':
        return Path(os.environ.get('APPDATA', home / 'AppData/Roaming')) / 'Cursor/User'
    return Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / 'Cursor/User'


def discover(home, providers, cursor_root=None):
    sources = []
    for provider, roots in [
        ('codex', [home / '.codex/sessions', home / '.codex/archived_sessions']),
        ('claude', [home / '.claude/projects']),
    ]:
        if provider in providers:
            for root in roots:
                for path in walk_files(root, '*.jsonl'):
                    sources.append({'provider': provider, 'path': path, 'size': path.stat().st_size})
    if 'cursor' in providers:
        base = cursor_root or cursor_directory(home)
        for subdir in ['globalStorage', 'workspaceStorage']:
            for path in walk_files(base / subdir, 'state.vscdb'):
                sources.append({'provider': 'cursor', 'path': path, 'size': path.stat().st_size})
    return sources


def stream_jsonl(source, counts, manifest):
    """Read only the original byte range, hash what was actually read."""
    consumed, line_number, digest = 0, 0, hashlib.sha256()
    with source['path'].open('rb') as handle:
        while consumed < source['size']:
            offset = consumed
            line = handle.readline(min(MAX_LINE + 1, source['size'] - consumed))
            if not line:
                counts['source_shrank'] += 1
                break
            consumed += len(line)
            digest.update(line)
            line_number += 1
            too_large = len(line) > MAX_LINE
            complete = line.endswith(b'\n')
            while not complete and consumed < source['size']:
                chunk = handle.readline(min(MAX_LINE, source['size'] - consumed))
                if not chunk:
                    break
                consumed += len(chunk)
                digest.update(chunk)
                too_large = True
                complete = chunk.endswith(b'\n')
            if not complete:
                counts['incomplete_tail'] += 1
                break
            if too_large:
                counts['oversized_json_line'] += 1
                continue
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                counts['invalid_json_line'] += 1
                continue
            if isinstance(event, dict):
                yield event, {'line': line_number, 'byte_offset': offset}
            else:
                counts['non_object_json'] += 1
    manifest.update(read_bytes=consumed, read_prefix_sha256=digest.hexdigest(), lines_seen=line_number)


def terminal_event(provider, session, call_id, command, cwd, shell, coord, tool, **extra):
    return dict(kind='call', provider=provider, session=session, call_id=call_id,
                command=command, cwd=cwd, shell=shell, coord=coord, tool=tool, **extra)


def cursor_evidence(tool):
    def enum(field, allowed):
        value = tool.get(field)
        if value is None:
            return 'absent'
        return value if isinstance(value, str) and value in allowed else 'unknown'
    return {
        'tool_status': enum('status', {'completed', 'cancelled', 'error', 'running', 'pending', 'success', 'done'}),
        'user_decision': enum('userDecision', {'accepted', 'rejected', 'approved', 'denied', 'allowed'}),
        'result_present': 'result' in tool and tool['result'] is not None,
    }


def jsonl_events(source, counts, manifest):
    provider = source['provider']
    session, cwd = str(source['path']), None
    for event, coord in stream_jsonl(source, counts, manifest):
        if provider == 'codex':
            payload = event.get('payload', {})
            if not isinstance(payload, dict):
                continue
            if event.get('type') == 'session_meta':
                client = payload.get('cli_version', '')
                if isinstance(client, str) and re.fullmatch(r'[0-9][0-9A-Za-z.+_-]{0,50}', client):
                    manifest['client_versions'] = sorted(set(manifest.get('client_versions', []) + [client]))
                session = payload.get('id') or payload.get('session_id') or session
                cwd = payload.get('cwd') or cwd
                continue
            if event.get('type') != 'response_item':
                continue
            name = str(payload.get('name', '')).split('.')[-1]
            if payload.get('type') == 'custom_tool_call' and name == 'exec':
                counts['unsupported_codex_js_wrapper'] += 1
                continue
            if payload.get('type') == 'function_call_output':
                yield dict(kind='result', provider=provider, session=session,
                           call_id=payload.get('call_id'), state='tool_result_observed')
                continue
            if payload.get('type') != 'function_call' or name not in {'exec_command', 'shell_command'}:
                continue
            try:
                args = payload.get('arguments', {})
                args = json.loads(args) if isinstance(args, str) else args
            except ValueError:
                counts['invalid_or_encrypted_tool_arguments'] += 1
                continue
            if not isinstance(args, dict):
                counts['invalid_tool_arguments'] += 1
                continue
            yield terminal_event(provider, session, payload.get('call_id') or payload.get('id'),
                                 args.get('cmd') if name == 'exec_command' else args.get('command'),
                                 args.get('workdir') or args.get('cwd') or cwd,
                                 args.get('shell', 'unknown'), coord, name)
        else:
            client = event.get('version', '')
            if isinstance(client, str) and re.fullmatch(r'[0-9][0-9A-Za-z.+_-]{0,50}', client):
                manifest['client_versions'] = sorted(set(manifest.get('client_versions', []) + [client]))
            session = event.get('sessionId') or session
            cwd = event.get('cwd') or cwd
            message = event.get('message', {})
            if not isinstance(message, dict) or not isinstance(message.get('content'), list):
                continue
            for block in message['content']:
                if not isinstance(block, dict):
                    continue
                if event.get('type') == 'user' and block.get('type') == 'tool_result':
                    yield dict(kind='result', provider=provider, session=session,
                               call_id=block.get('tool_use_id'), state='tool_error' if block.get('is_error') is True else 'tool_result_observed')
                if event.get('type') != 'assistant' or message.get('role') != 'assistant' or block.get('type') != 'tool_use' or block.get('name') != 'Bash':
                    if block.get('type') == 'tool_use' and block.get('name') == 'Bash':
                        counts['claude_bash_blocks_wrong_or_unknown_role'] += 1
                    continue
                args = block.get('input', {})
                yield terminal_event(provider, session, block.get('id'),
                                     args.get('command') if isinstance(args, dict) else None,
                                     cwd, 'bash_tool', coord, 'Bash')


def open_database(path):
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    con.execute('PRAGMA query_only=ON')
    con.execute('BEGIN')
    return con


def cursor_projects(sources, counts):
    mapping = {}
    for source in sources:
        if source['provider'] != 'cursor':
            continue
        workspace = source['path'].parent / 'workspace.json'
        if not workspace.is_file() or workspace.is_symlink() or workspace.stat().st_size > 1024 * 1024:
            continue
        try:
            info = json.loads(workspace.read_text(encoding='utf-8'))
            if not isinstance(info, dict) or not isinstance(info.get('folder', ''), str):
                counts['cursor_workspace_mapping_unavailable'] += 1
                continue
            location = urlparse(info.get('folder', ''))
            if location.scheme != 'file' or location.netloc not in {'', 'localhost'}:
                continue
            root = url2pathname(location.path)
            con = open_database(source['path'])
            try:
                row = con.execute("SELECT value FROM ItemTable WHERE key='composer.composerData'").fetchone()
                data = json.loads(row[0]) if row else {}
                if not isinstance(data, dict) or not isinstance(data.get('allComposers', []), list):
                    counts['cursor_workspace_mapping_unavailable'] += 1
                    continue
                for item in data.get('allComposers', []):
                    if isinstance(item, dict) and isinstance(item.get('composerId'), str):
                        cid = item['composerId']
                        if cid not in mapping:
                            mapping[cid] = root
                        elif mapping[cid] != root:
                            mapping[cid] = None
            finally:
                con.rollback()
                con.close()
        except (OSError, ValueError, TypeError, sqlite3.Error):
            counts['cursor_workspace_mapping_unavailable'] += 1
    return mapping


def cursor_events(source, mapping, counts, manifest):
    digest, total = hashlib.sha256(), 0
    con = open_database(source['path'])
    try:
        tables = {x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'cursorDiskKV' not in tables:
            counts['unsupported_cursor_database'] += 1
            return
        for key, length in con.execute("SELECT key,length(value) FROM cursorDiskKV WHERE key LIKE 'bubbleId:%' AND length(value)>?", (MAX_LINE,)):
            counts['oversized_cursor_bubble'] += 1
        query = "SELECT key,value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%' AND length(value)<=? ORDER BY key"
        for key, value in con.execute(query, (MAX_LINE,)):
            if not isinstance(value, (str, bytes)):
                counts['invalid_cursor_bubble'] += 1
                continue
            raw = value.encode() if isinstance(value, str) else value
            digest.update(str(key).encode() + b'\0' + raw + b'\0')
            total += 1
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                counts['invalid_cursor_bubble'] += 1
                continue
            if not isinstance(data, dict):
                continue
            tool = data.get('toolFormerData')
            if data.get('type') != 2 or not isinstance(tool, dict) or not isinstance(tool.get('name'), str) or tool['name'] not in TERMINAL_NAMES:
                continue
            counts['cursor_native_terminal_objects'] += 1
            if type(data.get('_v')) is not int or data['_v'] not in {2, 3}:
                counts['unsupported_cursor_version'] += 1
                continue
            try:
                args = tool.get('params')
                args = json.loads(args) if isinstance(args, str) else args
            except ValueError:
                counts['invalid_cursor_params'] += 1
                continue
            if not isinstance(args, dict):
                counts['missing_cursor_params'] += 1
                continue
            parts = key.split(':')
            if len(parts) != 3:
                counts['unsupported_cursor_bubble_key'] += 1
                continue
            session = parts[1]
            yield terminal_event('cursor', session, tool.get('toolCallId'), args.get('command'),
                                 args.get('cwd') or mapping.get(session), 'unknown', {'table': 'cursorDiskKV', 'key': key},
                                 tool['name'], object_version=data['_v'], evidence=cursor_evidence(tool))
    finally:
        con.rollback()
        con.close()
        manifest.update(selected_rows=total, selected_rows_sha256=digest.hexdigest(), snapshot='read_only_transaction')


def source_roots(sources, mapping):
    roots = set(value for value in mapping.values() if isinstance(value, str))
    for source in sources:
        if source['provider'] == 'cursor':
            continue
        try:
            with source['path'].open('rb') as handle:
                # Metadata only, do not mine arbitrary user text for paths.
                for unused in range(20):
                    line = handle.readline(1024 * 1024)
                    if not line or len(line) == 1024 * 1024:
                        break
                    event = json.loads(line)
                    candidate = event.get('payload', {}).get('cwd') if event.get('type') == 'session_meta' else event.get('cwd')
                    if isinstance(candidate, str):
                        roots.add(candidate)
        except (OSError, ValueError, AttributeError):
            continue
    return roots


def excluded_project(cwd, exclusions):
    if not isinstance(cwd, str):
        return False
    path = Path(cwd)
    for item in exclusions:
        if '/' not in item and '\\' not in item:
            if item.casefold() in {part.casefold() for part in path.parts}:
                return True
        elif path == Path(item) or Path(item) in path.parents:
            return True
    return False


def collect(args):
    from privacy import Masker, Quarantine, pseudonym
    dependencies = dependency_versions()
    home = args.home.expanduser().resolve()
    output = args.output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise RuntimeError('output_already_exists')
    profile = json.loads(args.profile.read_text(encoding='utf-8')) if args.profile else {}
    if not isinstance(profile, dict) or any(not isinstance(profile.get(k, []), list) for k in ['person_names', 'private_literals']) or any(not isinstance(x, str) for key in ['person_names', 'private_literals'] for x in profile.get(key, [])):
        raise RuntimeError('invalid_profile')
    sources = discover(home, args.providers.split(','), args.cursor_user_dir)
    # Input sizes are frozen before this run creates any result artifacts.
    if not sources:
        raise RuntimeError('no_sources_found')
    output.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    private = output / 'private'
    share = output / 'share'
    private.mkdir(mode=0o700)
    share.mkdir(mode=0o700)
    key = args.key_file.read_bytes() if args.key_file else os.urandom(32)
    if len(key) != 32:
        raise RuntimeError('invalid_key_length')
    (private / 'key.bin').write_bytes(key)
    (private / 'key.bin').chmod(0o600)
    encode = lambda kind, value: pseudonym(key, kind, value)
    counts, rejects, edits = Counter(), Counter(), Counter()
    provider_counts = {name: Counter() for name in ['codex', 'claude', 'cursor']}
    source_cursor_statuses, source_cursor_decisions = Counter(), Counter()
    mapping = cursor_projects(sources, counts)
    masker = Masker(key, home, source_roots(sources, mapping), profile)
    protected = set()
    for path in args.exclude_csv:
        with path.open(newline='', encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                if not isinstance(row.get('command'), str):
                    raise RuntimeError('invalid_exclusion_csv')
                protected.add(sha(row['command'].encode()))
    database = sqlite3.connect(private / 'intake.sqlite')
    database.execute('CREATE TABLE calls (id TEXT PRIMARY KEY, raw_hmac TEXT, data TEXT, conflict INTEGER DEFAULT 0, state TEXT DEFAULT "request_observed")')
    database.execute('CREATE TABLE outcomes (id TEXT PRIMARY KEY, state TEXT)')
    database.execute('CREATE TABLE seen_events (id TEXT PRIMARY KEY, raw_hmac TEXT)')
    database.execute('CREATE TABLE evidence (id TEXT, data TEXT, PRIMARY KEY(id,data))')
    (private / 'intake.sqlite').chmod(0o600)
    origin_handle = (private / 'origins.jsonl').open('w', encoding='utf-8')
    quarantine_handle = (private / 'quarantine.jsonl').open('w', encoding='utf-8')
    for path in [private / 'origins.jsonl', private / 'quarantine.jsonl']:
        path.chmod(0o600)
    source_manifests = []
    for source in sources:
        provider = source['provider']
        source_id = encode('SOURCE', str(source['path']))
        manifest = {'provider': provider, 'path': str(source['path']), 'source_id': source_id, 'bytes_at_discovery': source['size']}
        try:
            events = cursor_events(source, mapping, counts, manifest) if provider == 'cursor' else jsonl_events(source, counts, manifest)
            for event in events:
                call_id = encode('CALL', provider + '\0' + str(event['session']) + '\0' + str(event.get('call_id')))
                if event['kind'] == 'result':
                    if event.get('call_id'):
                        database.execute('INSERT OR REPLACE INTO outcomes VALUES (?,?)', (call_id, event['state']))
                    continue
                counts['native_requests_seen'] += 1
                provider_counts[provider]['native_requests_seen'] += 1
                origin = {'origin_id': call_id, 'source_id': source_id, 'provider': provider,
                          'session': str(event['session']), 'tool_call_id': event.get('call_id'),
                          'cwd': event.get('cwd'), 'coordinate': event['coord']}
                if event.get('evidence'):
                    origin['source_observation'] = event['evidence']
                    source_cursor_statuses[event['evidence']['tool_status']] += 1
                    source_cursor_decisions[event['evidence']['user_decision']] += 1
                origin_handle.write(json.dumps(origin, ensure_ascii=False) + '\n')
                try:
                    command = event['command']
                    if not isinstance(command, str):
                        raise Quarantine('missing_literal_command')
                    if not event.get('call_id'):
                        raise Quarantine('missing_native_call_id')
                    if not isinstance(event['call_id'], str) or not isinstance(event['session'], str) or not isinstance(event.get('shell'), str) or (event.get('cwd') is not None and not isinstance(event['cwd'], str)):
                        raise Quarantine('invalid_native_metadata_types')
                    raw_hmac = encode('RAW', command + '\0' + str(event.get('cwd')) + '\0' + event['shell'])
                    if event.get('evidence'):
                        database.execute('INSERT OR IGNORE INTO evidence VALUES (?,?)',
                                         (call_id, json.dumps(event['evidence'], sort_keys=True)))
                    previous = database.execute('SELECT raw_hmac FROM seen_events WHERE id=?', (call_id,)).fetchone()
                    if previous:
                        if previous[0] != raw_hmac:
                            database.execute('UPDATE calls SET conflict=1 WHERE id=?', (call_id,))
                            raise Quarantine('native_call_id_conflict')
                        counts['duplicate_native_events'] += 1
                        continue
                    database.execute('INSERT INTO seen_events VALUES (?,?)', (call_id, raw_hmac))
                    if excluded_project(event.get('cwd'), args.exclude_project):
                        raise Quarantine('excluded_project')
                    if len(command.encode('utf-8', 'surrogatepass')) > args.max_command_bytes:
                        raise Quarantine('oversized_command')
                    if sha(command.encode('utf-8', 'surrogatepass')) in protected:
                        raise Quarantine('exact_protected_test_command')
                    masked, changes, complexity = masker.mask(command)
                    shell = event['shell'] if isinstance(event['shell'], str) and event['shell'] in {'bash_tool', 'bash', '/bin/bash', '/usr/bin/bash', 'sh', '/bin/sh', 'zsh', '/bin/zsh', 'unknown'} else 'other'
                    record = {'origin_id': call_id, 'command': masked, 'source': 'local', 'seed': '-',
                              'provider': provider, 'tool_name': event['tool'],
                              'source_schema': 'cursor-bubble-' + str(event.get('object_version')) if provider == 'cursor' else 'claude-assistant-tool-use' if provider == 'claude' else 'codex-response-item-function-call',
                              'group_id': encode('GROUP', provider + '\0' + str(event['session'])),
                              'workspace_hint_id': encode('CONTEXT', event.get('cwd') or 'unknown'),
                              'shell': shell, 'bash_parse': 'passed',
                              'shell_status': 'bash_tool' if shell == 'bash_tool' else 'explicit' if shell != 'unknown' else 'unknown',
                              'shell_evidence': 'tool_contract' if shell == 'bash_tool' else 'request_argument_or_unknown',
                              'masking_kinds': changes, 'complexity': complexity,
                              'annotation_status': 'unlabeled', 'privacy_status': 'automatic_filters_passed_owner_review_required'}
                    database.execute('INSERT INTO calls(id,raw_hmac,data) VALUES (?,?,?)', (call_id, raw_hmac, json.dumps(record, ensure_ascii=False)))
                    edits.update(changes)
                    provider_counts[provider]['accepted_unique_native_requests'] += 1
                except Quarantine as exc:
                    reason = str(exc)
                    rejects[reason] += 1
                    provider_counts[provider]['quarantined_requests'] += 1
                    quarantine_handle.write(json.dumps({'origin_id': call_id, 'source_id': source_id, 'reason': reason}) + '\n')
        except (OSError, sqlite3.Error) as exc:
            counts['unreadable_sources'] += 1
            manifest['error_type'] = type(exc).__name__
        source_manifests.append(manifest)
        database.commit()
        print(json.dumps({'progress': len(source_manifests), 'sources': len(sources), 'native_requests': counts['native_requests_seen']}, ensure_ascii=False), file=sys.stderr)
    origin_handle.close()
    quarantine_handle.close()
    masker.close()
    database.execute('UPDATE calls SET state=COALESCE((SELECT state FROM outcomes WHERE outcomes.id=calls.id),state)')
    database.commit()
    grouped = {}
    cursor_statuses, cursor_decisions = Counter(), Counter()
    for call_id, data, state in database.execute('SELECT id,data,state FROM calls WHERE conflict=0 ORDER BY id'):
        record = json.loads(data)
        identity = (record['command'], record['group_id'], record['workspace_hint_id'], record['shell'])
        if identity not in grouped:
            record['record_id'] = encode('RECORD', '\0'.join(identity))
            record['origin_ids'] = []
            record['observations'] = Counter()
            record['origin_observations'] = []
            grouped[identity] = record
        merged = grouped[identity]
        merged['origin_ids'].append(call_id)
        merged['observations'][state] += 1
        evidence = [json.loads(item[0]) for item in database.execute('SELECT data FROM evidence WHERE id=? ORDER BY data', (call_id,))]
        merged['origin_observations'].append({'origin_id': call_id, 'result_state': state,
                                              'source_observations': evidence})
        if record['provider'] == 'cursor':
            cursor_statuses.update({item['tool_status'] for item in evidence})
            cursor_decisions.update({item['user_decision'] for item in evidence})
    records_path = share / 'commands.jsonl'
    with records_path.open('w', encoding='utf-8') as handle:
        for record in sorted(grouped.values(), key=lambda r: r['record_id']):
            record.pop('origin_id', None)
            record['occurrence_count'] = len(record['origin_ids'])
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    records_path.chmod(0o600)
    conflicts = database.execute('SELECT COUNT(*) FROM calls WHERE conflict=1').fetchone()[0]
    database.close()
    counts['conflicted_calls_excluded'] = conflicts
    counts['handoff_records'] = len(grouped)
    counts['handoff_native_origins'] = sum(len(record['origin_ids']) for record in grouped.values())
    counts['exact_command_repeats_grouped_within_context'] = counts['handoff_native_origins'] - len(grouped)
    report = {'schema': SCHEMA, 'collector_version': VERSION,
              'created_utc': datetime.now(timezone.utc).isoformat(),
              'participant_id': encode('PARTICIPANT', 'owner'),
              'stage': 'masked_unlabeled_intake_for_further_filtering', 'training_ready': False,
              'completeness': 'partial_source_read_errors' if counts['unreadable_sources'] or counts['source_shrank'] else 'supported_native_formats_only',
              'owner_review_required_before_sending': True, 'source': 'local', 'seed': '-',
              'dependencies': dependencies, 'python': platform.python_version(),
              'collector_code_sha256': {name: sha((Path(__file__).parent / name).read_bytes()) for name in ['collect_logs.py', 'privacy.py']},
              'source_files': dict(Counter(s['provider'] for s in sources)),
              'counts': dict(counts), 'quarantine_reasons': dict(rejects),
              'provider_counts': {k: dict(v) for k, v in provider_counts.items()},
              'cursor_native_origins_by_source_status': dict(cursor_statuses),
              'cursor_native_origins_by_user_decision': dict(cursor_decisions),
              'cursor_source_requests_by_status': dict(source_cursor_statuses),
              'cursor_source_requests_by_user_decision': dict(source_cursor_decisions),
              'masking_operations': dict(edits), 'raw_logs_copied': False,
              'network_verification': False, 'commands_executed': False,
              'limitations': ['Automatic masking is not a guarantee that all sensitive data was found.',
                             'Unknown shell stays unknown, Bash parse is not execution evidence.',
                             'Source status, user decision and result presence are evidence only, not proof of execution or a safety label. Multiple snapshots may overlap.',
                             'Codex JavaScript wrappers are counted and excluded.',
                             'Deduplication is exact within session/workspace/shell, semantic dedup and test-family checks are downstream.',
                             'Session grouping does not yet merge cross-session forks.'],
              'commands_file': {'path': 'commands.jsonl', 'records': len(grouped), 'sha256': sha(records_path.read_bytes())}}
    write_json(share / 'report.json', report)
    write_json(private / 'source-manifest.json', source_manifests)
    write_json(private / 'run-config.json', {'exclude_projects': args.exclude_project, 'excluded_csv_files': [str(p) for p in args.exclude_csv],
                                            'profile_sha256': sha(args.profile.read_bytes()) if args.profile else None})
    write_json(share / 'MANIFEST.json', {'schema': SCHEMA, 'files': {p.name: sha(p.read_bytes()) for p in [records_path, share / 'report.json']}})
    archive = output / 'handoff.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as handle:
        for name in ['commands.jsonl', 'report.json', 'MANIFEST.json']:
            handle.write(share / name, name)
    archive.chmod(0o600)
    with zipfile.ZipFile(archive) as handle:
        if handle.testzip() is not None or set(handle.namelist()) != {'commands.jsonl', 'report.json', 'MANIFEST.json'}:
            raise RuntimeError('invalid_handoff_archive')
        for name in ['commands.jsonl', 'report.json', 'MANIFEST.json']:
            if handle.read(name) != (share / name).read_bytes():
                raise RuntimeError('handoff_checksum_mismatch')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['discover', 'collect'])
    parser.add_argument('--home', type=Path, default=Path.home(), help='Own profile root, default current home')
    parser.add_argument('--providers', default='codex,claude,cursor')
    parser.add_argument('--cursor-user-dir', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--key-file', type=Path, help='Optional previous private/key.bin for stable pseudonyms')
    parser.add_argument('--exclude-project', action='append', default=[])
    parser.add_argument('--exclude-csv', action='append', default=[], type=Path)
    parser.add_argument('--max-command-bytes', type=int, default=MAX_COMMAND)
    args = parser.parse_args(argv)
    if not set(args.providers.split(',')) <= {'codex', 'claude', 'cursor'}:
        parser.error('unknown provider')
    if args.action == 'discover':
        found = discover(args.home.expanduser().resolve(), args.providers.split(','), args.cursor_user_dir)
        print(json.dumps({'source_files': dict(Counter(s['provider'] for s in found)),
                          'bytes': dict((name, sum(s['size'] for s in found if s['provider'] == name)) for name in ['codex', 'claude', 'cursor'])}))
        return 0
    if args.output is None:
        parser.error('collect requires --output pointing to a new private directory')
    try:
        report = collect(args)
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(json.dumps({'error': type(exc).__name__, 'status': 'failed_no_verified_handoff',
                          'note': 'Check local inputs and dependencies. No raw source text is printed.'}), file=sys.stderr)
        return 2
    print(json.dumps({'status': 'intake_created_owner_review_required', 'records': report['counts']['handoff_records'],
                      'quarantine_reasons': report['quarantine_reasons'], 'training_ready': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
