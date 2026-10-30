# D2, сбор локальных команд

Скрипт извлекает терминальные вызовы из локальных логов Codex, Claude Code и Cursor, маскирует чувствительные значения и объединяет повторы внутри сессии и контекста. Результат — неразмеченные данные для подготовки train. Команды из логов не исполняются.

Версия 0.2.0. Нужен Python 3.10+. Проверено на Python 3.13 и macOS, полный прогон на Linux и Windows пока не выполнен.

## Установка

Из корня репозитория перейти в папку скрипта:

```bash
cd tools/d2_collect
```

Если используется ZIP, распаковать его и открыть папку `d2_collect`.

macOS и Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp profile.example.json my-profile.json
```

Windows, PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item profile.example.json my-profile.json
```

В `my-profile.json` заменить примеры своими значениями:

- `person_names` — имена, фамилии и варианты написания.
- `private_literals` — личные логины, названия приватных проектов и другие идентификаторы.

Если значений нет, оставить пустые списки `[]`. Домашний путь и имя локального аккаунта определяются автоматически. Системные пути и флаги команд в профиль не добавлять. Сам профиль оставить у себя.

## Запуск

macOS и Linux:

```bash
.venv/bin/python collect_logs.py discover
.venv/bin/python collect_logs.py collect --output ~/d2-output --profile my-profile.json
```

Windows, PowerShell:

```powershell
.venv\Scripts\python.exe collect_logs.py discover
.venv\Scripts\python.exe collect_logs.py collect --output "$env:USERPROFILE\d2-output" --profile my-profile.json
```

`discover` показывает найденные источники. `collect` обрабатывает их и сохраняет результат. Для `--output` нужен новый приватный каталог вне репозитория и общей облачной папки. При повторном сборе указать другое имя, например `d2-output-new`. Существующий каталог не перезаписывается. На Windows доступ к каталогу нужно ограничить средствами системы.

По умолчанию обрабатываются все три агента. Для выбора источников добавить `--providers claude` или `--providers codex,cursor`. Нестандартный каталог Cursor задаётся через `--cursor-user-dir`. Логи работы над benchmark исключать через `--exclude-project ИМЯ_ПРОЕКТА`. Остальные параметры доступны через `--help`.

## Результат и передача

В указанном каталоге появятся:

- `handoff.zip` — пакет для передачи.
- `share/commands.jsonl` — обезличенные команды с происхождением и статусами.
- `share/report.json` — количество записей, пропуски и причины карантина.
- `private/` — ключ маскирования и локальная карта происхождения.

Перед отправкой просмотреть `share/commands.jsonl` и отчёт. Автоматическое маскирование не гарантирует обнаружение всех личных данных. Если остались приватные значения, дополнить профиль и повторить сбор в новый каталог.

Передать только `handoff.zip`. Профиль, каталог `private` и исходные логи оставить у себя. Обезличенные результаты также не добавлять в репозиторий со скриптом.

Спорные команды отправляются в локальный карантин. Неподдержанные форматы и JS-обёртки Codex учитываются в отчёте и не попадают в пакет. Общая дедупликация выполняется после объединения пакетов участников, финальная разметка относится к D3.

## Проверка скрипта

macOS и Linux:

```bash
.venv/bin/python -m unittest discover -s tests
```

Windows, PowerShell:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
```
