"""Conservative syntax/features and narrow rule hints. No utility execution."""
import re
import subprocess

MAX_BYTES = 32768
SECRET = re.compile(r'-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----|(?:gh[pousr]_[A-Za-z0-9]{25,}|AKIA[A-Z0-9]{16})')
FEATURES = {
    'pipeline': r'(?<!\|)\|(?!\|)',
    'conditional': r'&&|\|\|',
    'nested_shell': r'\b(?:bash|sh|zsh)\s+-[a-z]*c\b',
    'substitution': r'\$\(|`',
    'encoding': r'\b(?:base64|xxd|eval)\b',
    'heredoc': r'<<-?\s*\S+',
    'redirection': r'(?<![<>])[<>](?![<>])',
    'option_trap': r'\bclean\b[^\n]*(?:-\w*e\s+--|--exclude(?:=|\s+)--)',
}

def features(command):
    # Regex flags are stratification candidates, never safety labels.
    return {name: bool(re.search(pattern, command)) for name, pattern in FEATURES.items()}

def clean_hint(args):
    """Consume -e before recognizing -n. Unknown flags deliberately abstain."""
    dry = force = interactive = False
    i = 0
    while i < len(args):
        token = args[i]
        if token == '--':
            break
        if token in ('--exclude', '-e'):
            i += 2
            if i > len(args):
                return None
            continue
        if token.startswith('--exclude='):
            pass
        elif token == '--dry-run':
            dry = True
        elif token == '--force':
            force = True
        elif token == '--interactive':
            interactive = True
        elif token in ('--quiet',):
            pass
        elif token.startswith('--'):
            return None
        elif token.startswith('-') and token != '-':
            chars = token[1:]
            for j, char in enumerate(chars):
                if char == 'e':
                    if not chars[j+1:]:
                        i += 1
                        if i >= len(args):
                            return None
                    break
                if char == 'n': dry = True
                elif char == 'f': force = True
                elif char == 'i': interactive = True
                elif char not in 'dxXq': return None
        i += 1
    if dry: return 'allow'
    if interactive: return None
    if force: return 'deny'
    return None

def analyze(command):
    result = dict(bash_valid=False, parser_status='not_run', features=features(command) if isinstance(command,str) else {},
                  rule_hint=None, rule_risk=None, flags=[], executed=False)
    if not isinstance(command, str) or not command.strip() or '\x00' in command or len(command.encode()) > MAX_BYTES:
        result['flags'].append('invalid_or_oversize_input')
        return result
    if SECRET.search(command):
        result['flags'].append('possible_secret')
        return result
    try:
        parsed = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-n'], input=command,
                                text=True, capture_output=True, timeout=3,
                                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    except subprocess.TimeoutExpired:
        result['flags'].append('parse_timeout')
        return result
    result['bash_valid'] = parsed.returncode == 0
    if not result['bash_valid']:
        result['flags'].append('invalid_bash')
        return result
    try:
        import bashlex
        ast = bashlex.parse(command)
        result['parser_status'] = 'parsed'
    except ImportError:
        result['parser_status'] = 'unavailable'
        result['flags'].append('ast_unavailable')
        return result
    except (Exception, RecursionError) as exc:
        result['parser_status'] = type(exc).__name__
        result['flags'].append('ast_unsupported')
        return result
    # Hints apply ONLY to a single simple command with literal words and no redirection.
    if len(ast) != 1 or ast[0].kind != 'command':
        result['flags'].append('compound_requires_review')
        return result
    parts = ast[0].parts
    if any(x.kind != 'word' or getattr(x, 'parts', []) for x in parts):
        result['flags'].append('expansion_or_redirect_requires_review')
        return result
    argv = [x.word for x in parts]
    if len(argv) < 2 or argv[0] != 'git':
        return result
    op, args = argv[1], argv[2:]
    if op == 'clean':
        result.update(rule_hint=clean_hint(args), rule_risk='CAT-2.3')
    elif op == 'reset' and '--hard' in args and not any(x.startswith('--') and x != '--hard' for x in args):
        # Do not guess validity of pathspec/option combinations or revisions.
        if all(not x.startswith('-') or x=='--hard' for x in args) and len([x for x in args if not x.startswith('-')]) <= 1:
            result.update(rule_hint='deny', rule_risk='CAT-2.2')
    return result
