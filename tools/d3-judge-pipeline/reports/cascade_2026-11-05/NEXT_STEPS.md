# Следующие PR после демонстрации

1. **Human calibration и политика (P0).** Разобрать 52 blind карточки, сначала без reference/model labels; отдельно связать все 43 исторических CAT-2.2 с решением лида. Done: reviewer/date/evidence, независимые метки и resolved policy IDs. Риск: согласие с моделью вместо самостоятельного решения.
2. **Строгий structured output и evidence (P0).** Проверить поддерживаемый провайдерами JSON Schema constrained decoding; stage-specific validator + bounded repair на новом dev-наборе. Done: снижение форматных отказов без роста false-allow на независимом gold. Текущий holdout не использовать для подгонки промпта.
3. **Командная семантика и unknown utilities (P1).** Typed utility adapters с версиями, global flags Git, вложенные wrappers, literal variable resolution. Done: неизвестная опция никогда не становится confident allow; regression cases отдельно от peer eval. Риск: whitelist превращается в ложное разрешение.
4. **Контракт cgen→D3 (P1).** Sidecar split/family/provenance; Git flags_unchecked, точный dedup без изменения кавычек, semantic-clean quarantine, min-pair generation. Done: независимые seed families не пересекаются, proposals не выглядят как gold CSV. Изменения согласуются через отдельный PR коллегам.
5. **D2 Codex extraction (P1).** Перенести протестированный JS-literal extractor функций exec, exclusion CodeBench, privacy-owner gate. Done: golden extraction fixtures и сохранение native tool-call boundary. Real/local остаются test-only; приватные логи не становятся API inputs автоматически.
6. **Выбор архитектуры (P1).** Повторный frozen experiment с одинаковыми базовыми ответами/параметрами sampling и отдельным calibration gold. Done: cost/coverage/false-allow сравнимы, CI рассчитаны по независимым семействам. Per-CAT specialists оценить отдельно от общей смены модели.

Никакой новый сбор «до250» не заменяет эти проверки. 250 строк с перестановкой путей не являются 250 механизмами.
