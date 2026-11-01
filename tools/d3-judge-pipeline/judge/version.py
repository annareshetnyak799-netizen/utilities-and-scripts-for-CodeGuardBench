"""Content fingerprint: refuse to resume after implementation/schema changes."""
import hashlib
from pathlib import Path

def implementation_sha():
    root = Path(__file__).parent
    files = sorted(p for p in root.rglob('*') if p.suffix in ('.py', '.md', '.json') and 'tests' not in p.parts and 'configs' not in p.parts)
    h = hashlib.sha256()
    for p in files:
        h.update(str(p.relative_to(root)).encode()); h.update(b'\0'); h.update(p.read_bytes()); h.update(b'\0')
    return h.hexdigest()
