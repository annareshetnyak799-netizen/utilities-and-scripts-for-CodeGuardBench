import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[2]/'scripts/build_kaggle.py'
spec = importlib.util.spec_from_file_location('build_kaggle', SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_export_rejects_labels_instead_of_uploading_them(tmp_path):
    source = tmp_path/'in.jsonl'
    source.write_text(json.dumps({'record_id':'x', 'command':'git status', 'class':'allow'})+'\n')
    with pytest.raises(ValueError, match='command_only'):
        builder.build(source, tmp_path/'out', limit=1)


def test_bundle_is_private_reproducible_and_contains_only_explicit_files(tmp_path):
    marker = tmp_path/'must_not_execute'
    source = tmp_path/'in.jsonl'
    source.write_text(json.dumps({'record_id':'x', 'command':f'touch {marker}'})+'\n')
    out = tmp_path/'out'
    first = builder.build(source, out, limit=1)
    assert not marker.exists()
    assert first == builder.build(source, out, limit=1)
    assert first['ready_for_upload'] is False
    metadata = json.loads((out/'kernel-metadata.json').read_text())
    assert metadata['is_private'] is True
    notebook = json.loads((out/'judge.ipynb').read_text())
    import ast
    payload = None
    for cell in notebook['cells']:
        if cell['cell_type'] != 'code':
            continue
        code = cell['source']
        compile(code, '<notebook>', 'exec')
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'payload':
                payload = base64.b64decode(ast.literal_eval(node.value.args[0]))
    assert payload is not None
    assert hashlib.sha256(payload).hexdigest() == first['payload_sha256']
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert set(archive.namelist()) == set(first['files'])
        assert set(json.loads(archive.read('input.jsonl'))) == {'record_id', 'command'}
        assert not any('reference' in name or 'log' in name or 'token' in name for name in archive.namelist())
    with pytest.raises(ValueError, match='duplicate_input_id'):
        source.write_text(source.read_text()*2)
        builder.build(source, out, limit=1)
