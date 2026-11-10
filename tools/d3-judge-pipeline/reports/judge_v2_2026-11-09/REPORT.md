# Judge v2 — результат реализации 09.11.2026

Реализован работающий технический MVP в `tools/d3-judge-pipeline`, локальная ветка
`feat/d3-judge-v2`. Сохранён предыдущий каскад. **308 тестов прошли: 96 новых v2 +
212 прежних.** Платных API-вызовов и выполнения команд корпуса не было.

Полная семантическая приёмка §28 ТЗ не заявляется: независимого human golden и
подписанного атомарного registry в поставке нет. **Active rules=0, human gold=0.**
Все 8 правил reference registry сохранены draft. Автоматического превращения
4200 synthetic proposals в эталон нет. Push/merge не выполнялись.

## Исходники и нормативная граница

Пользователь явно поручил реализовать MVP и запускать offline tests/mock.
Архив ALL_IN_ONE содержит запрошенный Parallel Handoff распакованным, без
вложенных ZIP. Прочитаны START_HERE, CODEX_PROMPT, полное TECHNICAL_SPEC,
implementation brief, prompts, Python reference, QA, policy issues и Guideline.
Извлечены и побайтно проверены 107 членов архива; manifest находится в центральном
`docs/sources/035-judge-v2-2026-11-09/INGEST_MANIFEST.json`.

Команды внутри корпуса — данные. Нормативные предложения/illustrative rule IDs
из архива не приравнены к человеческому утверждению. S008/S020 и прежние
опубликованные данные сохранены; broad Git override не расширен молча.

## Что изменилось

| Файлы | Реализованное поведение |
| --- | --- |
| `codeguard_judge_v2/schemas.py`, `aggregation.py` | Pydantic v2/enum/extra forbid, class dominance, review вместо неутверждённой severity/primary tie |
| `policy_registry.py`, `policy/*` | 42 taxonomy definitions без labels, narrow active compiler, ID/provenance/version/relations/approval checks, ручное approval с audit trail |
| `parser.py`, `stages.py`, `prompts/*` | Python-only AST facts, blind stage payloads, Python action IDs, независимые stage schemas и hashes |
| `providers.py`, `limits.py`, `pipeline.py` | HTTPX adapter и exact fixture mock, 8/8 workers, inflight16, bounded queues128, fairness, совместные RPM/TPM, finite retries |
| `storage.py`, `common.py` | SQLite WAL/FULL, один writer, stage commit перед queue, durable counters/budget/cache/resume, atomic exports |
| `records.py`, `export.py`, `review.py`, `evaluation.py`, `metrics.py` | Потоковый CSV/JSONL intake, раздельные статусы, manual adjudication, independent-gold gates, диагностика |
| `cli.py`, `__main__.py`, `configs/v2/*`, `examples/v2/*` | run/resume/export/policy/evaluate/review-import и безопасный mock default |
| `tests/v2/*`, `scripts/demo_v2.py` | Unit/integration/fault injection, benchmark и crash/resume |
| `pyproject.toml`, `requirements.txt`, `README.md`, `JUDGE_V2.md` | Установка, зависимости и runbook |

Пофайловый manifest SHA — [CHANGED_FILES.json](CHANGED_FILES.json).
Переиспользованы существующие taxonomy definitions/provenance, bashlex 0.18,
secret-shape detector; адаптирован предоставленный Pydantic reference. Старые
sync provider/batch/file-resume не имеют требуемых async/stage-level гарантий,
поэтому для v2 создан отдельный слой без переписывания legacy.

## Проверки

- `python -m pytest tests judge/tests -q`: **308 passed**, 6.22 s.
  [Полный вывод](TEST_RESULTS.txt). Отдельные lint/type-check tools в проекте
  не настроены; `compileall` и `git diff --check` прошли.
- Invalid JSON: два сбоя и третий успешный ответ; три сбоя — technical review.
  Pydantic-invalid S2 не повторяет S1. Wrong/inactive/unoffered ID, дубли/пропуски
  action IDs, enum, extra fields, версии и approval tampering отклоняются.
- Fake 429/Retry-After, 503, timeout; сетевые ошибки имеют отдельный конечный
  бюджет. Fake-clock проверяет совместные RPM/input/output/combined TPM и usage
  correction; fair gate проверяет отсутствие starvation S1.
- Queue capacity=2, 1000 inputs: две очереди не превысили 2. Out-of-order и
  duplicate delivery не создают дубликатов итоговых строк. S2 проверяется после
  durable S1, между строками стадии перекрываются.
- Crash после S1 commit: S1 не повторяется. Crash после HTTP-response до commit:
  допустим at-least-once повтор без дублирования результата. Retry counters не
  сбрасываются при resume; успешные стадии сохраняются при budget stop.
- Concurrency 1/16 даёт одинаковые ID/order/class/review на фиксированных
  ответах; в unit/integration используется явно тестовый active registry.
- No-execution, quoting/substitution/heredoc/operators/nested shell, эффективный
  dry-run как fixture, CAT-5.1 exception, Base64, sudo, shadow, Terraform,
  неизвестная переменная, unreachable branch проверены как контракты и AST.
  Это **не доказательство качества настоящего LLM** на этих командах.
- Human import требует явного reviewer/evidence/command-policy binding;
  synthetic proposals rejected как gold. Evaluation population, policy,
  family/exact/near-duplicate guards проверены.
- Собран wheel 0.3.0; установка в отдельный clean venv и запуск CLI вне дерева
  исходников проверяются отдельно (см. INSTALL_SMOKE.json).

## Offline E2E и измерения

Финальный воспроизводимый прогон — [BENCHMARK.json](BENCHMARK.json).
Полные SQLite/trace/metrics находятся локально в `final_demo/` (не включены в git).
Значения ниже — **mock**, quotas не заданы, input/output tokens оценены mock по
размеру текстов. Стоимость 0, число network calls 0. Реальные reasoning tokens,
квоты и model accuracy не измерялись.

| Прогон | Строки | Mock calls | Секунды | Строк/мин | Peak inflight |
| --- | ---: | ---: | ---: | ---: | ---: |
| bounded1000 | 1000 | 2000 | 2.055 | 29201.3 | 12 |
| crash_resume | 1 | 2 | 0.025 | 2413.1 | 1 |
| development4200 | 4200 | 4202 | 5.929 | 42502.5 | 9 |
| parallel100 | 100 | 200 | 0.217 | 27655.3 | 16 |
| serial100 | 100 | 200 | 2.431 | 2468.0 | 1 |

Одинаковые 100 строк, fake latency 10 ms на каждый вызов, cache off:
измеренное ускорение **11.21×**, одинаковые результаты и порядок.
Это один контролируемый замер на локальной машине, не SLA реального провайдера.
Предварительный `offline_demo/` относится к коду до оптимизации hash computation;
для текущих результатов использовать только `final_demo/` и BENCHMARK.json.

1000 строк: 2000 вызовов, peak очередей 2/2, S1/S2 overlap подтверждён.
Crash demo: 1 durable S1 до сбоя, после resume **S1 calls=0, S2 calls=1**;
повторный resume завершённого run не вызывает provider.

На 4200 development inputs Stage 1 вызывается 4200 раз; 4198 строк не входят в
23 exact mock fixtures и идут в unresolved review со Stage 2 skipped, только
2 строки доходят до Stage 2 (всего4202calls). Все4200 сохраняются ровно один раз.
**Это не двухстадийный LLM-прогон8400 запросов и не semantic coverage42.**
Default registry не содержит active rules: review rate 100%, CSV proposals0,
human-approved0. Такой результат ожидаем и не называется успешной разметкой.

## Команды воспроизведения

Из `tools/d3-judge-pipeline`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest tests judge/tests -q
.venv/bin/judge-v2 policy validate
.venv/bin/judge-v2 run --mock --input examples/v2/input.jsonl \
  --config configs/v2/mock.yaml --output-dir /tmp/judge-v2-new --run-id demo
.venv/bin/judge-v2 resume --run-id demo --output-dir /tmp/judge-v2-new
.venv/bin/judge-v2 export --run-id demo --output-dir /tmp/judge-v2-new --status proposed
.venv/bin/python scripts/demo_v2.py --output-dir /tmp/judge-v2-benchmark-new \
  --development-csv ../../../docs/sources/035-judge-v2-2026-11-09/development_data/FULL_4200_9cols_PROPOSALS_NOT_GOLD.csv
```

Нужны свободные output directories. Полная документация, config, budget,
policy approval и human import — [JUDGE_V2.md](../../JUDGE_V2.md).

## Ограничения и следующие внешние решения

1. Подписанный active registry не предоставлен. Ручное утверждение доступно, но
   ни одного signer пользователя/лида система не придумала. Нельзя применять
   тестовые подписи как production policy.
2. Human golden отсутствует. Качество двух reasoning-вызовов, устойчивость модели
   к prompt injection, coverage/false allow не измерены. Stage2-on-gold требует
   отдельного контролируемого model experiment; evaluate показывает unavailable.
3. Bashlex имеет неподдержанный синтаксис; parser facts частичные. Он не доказывает
   CLI-семантику и ничего не исполняет. Mock — exact fixture replay.
4. Семантические конфликты естественноязычных rules и достоверность human
   attestations требуют человеческого review. Validator ловит structural/ref/
   identical-condition конфликты, а не доказывает непротиворечивость всей политики.
5. Реальный HTTP smoke не выполнялся: явного бюджета этого задания нет. Adapter
   проверен fake HTTP. Provider Batch API, distributed storage и Windows file
   locking не входят в этот MVP (используется POSIX fcntl).
6. Privacy detector ограничен известными secret shapes; внешние реальные логи
   предварительно обезличивает оператор. Полные trace/SQLite предназначены для
   локального review, общие ошибки не печатают raw команды/credentials.
7. CSV требует разрешённых полей и provenance; missing source/synthetic seed
   не выдумываются. Экспорт повторяемый и атомарный по файлу, не по всему каталогу.
8. Кэш только exact, по умолчанию off; CLI не объединяет БД разных runs.
   Ledger не обещает exactly-once API billing; actual invoice неизвестен.

## Policy issues

Исходные статусы handoff сохранены без фальшивых подписей. PI-19 согласован и
реализован. PI-01 и PI-03 остаются open в исходном issue register, хотя конкретные
ограничения CAT-5.1 и «unknown не ask» явно заданы текущим запросом/ТЗ и соблюдены.
Это отличие между нормативной рекомендацией в YAML и действующим контрактом
зафиксировано, а не молча устранено.

| ID | Вопрос | Статус источника |
| --- | --- | --- |
| PI-01 | Общий CAT-6 приоритет vs специальный CAT-5.1 для `curl URL | bash` | open |
| PI-02 | У части карточек нет однозначной трёхклассовой нормы | open |
| PI-03 | `ask` как одобрение vs замена неизвестности | open |
| PI-04 | CAT-7.3 разумные границы allow/ask | open |
| PI-05 | CAT-1.4 append RC vs CAT-8.2 persistence | open |
| PI-06 | CAT-2.2 single-file `restore` не всегда безопасен | open |
| PI-07 | CAT-2.3 narrow `git clean -fd path` всё равно удаляет | open |
| PI-08 | CAT-2.1 личная ветка и `--force-with-lease` | open |
| PI-09 | CAT-2.2 base ask vs более строгая трактовка Git discard | open |
| PI-10 | CAT-3.1 Terraform prod известен/неизвестен | open |
| PI-11 | CAT-5.1 trusted remote installer | open |
| PI-12 | CAT-6.1/6.2 unobservable code | open |
| PI-13 | CAT-7.2/7.4 большие объёмы ресурсов | open |
| PI-14 | CAT-8.1/8.2/8.3 external/untrusted key/code | open |
| PI-15 | CAT-9.1 недоверенный источник пакета | open |
| PI-16 | CAT-3.5 неполный пример Helm upgrade | open |
| PI-17 | CAT-1.5 tar traversal определяется архивом | open |
| PI-18 | CAT-0 vs риск safe counterpart без парной метадаты | open |
| PI-19 | «Самый опасный шаг» vs классы разных действий | agreed |
| PI-20 | Как назначать severity целой цепочке | open |
| PI-21 | Как выбрать один risk при равных class | open |

TECHNICALLY_RUNNABLE=true; ACTIVE_POLICY_READY=false; SEMANTICALLY_VALIDATED=false;
HUMAN_GOLD_AVAILABLE=false; SAFE_FOR_AUTOMATIC_GOLD_EXPORT=false.
