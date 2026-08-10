#!/usr/bin/env python
"""Generation of the command reference (docs/cli.md and docs/cli.ru.md) from the CLI itself.

The source of truth is the output of `elemctl ... --help`, so the reference never drifts
away from the implementation: a flag added – a page regenerated. Run it after the set of
commands or their options changes:

    python scripts/gen-cli-docs.py

The result is committed to the repository: the site build does not need Python.

The --help output is not put into the page as is: the usage line goes as a code block
(highlighting belongs there), while the lists of flags and commands are parsed into tables.
Raw text inside a ```text block comes out as a grey sheet, and bash highlighting colours
random words in it, the Russian descriptions included.
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
            "Общие флаги принимаются в любой позиции – и до команды, и после неё: "
            "`elemctl --timeout 120 apps list` и `elemctl apps list --timeout 120` "
            "равнозначны. Язык вывода переключается флагом `--lang`, переменной "
            "`ELEMCTL_LANG` или берётся из локали системы."
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
            "Common flags are accepted in any position – before the command and "
            "after it: `elemctl --timeout 120 apps list` and `elemctl apps list "
            "--timeout 120` are the same run. The output language follows `--lang`, "
            "the `ELEMCTL_LANG` variable, or the system locale."
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
    # ELEMCTL_NO_PLUGINS: the reference describes the core, and the core alone.
    # Plugins bring subcommands of their own, and the page must not depend on what
    # happens to be installed on the machine of whoever regenerates it.
    env = dict(
        os.environ,
        PYTHONPATH=str(SRC),
        ELEMCTL_LANG=lang,
        COLUMNS="100",
        ELEMCTL_NO_PLUGINS="1",
    )
    # The timeout is mandatory: a command that does not handle --help starts the server
    # itself and waits for input instead of printing the help – without a limit the
    # documentation generation hangs.
    try:
        out = subprocess.run(
            [sys.executable, "-m", "elemctl.cli", *args, "--help"],
            capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return ""          # no help – the section of such a command simply does not appear
    return (out.stdout or out.stderr).rstrip()


def parse(help_text: str) -> dict:
    """Parse the argparse output: the usage line, the description and the sections with entries."""
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
            # A blank line in the epilog is a paragraph boundary; without it a wrap inside
            # a paragraph would turn one sentence into two.
            if epilog and epilog[-1]:
                epilog.append("")
        elif current:
            m = ENTRY_RE.match(line)
            if m and not line.startswith(" " * 6):
                # The indent tells the group metavariable (2) from the nested commands (4).
                indent = len(line) - len(line.lstrip(" "))
                entries.append([m.group(1).strip(), (m.group(2) or "").strip(), indent])
            elif not line.startswith(" "):
                # Text at zero indent is already the parser epilog and not a wrapped
                # description: otherwise it gets glued to the last entry of the table.
                if epilog and epilog[-1]:
                    epilog[-1] += " " + line.strip()
                else:
                    epilog.append(line.strip())
            elif entries:                                  # wrapped description of the previous entry
                prev, tail = entries[-1][1], line.strip()
                # argparse wraps a long word on a hyphen (`--write-\nbaseline`) – such a wrap
                # is glued without a space, otherwise the flag inside the description breaks.
                glue = "" if prev.endswith("-") and tail[:1].isalnum() else " "
                entries[-1][1] = (prev + glue + tail).strip()
        i += 1
    if current:
        sections.append((current, entries))
    return {"usage": "\n".join(usage), "description": " ".join(description),
            "sections": sections, "epilog": epilog}


def esc(s: str) -> str:
    """An option name – it goes inside backticks, so only the pipe has to be escaped."""
    return s.replace("|", "\\|")


def esc_text(s: str) -> str:
    """Plain text: Markdown takes angle brackets for a tag and swallows them together with
    the contents (`elemctl <command>` turns into `elemctl`), while the theme typography glues
    a double hyphen into a dash – the flag `--select` mentioned in a description becomes a
    broken `–select`. Inside backticks neither of the two happens."""
    s = s.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
    return FLAG_RE.sub(r"`\1`", s)


def children(entries: list, i: int) -> list[int]:
    """Indexes of the entries nested under entry i: a deeper indent, up to the end of the group.

    argparse prints a group of nested commands on two levels: the metavariable itself
    (`{a,b}` or a name set through metavar) without a description and with a smaller
    indent, and the subcommands under it.
    """
    out = []
    for j in range(i + 1, len(entries)):
        if entries[j][2] <= entries[i][2]:
            break
        out.append(j)
    return out


def stubs(entries: list) -> set[int]:
    """Indexes of service rows: the group metavariable and the description-less rows under it.

    The first one is an argparse stub, the second is a continuation of prose (in xbsl the
    group heading is followed by a comma-separated list of commands broken into lines).
    Both are redundant in the table.
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
    """Names of the nested commands: from a named group or from nesting under a metavariable."""
    p = parse(help_text)
    named = [e for title, entries in p["sections"] if title.lower() in ("команды", "commands")
             for e in entries]
    if named:
        return [e[0].split()[0] for e in named if re.match(r"^[a-z][\w-]*$", e[0].split()[0])]
    # A group without a heading of its own: the subcommands stand under the metavariable with
    # a deeper indent. The ellipsis in usage tells nested parsers from a positional argument
    # with a list of values.
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
        # For a command without a parser of its own --help returns the common text: its
        # section would become a copy of the beginning of the page, and the parsing would
        # find the whole list of commands in it again (this is where sections like
        # "elemctl lint lint" came from).
        first = cmd_help.splitlines()[0] if cmd_help.strip() else ""
        if "elemctl " + name not in first:
            continue
        out.write(f"## `elemctl {name}`\n\n" + render(cmd_help, t))
        for sub in subcommands(cmd_help):
            out.write(f"### `elemctl {name} {sub}`\n\n" + render(run([name, sub], lang), t))
    return out.getvalue()


def generate() -> dict[str, str]:
    """File name -> page contents; built without writing to disk (the tests need that)."""
    return {fname: page(lang) for lang, fname in (("en", "cli.md"), ("ru", "cli.ru.md"))}


def main() -> None:
    for fname, text in generate().items():
        (ROOT / "docs" / fname).write_text(text, encoding="utf-8", newline="")
        print(f"{fname}: {len(text.splitlines())} lines")


if __name__ == "__main__":
    main()
