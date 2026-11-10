# Применение обновления Judge v2 — 09.11.2026

Из пользовательского `CodeGuardBench_Judge_v2_Changed_Files_2026-11-09.zip`
применены все 8 файлов кода, промптов и тестов с сохранением относительных путей.
Структура соответствует корню `tools/d3-judge-pipeline`, а не корню utilities.
Существующие изменения не потеряны: заменённые версии сохранены в центральном
`docs/sources/036-judge-v2-changes-2026-11-09/before/`. Там же сохранены исходный ZIP,
все 10 входящих файлов и INGEST_MANIFEST.json с SHA256. APPLY_AND_TEST.md и
CHANGES.diff сохранены как документация источника, а не исполняемые инструкции.

## Поведение и исправление

- Активированы оба промпта v2; контракт judge-v2-contract-2. Stage 1 получает и
  валидирует 30 кодов CAT-0–6 вместо 42. Исходный справочник 42 сохранён; поэтому
  policy report-gaps всё ещё перечисляет 42 категории. Это явное изменение
  скоупа относительно S035, применённое по текущему запросу на обновление.
- Известный эффект без риска допустим только с unresolved. Известный риск с
  неизвестным payload/target передаётся в Stage 2, где может соответствовать
  active approved rule. При существенном недостатке контекста остаётся review.
- Если ни у одного действия нет риска, S2 skipped/no_identified_risk. В смешанной
  команде неизвестные действия сохраняются и не превращаются в allow.
- Первый полный pytest выявил оставшийся в MockProvider безусловный запрет
  выбора правила при unresolved. Он удалён: mock воспроизводит только явно
  заданный fixture rule_id, присутствующий среди предложенных active правил.
  Классификации произвольных команд или автоматической активации правил нет.
- Дополнительно проверены явные missing_context/policy_gap, известный эффект без
  риска, смешанная цепочка deny+unknown и конечные ретраи для CAT вне скоупа.
  Обновлён JUDGE_V2.md. [Пофайловые hashes](CHANGED_FILES.json).

## Проверки

**319 passed in 6.22s**: 107 тестов v2 и 212 прежних. Команда `python -m pytest -q`
в корне проекта обнаружила и выполнила весь набор. [Результаты](TEST_RESULTS.txt).
Compileall и git diff --check прошли. Registry валиден, active rules=0.

[Offline benchmark](BENCHMARK.json): последовательные и параллельные 100 строк
дали одинаковые результаты; peak inflight=16. На 1000 строках завершены 2000
mock-вызовов, очереди не превысили 2/2, стадии разных строк перекрывались.
Crash после durable S1: после resume S1 calls=0, S2 calls=1. Повторный resume
завершённого прогона не вызвал provider.

CLI smoke: 23 строки, 45 mock-вызовов (23 S1 + 22 S2), 0 format/transport errors.
После CLI resume число вызовов осталось 45, все 23 результата сохранены.
Одно дополнительное обращение S2 по сравнению со старым smoke ожидаемо:
известный риск с unknown_payload теперь проходит policy evaluation.
Все 23 результата остаются needs_review, proposals=0, human_approved=0,
поскольку штатный registry содержит только draft. Реальных API-вызовов нет.

## Воспроизведение

Из `utilities-and-scripts-for-CodeGuardBench/tools/d3-judge-pipeline`, в окружении
с установленным `pip install -e '.[test]'`:

```bash
python -m pytest -q
python -m compileall -q codeguard_judge_v2 tests/v2
judge-v2 policy validate
judge-v2 run --mock --input examples/v2/input.jsonl --config configs/v2/mock.yaml \
  --output-dir /tmp/judge-v2-patch-new --run-id patch-smoke
judge-v2 resume --output-dir /tmp/judge-v2-patch-new --run-id patch-smoke
python scripts/demo_v2.py --output-dir /tmp/judge-v2-patch-benchmark-new
```

Для run/demo нужны свободные output-dir. Проверенные локальные прогоны находятся
в `/tmp/codeguard-v2-patch-20261109-cli` и `/tmp/codeguard-v2-patch-20261109-demo`.

## Границы результата

Новые hashes кода, схем, промптов и taxonomy делают resume старых runs новой
версией несовместимым; для них нужен прежний снимок проекта. Предыдущий экспортный
ZIP и отчёт S035 сохранены без изменений и не описывают это обновление.

Active rules=0, human gold=0, semantic_validation=false. Тесты и mock не измеряют
качество LLM. PI-20/21 и прочие открытые policy issues не объявлены решёнными.
Bash-команды корпуса не исполнялись; платные запросы не выполнялись.
Изменения локальны в feat/d3-judge-v2; commit/push/merge в этом задании не выполнялись.
