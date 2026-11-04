"""Offline Colab packaging. Reuse the audited Kaggle payload, not its runtime.

Run from the pipeline root with python -m scripts.build_colab.
No authentication, upload, inference, or execution of corpus commands here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from scripts.build_kaggle import build as build_payload, canonical, cell, read_inputs
from judge.static import SECRET


RUN_CELL = '''
    # LIMIT is the total population, not an additional batch on every rerun.
    all_inputs = [json.loads(line) for line in (WORK/'input.jsonl').read_text().splitlines() if line.strip()]
    assert isinstance(LIMIT, int) and 1 <= LIMIT <= len(all_inputs), 'LIMIT must be 1..input size'
    selected = all_inputs[:LIMIT]
    input_path = WORK/f'input_{LIMIT}.jsonl'
    input_path.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\\n' for row in selected))
    expected_ids = [row['record_id'] for row in selected]
    (WORK/'expected_ids.json').write_text(json.dumps(expected_ids, indent=2))
    output = WORK/f'run_{LIMIT}'
    cmd = [sys.executable, '-m', 'judge.pipeline', '--input', str(input_path),
           '--config', str(WORK/'config.json'), '--output', str(output)]
    if (output/'manifest.json').exists():
        cmd.append('--resume')
    receipt = {'gold': False, 'expected_ids': expected_ids, 'expected_n': LIMIT, 'status': 'running'}
    failure = None
    try:
        with (WORK/'run.log').open('a') as log:
            subprocess.run(cmd, cwd=WORK, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=3600)
        rows = [json.loads(line) for line in (output/'results.jsonl').read_text().splitlines() if line.strip()]
        ids = [row['record_id'] for row in rows]
        assert len(ids) == len(set(ids)) and set(ids) == set(expected_ids), 'Incomplete or duplicate results'
        valid = sum(any(answer.get('response') is not None and not answer.get('errors')
                        for answer in row['judges']) for row in rows)
        receipt.update(status='completed', total_records=len(rows), schema_valid_records=valid)
        if valid != len(rows):
            receipt['status'] = 'completed_with_invalid_answers'
        if not valid:
            raise RuntimeError('No schema-valid answers; inspect results and run.log')
    except Exception as exc:
        failure = exc
        receipt.update(status='failed' if receipt['status']=='running' else receipt['status'],
                       error_type=type(exc).__name__)
    finally:
        (WORK/'run_receipt.json').write_text(json.dumps(receipt, indent=2))
        # Explicit output allowlist: never archive HF caches, weights, account files or /content.
        archive_path = WORK.parent/'codeguard_colab_results.zip'
        exports = ['hardware.json', 'runtime.json', 'bundle_manifest.json', 'config.json',
                   'expected_ids.json', f'input_{LIMIT}.jsonl', 'run.log', 'run_receipt.json']
        exports += [f'run_{LIMIT}/'+name for name in
                    ('manifest.json', 'summary.json', 'results.jsonl', 'results.interrupted-tail')]
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name in exports:
                path = WORK/name
                if path.is_file():
                    archive.write(path, arcname=name)
        print(json.dumps(receipt, indent=2))
        print('Results archive:', archive_path)
        print('Download ZIP via Colab Files (web) or Colab > Contents > right-click ZIP > Download (VS Code).')
        if globals().get('DOWNLOAD_IN_BROWSER', True):
            try:
                from google.colab import files
                files.download(str(archive_path))
            except Exception as exc:
                print('Automatic download unavailable:', type(exc).__name__)
    if failure is not None:
        raise RuntimeError('Pilot failed; ZIP contains diagnostic evidence') from failure
'''


def build(input_path, output, limit=2, interface='web'):
    if interface not in ('web', 'vscode'):
        raise ValueError('unknown_notebook_interface')
    rows = read_inputs(input_path)
    if any(SECRET.search(row['command']) for row in rows):
        raise ValueError('possible_secret_in_upload_input')
    with tempfile.TemporaryDirectory() as temporary:
        manifest = build_payload(input_path, temporary, model='granite8b', limit=limit)
        notebook = json.loads((Path(temporary)/'judge.ipynb').read_text())
    cells = notebook['cells']
    cells[0] = cell('''
        # CodeGuard: первый запуск judge в Google Colab

        1. Среда выполнения → Сменить среду выполнения → GPU (T4, если доступна).
        2. Среда выполнения → Выполнить все. По умолчанию проверяются **2 команды**.
        3. Сохраните `codeguard_colab_results.zip` и передайте его для разбора.

        Модель: Granite 3.3 8B Instruct, фиксированная revision, NF4/FP16, одна GPU.
        Первая загрузка скачивает около 16 GB весов. На CPU запуск остановится до загрузки.
        Публичный checkpoint не требует HF-токена. Google Drive подключать не нужно.
        Команды анализируются как текст и не исполняются. Входы — прежние diagnostic
        случаи; ответов-эталонов, частных Codex-логов и ключей здесь нет.

        Результаты — предложения разметки, не human gold. Текущая рубрика CAT-2
        ещё проходит проверку. Этот notebook не доказывает качество всей таксономии.
        После успешного smoke можно изменить LIMIT с 2 на 12 и повторить запуск:
        это отдельный полный прогон, содержащий первые две команды повторно.
        Повторный запуск с тем же LIMIT в живой сессии продолжит незавершённый прогон.
        Новая Colab-сессия не восстанавливает результаты автоматически: скачайте ZIP
        до отключения. Если модель выдаёт ошибки, сначала разберите их, затем расширяйте прогон.
    ''', 'markdown')
    cells[1]['source'] = cells[1]['source'].replace('/kaggle/working/codeguard_judge', '/content/codeguard_judge')
    cells[1]['source'] = cells[1]['source'].replace('/kaggle/temp/codeguard_hf', '/content/codeguard_hf')
    cells[1]['source'] += f'\nDOWNLOAD_IN_BROWSER = {interface == "web"!r}\n'
    cells[1]['source'] = cells[1]['source'].replace(
        "assert torch.cuda.is_available(), 'Enable a GPU accelerator before running this notebook'",
        "print(json.dumps(hardware, indent=2))\nassert torch.cuda.is_available(), 'Select Runtime > Change runtime type > GPU, then rerun'")
    cells[2] = cell('''
        # Preserve the platform's matching Torch/audio/vision wheels.
        # Install packages in a subprocess; inference also starts in a fresh subprocess.
        import importlib.metadata
        constraints = []
        for name in ('torch', 'torchvision', 'torchaudio'):
            try:
                constraints.append(name+'=='+importlib.metadata.version(name))
            except importlib.metadata.PackageNotFoundError:
                pass
        constraint_file = WORK/'platform_constraints.txt'
        constraint_file.write_text('\\n'.join(constraints)+'\\n')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet',
                        '--constraint', str(constraint_file),
                        'transformers==5.1.0', 'accelerate==1.12.0', 'bitsandbytes==0.49.2',
                        'bashlex==0.18', 'jsonschema==4.25.1'], check=True, timeout=900)
        versions = {name: importlib.metadata.version(name) for name in
                    ('torch', 'transformers', 'accelerate', 'bitsandbytes', 'bashlex', 'jsonschema')}
        (WORK/'runtime.json').write_text(json.dumps(versions, indent=2))
        print(versions)
    ''')
    cells[4] = cell(RUN_CELL)
    filename = 'CodeGuard_Granite8B_Colab.ipynb'
    if interface == 'vscode':
        filename = 'CodeGuard_Granite8B_VSCode.ipynb'
        cells[0]['source'] = '''# CodeGuard: Colab GPU через VS Code

1. Select Kernel → Select Another Kernel… (если нужно) → Colab → New Colab Server.
2. Войдите в Google при запросе, выберите GPU/T4, затем Python kernel этого сервера.
   Auto Connect может выбрать CPU: фактическое оборудование проверит первая ячейка.
3. Run All. По умолчанию LIMIT=2, модель Granite3.3-8B NF4/FP16.
4. Colab (иконка слева) → Contents → codeguard_colab_results.zip → Download.
   Если дерево пусто, нажмите Refresh. Сохраните ZIP локально для разбора результатов.

Ноутбук хранится локально, код выполняется на выданном сервере Colab.
Google Drive и HF-токен не нужны. Первая загрузка весов около16 GB.
Браузерная files.download отключена: она не поддерживается расширением как в Colab Web.
Команды анализируются как данные, не исполняются. Внутри прежние12 diagnostic
случаев без эталонов, private логов и ключей. Human gold отсутствует.

Повтор с тем же LIMIT продолжает прогон в той же сессии. LIMIT=12 создаёт новый
полный прогон, включая первые2 команды; расширять только после проверки smoke.
Новая сессия не восстанавливает прежние файлы: скачайте ZIP до отключения.
'''
        cells[1]['source'] = cells[1]['source'].replace(
            'Select Runtime > Change runtime type > GPU, then rerun',
            'Select Kernel > Colab > New Colab Server > GPU, then rerun')
    for index, item in enumerate(cells):
        item['id'] = f'codeguard-colab-{index}'
        if item['cell_type'] == 'code':
            compile(item['source'], f'<colab-cell-{index}>', 'exec')
    notebook['metadata'].update(accelerator='GPU', colab={'name':filename, 'provenance':[], 'gpuType':'T4'})
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    path = output/filename
    path.write_text(canonical(notebook))
    for key in ('ready_for_upload', 'private'):
        manifest.pop(key, None)
    manifest.update(platform='google_colab', interface=interface, uploaded=False, gpu_inference_completed=0,
                    notebook_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    visibility='User-controlled on import; no sharing or upload performed by builder')
    (output/'build_manifest.json').write_text(canonical(manifest))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--limit', type=int, default=2)
    parser.add_argument('--interface', choices=('web', 'vscode'), default='web')
    args = parser.parse_args()
    result = build(args.input, args.output, args.limit, args.interface)
    print(json.dumps({key: result[key] for key in ('platform', 'input_records', 'limit', 'uploaded', 'notebook_sha256')}))
