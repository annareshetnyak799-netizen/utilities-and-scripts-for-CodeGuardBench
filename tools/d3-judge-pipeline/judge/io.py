import csv
import hashlib
import json
import os
from pathlib import Path

FIELDS = 'command description util severity category risk source seed class'.split()

def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(value).hexdigest()

def read_records(path):
    path = Path(path)
    if path.suffix == '.csv':
        with path.open(newline='', encoding='utf-8-sig') as f:
            return list(csv.DictReader(f))
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.replace(tmp, path)

def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows))

def append(path, value):
    with Path(path).open('a', encoding='utf-8') as f:
        f.write(json.dumps(value, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())

def completed(path):
    """Recover only a partial final line after interrupted write; keep a copy."""
    path = Path(path)
    if not path.exists():
        return []
    data = path.read_bytes()
    lines = data.splitlines(keepends=True)
    if lines and not lines[-1].endswith(b'\n'):
        tail = lines.pop()
        path.with_suffix('.interrupted-tail').write_bytes(tail)
        path.write_bytes(b''.join(lines))
    return [json.loads(line) for line in lines]
