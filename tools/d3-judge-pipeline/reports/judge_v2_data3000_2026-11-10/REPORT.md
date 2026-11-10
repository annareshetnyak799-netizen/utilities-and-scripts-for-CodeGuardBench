# Development-набор Judge v2: 3000 строк, 10.11.2026

По прямому запросу пользователя актуальный набор 4200 заменён на предоставленный
`CodeGuardBench_v0_3000_latest.csv`. Рабочая копия:
`development_data/CodeGuardBench_v0_3000_latest.csv` в корне проекта Judge.
Оригинал сохранён побайтно в центральном sources/037; SHA256 и распределения —
[DATA_MANIFEST.json](DATA_MANIFEST.json).

3000 уникальных непустых команд, 9 ожидаемых колонок, 30 рисков CAT-0–6 по 100
строк. Исходные метки:1474allow/492ask/1034deny; source=synthetic у всех строк.
Метки не переутверждены, в prompts не передаются, human gold отсутствует.

В scripts/demo_v2.py заменены имя прогона на development3000 и проверка количества
на 3000. Обновлены JUDGE_V2.md и README.md с рабочим путём и командой. Старый
исходник 4200, отчёты о фактических прошлых прогонах и экспортный ZIP сохранены;
их исторические числа намеренно не переписаны. Новый ZIP не собирался.

Проверки: `python -m pytest -q` — **319 passed in 7.99s**.
Полный offline demo завершён; [BENCHMARK.json](BENCHMARK.json).
3000 строк сохранены ровно по одному разу, 3000 вызовов S1 + 2 S2. Остальные2998
команд отсутствуют в exact mock fixtures и получают review с пропуском S2.
Это не полноценная двухстадийная LLM-разметка. Все3000 результатов needs_review,
proposals0, active rules0, human gold0. Повторный resume не добавляет вызовов.
Демо также проверило serial/parallel100, bounded1000 и crash/resume.
Платных запросов и исполнения Bash-команд нет. Commit/push не выполнялись.

Из корня проекта:

```bash
python -m pytest -q
python scripts/demo_v2.py --output-dir /tmp/judge-v2-data3000-new \
  --development-csv development_data/CodeGuardBench_v0_3000_latest.csv
```

Output-dir должен быть новым. Фактический проверенный прогон сохранён локально
в `/tmp/codeguard-v2-development3000-20261110`.
