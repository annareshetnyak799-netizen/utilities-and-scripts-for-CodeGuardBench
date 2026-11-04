# Прогресс по этапам

- d3ade73: сохранён предыдущий незакоммиченный GPU/evaluation этап; не выдан за работающий GPU inference.
- fdb99f8: red→green регрессии, source registry42, исходный NIGHT SPEC сохранён побайтно. 62 tests.
- 0bf406f: рабочий CLI/Python API, policy compiler, semantic/classifier/critic/optional arbiter, без исполнения команд, budget ledger, blind cross-repo ingestion/evaluation, 200 tests.
- Чистая wheel-установка на Python3.11.9 и demo из /tmp выполнены; expected==actual.
- discovery_v2: 3425 canonical строк (1250 train, 2175 test); 1975 v0 test. 200 test modify/defer исключены явно. Source anomalies сохранены.
- Полный rules+mock прогон 1975: результаты, disagreements и метрики на диске; никаких human gold утверждений.
- Реальные Qwen3-32B / gpt-oss-120b эксперименты: фиксированные32 peer команды, семь вариантов включая rules. Сводка пересобирается summarize_cascade.py после окончания прогонов.
- Отдельный реальный probe42 authored mechanisms: не смешивается с peer datasets или human accuracy.
- 52 blind human review cards; человек ещё не разметил ни одной. Human gold0, финальных CSV-export0.
- CLI adapters D1/D2 и проверки конкурирующих writers/budget; integration_tests.txt хранит текущий результат.

Статусы финальной готовности и завершённые прогоны — в HANDOFF_2026-11-05.md, а не в этой промежуточной записи.
