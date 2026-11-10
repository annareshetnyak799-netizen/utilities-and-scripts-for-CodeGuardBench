import csv
import json
from pathlib import Path
from .config import StrictModel
from pydantic import Field


class Context(StrictModel):
    cwd: str | None = None
    environment_tier: str | None = None
    namespace: str | None = None
    workspace: str | None = None
    known_env: dict[str, str] = Field(default_factory=dict)


def read_records(path):
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = csv.DictReader(f) if path.suffix.lower() == '.csv' else (json.loads(line) for line in f if line.strip())
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError('input row must be an object')
            identifier = row.get('id', row.get('record_id', f'row-{i + 1:06d}'))
            if not isinstance(identifier, str) or not identifier or len(identifier) > 256:
                raise ValueError('invalid input id')
            context = row.get('context', {})
            if isinstance(context, str):
                context = json.loads(context or '{}')
            # Strict allowlist: no labels, pair metadata, seed or provenance in context.
            context = Context.model_validate(context).model_dump(exclude_none=True, exclude_unset=True)
            yield dict(id=identifier, command=row.get('command'), context=context,
                       metadata={k: v for k, v in row.items() if k not in ('id', 'record_id', 'command', 'context')})
