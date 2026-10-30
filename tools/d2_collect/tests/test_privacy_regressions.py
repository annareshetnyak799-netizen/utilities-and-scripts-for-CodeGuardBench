"""Regression fixtures from the 0.1.0 audit. No corpus execution."""
import base64
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from privacy import Masker, Quarantine
import collect_logs


class AuditRegressions(unittest.TestCase):
    def candidate(self, command, roots=(), profile=None):
        masker = Masker(b'z' * 32, Path('/Users/alice'), roots, profile)
        try:
            try:
                return masker.mask(command)[0]
            except Quarantine:
                return None
        finally:
            masker.close()

    def secret_removed_or_quarantined(self, command, secret):
        result = self.candidate(command)
        self.assertTrue(result is None or secret not in result, 'sensitive_fixture_value_exported')

    def test_basic_authorization_header(self):
        value = base64.b64encode(b'demo:pass123').decode()
        self.secret_removed_or_quarantined('curl -H "Authorization: Basic ' + value + '" https://example.com', value)

    def test_mysql_attached_password(self):
        self.secret_removed_or_quarantined('mysql -udemo -ppass123 -e "SELECT 1"', 'pass123')

    def test_redis_password_flag(self):
        self.secret_removed_or_quarantined('redis-cli -a pass123 ping', 'pass123')

    def test_sshpass_password_flag(self):
        self.secret_removed_or_quarantined('sshpass -p pass123 ssh demo@example.com', 'pass123')

    def test_short_configured_name(self):
        result = self.candidate('echo Bo', profile={'person_names': ['Bo']})
        self.assertTrue(result is None or 'Bo' not in result, 'configured_identifier_exported')

    def test_protected_path_is_not_a_private_project(self):
        result = self.candidate('rm -rf /etc', roots=['/etc'])
        self.assertTrue(result is None or '/etc' in result, 'protected_target_semantics_changed')

    def test_profile_literal_cannot_erase_protected_anchor(self):
        result = self.candidate('rm -rf /etc', profile={'private_literals': ['etc']})
        self.assertTrue(result is None or '/etc' in result, 'protected_target_semantics_changed')

    def test_person_name_cannot_change_option(self):
        result = self.candidate('rm --force /etc', profile={'person_names': ['Force']})
        self.assertTrue(result is None or '--force' in result, 'operation_flag_changed')

    def test_public_ipv4_mapping_is_injective_for_fixture(self):
        first = self.candidate('ping -c 1 9.0.0.11')
        second = self.candidate('ping -c 1 9.0.0.21')
        if first is not None and second is not None:
            self.assertNotEqual(first, second, 'distinct_addresses_collapsed')

    def test_same_account_value_preserves_binding(self):
        command = 'ACCOUNT=alice; test "$ACCOUNT" = "$(basename /home/alice)"'
        result = self.candidate(command)
        if result is not None:
            account = result.split('ACCOUNT=', 1)[1].split(';', 1)[0]
            basename = result.split('/home/', 1)[1].split(')', 1)[0]
            self.assertEqual(account, basename, 'literal_equality_relation_changed')

    def test_same_account_value_with_trailing_slash_preserves_binding(self):
        command = 'ACCOUNT=alice; test "$ACCOUNT" = "$(basename /home/alice/)"'
        result = self.candidate(command)
        if result is not None:
            account = result.split('ACCOUNT=', 1)[1].split(';', 1)[0]
            basename = result.split('/home/', 1)[1].split(')', 1)[0].rstrip('/')
            self.assertEqual(account, basename, 'literal_equality_relation_changed')

    def test_malformed_shell_does_not_abort_other_valid_requests(self):
        with tempfile.TemporaryDirectory(prefix='d2-audit-fixture-') as temp:
            root = Path(temp)
            home = root / 'home'
            path = home / '.codex/sessions/source.jsonl'
            path.parent.mkdir(parents=True)
            events = []
            for cid, shell in [('invalid', ['bash']), ('valid', 'bash')]:
                events.append({'type': 'response_item', 'payload': {'type': 'function_call',
                               'name': 'exec_command', 'call_id': cid,
                               'arguments': {'cmd': 'pwd', 'shell': shell}}})
            path.write_text(''.join(json.dumps(event) + '\n' for event in events))
            args = SimpleNamespace(home=home, output=root / 'out', profile=None, providers='codex',
                                   cursor_user_dir=None, key_file=None, exclude_project=[], exclude_csv=[],
                                   max_command_bytes=collect_logs.MAX_COMMAND)
            with contextlib.redirect_stderr(io.StringIO()):
                report = collect_logs.collect(args)
            self.assertEqual(report['counts']['handoff_records'], 1)

    def test_all_short_names_are_honored(self):
        for name in ['Li', 'Bo', 'A', 'Ю']:
            with self.subTest(name=name):
                result = self.candidate('echo ' + name, profile={'person_names': [name]})
                self.assertIsNotNone(result)
                self.assertNotEqual(result, 'echo ' + name)

    def test_quoted_protected_path_cannot_be_masked(self):
        result = self.candidate('rm -rf /e"tc"', profile={'private_literals': ['tc']})
        self.assertIsNone(result)

    def test_quoted_option_cannot_be_masked(self):
        result = self.candidate('rm --fo"rce" /etc', profile={'private_literals': ['rce']})
        self.assertIsNone(result)

    def test_system_paths_and_sensitive_basenames_fail_closed(self):
        for command, name in [('rm -rf /root', 'Root'), ('cat /etc/passwd', 'passwd'),
                              ('rm -rf .git', 'git'), ('cat ~/.ssh/config', 'ssh')]:
            with self.subTest(command=command):
                self.assertIsNone(self.candidate(command, profile={'person_names': [name]}))

    def test_assignment_argument_keys_and_numeric_bounds_stay_fixed(self):
        for command, value in [('dd if=/dev/zero of=/dev/sdb', 'of'),
                               ('truncate -s 250 disk.img', '250')]:
            self.assertIsNone(self.candidate(command, profile={'private_literals': [value]}))

    def test_one_value_has_one_alias_across_kinds(self):
        result = self.candidate('ACCOUNT=alice; printf "%s" /home/alice/', profile={'person_names': ['alice']})
        self.assertIsNotNone(result)
        self.assertEqual(result.split('ACCOUNT=')[1].split(';')[0], result.split('/home/')[1].rstrip('/'))

    def test_partial_entity_mask_is_quarantined(self):
        self.assertIsNone(self.candidate('ACCOUNT=demo; ssh demo@production uptime'))

    def test_incompatible_entity_context_is_quarantined(self):
        self.assertIsNone(self.candidate('client --username sample --host sample'))

    def test_ipv4_cannot_bypass_quarantine_via_host_flag(self):
        self.assertIsNone(self.candidate('client --host 9.0.0.11'))

    def test_short_credential_variants_are_quarantined(self):
        for command in ['sudo /usr/bin/mysql -p"pass123"', 'mysqldump -p pass123',
                        'mariadb -ppass123', 'redis-cli -apass123 ping',
                        'sshpass -p"pass123" ssh target', 'bash -c "redis-cli -a pass123 ping"']:
            with self.subTest(command=command):
                self.assertIsNone(self.candidate(command))

    def test_utilities_without_credentials_stay_available(self):
        for command in ['mysql --version', 'redis-cli ping', 'sshpass -V', 'curl -I https://example.com']:
            self.assertEqual(self.candidate(command), command)

    def test_preflight_is_not_bypassed_by_profile_or_literal_quotes(self):
        value = base64.b64encode(b'demo:pass123').decode()
        self.assertIsNone(self.candidate('curl -H "Authorization: Basic ' + value + '" https://example.com',
                                         profile={'private_literals': ['Basic']}))
        self.assertIsNone(self.candidate('curl -H \'Authorization: Ba\'"sic ZGVtbzpwYXNzMTIz" https://example.com'))
        self.assertIsNone(self.candidate('my"sql" -p"pass123"'))
        self.assertIsNone(self.candidate('ping 9.0.0."11"'))


if __name__ == '__main__':
    unittest.main()
