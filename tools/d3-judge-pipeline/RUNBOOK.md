# Воспроизводимый запуск

Из корня репозитория сначала выполните `cd tools/d3-judge-pipeline`.
Все команды ниже запускаются из этого каталога.

Python3.11. Корпус не исполняется: только `/bin/bash --noprofile --norc -n`
с очищенной средой, bashlex и статические проверки. Bashlex поддерживает не
весь Bash; unsupported переводит запись в review, не объявляет её unsafe.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m judge.pipeline --input evidence/calibration_draft.jsonl --output runs/mock --config judge/configs/mock.json --dry-run
```

Локальная модель требует дополнительно requirements-local.txt и заранее
скачанный checkpoint **точной revision** из config. `allow_download=false`
в runtime. Платные API по умолчанию не используются. MPS-конфиг предназначен
для Apple Silicon; на другой машине задайте cpu/cuda отдельной версией конфига.

```bash
.venv/bin/python -m judge.pipeline --input evidence/calibration_draft.jsonl --output runs/pilot --config judge/configs/qwen3_4b_local.json --limit 40
.venv/bin/python -m judge.pipeline --input evidence/calibration_draft.jsonl --output runs/pilot --config judge/configs/qwen3_4b_local.json --resume
.venv/bin/python -m judge.evaluate --results runs/pilot/results.jsonl --references evidence/calibration_draft.jsonl --output runs/pilot/diagnostics.json --diagnostic
```

`--resume` проверяет fingerprint input/config/prompts/implementation. Частично записанная
последняя JSONL-строка сохраняется отдельно. Нельзя продолжать старый run после
изменения входа/промпта. Отдельный run — для нового checkpoint или политики.
Исходные метки/source/description не отправляются judge. Отчёт содержит
буквальный raw output, schema errors и latency, не секреты провайдера.

Для generation: один файл seeds одного split, без test/examples в train.
Draft seeds нельзя передавать до перевода проверенных записей в
`approved_for_generation`; сохраните решение в отдельном журнале. Train
хранится вне этого тестового репозитория. `experimental_only=true` допускает
пробу до выбора guard family, но результат только review, не готовый train.

```bash
.venv/bin/python -m judge.generate --input data/seeds/test_pilot_approved.jsonl --split test --output runs/test-generation --config judge/configs/generation_local.json --limit 4
.venv/bin/python -m judge.dataset --input CAT-2.2/commands.csv --output runs/validation.json
.venv/bin/python -m judge.select_val --input /path/to/synthetic-train.jsonl --output runs/val-selection.json
```

Последняя команда принимает только synthetic train/val с family_id; группы
не делятся между train/val. Небольшие страты отмечаются, не раздуваются.
Regex-признаки сложного среза — кандидаты на сложность, не измеренная трудность.

Экспорт: `judge.dataset.export_reviewed` требует отдельные решения с
human_reviewed=true и human_reviewer, строгую схему9полей и source evidence.
Вывод LLM не назначает себе human-review. Скрипт не меняет ветки, не пушит.

Dual: два разных family в config, два server/model adapters; все разногласия
попадают в очередь. Разные размеры Qwen не считаются независимыми семействами.
Этап финального human gold не выполнен автоматической проверкой или голосованием.

Архивные reports от65efe14 не продолжать новым кодом: используйте новый output.
Сводка без inference: `python -m scripts.summarize_experiments`.
Независимая ручная форма: reports/HUMAN_REVIEW_BLIND.csv.
