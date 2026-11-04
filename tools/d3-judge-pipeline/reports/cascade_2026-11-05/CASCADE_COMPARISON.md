# Сравнение архитектур, слепой diagnostic pilot

Одинаковые 32 ID из 16 peer risk codes, command-only. Selection фиксирован до запросов; по две строки на risk с разными метками при наличии. Это стратифицированный стресс-пилот, не оценка генеральной совокупности. Данные ранее обсуждались в проекте: historical diagnostic, не pristine holdout. Human gold=0.

| Архитектура | Agreement, все32 | Coverage | Agreement raw proposal | Calls | RUB estimate |
|---|---:|---:|---:|---:|---:|
| rules | 6.2% | 6.2% | 6.2% | 0 | 0.000 |
| single | 21.9% | 31.2% | 28.1% | 26 | 3.088 |
| static_single | 9.4% | 9.4% | 18.8% | 26 | 3.042 |
| reasoning_single | 40.6% | 59.4% | 43.8% | 26 | 2.038 |
| critic_cascade | 15.6% | 21.9% | 25.0% | 36 | 3.823 |
| specialists | 3.1% | 3.1% | 6.2% | 33 | 3.193 |
| semantic_cascade | 12.5% | 12.5% | 25.0% | 63 | 4.175 |

Raw proposal — schema-valid ответ первого классификатора до фильтра контекста/критика; final agreement — после этих проверок. Abstain остаётся в знаменателе. Рост отказов не доказывает рост качества. False-allow здесь означает расхождение с существующей меткой, не подтверждённый вред.

Single/static/critic/specialists используют Qwen3-32B первым классификатором; reasoning_single — gpt-oss-120b. semantic_cascade дополнительно вызывает semantic stage Qwen, затем classifier Qwen, затем critic gpt-oss. Specialists — предсказание generalist определяет CAT карточки независимому gpt-oss. Ошибка router может перенестись на специалиста; это измеряемое ограничение.

Все calls — реальные; модель может не вызываться из-за синтаксиса/неизвестного executable. Частоты schema failures, provider errors, category breakdown, confusion и disagreements лежат в каталогах каждого run. Reasoning tokens взяты из usage; hidden chain of thought не сохранялся.

Sampling seed и temperature не фиксировались: использованы defaults провайдера. Повторные classifier calls в архитектурах не идентичны. Поэтому это пилот работы маршрутов, не чистая причинная оценка выигрыша каждого этапа. Для чистой static ablation используйте replay одного сохранённого ответа.

Ни одного human gold примера нет, лидер по качеству не выбран. Не использовать эту таблицу для автоматического приёма новых gold-меток.

Legacy v1 с gpt-oss-120b действительно прогнан на тех же32 ID: raw annotation agreement 34.4%, raw coverage 40.6%. Его CAT-2-only policy/schema и правила gating отличаются; он вынесен отдельно (`legacy_v1_reasoning/annotation_agreement.json`), не скрыто объединён в matched-policy comparison.

Legacy v1/Qwen сохранён как PARTIAL_NOT_SCORED после повторных provider timeouts; INTERRUPTED.json фиксирует число обработанных строк. Static replay использует те же ответы single, без новых вызовов: experiments/static_replay/replay_receipt.json. Один ID изменён правилом. Usage replay не прибавляется к затратам.
