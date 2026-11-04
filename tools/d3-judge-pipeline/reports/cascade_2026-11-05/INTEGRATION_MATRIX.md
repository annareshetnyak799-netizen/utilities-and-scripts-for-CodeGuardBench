# Интеграция без переписывания коллег

| Владелец / компонент | Что используем | Реализованный стык | Что остаётся |
|---|---|---|---|
| Влад, cgen 22bb3ab | split/seed/family/provenance, этапы clean/dedup/validate, flags dictionaries | `scripts/adapt_candidates.py --kind d1`: validated JSONL → blind inputs + provenance; warnings/class/risk не попадают модели | Исправления upstream flags_unchecked Git, quoted whitespace и снятия backticks не внесены. cgen CSV остаётся proposals, не gold. |
| Анна, D2 9dfa379 | native tool request, privacy filters, exact dedup, lossless origin map | `--kind d2`: только owner_privacy_approved; иначе quarantine без текста. test_only в sidecar | functions.exec→tools.exec_command JS extraction остаётся прежним локальным прототипом; полноценный перенос в D2 не сделан. Private логи не отправлялись в API. |
| Анна, CAT-1.1 0417159 / CAT-1.3 c6534c5 | публичные команды + sources, разные утилиты | read-only Git blob ingest; участвовали в blind pilot и полном rules/mock проходе | source linkage/minimal-pair validity нуждаются в human review; внешние sources не становятся training prompts |
| Татьяна, CAT-3 2b1801f | 250 test строк, explicit provenance/queues | 5 подкатегорий в оценке; labels присоединены после inference | разрушение infra vs approval, невидимые manifest/plan требуют политики |
| Александр, CAT-4 a3c33eb | 1250 test +1250 train | train из оценки исключён; test modify/defer исключены; нестандартный source сохранён как ingest issue | CSV source taxonomy требует согласования; данные не меняли |
| D3 прежний da19944 | static/parser, schema/io/adapters, legacy HF и экспорт | расширение внутри существующего tools/d3; legacy API/тесты сохранены | старый GPU notebook не объявляется работающим; новый CLI не требует его |

Пример (из установленного d3 окружения с `PYTHONPATH=.`):

```bash
python scripts/adapt_candidates.py --kind d1 --input validated.jsonl --output d1-for-judge
codeguard-judge annotate --input d1-for-judge/blind_inputs.jsonl --config config.json --output run-new
```

D1 обязательно должен принести `split` в каждой строке: если исходный validated.jsonl хранит его только в config/manifest, объединить отдельно с этим манифестом, не угадывать. family_id/provenance не влияют на вердикт модели. D2 owner approval означает только приватность, не правильность метки; внешняя отправка требует отдельно разрешённого сценария.

В CI: установить пакет, pytest, CPU demo в новом каталоге; discovery/evaluation на fixture blobs. Платные эксперименты — отдельная opt-in job, ключ только через credential_file, один ledger на весь бюджет. Никакой auto-accept при consensus. `codeguard-judge export` требует связанный с hash команды human_lock, reviewer/date/evidence/policy и provenance для real/local. Реальных human locks в этом этапе нет.
