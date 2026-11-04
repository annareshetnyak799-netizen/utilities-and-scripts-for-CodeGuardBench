# Kaggle GPU pilot

Приватный технический пилот, отдельно от human-gold оценки. Начинать с двух
command-only диагностических записей и проверять фактическое устройство внутри
сессии. `enable_gpu=true` в metadata само по себе не подтверждает наличие CUDA.

Сборка самодостаточного notebook не вызывает сеть и не отправляет файлы:

```bash
python scripts/build_kaggle.py --input /path/to/command-only.jsonl --output /path/to/bundle --owner KAGGLE_USERNAME --model granite8b --limit 2
```

`--model qwen32b` создаёт второй вариант. Checkpoints и revisions закреплены
в builder. Вход имеет ровно `record_id,command`, максимум12 строк. Builder
отклоняет ожидаемые метки, описания и другое metadata; происхождение и право
передачи входных данных проверяет составитель до сборки. Эти диагностические
входы не становятся train-seeds и не являются новым независимым holdout.

Встроенный архив содержит только явно перечисленные Python-файлы judge,
два prompt-файла, config и вход. Приватные логи, credentials, reports и эталонные
ответы не включаются. Извлечение проверяет хеши и пути. Все shell-команды
входа остаются данными; Bash вызывается только с `-n` для проверки синтаксиса.

После проверки подготовленного notebook:

```bash
kaggle kernels push -p /path/to/bundle --accelerator NvidiaTeslaT4 -t 3600
kaggle kernels status KAGGLE_USERNAME/codeguard-judge-granite8b-smoke-20261104
kaggle kernels output KAGGLE_USERNAME/codeguard-judge-granite8b-smoke-20261104 -p /path/to/results
```

Metadata всегда private. `NvidiaTeslaT4` — официальный идентификатор T4×2;
фактический доступ аккаунта/выдача устройства проверяются по hardware.json,
`nvidia-smi`, device nodes и CUDA. Образ запрашивается latest, его фактический SHA
после запуска сохранять через `kernels pull -m`. Сборка не делает upload сама.

CUDA adapter использует NF4 double quant, FP16 compute, `device_map=auto`,
резерв2GiB на каждом GPU, без CPU/disk offload. Qwen32B требует два GPU и
суммарный бюджет весов23GiB; фактическая вместимость ещё требует GPU smoke.
Проверка свободного диска учитывает загрузку исходных весов до квантования:
75GiB для Qwen32B,20GiB для Granite8B. Cache идёт в `/kaggle/temp`, результаты —
в `/kaggle/working/codeguard_judge`. В notebook нет замены platform Torch.

Пакеты Python закреплены, фактические torch/CUDA/package versions, device map,
chat-template hash, входные/выходные токены и peak GPU memory записываются.
GPU токенизация использует `apply_chat_template(tokenize=True)`; это отдельный
runtime от исторического MPS adapter. NF4 и смена токенизации означают, что
сравнение с прежними результатами не изолирует только размер модели.

Изменение thinking/decoding требует нового экспериментального конфига. В
начальном пилоте greedy/non-thinking, максимум768 выходных токенов; достижение
лимита отмечается отдельно. Никакая конфигурация не объявлена оптимальной.

Notebook сохраняет raw outputs и receipt. `LIMIT` — число дополнительных
записей при resume; fingerprint защищает вход/config/code/prompts. Разные batch
сессии не разделяют рабочий каталог: для resume нужно явно восстановить
совпадающую предыдущую директорию `run`, а не просто поставить флаг.

Известные policy/schema/evaluation замечания аудита04.11 остаются открытыми.
Этот адаптер не устраняет их и не расширяет CAT-2 prompt до всей taxonomy.
Сначала инфраструктура, затем отдельная проверка качества и сравнение A/B.

Источники: [Kaggle kernels](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md),
[metadata](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels_metadata.md),
[подтверждение T4×2](https://github.com/Kaggle/kaggle-cli/issues/1196),
[bitsandbytes](https://huggingface.co/docs/transformers/quantization/bitsandbytes),
[Qwen3-32B](https://huggingface.co/Qwen/Qwen3-32B),
[Granite3.3-8B](https://huggingface.co/ibm-granite/granite-3.3-8b-instruct).
