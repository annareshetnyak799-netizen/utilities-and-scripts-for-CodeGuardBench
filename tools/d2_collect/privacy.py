"""Offline, conservative command masking. No command is ever executed."""
import hashlib
import hmac
import ipaddress
import re
import shlex
from collections import Counter
from contextlib import ExitStack

from tree_sitter import Language, Parser
import tree_sitter_bash
from detect_secrets.core.scan import _process_line_based_plugins
from detect_secrets.settings import default_settings


class Quarantine(Exception):
    """A reason code only, never include source command text in the exception."""


def pseudonym(key, kind, value):
    value = str(value).encode('utf-8', 'surrogatepass')
    return kind + '_' + hmac.new(key, kind.encode() + b'\0' + value, hashlib.sha256).hexdigest()[:20]


def nodes(root):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def fingerprint(root, source):
    # Literal content is intentionally ignored. Operators, executable/binding
    # names, nesting and node boundaries are checked independently of secrets.
    result = []
    for node in nodes(root):
        text = source[node.start_byte:node.end_byte]
        fixed = text if not node.is_named or node.type in {
            'command_name', 'variable_name', 'heredoc_start', 'heredoc_end'
        } else b''
        result.append((node.type, node.child_count, fixed))
    return result


def semantic_anchors(text):
    """Conservative lexical invariants, in addition to the Bash tree.

    Do not hide an operation's options, system targets or sensitive basenames.
    Matching inside quoted/embedded text is intentional and fails closed.
    """
    return (
        re.findall(r'(?<![\w])--?[A-Za-z][A-Za-z0-9_-]*', text),
        re.findall(r'''(?<![\w/])/(?:etc|usr|var|boot|lib|lib64|dev|root|proc|sys|bin|sbin|run)(?=$|[/\s'";|&<>()])(?:/[^\s'";|&<>()`]*)?''', text),
        re.findall(r'(?<![\w])(?:\.git|\.env|\.ssh|authorized_keys|sudoers|shadow|passwd)(?![\w])', text),
        re.findall(r'''(?<![\w/])/(?:home|Users|tmp|private)(?=$|[/\s'";|&<>()])''', text),
        re.findall(r'(?<![\w])([A-Za-z_][\w-]*)=', text),
        re.findall(r'(?<![\w])\d+(?:\.\d+)?(?:[kKmMgGtT][bB]?)?(?![\w])', text),
    )


def literal_words(root, source):
    """Decode literal quoting only, never expand variables or run a shell."""
    result = []
    literal_types = {'word', 'string', 'raw_string', 'concatenation'}
    for node in nodes(root):
        if node.type not in literal_types or (node.parent and node.parent.type in literal_types):
            continue
        try:
            words = shlex.split(source[node.start_byte:node.end_byte].decode(), comments=False)
        except ValueError:
            continue
        result.append(tuple(words))
    return result


def literal_anchors(root, source):
    return [tuple(semantic_anchors(word) for word in words) for words in literal_words(root, source)]


class Masker:
    def __init__(self, key, home, project_roots=(), profile=None):
        self.key = key
        self.alias_values = {}
        self.home = str(home).rstrip('/')
        self.profile = profile or {}
        if any(value in {'/', '/etc', '/usr', '/var', '/boot', '/lib', '/dev', '/home', '/root', '$HOME'}
               for value in self.profile.get('private_literals', [])):
            raise RuntimeError('profile_masks_protected_path')
        self.parser = Parser(Language(tree_sitter_bash.language()))
        self.stack = ExitStack()
        self.settings = self.stack.enter_context(default_settings())
        # Never honor an allowlist comment supplied by an untrusted log line.
        self.settings.disable_filters('detect_secrets.filters.allowlist.is_line_allowlisted')
        self.settings.disable_filters('detect_secrets.filters.common.is_ignored_due_to_verification_policies')
        if any('verif' in item['path'] for item in self.settings.json()['filters_used']):
            raise RuntimeError('network_verification_filter_present')
        roots = {str(root).rstrip('/') for root in project_roots if root and str(root) not in {'/', self.home}}
        self.roots = sorted(roots, key=len, reverse=True)
        self.names = list(self.profile.get('person_names', []))
        username = re.split(r'[/\\]', self.home)[-1]
        if username not in {'', 'root', 'user', 'fixture'}:
            self.names.append(username)

    def close(self):
        self.stack.close()

    def mask(self, command):
        if not command or '\x00' in command or any(0xD800 <= ord(c) <= 0xDFFF for c in command):
            raise Quarantine('invalid_command_text')
        original = command.encode()
        tree = self.parser.parse(original)
        if tree.root_node.has_error:
            raise Quarantine('bash_parse_error')
        if re.search(r'-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----', command):
            raise Quarantine('private_key_material')
        preflight_text = command + '\n' + '\n'.join(word for words in literal_words(tree.root_node, original) for word in words)
        # Encoded credentials and tool-specific short flags are not rewritten:
        # they need protocol/utility interpretation, so keep the call private.
        # Match conservatively even inside wrappers or quoted shell bodies.
        if re.search(r'(?i)\b(?:Authorization|Proxy-Authorization)\s*:\s*Basic\b', preflight_text):
            raise Quarantine('basic_auth_requires_review')
        for utility, flag in [('mysql', 'p'), ('mysqldump', 'p'), ('mariadb', 'p'),
                              ('mariadb-dump', 'p'), ('redis-cli', 'a'), ('sshpass', 'p')]:
            if re.search(r'(?<![\w-])' + re.escape(utility) + r'(?![\w-])', preflight_text, re.I) and re.search(r'(?<![\w])-' + flag, preflight_text):
                raise Quarantine('short_credential_flag_requires_review')
        for value in re.findall(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', preflight_text):
            try:
                ip = ipaddress.IPv4Address(value)
            except ValueError:
                continue
            if not (ip.is_loopback or ip.is_unspecified or any(ip in ipaddress.ip_network(net) for net in
                    ['192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24'])):
                raise Quarantine('ipv4_literal_requires_review')
        def ipv6(m):
            try:
                address = ipaddress.IPv6Address(m[0])
            except ValueError:
                return m[0]
            if address.is_loopback or address.is_unspecified or address in ipaddress.ip_network('2001:db8::/32'):
                return m[0]
            raise Quarantine('ipv6_literal_requires_review')
        for match in re.finditer(r'(?<!\w)(?:[A-Fa-f0-9]{0,4}:){2,}[A-Fa-f0-9:]+', preflight_text):
            ipv6(match)
        generated = set()
        renderings = {}
        counts = Counter()

        def token(kind, value, suffix=''):
            if any(c in value for c in '$`\\*?{}[]();|&<>\n\r'):
                raise Quarantine('sensitive_expression_not_safely_maskable')
            # One value has one alias in every context. Kinds describe edits,
            # they must not break equality between a path and an assignment.
            name = pseudonym(self.key, 'MASK', value)
            if name in command or (name in self.alias_values and self.alias_values[name] != value):
                raise Quarantine('pseudonym_collision_requires_review')
            self.alias_values[name] = value
            name += suffix
            if value in renderings and renderings[value] != name:
                raise Quarantine('inconsistent_entity_context_requires_review')
            renderings[value] = name
            generated.add(name)
            counts[kind] += 1
            return name

        text = command

        def substitution(pattern, function, flags=0):
            nonlocal text
            text = re.sub(pattern, function, text, flags=flags)

        def private_path(value):
            # Keep separators, whitespace and syntax-bearing punctuation intact.
            return re.sub(r'[\w]+', lambda m: m[0] if m[0] in {
                'Users', 'home', 'private', 'var', 'tmp', 'workspace'
            } else token('PATH', m[0]), value)

        for root in self.roots:
            if semantic_anchors(root)[1]:
                continue
            if root in text:
                text = text.replace(root, private_path(root))
            if root.startswith(self.home + '/'):
                shorthand = '~' + root[len(self.home):]
                if shorthand in text:
                    text = text.replace(shorthand, private_path(shorthand))
        if self.home and self.home in text:
            text = text.replace(self.home, private_path(self.home))
        substitution(r'(/(?:Users|home)/)([^/\s\'";|&<>()`]+)',
                     lambda m: m[1] + (m[2] if m[2] in generated else token('USER', m[2])))
        for name in sorted(set(self.names), key=len, reverse=True):
            if not name:
                continue
            pattern = r'(?<![\w])' + re.escape(name) + r'(?![\w])'
            substitution(pattern, lambda m: re.sub(r'\w+', lambda part: token('PERSON', part[0]), m[0]), re.I)
        for value in sorted(set(self.profile.get('private_literals', [])), key=len, reverse=True):
            if value and value in text:
                text = text.replace(value, token('PRIVATE', value))

        substitution(r'\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}|(?:AKIA|ASIA)[A-Z0-9]{16}|glpat-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{12,})\b',
                     lambda m: token('SECRET', m[0]))
        value_pattern = r'''(?P<value>"(?:\\.|[^"\\])*"|'[^']*'|[^\s;&|<>]+)'''

        def credential(m):
            value = m['value']
            quote = value[:1] if value[:1] in {'"', "'"} and value[-1:] == value[:1] else ''
            content = value[1:-1] if quote else value
            if quote and m.end() < len(text) and text[m.end()] not in ' \t\r\n;&|<>)},]' and not m['prefix'].lstrip().startswith(('"', "'")):
                raise Quarantine('sensitive_concatenation_requires_review')
            if re.fullmatch(r'\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})', content):
                return m[0]  # A reference is not a leaked literal value.
            if content in generated or not content:
                return m[0]
            return m['prefix'] + quote + token('SECRET', content) + quote

        substitution(r'''(?P<prefix>\b[A-Za-z_][A-Za-z0-9_]*(?:TOKEN|PASSWORD|PASSWD|SECRET|API_KEY|ACCESS_KEY)\b\s*=\s*|\b(?:TOKEN|PASSWORD|PASSWD|SECRET|API_KEY)\s*=\s*)''' + value_pattern, credential, re.I)
        substitution(r'''(?P<prefix>--(?:password|passwd|token|api-key|access-key|secret)(?:=|\s+))''' + value_pattern, credential, re.I)
        def account(m):
            value = m['value']
            quote = value[:1] if value[:1] in {'"', "'"} and value[-1:] == value[:1] else ''
            content = value[1:-1] if quote else value
            if content in generated or content in {'localhost', '127.0.0.1'} or re.fullmatch(r'\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})', content):
                return m[0]
            kind = 'HOST' if re.search('host', m['prefix'], re.I) else 'USER'
            return m['prefix'] + quote + token(kind, content, '.invalid' if kind == 'HOST' else '') + quote
        substitution(r'''(?P<prefix>--(?:username|user-name|hostname|host)(?:=|\s+)|\b(?:USERNAME|DB_USER|HOST|HOSTNAME)\s*=\s*)''' + value_pattern, account, re.I)
        substitution(r'''(?P<prefix>["'](?:api_key|token|password|secret|access_token)["']\s*:\s*)''' + value_pattern, credential, re.I)
        substitution(r'(?i)(Bearer\s+)([A-Za-z0-9._~+/-]{8,})', lambda m: m[1] + token('SECRET', m[2]))
        substitution(r'([?&](?:token|api_key|password|secret|signature)=)([^\s&#\'"<>]+)',
                     lambda m: m[1] + token('SECRET', m[2]), re.I)
        substitution(r'([a-z][a-z0-9+.-]*://)([^\s/:@\'"<>]+):([^\s/@\'"<>]+)@',
                     lambda m: m[1] + token('USER', m[2]) + ':' + token('SECRET', m[3]) + '@', re.I)
        if any(node.type == 'command_name' and original[node.start_byte:node.end_byte] in {b'curl', b'wget'} for node in nodes(tree.root_node)):
            substitution(r'''((?:--user|-u)(?:=|\s+))(["']?)([^\s:"']+):([^\s"']+)(["']?)''',
                         lambda m: m[1] + m[2] + token('USER', m[3]) + ':' + token('SECRET', m[4]) + m[5])
        substitution(r'(https?|wss?|ftps?|ssh|git|s3|postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?)://([^\s/\'"<>]+)',
                     self._url_host(token), re.I)
        substitution(r'(?<![A-Za-z0-9._%+:/-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
                     lambda m: token('EMAIL', m[0], '@example.invalid'))
        substitution(r'(?<![\w/@])([A-Za-z_][A-Za-z0-9_.-]*)@([A-Za-z0-9_.-]+)',
                     lambda m: m[0] if any(m[0] == alias or m[1] == alias.split('@')[0] for alias in generated)
                     else token('USER', m[1]) + '@' + token('HOST', m[2], '.invalid'))

        # Escaped/encoded personal paths and unsupported known identifiers remain
        # private rather than silently bypassing a detector.
        identifier_view = text
        for alias in generated:
            identifier_view = identifier_view.replace(alias, '')
        for value in renderings:
            if value and re.search(r'(?<!\w)' + re.escape(value) + r'(?!\w)', identifier_view):
                raise Quarantine('partially_masked_entity_requires_review')
        for value in self.names + self.profile.get('private_literals', []):
            if value and (value.casefold() in identifier_view.casefold() if len(value) >= 3 else
                          re.search(r'(?<!\w)' + re.escape(value) + r'(?!\w)', identifier_view, re.I)):
                raise Quarantine('residual_private_identifier')
        command_names = {original[node.start_byte:node.end_byte].decode() for node in nodes(tree.root_node) if node.type == 'command_name'}
        if counts.get('SECRET') and command_names & {'python', 'python3', 'node', 'ruby', 'perl', 'osascript', 'powershell', 'pwsh', 'eval'}:
            raise Quarantine('masked_credential_in_embedded_language')
        masked = text.encode()
        after = self.parser.parse(masked)
        if after.root_node.has_error or fingerprint(tree.root_node, original) != fingerprint(after.root_node, masked):
            raise Quarantine('mask_changed_shell_structure_or_binding')
        if (semantic_anchors(command) != semantic_anchors(text) or
                literal_anchors(tree.root_node, original) != literal_anchors(after.root_node, masked)):
            raise Quarantine('mask_changed_protected_path_or_option')
        # Scan every line as well as the complete command. Generated pseudonyms
        # are removed ONLY from the scanner view, never from the saved command.
        view = text
        for alias in sorted(generated, key=len, reverse=True):
            view = view.replace(alias, '')
        # Pinned detect-secrets 1.5.0 file-mode scanner, not its eager --string
        # scanner which intentionally returns candidates below entropy limits.
        if next(_process_line_based_plugins(list(enumerate(view.splitlines() or [view], 1)), 'candidate.sh'), None) is not None:
            raise Quarantine('residual_secret_detector')
        types = {node.type for node in nodes(tree.root_node)}
        return text, dict(counts), {
            'multiline': '\n' in command,
            'heredoc': 'heredoc_redirect' in types,
            'pipeline': 'pipeline' in types,
            'nested_substitution': 'command_substitution' in types or 'process_substitution' in types,
            'needs_semantic_review': True,
        }

    @staticmethod
    def _url_host(token):
        def replace(m):
            authority = m[2]
            userinfo, sep, hostport = authority.rpartition('@')
            if not sep:
                hostport = authority
            if hostport.startswith('['):
                raise Quarantine('ipv6_authority_requires_review')
            host, colon, port = hostport.partition(':')
            try:
                ipaddress.ip_address(host)
                return m[0]  # A later pass preserves IPv4 address syntax.
            except ValueError:
                pass
            if host in {'localhost', 'example.com', 'example.invalid', '127.0.0.1', '0.0.0.0'} or host.endswith('.invalid'):
                return m[0]
            new_host = token('HOST', host, '.invalid')
            return m[1] + '://' + (userinfo + '@' if sep else '') + new_host + (colon + port if colon else '')
        return replace
