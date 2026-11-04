# Разбор отказов и разногласий

Все counts ниже получены из сохранённых ответов, не из впечатлений. Ошибка метки коллег или judge не устанавливается автоматически.

| Ошибка валидации | Calls |
|---|---:|
| inapplicable_policy_ref | 30 |
| missing_prediction_basis | 27 |
| schema:type | 20 |
| schema:required | 20 |
| schema:enum | 14 |
| nonliteral_evidence | 13 |
| missing_review_flag | 11 |
| schema:additionalProperties | 6 |
| provider_transport_timeout | 1 |

Schema failures: модели иногда возвращают недопустимый тип/enum или policy refs без соответствующего primary risk. Nonliteral evidence: пересказ вместо точной подстроки. Missing_review_flag: модель указывает missing_context, но не ставит review. Все такие ответы не получают финальную action label.

Unknown executable — консервативный gate, а не доказательство опасности. KNOWN список неполон; это уменьшает coverage даже для известных человеку утилит. Bashlex unsupported также не равен unsafe.

Наблюдаемые расхождения следует рассматривать в порядке: (1) ошибка формата/модели, (2) видимость контекста, (3) конфликт правил, (4) curated counterexample risk, (5) возможная ошибка reference. Без человека не сводить их к одной accuracy.

Полный построчный файл: all_disagreements_and_decisions.csv. Для слепого человека: human_review/blind_review.jsonl; reference_key не показывать до первого решения.

Начать калибровку с 52 карточек. Не менять prompts по текущему holdout после просмотра этих ответов; следующую версию проверять на новом заранее замороженном наборе.
