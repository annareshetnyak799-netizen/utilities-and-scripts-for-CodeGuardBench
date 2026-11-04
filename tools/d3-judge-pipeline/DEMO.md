# CodeGuard Judge: воспроизводимое CPU-демо

Python 3.10+, Linux/macOS. Из `tools/d3-judge-pipeline`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install . pytest==9.0.2
.venv/bin/codeguard-judge doctor
.venv/bin/codeguard-judge demo --output /tmp/codeguard-demo-new
.venv/bin/python -m pytest -q
```

`--output` должен быть новым каталогом. Demo не требует torch, GPU, весов, токена или сети. 11 входов, все направлены на review; есть неправильный Bash, неизвестный исполняемый файл и намеренный отказ провайдера. `expected.json` сравнивается с `actual.json`; повторный batch/resume уже включён. Mock не измеряет качество LLM.

Чистая установка **выполнена**, не только описана: `reports/cascade_2026-11-05/clean_install_receipt.json`, `clean_install_demo/`. Вызов установленного CLI из `/tmp` исключает случайный импорт кода из рабочей папки.

## Python API

```python
from codeguard_judge.cascade import Cascade
result = Cascade({"architecture": "rules"}).annotate(
    {"record_id": "example", "command": "git clean -n"}
)
assert result["predicted_class"] == "allow"
assert result["human_lock"] is False
```

## Batch, оценка и resume

```bash
codeguard-judge annotate --input input.jsonl --config config.json --output run-new
codeguard-judge annotate --input input.jsonl --config config.json --output run-new --resume
codeguard-judge evaluate --run run-new --references references.jsonl
codeguard-judge compare --run run-a --run run-b --output comparison.json
```

Минимальный config: `{"architecture":"rules"}`. Сетевой config включается явно, пример сохранён в `reports/cascade_2026-11-05/experiments/configs/single.json`. Он ссылается на локальный файл ключа, сам ключ не входит в артефакты. Для переноса заменить credential_file и budget_file. Не запускать платные примеры без собственного бюджета. Модельные имена у провайдера не являются неизменяемыми checkpoint SHA; сохранены requested/returned model, usage и дата.

Слепая модель получает **только command, policy и выводы предыдущих стадий**; reference class/risk/severity/source/description в запрос не попадают. `evaluate` присоединяет их после inference. Оценка — agreement с существующими метками. Human gold отсутствует.

Все решения требуют human review. `ask` означает известную операцию, требующую согласования, а не неуверенность модели. `safe` значит safe_to_execute_unconditionally: это версия производного контракта, ещё не утверждённая лидом.

Актуальный handoff: [reports/cascade_2026-11-05/HANDOFF_2026-11-05.md](reports/cascade_2026-11-05/HANDOFF_2026-11-05.md). Старые GPU notebooks к этому демо не относятся.
