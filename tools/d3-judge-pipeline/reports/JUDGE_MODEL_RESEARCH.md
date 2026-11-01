# Открытые модели для judge: проверка 01.11.2026

Это shortlist для эксперимента, не рейтинг безопасности Bash. Model cards
сохранены с revision и SHA256 в evidence/model_cards; фактические вызовы
отделены от паспортных возможностей. Open-weight не означает открытый pretrain.

| Семейство / checkpoint | Лицензия и контекст по card | Роль и ограничения |
|---|---|---|
| [Qwen2.5-Coder-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct) | Apache2;32768 штатно, расширение до131072 с YaRN | Кодовая instruct-модель; не запускалась в этом пилоте |
| [Granite3.3-8B-Instruct](https://huggingface.co/ibm-granite/granite-3.3-8b-instruct) | Apache2;128K | Иное семейство, instruction/coding; 8B не запускался |
| [Devstral-Small-2507](https://huggingface.co/mistralai/Devstral-Small-2507) | Apache2;24B,128K | Кодовый агент; больше памяти; не запускался |
| [Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) | Apache2;32768 | Реальный локальный smoke, слабый контроль схемы |
| [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B) | Локальный checkpoint, точная revision в конфиге | Реальный пилот; то же семейство, не независимый второй judge |
| [Granite3.3-2B-Instruct](https://huggingface.co/ibm-granite/granite-3.3-2b-instruct) | Apache2;128K | Компактный кандидат для доступного независимого второго семейства |

Локальный runtime: Apple Silicon48GiB, PyTorch2.11.0, Transformers5.1.0,
MPS. Model calls cache-only после отдельного download. У сервера нет платы
за API-вызов; электричество и аппаратные расходы не измерялись. Удалённые
цены/rate limits не приписываются локальным моделям. Общие API-кандидаты из
ночного задания не выбраны вместо предпочтения пользователя открытых моделей.

JSON в model card не является гарантией соблюдения нашей схемы. HF-адаптер
использует обычный decode+строгую валидацию; constrained decoding в нём
не реализован. OpenAI-compatible адаптер умеет JSON-object запрос к локальному
vLLM/llama.cpp, но поддержку сервером нужно проверить отдельно. Invalid JSON,
schema error и несовпадение evidence ведут в очередь, не в автоматический ask.

Single+rules дешевле и проще для диагностики. Dual разных семейств повышает
число выявленных расхождений, но не доказывает истинность согласованных ответов.
Семейство генератора и guard нужно фиксировать до включения синтетики в train.
Qwen-generated proposals нельзя считать независимо проверенными только Qwen.

40 handmade calibration drafts не имеют независимого human gold. Метрики по
ним — диагностическое согласие с предложениями агента, не оценка качества
настоящего теста. Этот набор не экспортируется в selected/train. После
человеческого lock требуется отдельный untouched holdout для выбора модели.
