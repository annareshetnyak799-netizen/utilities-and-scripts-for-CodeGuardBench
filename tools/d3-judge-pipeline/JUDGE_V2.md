# CodeGuardBench Judge v2

Рабочий MVP для предварительной офлайн-разметки Bash. Python 3.11+, CPU, без GPU.
Результаты модели — предложения. Human gold в поставке отсутствует.

## Запуск

Из `tools/d3-judge-pipeline`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest tests judge/tests -q
.venv/bin/judge-v2 policy validate
.venv/bin/judge-v2 policy report-gaps
.venv/bin/judge-v2 run --mock --input examples/v2/input.jsonl \
  --config configs/v2/mock.yaml --output-dir /tmp/codeguard-v2-demo --run-id demo
.venv/bin/judge-v2 resume --run-id demo --output-dir /tmp/codeguard-v2-demo
```

Для `run` нужен новый output-dir. Повторное использование существующей SQLite
разрешено через `resume`. Указанный `/tmp`-каталог — пример; выберите свободное имя.
CLI также доступен как `python -m codeguard_judge_v2`.

## Архитектура и переиспользование

`raw Bash → bashlex AST → S1 semantic/taxonomy → policy compiler → S2 rule ID → Python → trace/export`.

Сохранены существующие `codeguard_judge`, `judge` и их 212 тестов. Старый CLI
`codeguard-judge` явно выбирает прежний каскад; v2 запускается только `judge-v2`.
Переиспользованы pinned bashlex 0.18, исходный registry с 42 определениями и
детектор форм секретов `judge.static.SECRET`. После обновления Changed Files от
09.11.2026 Stage 1 получает и валидирует только **30 кодов CAT-0–6**. Полный
справочник сохранён; `policy report-gaps` по-прежнему показывает все 42 кода.
Активны `stage1_system_v2.txt` и `stage2_system_v2.txt` из обновления; прежние
промпты v1 сохранены для истории. Контракт — `judge-v2-contract-2`.

Прежние sync HTTP/threaded batch, общий classifier/critic, binary overlay и
file-ledger не соответствуют новому async/stage-persistence контракту.
В v2 они заменены HTTPX, asyncio и SQLite. Старый `analyze()` с `bash -n` не вызывается.
Ни parser, ни provider, ни тесты v2 не запускают команды корпуса.

Stage 1 получает только команду, AST-факты, проверенный контекст и taxonomy.
`class`, `severity`, `description`, `source`, `seed`, pair/family/reference metadata
во входы моделей не передаются. Stage 2 видит только active rules по выбранным
рискам и выбирает `rule_id XOR review_reason`. Python назначает `a1`, `a2` и
материализует классы/важность из registry. Валидный ID не доказывает применимость
правила: это задача независимой человеческой оценки.

Известный риск с неизвестным payload/target передаётся в Stage 2: `unresolved`
сам по себе не отменяет применимость утверждённого правила к видимому механизму.
Если контекст нужен для выбора правила, Stage 2 возвращает `missing_context`.
Известный эффект без обоснованного риска допускается только с причиной
неопределённости. Если рисков нет у всех действий, Stage 2 пропускается с
`no_identified_risk`, результат остаётся в review. Для смешанной команды Stage 2
оценивает все действия, включая неразрешённые.

Изменены hashes кода, промптов, taxonomy и схем: старые runs нельзя продолжать
новой версией через CLI. Для нового прогона используйте новый output-dir;
точный resume старого run требует прежней версии проекта. Старый ZIP и отчёты
остаются историческими снимками и не содержат это обновление.

Только `allow|ask|deny`, приоритет `deny > ask > allow`. Известный deny остаётся
`operational_verdict=deny` при соседнем неизвестном действии; proposal при этом
не утверждается. При неразрешённой ничьей рисков — PI-21 review. Для нескольких
действий общая severity не вычисляется: PI-20 пока не утверждён. Severity одного
разрешённого действия берётся прямо из правила. `needs_review` — статус, не класс.

## Политика и ручное утверждение

По умолчанию используются **8 draft rules, active=0** из handoff. Это честно даёт
policy review, а не фиктивную разметку. Запрос на реализацию не был истолкован как
подпись владельца под этими rule IDs. Прямые нормы Guideline сохранены в draft
с происхождением; спорные legacy defaults и пять старых классов не активируются.

После реального человеческого решения оператор может создать новую версию:

```bash
judge-v2 policy approve \
  --registry codeguard_judge_v2/policy/registry_example.yaml \
  --output /path/to/reviewed-policy.json \
  --rule-id G-2.4-METADATA-DELETE \
  --reviewer REAL_REVIEWER --evidence REAL_REVIEW_RECORD --version v0-approved-001
judge-v2 policy validate --registry /path/to/reviewed-policy.json
judge-v2 run --mock --policy /path/to/reviewed-policy.json \
  --input examples/v2/input.jsonl --output-dir /tmp/codeguard-reviewed-demo
```

Это шаблон будущего действия, **не выполненное утверждение**. Команда сохраняет
signer/time/evidence, hash содержимого правила и прежнего registry, требует новой
версии и проверяет ссылки/циклы. Зависимые исключения требуют active base rule.
Простого изменения `status` недостаточно. Семантические противоречия условий,
написанных естественным языком, всё равно требуют policy-review.

В тестах есть отдельный registry с signer `TEST_FIXTURE_NOT_HUMAN_SIGNOFF`:
он проверяет преобразование rule ID → class/severity и **не поставляется как
production active registry**. Полный список вопросов —
[policy/issues.yaml](codeguard_judge_v2/policy/issues.yaml).

## Параллелизм, лимиты и восстановление

По умолчанию S1=8, S2=8, global inflight=16, обе очереди capacity=128.
SQLite WAL, synchronous=FULL, один логический writer в event loop; транзакции не
содержат `await`. OS lock исключает два writer-процесса для одной БД.
Вход читается потоком в транзакционный ingest, далее задания выбираются из БД.
Число worker tasks ограничено конфигом, unbounded gather по корпусу нет.
При backlog у S2 приоритет, но не более трёх S2 admissions подряд, если ждёт S1.

Общий rolling limiter учитывает RPM, input/output/combined TPM по обеим стадиям.
До запроса резервируется консервативная оценка UTF-8 bytes + framing/schema и
output budget; после ответа она корректируется по usage. Это верхняя оценка,
не точный tokenizer. Retry-After действует на общую очередь. HTTPX auto-retry
отключён. Формат: не более 1+2 ответов; transport: отдельный общий бюджет на стадию,
по умолчанию 3 повтора, с backoff/jitter и ограниченным ожиданием. Review-ответы
никогда не запускают повторное обсуждение LLM.

Каждый результат стадии durable до следующей очереди. Resume не вызывает
успешные стадии повторно и не сбрасывает сохранённые retry counters. При потере
ответа до commit возможен повтор API — exactly-once оплату не обещаем. Ошибки
JSON/Pydantic и transport после исчерпания бюджета становятся terminal technical
review; обычный resume их не повторяет. Для новой попытки создайте новый run.

Бюджет резервируется транзакционно на каждый запрос; неизвестный расход после
сбоя остаётся консервативной резервацией. При исчерпании — `budget_paused`,
сохранённые стадии остаются доступны. Явное увеличение:

```bash
judge-v2 resume --run-id RUN_ID --output-dir RUN_DIRECTORY --max-spend NEW_CEILING
```

Цены/валюта задаются конфигом. `usage_based_cost` — расчёт по usage и введённым
ценам, **не подтверждённое списание**. Тарифы cached input отдельно не моделируются.

Exact cache выключен по умолчанию. Включение: `run.cache_policy: exact`.
Ключи учитывают точный текст, context, model/revision/inference settings,
parser/taxonomy/schema/prompt/code hashes; S2 дополнительно получает S1 и policy.
S1 cache не зависит от содержимого policy. Сходные команды не объединяются.
Cache между runs доступен через Python API при общей БД; CLI требует новый
каталог для нового run. Версии фиксируются в manifest; несовместимый resume
отклоняется. Старые checkpoints предыдущих реализаций не мигрируют в v2.

## Провайдер

`configs/v2/provider.example.yaml` — неготовый шаблон, сеть выключена.
Для внешнего HTTP нужны явно включённая сеть, base URL, model/revision,
credentials через env, положительные цены и положительный max_spend.
Поддерживаются JSON schema, JSON object или plain JSON; имя output-token
параметра конфигурируется. Ключи не записываются в manifest/trace. HTTPS обязателен
для удалённого endpoint, redirects запрещены. Реальный API в этой реализации
не запускался; совместимость конкретного endpoint ещё требует бюджетного smoke.

Mock возвращает только 23 точных authored fixtures. Для остальных команд —
unknown/unsupported; это проверка инфраструктуры, не универсальный Bash judge.
Модельные приказы в комментариях/строках передаются как JSON-данные, системный
prompt запрещает их выполнять. Тесты проверяют разделение ролей и отсутствие
утечек меток; устойчивость настоящей модели к prompt injection ещё не измерена.

Parser отдаёт partial/unsupported для неподдержанного bashlex синтаксиса,
сохраняет raw текст и ranges. Вложенный `bash -c` статически разбирается до 4 уровней.
Размер команды ограничен 32 KiB, число AST-узлов — 4096; текст не обрезается.
Secret-shape detector отправляет подозрительные записи в локальный review без API.
Это не полная анонимизация PII: реальные логи должен заранее проверить оператор.

## Результаты и human gates

- `state.sqlite3`: inputs, jobs, attempts с response content/usage, stage results,
  decisions, reviews, events, cache, explicit human decisions, export manifests.
- `reports/results.jsonl`: ровно одна итоговая строка на завершённый input ID,
  в исходном порядке; обе стадии, parser, provenance и причины review.
- `proposals/results.jsonl`: только status=proposed.
- `proposals/commands_NOT_GOLD.csv`: ровно 9 полей, только полностью разрешённые
  class/risk/severity и известное provenance. Для не-synthetic пустой seed заменяется
  согласованным `-`; missing source или synthetic seed не выдумываются.
- `needs_review/results.jsonl`: review, invalid_input и technical failures.
- `human_approved/`: пуст до отдельного импорта человеческого решения.
- `reports/metrics.json`: throughput, stage/e2e p50/p95/p99, токены, очереди,
  retries/429, usage-based/unknown costs, review reasons и rule/risk diagnostics.

Экспорты атомарны для каждого файла (`fsync`, rename), не являются одной
многофайловой транзакцией; после аварии весь экспорт можно повторить из SQLite.
E2E latency относится к обработке записи в текущем сегменте resume; общий
throughput учитывает накопленное время работы orchestrator, без offline-простоя.

```bash
judge-v2 export --run-id RUN_ID --output-dir RUN_DIRECTORY --status proposed
judge-v2 review-import --run-id RUN_ID --output-dir RUN_DIRECTORY --decisions reviewed.jsonl
judge-v2 export --run-id RUN_ID --output-dir RUN_DIRECTORY --status human_approved
```

Формат человеческого решения задаёт `review.HumanDecision`: точные command/policy
hash, reviewer, date, evidence, independent=true, class/risk/severity, active rule,
описание. Это явная аттестация оператора, не криптографическая аутентификация
личности. По умолчанию модель не может создавать такие записи. Нормативно
неразрешённые многодействийные решения сначала требуют соответствующего policy signoff.

## Evaluation и воспроизведение нагрузки

```bash
judge-v2 evaluate --gold locked-human.jsonl --predictions RUN_DIRECTORY/reports/results.jsonl \
  --development development-manifest.jsonl --output evaluation.json
python scripts/demo_v2.py --output-dir /tmp/codeguard-v2-benchmark
```

Evaluate требует независимые human attestations, locked_test, совпадающие policy
и command hashes, одинаковые уникальные ID populations. Проверяет family/exact/
near-overlap с предоставленным development manifest. Человеческая независимость
не доказывается одними полями JSON; полнота manifest остаётся ответственностью
оператора. Near-check — консервативный SequenceMatcher >=0.90, не semantic oracle.
Метрики: confusion, macro-F1, exact triple, false allow/deny, coverage/review,
per-risk и Stage 1 effect/risk при наличии независимо размеченных действий.
`stage2_on_gold` явно NOT_AVAILABLE: отдельный эксперимент с gold Stage 1 и
настоящей моделью ещё не проведён. Human accuracy на synthetic proposals запрещена.

Демо сравнивает одинаковые 100 строк при concurrency 1/16, выполняет 1000 строк
с queue=2 и crash/resume. Опциональный `--development-csv` принимает именно
3000 строк актуального development-файла
`development_data/CodeGuardBench_v0_3000_latest.csv` (обновление 10.11.2026).
В нём 30 рисков CAT-0–6, по 100 строк; все источники обозначены synthetic.
Метки остаются только локальной metadata, в промпты судей не передаются;
это не human golden. Прежний набор 4200 и его результаты сохранены в истории.

```bash
python scripts/demo_v2.py --output-dir /tmp/codeguard-v2-benchmark-3000 \
  --development-csv development_data/CodeGuardBench_v0_3000_latest.csv
```
Provider Batch API, распределённый scheduler и model-quality validation — вне MVP.

Проверенные результаты и открытые нормативные вопросы:
[отчёт 09.11.2026](reports/judge_v2_2026-11-09/REPORT.md).
