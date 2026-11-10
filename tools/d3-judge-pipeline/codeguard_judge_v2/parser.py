"""Pure Python grammar facts. Never call bash -n, subprocess, eval or shell."""
import bashlex
from importlib.metadata import version

PARSER_VERSION = 'bashlex-' + version('bashlex') + '-facts-v2.1'
MAX_BYTES = 32768


def parse(command, depth=0):
    facts = dict(parse_status='parsed', version=PARSER_VERSION, nodes=[], nested_shells=[], errors=[], executed=False)
    if not isinstance(command, str) or not command.strip() or '\x00' in command or len(command.encode()) > MAX_BYTES:
        facts.update(parse_status='unsupported', errors=['invalid_or_oversize_input'])
        return facts
    if depth > 4:
        facts.update(parse_status='partial', errors=['nested_depth_limit'])
        return facts
    def walk(n):
        if len(facts['nodes']) >= 4096:
            raise ValueError('node_limit')
        start, end = n.pos
        row = {'kind': n.kind, 'span': [start, end], 'text': command[start:end]}
        if n.kind == 'word':
            row['word'] = n.word
            row['expansions'] = [x.kind for x in getattr(n, 'parts', [])]
        if n.kind in ('operator', 'pipe'):
            row['operator'] = getattr(n, 'op', '|')
        if n.kind == 'command':
            words = [x for x in n.parts if x.kind == 'word']
            row['argv'] = [x.word for x in words]
            if words and words[0].word in ('bash', 'sh', 'zsh'):
                for i, w in enumerate(words[1:], 1):
                    if w.word.startswith('-') and 'c' in w.word[1:] and i + 1 < len(words):
                        script = words[i + 1]
                        if not getattr(script, 'parts', []):
                            facts['nested_shells'].append({'span': list(script.pos), 'facts': parse(script.word, depth + 1)})
                        break
        facts['nodes'].append(row)
        for v in vars(n).values():
            for child in v if isinstance(v, list) else [v]:
                if hasattr(child, 'kind'):
                    walk(child)
    try:
        for root in bashlex.parse(command):
            walk(root)
    except (Exception, RecursionError) as exc:
        facts['parse_status'] = 'partial' if facts['nodes'] else 'unsupported'
        facts['errors'].append(type(exc).__name__)  # no raw input in error logs
    return facts
