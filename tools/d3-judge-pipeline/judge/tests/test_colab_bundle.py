import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import zipfile

import pytest
from scripts.build_colab import build, RUN_CELL
from scripts.build_kaggle import cell


def test_colab_notebook_is_deterministic_gpu_and_blind(tmp_path):
    source = tmp_path/'input.jsonl'
    source.write_text(json.dumps({'record_id':'one', 'command':'git status'})+'\n')
    output = tmp_path/'bundle'
    manifest = build(source, output, limit=1)
    assert manifest == build(source, output, limit=1)
    notebook = json.loads((output/'CodeGuard_Granite8B_Colab.ipynb').read_text())
    assert notebook['metadata']['accelerator'] == 'GPU'
    assert manifest['uploaded'] is False and manifest['gpu_inference_completed'] == 0
    assert not (output/'kernel-metadata.json').exists()
    for item in notebook['cells']:
        if item['cell_type'] == 'code':
            compile(item['source'], '<colab>', 'exec')
            assert '/kaggle/' not in item['source']
    source.write_text(json.dumps({'record_id':'one', 'command':'git status', 'class':'allow'})+'\n')
    with pytest.raises(ValueError, match='command_only'):
        build(source, output, limit=1)
    source.write_text(json.dumps({'record_id':'one', 'command':'echo ghp_'+'a'*30})+'\n')
    with pytest.raises(ValueError, match='possible_secret'):
        build(source, output, limit=1)


def test_vscode_variant_disables_web_download(tmp_path):
    source = tmp_path/'input.jsonl'
    source.write_text(json.dumps({'record_id':'one', 'command':'git status'})+'\n')
    build(source, tmp_path/'bundle', limit=1, interface='vscode')
    notebook = json.loads((tmp_path/'bundle/CodeGuard_Granite8B_VSCode.ipynb').read_text())
    assert 'DOWNLOAD_IN_BROWSER = False' in notebook['cells'][1]['source']
    assert 'New Colab Server' in notebook['cells'][0]['source']
    assert "globals().get('DOWNLOAD_IN_BROWSER', True)" in notebook['cells'][4]['source']


@pytest.mark.parametrize('fail', [False, True])
def test_colab_runner_exports_success_or_failure_without_running_inputs(tmp_path, fail):
    marker = tmp_path/'never_execute'
    work = tmp_path/'work'
    work.mkdir()
    inputs = [{'record_id':str(i), 'command':f'touch {marker}'} for i in range(3)]
    (work/'input.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in inputs))
    (work/'config.json').write_text('{}')
    (work/'unrelated_credentials.txt').write_text('must not export')
    calls = []

    def simulate_pipeline(cmd, **kwargs):
        calls.append(cmd)
        assert cmd[1:3] == ['-m', 'judge.pipeline']
        selected = [json.loads(line) for line in Path(cmd[cmd.index('--input')+1]).read_text().splitlines()]
        assert len(selected) == 2
        if fail:
            raise subprocess.CalledProcessError(1, cmd)
        output = Path(cmd[cmd.index('--output')+1])
        output.mkdir(exist_ok=True)
        (output/'manifest.json').write_text('{}')
        rows = [dict(record_id=row['record_id'], judges=[{'response': {'predicted_class':'allow'}, 'errors':[]}]) for row in selected]
        (output/'results.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))

    namespace = dict(WORK=work, LIMIT=2, json=json, zipfile=zipfile,
                     sys=SimpleNamespace(executable='fixture-python'),
                     subprocess=SimpleNamespace(run=simulate_pipeline, STDOUT=subprocess.STDOUT))
    code = cell(RUN_CELL)['source']
    if fail:
        with pytest.raises(RuntimeError, match='Pilot failed'):
            exec(code, namespace)
    else:
        exec(code, namespace)
        exec(code, namespace)
        assert '--resume' in calls[-1]
    assert not marker.exists()
    with zipfile.ZipFile(tmp_path/'codeguard_colab_results.zip') as archive:
        assert 'unrelated_credentials.txt' not in archive.namelist()
        receipt = json.loads(archive.read('run_receipt.json'))
        assert receipt['expected_ids'] == ['0', '1']
        assert receipt['status'] == ('failed' if fail else 'completed')
        assert json.loads(archive.read('expected_ids.json')) == ['0', '1']
