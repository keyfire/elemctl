#!/usr/bin/env python
"""Генерация справочника команд (docs/cli.md и docs/cli.ru.md) из самого CLI.

Источник истины – вывод `elemctl ... --help`, поэтому справочник не расходится с
реализацией: добавили флаг – перегенерировали страницу. Запускать после изменения
состава команд или их параметров:

    python scripts/gen-cli-docs.py

Результат коммитится в репозиторий: сборке сайта Python не нужен.

Вывод --help не кладётся в страницу как есть: строка usage идёт блоком кода (там
подсветка к месту), а перечни флагов и команд разбираются в таблицы. Сырой текст в
блоке ```text выходит серой простынёй, а подсветка bash красит в нём случайные слова,
включая русские описания.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

TEXT = {
    "ru": {
        "title": "Команды",
        "desc": "Справочник команд и параметров elemctl: общие флаги, приложения, сборки, деплой и всё остальное.",
        "label": "Команды",
        "intro": (
            "Справочник собран из самого инструмента – это то же, что показывает "
            "`elemctl --help`, только на одной странице и целиком.\n\n"
            "Общие флаги ставятся до команды: `elemctl --timeout 120 apps list`. "
            "Язык вывода переключается флагом `--lang`, переменной `ELEMCTL_LANG` "
            "или берётся из локали системы."
        ),
        "common": "Общие флаги",
        "col_opt": "Параметр",
        "col_desc": "Описание",
        "col_cmd": "Команда",
        "sections": {"options": "Параметры", "positional arguments": "Аргументы"},
    },
    "en": {
        "title": "Commands",
        "desc": "Reference of elemctl commands and options: common flags, applications, builds, deploy and the rest.",
        "label": "Commands",
        "intro": (
            "This reference is generated from the tool itself – the same text "
            "`elemctl --help` prints, gathered on one page.\n\n"
            "Common flags go before the command: `elemctl --timeout 120 apps list`. "
            "The output language follows `--lang`, the `ELEMCTL_LANG` variable, or "
            "the system locale."
        ),
        "common": "Common flags",
        "col_opt": "Option",
        "col_desc": "Description",
        "col_cmd": "Command",
        "sections": {"options": "Options", "positional arguments": "Arguments"},
    },
}

SECTION_RE = re.compile(
    r"^(options|positional arguments|commands|параметры|аргументы|команды)\s*:\s*$", re.I)
ENTRY_RE = re.compile(r"^\s{2,4}(\S.*?)(?:\s{2,}(.*))?$")
CHOICES_RE = re.compile(r"^\{([\w,-]+)\}$")
SUBPARSERS_RE = re.compile(r"\{([\w,-]+)\}\s*\.\.\.")
FLAG_RE = re.compile(r"(?<![\w`-])(--?[a-zA-Z][\w-]*)")


def run(args: list[str], lang: str) -> str:
    env = dict(os.environ, PYTHONPATH=str(SRC), ELEMCTL_LANG=lang, COLUMNS="100")
    # Таймаут обязателен: команда, которая не разбирает --help, вместо справки запускает
    # сам сервер и ждёт ввода – без ограничения генерация документации зависает.
    try:
        out = subprocess.run(
            [sys.executable, "-m", "elemctl.cli", *args, "--help"],
            capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return ""          # справки нет – раздел такой команды просто не появится
    return (out.stdout or out.stderr).rstrip()


def parse(help_text: str) -> dict:
    """Разбираем вывод argparse: строка usage, описание и секции с записями."""
    lines = help_text.split("\n")
    usage, i = [], 0
    while i < len(lines) and (not usage or lines[i].startswith(" ")) and lines[i].strip():
        usage.append(lines[i]); i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    description = []
    while i < len(lines) and lines[i].strip() and not SECTION_RE.match(lines[i].strip()):
        description.append(lines[i].strip()); i += 1

    sections, current, entries, epilog = [], None, [], []
    while i < len(lines):
        line = lines[i]
        if SECTION_RE.match(line.strip()):
            if current:
                sections.append((current, entries))
            current, entries = line.strip().rstrip(":"), []
        elif not line.strip():
            # Пустая строка в эпилоге - граница абзаца; без неё перенос внутри абзаца
            # превратил бы одно предложение в два.
            if epilog and epilog[-1]:
                epilog.append("")
        elif current:
            m = ENTRY_RE.match(line)
            if m and not line.startswith(" " * 6):
                # Отступ отличает метапеременную группы (2) от самих вложенных команд (4).
                indent = len(line) - len(line.lstrip(" "))
                entries.append([m.group(1).strip(), (m.group(2) or "").strip(), indent])
            elif not line.startswith(" "):
                # Текст с нулевым отступом – это уже эпилог парсера, а не перенос описания:
                # иначе он приклеивается к последней записи таблицы.
                if epilog and epilog[-1]:
                    epilog[-1] += " " + line.strip()
                else:
                    epilog.append(line.strip())
            elif entries:                                  # перенос описания предыдущей записи
                prev, tail = entries[-1][1], line.strip()
                # argparse переносит длинное слово по дефису (`--write-\nbaseline`) –
                # такой перенос склеиваем без пробела, иначе флаг в описании рвётся.
                glue = "" if prev.endswith("-") and tail[:1].isalnum() else " "
                entries[-1][1] = (prev + glue + tail).strip()
        i += 1
    if current:
        sections.append((current, entries))
    return {"usage": "\n".join(usage), "description": " ".join(description),
            "sections": sections, "epilog": epilog}


def esc(s: str) -> str:
    """Имя параметра – оно идёт внутри обратных кавычек, экранировать нужно только черту."""
    return s.replace("|", "\\|")


def esc_text(s: str) -> str:
    """Обычный текст: угловые скобки Markdown принимает за тег и проглатывает вместе с
    содержимым (`elemctl <команда>` превращается в `elemctl`), а типографика темы склеивает
    двойной дефис в тире – упомянутый в описании флаг `--select` становится нерабочим
    `–select`. Внутри обратных кавычек ни то, ни другое не происходит."""
    s = s.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
    return FLAG_RE.sub(r"`\1`", s)


def children(entries: list, i: int) -> list[int]:
    """Индексы записей, вложенных под запись i: отступ больше, до конца группы.

    argparse печатает группу вложенных команд в два уровня: сама метапеременная
    (`{a,b}` или заданная через metavar `действие`) без описания и с меньшим отступом,
    а под ней – подкоманды.
    """
    out = []
    for j in range(i + 1, len(entries)):
        if entries[j][2] <= entries[i][2]:
            break
        out.append(j)
    return out


def stubs(entries: list) -> set[int]:
    """Индексы служебных строк: метапеременная группы и безописательные строки под ней.

    Первое – заглушка argparse, второе – продолжение прозы (у xbsl под заголовком группы
    идёт перечень команд через запятую, разбитый по строкам). В таблице лишние обе.
    """
    skip = set()
    for i, e in enumerate(entries):
        kids = children(entries, i) if not e[1] else []
        if not kids:
            continue
        skip.add(i)
        skip.update(j for j in kids if not entries[j][1])
    return skip


def render(help_text: str, t: dict) -> str:
    p = parse(help_text)
    out = io.StringIO()
    if p["description"]:
        out.write(esc_text(p["description"]) + "\n\n")
    out.write("```bash\n" + p["usage"] + "\n```\n\n")
    for title, entries in p["sections"]:
        if not entries:
            continue
        is_cmds = title.lower() in ("команды", "commands")
        head = t["col_cmd"] if is_cmds else t["col_opt"]
        name = t["sections"].get(title.lower(), title.capitalize())
        out.write(f"**{name}**\n\n")
        out.write(f"| {head} | {t['col_desc']} |\n|---|---|\n")
        skip = stubs(entries)
        for k, (opt, desc, _) in enumerate(entries):
            if k in skip:
                continue
            out.write(f"| `{esc(opt)}` | {esc_text(desc)} |\n")
        out.write("\n")
    for paragraph in p["epilog"]:
        if paragraph:
            out.write(esc_text(paragraph) + "\n\n")
    return out.getvalue()


def subcommands(help_text: str) -> list[str]:
    """Имена вложенных команд: из именованной группы или из вложенности под метапеременной."""
    p = parse(help_text)
    named = [e for title, entries in p["sections"] if title.lower() in ("команды", "commands")
             for e in entries]
    if named:
        return [e[0].split()[0] for e in named if re.match(r"^[a-z][\w-]*$", e[0].split()[0])]
    # Группа без своего заголовка: подкоманды стоят под метапеременной с бо́льшим отступом.
    # Многоточие в usage отличает вложенные парсеры от позиционного с перечнем значений.
    if "..." not in p["usage"]:
        return []
    for _, entries in p["sections"]:
        for i, e in enumerate(entries):
            kids = [entries[j][0].split()[0] for j in children(entries, i)] if not e[1] else []
            named = [n for n in kids if re.match(r"^[a-z][\w-]*$", n)]
            if named:
                return named
    return []


def page(lang: str) -> str:
    t = TEXT[lang]
    root_help = run([], lang)
    out = io.StringIO()
    out.write(
        f'---\ntitle: "{t["title"]}"\ndescription: "{t["desc"]}"\n'
        f'sidebar:\n  label: {t["label"]}\n  order: 3\n---\n\n'
    )
    out.write("<!-- Собрано из вывода `elemctl --help` скриптом scripts/gen-cli-docs.py. "
              "Не редактировать вручную. -->\n\n")
    out.write(t["intro"] + "\n\n")
    out.write(f"## {t['common']}\n\n" + render(root_help, t))
    for name in subcommands(root_help):
        cmd_help = run([name], lang)
        # У команды без своего парсера --help отдаёт общий текст: её раздел стал бы
        # копией начала страницы, а разбор нашёл бы в нём весь список команд заново
        # (отсюда брались разделы вида "elemctl lint lint").
        first = cmd_help.splitlines()[0] if cmd_help.strip() else ""
        if "elemctl " + name not in first:
            continue
        out.write(f"## `elemctl {name}`\n\n" + render(cmd_help, t))
        for sub in subcommands(cmd_help):
            out.write(f"### `elemctl {name} {sub}`\n\n" + render(run([name, sub], lang), t))
    return out.getvalue()


def generate() -> dict[str, str]:
    """Имя файла -> содержимое страницы; сборка без записи на диск (нужно тестам)."""
    return {fname: page(lang) for lang, fname in (("en", "cli.md"), ("ru", "cli.ru.md"))}


def main() -> None:
    for fname, text in generate().items():
        (ROOT / "docs" / fname).write_text(text, encoding="utf-8", newline="")
        print(f"{fname}: {len(text.splitlines())} строк")


if __name__ == "__main__":
    main()
