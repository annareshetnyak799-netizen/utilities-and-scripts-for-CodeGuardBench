#!/usr/bin/env python3
"""Build a text-only template catalogue; never execute the template sources."""
import argparse
import ast
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPO_URL = "https://github.com/annareshetnyak799-netizen/utilities-and-scripts-for-CodeGuardBench"
BASE_COMMIT = "438c9fec99ddb0285a031b7c78c3548dd2204e51"
SOURCE_COMMIT = "35dcf221b5f3fea94e06995c21e2a3ede3898d28"
GUIDELINE = "tools/d3-judge-pipeline/evidence/guideline.md"
PREFIX = HERE.relative_to(ROOT).as_posix()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(commit, path):
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)


def link(commit, path, first, last=None):
    suffix = f"#L{first}" + (f"-L{last}" if last and last != first else "")
    return f"{REPO_URL}/blob/{commit}/{path}{suffix}"


def split_items(text, category):
    # Keep slashed alternatives and clauses inside inline code together.
    # CAT-0 uses commas; all other template fields use semicolons.
    parts, current, in_code = [], [], False
    separator = "," if category == "CAT-0.0" else ";"
    for char in text:
        if char == "`":
            in_code = not in_code
        if char == separator and not in_code:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    parts.append("".join(current).strip())
    assert not in_code and all(parts)
    return parts


def plain(text):
    return re.sub(r"\\([+*\-])", r"\1", text.replace("`", ""))


def cell(text):
    return html.escape(str(text), quote=False).replace("|", "&#124;").replace("\n", "<br>")


def build():
    manifest = json.loads((HERE / "sources/manifest.json").read_text())
    for source in manifest["files"]:
        path = HERE / "sources" / source["snapshot_path"]
        data = path.read_bytes()
        assert digest(data) == source["sha256"], path
        assert data == git_blob(SOURCE_COMMIT, path.relative_to(ROOT).as_posix()), path
    notation_path = f"{PREFIX}/sources/notation.json"
    notation_bytes = (ROOT / notation_path).read_bytes()
    assert notation_bytes == git_blob(SOURCE_COMMIT, notation_path)
    notation = json.loads(notation_bytes)
    notation_lines = notation_bytes.decode().splitlines()
    notation_positions = {}
    for i, line in enumerate(notation_lines, 1):
        match = re.match(r'\s*"(B\d+)":', line)
        if match:
            notation_positions.setdefault(match[1], []).append(i)

    guideline_bytes = (ROOT / GUIDELINE).read_bytes()
    assert guideline_bytes == git_blob(BASE_COMMIT, GUIDELINE)
    rows, category_names, risk_names = [], {}, {}
    current = None
    definition = ""
    raw_template_fields = {}
    for number, line in enumerate(guideline_bytes.decode().splitlines(), 1):
        heading = re.match(r"### \*\*(CAT-\d+) · (.*?)\*\*", line)
        if heading:
            category_names[heading[1]] = re.sub(r"\s*`?\[PDF.*", "", heading[2]).strip()
        risk = re.match(r"\*\*(CAT-\d+\.\d+) (.*?)\*\*", line)
        if risk:
            current = risk[1]
            risk_names[current] = risk[2]
            definition = ""
        if line.startswith("* **Определение:**"):
            definition = plain(line.split("**Определение:**", 1)[1].strip())
        if not line.startswith("* **Шаблоны:**"):
            continue
        assert current and definition
        raw = line.split("**Шаблоны:**", 1)[1].strip()
        raw_template_fields[current] = raw
        for index, snippet in enumerate(split_items(raw, current), 1):
            rows.append({
                "id": f"{current}-GUIDE-{index:02}",
                "category": current.split(".")[0], "risk": current,
                "kind": "guideline_template", "title": risk_names[current],
                "template": plain(snippet[:-1] if snippet.endswith(".") else snippet), "description": definition,
                "source_text": snippet, "source_commit": BASE_COMMIT,
                "source_path": GUIDELINE, "source_line": number,
                "source_url": link(BASE_COMMIT, GUIDELINE, number),
                "origin": "guideline", "semantic_validation": False,
            })

    assert len(raw_template_fields) == 42
    # This is one row per source item, not per distinct syntax or executable command.
    assert len(rows) == 151
    for risk, raw in raw_template_fields.items():
        assert [r["source_text"] for r in rows if r["risk"] == risk] == split_items(raw, risk)

    libraries = [
        ("CAT-2.1", "train_synthetic_2026-11-11_cat21/axes.py"),
        ("CAT-2.2", "train_synthetic_2026-11-11_cat22/forms.py"),
        ("CAT-2.3", "train_synthetic_2026-11-11_cat23/forms.py"),
        ("CAT-2.4", "train_synthetic_2026-11-11_cat24/forms.py"),
        ("CAT-7.1", "train_synthetic_2026-11-19_cat7/forms.json"),
        ("CAT-7.3", "train_synthetic_2026-11-19_cat7/forms.json"),
        ("CAT-7.5", "train_synthetic_2026-11-19_cat7/forms.json"),
    ]
    for risk, rel in libraries:
        source_path = f"{PREFIX}/sources/{rel}"
        text = (ROOT / source_path).read_text()
        if rel.endswith(".py"):
            tree = ast.parse(text)
            assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == "FORMS" for t in node.targets)]
            assert len(assignments) == 1
            source_nodes = assignments[0].value.elts
            forms = []
            for node in source_nodes:
                fid, title, level, tags, construction, checks = ast.literal_eval(node)
                forms.append(dict(form_id=fid, title=title, level=level, tags=tags,
                                  construction=construction, checks=checks,
                                  source_line=node.lineno, source_end_line=node.end_lineno))
        else:
            forms = json.loads(text)
            positions = [i for i, line in enumerate(text.splitlines(), 1) if '"form_id":' in line]
            assert len(positions) == len(forms)
            for form, position in zip(forms, positions):
                form.update(source_line=position, source_end_line=position)
        assert len(forms) == 36
        assert [form["form_id"] for form in forms] == [f"B{i:02}" for i in range(1, 37)]
        for form in forms:
            fid = form["form_id"]
            special = risk.startswith("CAT-7.") and fid in notation["cat7_overrides"]
            schematic = (notation["cat7_overrides"] if special else notation["forms"])[fid]
            sketch_line = notation_positions[fid][-1 if special else 0]
            rows.append({
                "id": f"{risk}-FORM-{fid}", "category": risk.split(".")[0], "risk": risk,
                "kind": "author_form", "title": form["title"], "form_id": fid,
                "template": schematic, "description": form["checks"],
                "construction": form["construction"], "level": form["level"], "tags": form["tags"],
                "source_commit": SOURCE_COMMIT, "source_path": source_path,
                "source_line": form["source_line"], "source_end_line": form["source_end_line"],
                "source_url": link(SOURCE_COMMIT, source_path, form["source_line"], form["source_end_line"]),
                "notation_url": link(SOURCE_COMMIT, notation_path, sketch_line),
                "origin": "author_synthetic_form_library", "status": "draft",
                "semantic_validation": False,
            })

    common = notation["end_of_options"]
    common_line = next(i for i, s in enumerate(notation_lines, 1) if '"end_of_options":' in s)
    rows.append({
        "id": common["id"], "category": "COMMON", "risk": "COMMON", "kind": "syntax_note",
        "title": "Конец разбора опций", "template": common["template"],
        "description": common["description"], "origin": common["origin"],
        "source_commit": SOURCE_COMMIT, "source_path": notation_path, "source_line": common_line,
        "source_url": link(SOURCE_COMMIT, notation_path, common_line), "semantic_validation": False,
    })
    assert len(rows) == 404 and len({r["id"] for r in rows}) == 404
    assert sum(r["kind"] == "author_form" for r in rows) == 252
    for risk, _ in libraries:
        assert sum(r["risk"] == risk and r["kind"] == "author_form" for r in rows) == 36

    def order(row):
        if row["risk"] == "COMMON":
            return (10, 0, row["kind"], row["id"])
        a, b = row["risk"].removeprefix("CAT-").split(".")
        return (int(a), int(b), 0 if row["kind"] == "guideline_template" else 1, row["id"])

    rows.sort(key=order)
    counts = Counter(r["kind"] for r in rows)
    per_risk = {risk: dict(Counter(r["kind"] for r in rows if r["risk"] == risk)) for risk in risk_names}
    summary = {
        "date": "2026-11-19", "rows": len(rows), "by_kind": dict(counts),
        "taxonomy_categories": 10, "taxonomy_risks": len(risk_names), "by_risk": per_risk,
        "deduplication": False, "base_commit": BASE_COMMIT, "source_snapshot_commit": SOURCE_COMMIT,
        "guideline_sha256": digest(guideline_bytes), "source_snapshot_files_verified": len(manifest["files"]),
        "commands_executed": 0, "semantic_validation": False,
        "unit": "source template item / per-subcategory author form / common syntax note",
    }
    labels = {"guideline_template": "Гайдлайн", "author_form": "Авторская форма", "syntax_note": "Общий синтаксис"}
    table = ["# Общая таблица шаблонов CAT-0–CAT-9", "",
             "404 строки: 151 пункт гайдлайна + 252 авторские формы + 1 пояснение `--`. Повторы сохранены.", "",
             "Это каталог схем, не готовые команды или safety-метки. `<…>` и стрелки — метасинтаксис. "
             "[Состав и ограничения](README.md) · [Данные JSON](templates.json)", "",
             "| ID | Категория | Подкатегория | Тип | Шаблон в общем виде | Назначение / ограничения | Источник с коммитом |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        reference = f"[Источник {row['source_commit'][:7]}]({row['source_url']})"
        if "notation_url" in row:
            reference += f"<br>[Краткая схема]({row['notation_url']})"
        description = row["title"] + ". " + row["description"]
        table.append("| " + " | ".join([
            cell(row["id"]), cell(row["category"]), cell(row["risk"]), labels[row["kind"]],
            "<code>" + cell(row["template"]) + "</code>", cell(description), reference,
        ]) + " |")

    readme = ["# Общая таблица шаблонов", "",
              "[Открыть общую таблицу — 404 строки](TABLE.md)", "",
              "Собрано 19 ноября 2026 года по запросу: вся таксономия CAT-0–CAT-9 и авторские формы CAT-2/CAT-7. "
              "Каждый пункт и каждая подкатегория сохраняются отдельно. Дедупликации нет.", "",
              "| Состав | Строк | Единица учёта |", "| --- | ---: | --- |",
              "| Гайдлайн, все 42 подкатегории | 151 | Пункт поля «Шаблоны» исходной карточки |",
              "| Авторские формы CAT-2.1/2.2/2.3/2.4 | 144 | 36 форм на подкатегорию |",
              "| Авторские формы CAT-7.1/7.3/7.5 | 108 | 36 форм на подкатегорию |",
              "| Общий синтаксис `--` | 1 | Уточнение примера из запроса |",
              "| **Всего** | **404** | **Строки каталога, не уникальные механизмы или команды** |", "",
              "## Количество по подкатегориям", "",
              "| Подкатегория | Гайдлайн | Авторские формы | Всего |", "| --- | ---: | ---: | ---: |"]
    for risk, values in per_risk.items():
        a, b = values.get("guideline_template", 0), values.get("author_form", 0)
        readme.append(f"| {risk} | {a} | {b} | {a+b} |")
    readme += ["", "Общая строка `--` находится вне таксономии и прибавляется отдельно.", "",
               "## Что означает строка", "",
               "В гайдлайне пункты разделены точкой с запятой вне inline-кода; в CAT-0.0 — запятыми. "
               "Альтернативы через `/` и перечисления внутри одного пункта сохранены вместе ровно как в источнике. "
               "Это техническая граница строки, не объединение похожих шаблонов. Поле `source_text` в JSON сохраняет исходный пункт с разметкой. "
               "Контрпримеры, классы и severity из исторического гайдлайна не экспортируются как новые шаблоны или метки.", "",
               "Авторская форма — схема представления/исполнения: `$()`, `bash -c`, массив argv, alias, рекурсия, heredoc и другие. "
               "Одни и те же B01–B36 повторяются отдельными строками для каждой из семи подкатегорий. "
               "В CAT-7 формы B22/B23 используют shell aliases вместо Git aliases. Краткие схемы созданы для этого каталога; "
               "полные инструкции и проверки сохранены в источниках и JSON. Схемы с `<КОД>`, `<АРГУМЕНТЫ>` и стрелками — "
               "метасинтаксис, а не исполняемые примеры. Переводы строк в aliases и heredoc значимы.", "",
               "`--` обычно завершает разбор опций у поддерживающих его утилит; он не завершает выполнение команды. "
               "Его поддержка и позиция зависят от конкретной утилиты. Эта строка добавлена по примеру пользователя, не выдана за найденный внешний шаблон.", "",
               "## Происхождение и ограничения", "",
               f"Гайдлайн взят из [evidence/guideline.md]({link(BASE_COMMIT, GUIDELINE, 1)}) "
               f"на коммите `{BASE_COMMIT}` указанной пользователем ветки. Файл совпадает с локальным исходником S003. "
               "Таблица передаёт содержимое поля «Шаблоны», а не утверждает актуальность исторической политики классов.", "",
               f"[Авторские библиотеки]({REPO_URL}/tree/{SOURCE_COMMIT}/{PREFIX}/sources) впервые закреплены здесь "
               f"коммитом `{SOURCE_COMMIT}`. Это ссылка на публикацию авторского снимка, а не свидетельство заимствования "
               "из внешнего репозитория. Пять исходных файлов сохранены побайтно; их SHA256 и относительные пути находятся в `sources/manifest.json`. "
               "CAT-2.1 хранит формы внутри axes.py; соседние сценарии в этом снимке не увеличивают число строк каталога.", "",
               "404 строки не равны 8 910 seed-заданиям или 248 базовым сценариям. Матрица сценарий × форма и результаты "
               "модельных прогонов не входят в таблицу. Наличие формы в каталоге не означает совместимости с каждым сценарием: "
               "в банках есть исключённые сочетания. Авторские формы сохраняют статус draft; семантическая валидация и "
               "независимость семейств от test не подтверждены. Safety-класс по одному совпадению с шаблоном не назначается. "
               "Каталог не предназначен для допуска в train/few-shot: он включает справочные шаблоны гайдлайна и не является изолированным train-банком.", "",
               "## Форматы и воспроизводимость", "",
               "- [TABLE.md](TABLE.md) — одна общая таблица для просмотра на GitHub.",
               "- [templates.json](templates.json) — те же 404 строки с полными контрактами форм и ссылками.",
               "- [summary.json](summary.json) — точные счётчики и контрольные данные.",
               "- `sources/` — закреплённые библиотеки и обозначения.", "",
               "Из этого каталога в Git checkout:", "", "```bash", "python3 build.py --check", "```", "",
               "Для пересборки: `python3 build.py`. Нужны Python 3.9+ и Git с обоими указанными коммитами; внешние пакеты не нужны. "
               "Исходные Python-библиотеки читаются через AST/literal_eval, шаблоны не исполняются. Проверка сверяет "
               "снимки с Git, SHA256, все исходные пункты, 36 форм на каждую подкатегорию, число строк и побайтовую воспроизводимость."]
    return {"TABLE.md": "\n".join(table)+"\n", "README.md": "\n".join(readme)+"\n",
            "templates.json": json.dumps(rows, ensure_ascii=False, indent=2)+"\n",
            "summary.json": json.dumps(summary, ensure_ascii=False, indent=2)+"\n"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build()
    for name, text in outputs.items():
        path = HERE / name
        if args.check:
            assert path.read_bytes() == text.encode(), f"Not reproducible: {name}"
        else:
            path.write_text(text, encoding="utf-8")
    print(json.dumps({"mode": "check" if args.check else "build", "rows": 404,
                      "artifacts": list(outputs), "status": "pass"}))


if __name__ == "__main__":
    main()
