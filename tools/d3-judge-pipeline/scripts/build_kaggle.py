"""Build a self-contained PRIVATE notebook from an explicit code/data allowlist.

No network, authentication, upload, model inference or shell corpus execution.
The input must contain only record_id and command. References stay local.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import textwrap
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CODE_FILES = ['__init__.py', 'adapters.py', 'cuda_adapter.py', 'pipeline.py',
              'io.py', 'schema.py', 'static.py', 'version.py',
              'prompts/system_v1.md', 'prompts/user_template_v1.md']
MODELS = {
    'granite8b': dict(model_id='ibm-granite/granite-3.3-8b-instruct',
                      revision='51dd4bc2ade4059a6bd87649d68aa11e4fb2529b',
                      family='granite', min_gpus=1, min_weight_budget_gib=7),
    'qwen32b': dict(model_id='Qwen/Qwen3-32B',
                    revision='9216db5781bf21249d130ec9da846c4624c16137',
                    family='qwen3', min_gpus=2, min_weight_budget_gib=23),
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n'


def read_inputs(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if not rows or len(rows) > 12:
        raise ValueError('diagnostic_bundle_requires_1_to_12_records')
    for row in rows:
        if set(row) != {'record_id', 'command'} or not all(isinstance(v, str) and v for v in row.values()):
            raise ValueError('input_must_be_command_only_no_labels_or_metadata')
    if len({r['record_id'] for r in rows}) != len(rows):
        raise ValueError('duplicate_input_id')
    return rows


def cell(source, kind='code'):
    value = dict(cell_type=kind, metadata={}, source=textwrap.dedent(source).strip() + '\n')
    if kind == 'code':
        value.update(execution_count=None, outputs=[])
    return value


def build(input_path, output, model='granite8b', owner=None, limit=2):
    rows = read_inputs(input_path)
    if not 1 <= limit <= len(rows):
        raise ValueError('invalid_limit')
    if owner and not re.fullmatch(r'[A-Za-z0-9_-]+', owner):
        raise ValueError('invalid_owner_slug')
    config = dict(MODELS[model], provider='huggingface_cuda', quantization='nf4',
                  device_map='auto', reserve_gib_per_gpu=2, allow_download=True,
                  max_input_tokens=4096, max_new_tokens=768, seed=20261104,
                  do_sample=False, enable_thinking=False)
    files = {'judge/' + name: (ROOT/'judge'/name).read_bytes() for name in CODE_FILES}
    files['input.jsonl'] = ''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows).encode()
    files['config.json'] = canonical({'judges': [config]}).encode()
    file_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            item = zipfile.ZipInfo(name, date_time=(2026, 11, 4, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, data)
    blob = buffer.getvalue()
    encoded = base64.b64encode(blob).decode()
    sha = hashlib.sha256(blob).hexdigest()
    slug = f'codeguard-judge-{model}-smoke-20261104'
    cells = [cell('''
        # CodeGuard judge GPU diagnostic

        Private infrastructure pilot, NOT human-gold evaluation or full taxonomy validation.
        Uses 12 previously inspected CAT-2 diagnostic inputs, never training seeds.
        Only LIMIT inputs are processed (default 2). Commands are untrusted text and never executed.
        GPU T4 x2 and Internet must be enabled. No Codex logs, credentials or expected labels included.
        Current CAT-2 policy has known interpretation gaps; outputs remain proposals for review.
        Qwen non-thinking greedy and NF4 are explicit pilot settings, not a claim of optimal quality.
        Separate Kaggle batch sessions do not preserve /kaggle/working automatically:
        download results before session disposal; resume requires the matching previous output directory.
    ''', 'markdown'), cell(f'''
        import json, os, sys, pathlib, hashlib, base64, io, zipfile, subprocess, shutil
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        WORK = pathlib.Path('/kaggle/working/codeguard_judge')
        WORK.mkdir(parents=True, exist_ok=True)
        CACHE = pathlib.Path('/kaggle/temp/codeguard_hf')
        CACHE.mkdir(parents=True, exist_ok=True)
        os.environ['HF_HOME'] = str(CACHE)
        LIMIT = {limit}
        # Safe infrastructure probe only: none of the corpus commands is passed to a shell.
        import torch
        hardware = {{'torch': torch.__version__, 'cuda': torch.version.cuda,
                     'gpu_names': [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
                     'gpu_total_bytes': [torch.cuda.get_device_properties(i).total_memory for i in range(torch.cuda.device_count())]}}
        smi = shutil.which('nvidia-smi')
        hardware['nvidia_smi_path'] = smi
        hardware['nvidia_device_nodes'] = [str(p) for p in pathlib.Path('/dev').glob('nvidia*')]
        hardware['python_version'] = sys.version
        if smi:
            probe = subprocess.run([smi, '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'],
                                   capture_output=True, text=True, timeout=15)
            hardware['nvidia_smi_returncode'] = probe.returncode
            hardware['nvidia_smi_stdout'] = probe.stdout
            hardware['nvidia_smi_stderr'] = probe.stderr
        (WORK/'hardware.json').write_text(json.dumps(hardware, indent=2))
        assert torch.cuda.is_available(), 'Enable a GPU accelerator before running this notebook'
        free_disk = shutil.disk_usage(CACHE).free
        required_disk_gib = {75 if model == 'qwen32b' else 20}
        assert free_disk >= required_disk_gib * 1024**3, 'Insufficient temporary disk for pinned original weights'
        assert torch.cuda.device_count() >= {config['min_gpus']}, 'Selected model requires more GPUs'
        print(json.dumps(hardware, indent=2))
    '''), cell('''
        # Preserve the platform CUDA-enabled Torch. Record exact resolved dependencies after installation.
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet',
                        'transformers==5.1.0', 'accelerate==1.12.0', 'bitsandbytes==0.49.2',
                        'bashlex==0.18', 'jsonschema==4.25.1'], check=True, timeout=600)
        import importlib.metadata
        versions = {name: importlib.metadata.version(name) for name in
                    ('torch', 'transformers', 'accelerate', 'bitsandbytes', 'bashlex', 'jsonschema')}
        (WORK/'runtime.json').write_text(json.dumps(versions, indent=2))
        print(versions)
    '''), cell(f'''
        payload = base64.b64decode({encoded!r})
        assert hashlib.sha256(payload).hexdigest() == {sha!r}
        expected = json.loads({canonical(file_hashes)!r})
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            assert set(archive.namelist()) == set(expected)
            for name in archive.namelist():
                relative = pathlib.PurePosixPath(name)
                assert not relative.is_absolute() and '..' not in relative.parts
                data = archive.read(name)
                assert hashlib.sha256(data).hexdigest() == expected[name]
                target = WORK/name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        (WORK/'bundle_manifest.json').write_text(json.dumps({{'sha256': {sha!r}, 'files': expected}}, indent=2))
        print('Verified', len(expected), 'allowlisted files; no expected labels or private logs')
    '''), cell('''
        output = WORK/'run'
        cmd = [sys.executable, '-m', 'judge.pipeline', '--input', str(WORK/'input.jsonl'),
               '--config', str(WORK/'config.json'), '--output', str(output), '--limit', str(LIMIT)]
        # Same-session resume is fingerprint checked. Separate sessions need restored matching outputs.
        if (output/'manifest.json').exists():
            cmd.append('--resume')
        receipt = {'gold': False, 'requested_additional_limit': LIMIT, 'status': 'running'}
        try:
            with (WORK/'run.log').open('a') as log:
                subprocess.run(cmd, cwd=WORK, stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=3600)
            rows = [json.loads(line) for line in (output/'results.jsonl').read_text().splitlines() if line.strip()]
            valid = sum(any(answer.get('response') is not None and not answer.get('errors')
                            for answer in row['judges']) for row in rows)
            receipt.update(status='completed', total_records=len(rows), schema_valid_records=valid)
            if not valid:
                receipt['status'] = 'completed_no_valid_answers'
                raise RuntimeError('No valid responses; inspect run.log and results.jsonl before extending the pilot')
            print(json.dumps(receipt, indent=2))
        except BaseException as exc:
            receipt.update(status='failed' if receipt['status']=='running' else receipt['status'],
                           error_type=type(exc).__name__)
            raise
        finally:
            (WORK/'run_receipt.json').write_text(json.dumps(receipt, indent=2))
    ''')]
    notebook = dict(cells=cells, metadata={'kernelspec': {'display_name':'Python 3', 'language':'python', 'name':'python3'},
                                         'language_info': {'name':'python', 'version':'3.11'}}, nbformat=4, nbformat_minor=5)
    for index, item in enumerate(cells):
        item['id'] = f'codeguard-{index}'
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output/'judge.ipynb').write_text(canonical(notebook))
    metadata = dict(id=f'{owner or "SET_KAGGLE_OWNER"}/{slug}', title=slug,
                    code_file='judge.ipynb', language='python', kernel_type='notebook',
                    is_private=True, enable_gpu=True, enable_internet=True,
                    docker_image_pinning_type='latest',
                    machine_shape='NvidiaTeslaT4', dataset_sources=[], competition_sources=[],
                    kernel_sources=[], model_sources=[])
    (output/'kernel-metadata.json').write_text(canonical(metadata))
    manifest = dict(model=config, input_records=len(rows), limit=limit, human_gold=False,
                    payload_sha256=sha, files=file_hashes,
                    notebook_sha256=hashlib.sha256((output/'judge.ipynb').read_bytes()).hexdigest(),
                    ready_for_upload=owner is not None, private=True)
    (output/'build_manifest.json').write_text(canonical(manifest))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--model', choices=MODELS, default='granite8b')
    parser.add_argument('--owner')
    parser.add_argument('--limit', type=int, default=2)
    args = parser.parse_args()
    result = build(args.input, args.output, args.model, args.owner, args.limit)
    print(json.dumps({k: result[k] for k in ['input_records','limit','human_gold','ready_for_upload','payload_sha256']}))
