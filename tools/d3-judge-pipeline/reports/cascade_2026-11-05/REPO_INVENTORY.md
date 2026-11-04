# Инвентаризация репозиториев 05.11.2026

Remote refs обновлены HTTPS fetch; checkout/main/CSV коллег не менялись. Worktrees CAT-2 — рабочие копии тех же datasets, не дополнительные независимые тесты. Исторический worktrees/d3-judge не использовался как место разработки.

| Repo | Branch | Commit | Canonical CSV / rows |
|---|---|---|---|
| code_guard_benchmark | origin | a490ee6ed49b60a3104bf0da5496bd72d90ebe29 | нет |
| code_guard_benchmark | origin/feat/data_CAT-1.1 | 041715941872c99e1956bc13d871b91c180ab971 | CAT-1.1/commands.csv (250) |
| code_guard_benchmark | origin/feat/data_CAT-1.3 | c6534c5f95a926ae08bed19b3a9f1176556924c5 | CAT-1.3/commands.csv (250) |
| code_guard_benchmark | origin/feat/data_CAT-2.1 | ccab2348dd349ded9921a0e3ea703e591abf1002 | CAT-2.1/commands.csv (31) |
| code_guard_benchmark | origin/feat/data_CAT-2.2 | e0f96b88466ee1be3955b35c92e6dfced5f68230 | CAT-2.2/commands.csv (69) |
| code_guard_benchmark | origin/feat/data_CAT-2.3 | 9f81aa3aa8d22ad0a730a6b09f706a5ecb0f1b4f | CAT-2.3/commands.csv (35) |
| code_guard_benchmark | origin/feat/data_CAT-2.4 | e39df55d8827bbfc9990cfc67d26232aa107e77c | CAT-2.4/commands.csv (40) |
| code_guard_benchmark | origin/feat/data_CAT-3 | 2b1801fe9eea015b89b1e6a4aa59b0fd4bc56d45 | CAT-3/commands.csv (250) |
| code_guard_benchmark | origin/feat/data_CAT-4 | a3c33ebe0c1082cb8d9e092c04837411d1985367 | CAT-4/commands_test.csv (1250); CAT-4/commands_train.csv (1250) |
| code_guard_benchmark | origin/feat/generation-pipeline | 22bb3ab4ec108c75aaeac26a72a27067e1d40c0f | нет |
| code_guard_benchmark | origin/main | a490ee6ed49b60a3104bf0da5496bd72d90ebe29 | нет |
| utilities-and-scripts-for-CodeGuardBench | origin | 034c058e87a9e6a6aaae79ac989487b068bb1d53 | нет |
| utilities-and-scripts-for-CodeGuardBench | origin/feat/d2-local-log-collector | 9dfa379afb022098cf89118fba70d19bab244cda | нет |
| utilities-and-scripts-for-CodeGuardBench | origin/feat/d3-judge-pipeline | da1994434cd276355407de269ecea0d2283d916d | нет |
| utilities-and-scripts-for-CodeGuardBench | origin/main | 034c058e87a9e6a6aaae79ac989487b068bb1d53 | нет |

Всего canonical строк: 3425. Train: 1250. Test: 2175. V0-совместимых test для оценки: 1975.

Source, не входящий в enum, сохраняется в оригинале и отмечается ingest issue; он не подменяется real. В частности CAT-4 использует gtfobins:URL. Это НЕ валидный экспорт commands.csv, но допустимый diagnostic reference для class/risk. Modify/defer не переназначались, из оценки исключены.

CAT-0, CAT-1.2/1.4/1.5, CAT-5–9: peer test rows отсутствуют в доступных ветках. Нули явно сохранены в TAXONOMY_COVERAGE.csv. Fixtures не выданы за данные коллег.

Все Git blobs сохранены SHA256-именами в discovery_v2/snapshots. record_id=SHA256(repository, commit, path, physical CSV row, command). Data refs и blind inputs разделены; freeze хранится experiments/freeze.json. Historical diagnostic, не pristine holdout.

Первый discovery/ оставлен для аудита: он чрезмерно исключал nonconforming source; inference на нём не запускался. Актуален discovery_v2/.
