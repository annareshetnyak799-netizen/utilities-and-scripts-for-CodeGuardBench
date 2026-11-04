# Baseline

Исходный опубликованный D3 — da1994434cd276355407de269ecea0d2283d916d. Перед новой работой сохранены прежние локальные изменения в d3ade73: GPU packaging, строгая полнота evaluation population. 56 прежних тестов. Отдельная ветка feat/d3-judge-cascade, main не менялся.

fdb99f8: шесть воспроизведённых красных тестов стали зелёными (62 всего): P999, handmade, unknown CAT, quoted pipeline, git -C, сравнение populations и exact leakage. Одна функция теста объединяет handmade/unknown CAT.

0bf406f: новая версия каскада внутри прежнего D3, 200 тестов (126 из них — transport fixtures, не семантические эталоны). Политика 42 кода, отдельные schema/ref/evidence guards, budget ledger, слепая оценка, CPU demo. `stage3_tests.txt` хранит receipt.

Предыдущие локальные Qwen3-1.7B/Qwen3-4B/Granite-2B прогоны 12/40 команд относятся к старой CAT-2 rubric. Они не являются сравнимой baseline текущего cross-team pilot: и входы, и policy различаются. Старые цифры не перенесены в новую таблицу. Legacy v1 позднее действительно прогнан на тех же32 ID с gpt-oss-120b (raw agreement34.375%); его другая policy/schema и протокол proposal-гейтинга отмечены отдельно. Qwen/v1 остановлен после повторных таймаутов, partial не scored.
