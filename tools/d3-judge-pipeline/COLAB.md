# Запуск judge в Google Colab

Через VS Code также поддерживается официальный Colab kernel. На компьютере
найдены `google.colab`0.9.7 и Jupyter. Сборка варианта для IDE:

```bash
python -m scripts.build_colab --input /path/to/command_only.jsonl --output /path/to/vscode_bundle --interface vscode
```

Откройте `CodeGuard_Granite8B_VSCode.ipynb`: Select Kernel → Colab → New Colab
Server → GPU/T4, войдите в Google и выберите Python kernel сервера, затем Run All.
При необходимости сначала нажмите Select Another Kernel. `Auto Connect`
не гарантирует GPU. ZIP скачивается через Colab → Contents → контекстное меню
файла → Download. Вариант IDE отключает `google.colab.files.download`, поскольку
этот web-механизм не поддерживается так же в VS Code. Кнопка Run All остаётся
действием пользователя: из текущего чата нет инструмента выполнения ячеек IDE.
Открыть локальный файл через VS Code CLI можно; это не подключает GPU kernel.
[Официальное руководство](https://github.com/googlecolab/colab-vscode/wiki/User-Guide),
[ограничения](https://github.com/googlecolab/colab-vscode/wiki/Known-Issues-and-Workarounds).

Первый прогон: Granite 3.3 8B Instruct, NF4/FP16, одна CUDA GPU, две команды.
Qwen32B из Kaggle-пакета не переносится автоматически на одну T4.
Веса и runtime должны реально поместиться в выданную GPU; это проверяется при запуске.

Из корня `tools/d3-judge-pipeline`:

```bash
python -m scripts.build_colab --input /path/to/command_only.jsonl --output /path/to/colab_bundle --limit 2
```

Вход: 1–12 JSONL-строк с единственными полями `record_id` и `command`.
Используйте утверждённый диагностический набор; не передавайте private логи
или эталонные ответы. Builder использует allowlist и детерминированный payload
из `scripts.build_kaggle`; Kaggle API, токен и аккаунт для Colab не нужны.

1. Откройте https://colab.research.google.com/ и выберите File → Upload notebook.
2. Загрузите `CodeGuard_Granite8B_Colab.ipynb`.
3. Runtime → Change runtime type → GPU (T4, если доступна).
4. Runtime → Run all. Первая ячейка покажет фактическое оборудование.
5. Сохраните автоматически предлагаемый `codeguard_colab_results.zip`.
   Если браузер блокирует скачивание: Files → `/content/codeguard_colab_results.zip` → Download.

Перед расширением до12 разберите результат первых двух команд. `LIMIT=12`
создаёт отдельный полный прогон `run_12`, повторяющий первые две команды.
Повтор с тем же LIMIT продолжает прежний прогон в той же живой среде;
новая сессия не восстанавливает его автоматически. Сохраняйте ZIP до отключения.

В notebook встроены код, промпты, фиксированный checkpoint/config и command-only
вход. Установка сохраняет версии платформенного Torch/audio/vision через constraints.
GPU-модель не заменяется молча на CPU. Ошибки inference также выгружаются в ZIP;
при ошибке до inference сохраните вывод ячейки и `hardware.json`, если он создан.
Скачанные веса, кеши и посторонние файлы в результат не включаются.

Сервис запускается через notebook UI. Плагин для управления Colab в текущем
окружении не найден; браузерное управление недоступно. Авторизация Google и
фактическое получение GPU не проверены. Builder ничего не публикует и не задаёт
права доступа в аккаунте; не включайте публичный sharing для передачи результатов.

Результат — диагностические предложения CAT-2, не human gold и не оценка полной
таксономии. Локальные тесты упаковки не заменяют реальный CUDA-прогон.
Бесплатные ресурсы могут быть недоступны, тип GPU и лимиты меняются:
[официальный FAQ Colab](https://research.google.com/colaboratory/faq.html).
