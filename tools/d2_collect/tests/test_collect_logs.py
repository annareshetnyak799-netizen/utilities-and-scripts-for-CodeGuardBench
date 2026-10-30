import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect_logs as collector
from privacy import Masker, Quarantine


class MaskingTests(unittest.TestCase):
    def setUp(self):
        self.masker = Masker(b'a' * 32, Path('/Users/alice'), ['/Users/alice/My Project'])

    def tearDown(self):
        self.masker.close()

    def test_plain_command_unchanged(self):
        self.assertEqual(self.masker.mask('git status --short')[0], 'git status --short')

    def test_credentials_in_quotes(self):
        value, changes, unused = self.masker.mask('PASSWORD="hunter2"; printf "%s" "$PASSWORD"')
        self.assertNotIn('hunter2', value)
        self.assertIn('"$PASSWORD"', value)
        self.assertIn('SECRET', changes)

    def test_cli_credential(self):
        value = self.masker.mask('client --token=abc12345')[0]
        self.assertNotIn('abc12345', value)
        self.assertIn('--token=', value)

    def test_bearer_and_url(self):
        value = self.masker.mask('curl -H "Authorization: Bearer AbCdEf123456" https://private.host.test/api')[0]
        self.assertNotIn('AbCdEf123456', value)
        self.assertNotIn('private.host.test', value)
        self.assertIn('https://', value)

    def test_basic_auth(self):
        value = self.masker.mask('curl -u alice:hunter2 https://example.com')[0]
        self.assertNotIn('alice', value)
        self.assertNotIn('hunter2', value)

    def test_url_credentials(self):
        value = self.masker.mask('curl https://bob:abc12345@internal.test/path')[0]
        self.assertNotIn('bob', value)
        self.assertNotIn('abc12345', value)
        self.assertIn('https://MASK_', value)

    def test_private_path_preserves_unquoted_spaces(self):
        value = self.masker.mask('ls /Users/alice/My Project/file.txt')[0]
        self.assertNotIn('alice', value)
        self.assertNotIn('Project', value)
        self.assertEqual(value.count(' '), 2)

    def test_protected_paths_not_masked(self):
        command = 'dd if=/dev/zero of=/dev/sdb bs=512 count=1'
        self.assertEqual(self.masker.mask(command)[0], command)

    def test_multiline_and_heredoc_retained(self):
        command = "cat <<'END'\nhello\nEND\nprintf done\n"
        value, unused, complexity = self.masker.mask(command)
        self.assertEqual(value, command)
        self.assertTrue(complexity['heredoc'])
        self.assertTrue(complexity['multiline'])

    def test_nested_substitution_is_not_run(self):
        command = 'printf "%s" "$(printf inner)" | cat'
        value, unused, flags = self.masker.mask(command)
        self.assertEqual(value, command)
        self.assertTrue(flags['pipeline'])
        self.assertTrue(flags['nested_substitution'])

    def test_dynamic_sensitive_value_quarantined(self):
        with self.assertRaisesRegex(Quarantine, 'sensitive_expression'):
            self.masker.mask('PASSWORD="$(unknown)-literal"; echo done')

    def test_partial_quoted_credential_never_exported(self):
        for command in ['TOKEN="abc"suffix', 'client --token="abc"suffix', 'TOKEN="abc"${OTHER}']:
            with self.assertRaisesRegex(Quarantine, 'sensitive_concatenation'):
                self.masker.mask(command)

    def test_credential_in_embedded_language_requires_review(self):
        with self.assertRaisesRegex(Quarantine, 'embedded_language'):
            self.masker.mask('python3 -c \'password = "abc" "suffix"\'')

    def test_simple_sensitive_reference_is_preserved(self):
        command = 'TOKEN="$OTHER_TOKEN"; echo ready'
        self.assertEqual(self.masker.mask(command)[0], command)

    def test_binding_cannot_be_masked(self):
        with self.assertRaisesRegex(Quarantine, 'binding'):
            self.masker.mask('alice=1; echo "$alice"')

    def test_key_material_quarantined(self):
        with self.assertRaisesRegex(Quarantine, 'private_key'):
            self.masker.mask("printf '%s' '-----BEGIN PRIVATE KEY-----'")

    def test_invalid_bash_quarantined(self):
        with self.assertRaisesRegex(Quarantine, 'bash_parse_error'):
            self.masker.mask('echo "unterminated')

    def test_ipv6_quarantined(self):
        with self.assertRaisesRegex(Quarantine, 'ipv6'):
            self.masker.mask('ping 2001:4860:4860::8888')

    def test_private_ip_requires_review(self):
        with self.assertRaisesRegex(Quarantine, 'ipv4_literal_requires_review'):
            self.masker.mask('ping 192.168.12.7')

    def test_loopback_unchanged(self):
        self.assertEqual(self.masker.mask('curl http://127.0.0.1:8000')[0], 'curl http://127.0.0.1:8000')

    def test_encoded_identity_quarantined(self):
        with self.assertRaisesRegex(Quarantine, 'residual_private_identifier'):
            self.masker.mask('echo /Users%2Falice%2Fnotes')

    def test_ssh_account_and_host(self):
        value = self.masker.mask('ssh deploy@production uptime')[0]
        self.assertNotIn('deploy', value)
        self.assertNotIn('production', value)
        self.assertIn('@MASK_', value)

    def test_username_option_masked(self):
        value = self.masker.mask('client --username bob')[0]
        self.assertNotIn('bob', value)
        self.assertIn('--username MASK_', value)

    def test_known_secret_mask_stable(self):
        one = self.masker.mask('TOKEN=abc12345')[0]
        two = self.masker.mask('TOKEN=abc12345')[0]
        self.assertEqual(one, two)

    def test_network_not_used(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network_used')):
            self.masker.mask('PASSWORD="hunter2"; echo ready')

    def test_input_allowlist_comment_does_not_bypass_detector(self):
        command = 'export MY_UNKNOWN_CREDENTIAL="aB3dE5gH7jK9mN2pQ4sT6vW8yZ0cF1r"'
        for suffix in ['', ' # pragma: allowlist secret']:
            with self.assertRaises(Quarantine):
                self.masker.mask(command + suffix)


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='d2-fixture-')
        self.root = Path(self.temp.name)
        self.home = self.root / 'alice'
        self.codex = self.home / '.codex/sessions/session.jsonl'
        self.codex.parent.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def write_events(self, events, path=None):
        path = path or self.codex
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(event) + '\n' for event in events))

    def call(self, command, call_id='one', **extra):
        return {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'exec_command',
                'call_id': call_id, 'arguments': json.dumps({'cmd': command, **extra})}}

    def run_intake(self, **kwargs):
        args = dict(home=self.home, output=self.root / 'out', profile=None, providers='codex,claude,cursor',
                    cursor_user_dir=self.root / 'cursor', key_file=None, exclude_project=[], exclude_csv=[], max_command_bytes=collector.MAX_COMMAND)
        args.update(kwargs)
        with contextlib.redirect_stderr(io.StringIO()):
            report = collector.collect(SimpleNamespace(**args))
        rows = [json.loads(line) for line in (args['output'] / 'share/commands.jsonl').read_text().splitlines()]
        return report, rows

    def test_native_only_not_examples_or_results(self):
        self.write_events([
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'text': 'rm -rf /'}]}},
            {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'none', 'output': 'rm -rf /'}},
            {'type': 'event_msg', 'payload': self.call('rm -rf /')['payload']},
            self.call('git status'),
        ])
        unused, rows = self.run_intake()
        self.assertEqual([r['command'] for r in rows], ['git status'])

    def test_js_wrapper_counted_not_evaluated(self):
        self.write_events([{'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'exec', 'input': 'tools.exec_command({cmd:"rm -rf /"})'}}, self.call('pwd')])
        report, rows = self.run_intake()
        self.assertEqual(report['counts']['unsupported_codex_js_wrapper'], 1)
        self.assertEqual(len(rows), 1)

    def test_command_never_executed(self):
        sentinel = self.root / 'MUST_NOT_EXIST'
        self.write_events([self.call(f'touch {sentinel}')])
        self.run_intake()
        self.assertFalse(sentinel.exists())

    def test_claude_role_required(self):
        path = self.home / '.claude/projects/p/session.jsonl'
        block = {'type': 'tool_use', 'name': 'Bash', 'id': 'claude-one', 'input': {'command': 'pwd'}}
        self.write_events([
            {'type': 'user', 'message': {'role': 'user', 'content': [block]}},
            {'type': 'assistant', 'message': {'role': 'assistant', 'content': [block]}},
        ], path)
        unused, rows = self.run_intake()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['provider'], 'claude')

    def test_conflicting_call_excludes_first_even_if_second_private(self):
        self.write_events([self.call('pwd'), self.call('PASSWORD="$(unknown)-literal"')])
        report, rows = self.run_intake()
        self.assertEqual(rows, [])
        self.assertEqual(report['counts']['conflicted_calls_excluded'], 1)

    def test_repeated_event_and_same_context_command(self):
        self.write_events([self.call('pwd'), self.call('pwd'), self.call('pwd', 'two')])
        report, rows = self.run_intake()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['occurrence_count'], 2)
        self.assertEqual(report['counts']['duplicate_native_events'], 1)

    def test_different_workdirs_not_merged(self):
        self.write_events([self.call('pwd', workdir='/tmp/a'), self.call('pwd', 'two', workdir='/tmp/b')])
        unused, rows = self.run_intake()
        self.assertEqual(len(rows), 2)

    def test_results_joined_but_no_safety_class(self):
        self.write_events([self.call('pwd'), {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'one', 'output': 'done'}}])
        unused, rows = self.run_intake()
        self.assertEqual(rows[0]['observations'], {'tool_result_observed': 1})
        self.assertNotIn('class', rows[0])

    def test_excluded_project_and_protected_csv(self):
        self.write_events([self.call('pwd', workdir='/some/Benchmark'), self.call('git status', 'two')])
        path = self.root / 'test.csv'
        path.write_text('command\ngit status\n')
        report, rows = self.run_intake(exclude_project=['Benchmark'], exclude_csv=[path])
        self.assertEqual(rows, [])
        self.assertEqual(report['quarantine_reasons']['excluded_project'], 1)
        self.assertEqual(report['quarantine_reasons']['exact_protected_test_command'], 1)

    def test_archive_no_private_artifacts_or_secret(self):
        self.write_events([self.call('TOKEN=supersecretvalue; echo done')])
        self.run_intake()
        with zipfile.ZipFile(self.root / 'out/handoff.zip') as archive:
            self.assertEqual(set(archive.namelist()), {'commands.jsonl', 'report.json', 'MANIFEST.json'})
            for name in archive.namelist():
                self.assertNotIn(b'supersecretvalue', archive.read(name))
                self.assertNotIn(str(self.home).encode(), archive.read(name))
            manifest = json.loads(archive.read('MANIFEST.json'))
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)

    def test_output_not_overwritten(self):
        self.write_events([self.call('pwd')])
        self.run_intake()
        with self.assertRaisesRegex(RuntimeError, 'output_already_exists'):
            self.run_intake()

    def test_snapshot_does_not_read_appended_events(self):
        self.write_events([self.call('pwd')])
        source = collector.discover(self.home, ['codex'])[0]
        with self.codex.open('a') as handle:
            handle.write(json.dumps(self.call('echo later', 'two')) + '\n')
        counts, manifest = Counter(), {}
        events = list(collector.jsonl_events(source, counts, manifest))
        self.assertEqual([e['command'] for e in events], ['pwd'])
        self.assertEqual(manifest['read_bytes'], source['size'])

    def test_incomplete_tail_and_bad_json_accounted(self):
        self.codex.write_text('bad json\n' + json.dumps(self.call('pwd')) + '\n' + '{"unfinished":')
        report, rows = self.run_intake()
        self.assertEqual(len(rows), 1)
        self.assertEqual(report['counts']['invalid_json_line'], 1)
        self.assertEqual(report['counts']['incomplete_tail'], 1)

    def test_symlink_sources_not_followed(self):
        outside = self.root / 'outside.jsonl'
        self.write_events([self.call('pwd')], outside)
        try:
            self.codex.symlink_to(outside)
        except OSError:
            self.skipTest('symlink_unavailable')
        self.assertEqual(collector.discover(self.home, ['codex']), [])

    def write_cursor(self, tools):
        path = self.root / 'cursor/globalStorage/state.vscdb'
        path.parent.mkdir(parents=True)
        con = sqlite3.connect(path)
        con.execute('CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY,value TEXT)')
        for i, tool in enumerate(tools):
            bubble = {'_v': 3, 'type': 2, 'toolFormerData': {
                'name': 'run_terminal_cmd', 'toolCallId': str(i), 'params': {'command': 'pwd'}, **tool}}
            con.execute('INSERT INTO cursorDiskKV VALUES (?,?)', (f'bubbleId:conversation:{i}', json.dumps(bubble)))
        con.commit()
        con.close()

    def test_cursor_states_survive_command_grouping(self):
        self.write_cursor([
            {'status': 'completed', 'userDecision': 'accepted', 'result': {'output': 'DO_NOT_EXPORT_OUTPUT'}},
            {'status': 'cancelled', 'userDecision': 'rejected'},
            {'status': 'error'},
        ])
        report, rows = self.run_intake()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['occurrence_count'], 3)
        evidence = [item['source_observations'][0] for item in rows[0]['origin_observations']]
        self.assertEqual({item['tool_status'] for item in evidence}, {'completed', 'cancelled', 'error'})
        self.assertEqual(sum(item['result_present'] for item in evidence), 1)
        self.assertEqual(report['cursor_native_origins_by_user_decision'], {'accepted': 1, 'rejected': 1, 'absent': 1})
        self.assertNotIn('DO_NOT_EXPORT_OUTPUT', (self.root / 'out/share/commands.jsonl').read_text())
        self.assertEqual({x['origin_id'] for x in rows[0]['origin_observations']}, set(rows[0]['origin_ids']))

    def test_cursor_duplicate_native_snapshots_keep_both_states(self):
        self.write_cursor([{'toolCallId': 'same', 'status': 'running'},
                           {'toolCallId': 'same', 'status': 'cancelled', 'userDecision': 'rejected'}])
        report, rows = self.run_intake()
        self.assertEqual(rows[0]['occurrence_count'], 1)
        evidence = rows[0]['origin_observations'][0]['source_observations']
        self.assertEqual({item['tool_status'] for item in evidence}, {'running', 'cancelled'})
        self.assertEqual(report['counts']['duplicate_native_events'], 1)

    def test_cursor_unknown_state_never_exports_free_text(self):
        self.write_cursor([{'status': 'PRIVATE_STATE_TEXT', 'userDecision': {'secret': 'PRIVATE_DECISION'}}])
        unused, rows = self.run_intake()
        evidence = rows[0]['origin_observations'][0]['source_observations'][0]
        self.assertEqual(evidence, {'tool_status': 'unknown', 'user_decision': 'unknown', 'result_present': False})
        self.assertNotIn('PRIVATE_', (self.root / 'out/share/commands.jsonl').read_text())

    def test_malformed_shell_types_are_isolated(self):
        self.write_events([self.call('echo bad', str(i), shell=value) for i, value in enumerate([[], {}, None, 7, False])] +
                          [self.call('pwd', 'good', shell='bash')])
        report, rows = self.run_intake()
        self.assertEqual([row['command'] for row in rows], ['pwd'])
        self.assertEqual(report['quarantine_reasons']['invalid_native_metadata_types'], 5)

    def test_malformed_cursor_tool_does_not_stop_valid_call(self):
        self.write_cursor([{'name': ['invalid']}, {'name': 'run_terminal_cmd'}])
        unused, rows = self.run_intake()
        self.assertEqual([row['command'] for row in rows], ['pwd'])

    def test_cursor_native_fields_not_quoted_text(self):
        path = self.root / 'cursor/globalStorage/state.vscdb'
        path.parent.mkdir(parents=True)
        con = sqlite3.connect(path)
        con.execute('CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY,value TEXT)')
        con.execute('CREATE TABLE ItemTable (key TEXT PRIMARY KEY,value TEXT)')
        bubbles = [
            {'_v': 2, 'type': 2, 'text': 'run_terminal_cmd rm -rf /'},
            {'_v': 2, 'type': 1, 'toolFormerData': {'name': 'run_terminal_cmd', 'toolCallId': 'fake', 'params': '{"command":"rm -rf /"}'}},
            {'_v': 2, 'type': 2, 'toolFormerData': {'name': 'run_terminal_cmd', 'toolCallId': 'good', 'params': '{"command":"git status"}'}},
            {'_v': 99, 'type': 2, 'toolFormerData': {'name': 'run_terminal_cmd', 'toolCallId': 'unknown', 'params': '{"command":"pwd"}'}},
        ]
        for i, bubble in enumerate(bubbles):
            con.execute('INSERT INTO cursorDiskKV VALUES (?,?)', (f'bubbleId:conversation:{i}', json.dumps(bubble)))
        con.execute('INSERT INTO ItemTable VALUES (?,?)', ('secret.auth', 'MUST_NOT_BE_EXPORTED'))
        con.commit()
        con.close()
        before = path.read_bytes()
        report, rows = self.run_intake()
        self.assertEqual([row['command'] for row in rows], ['git status'])
        self.assertEqual(report['counts']['unsupported_cursor_version'], 1)
        self.assertEqual(path.read_bytes(), before)


from collections import Counter

if __name__ == '__main__':
    unittest.main()
