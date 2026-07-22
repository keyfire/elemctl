"""Справочник команд (docs/cli*.md) и его генератор.

Дефекты, которые уже жили в справочнике одновременно и не ловились глазом:
аргументы без help, английские описания в русской версии, разделы подкоманд,
потерянные разбором, и молча устаревшая страница после правки флага.
Каждый пункт держит свой тест.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path

import pytest

from elemctl import cli, i18n

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def walk(parser: argparse.ArgumentParser, path: str = "elemctl"):
    """(путь команды, парсер) для всего дерева подкоманд."""
    yield path, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from walk(sub, f"{path} {name}")


def actions_with_help(parser: argparse.ArgumentParser):
    """Записи справки парсера: и аргументы, и пункты перечня подкоманд."""
    for action in parser._actions:
        if action.help == argparse.SUPPRESS:
            continue
        if isinstance(action, argparse._SubParsersAction):
            for choice in action._choices_actions:
                yield choice.dest, choice.help
        else:
            yield action.dest, action.help


def test_every_argument_has_help():
    # голое APP_ID без единого слова в таблице - ровно так выглядела пустая клетка
    for path, parser in walk(cli.build_parser()):
        for dest, help_text in actions_with_help(parser):
            assert help_text and help_text.strip(), f"{path}: аргумент {dest} без help"


def test_russian_help_is_russian():
    # встроенные тексты argparse (-h, заголовки групп) приходят по-английски, если их
    # не перевести; ловим по отсутствию кириллицы в любом описании русской сборки
    i18n.set_lang("ru")
    try:
        for path, parser in walk(cli.build_parser()):
            for dest, help_text in actions_with_help(parser):
                assert CYRILLIC_RE.search(help_text or ""), (
                    f"{path}: аргумент {dest} в русской справке без кириллицы: {help_text!r}"
                )
    finally:
        i18n.set_lang("ru")


def test_parser_trees_match_between_languages():
    # язык меняет тексты, но не состав: набор команд и аргументов обязан совпадать
    def shape(lang: str) -> dict[str, list[str]]:
        i18n.set_lang(lang)
        try:
            return {
                path: [dest for dest, _ in actions_with_help(parser)]
                for path, parser in walk(cli.build_parser())
            }
        finally:
            i18n.set_lang("ru")

    assert shape("ru") == shape("en")


def page_sections(fname: str) -> set[str]:
    text = (DOCS / fname).read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^#{2,3} `(elemctl[^`]*)`", text, re.M)}


def command_paths() -> set[str]:
    # разделы страницы генерятся на команду и подкоманду; корень - раздел общих флагов
    return {path for path, _ in walk(cli.build_parser()) if path != "elemctl"}


def test_pages_cover_every_subcommand():
    # подкоманды групп (apps get, builds upload) выпадали из разбора целиком:
    # 17 разделов вместо 46 - и ни одна страница об этом не сообщала
    expected = command_paths()
    for fname in ("cli.md", "cli.ru.md"):
        missing = expected - page_sections(fname)
        assert not missing, f"{fname}: нет разделов {sorted(missing)}"


def test_page_sections_match_between_languages():
    assert page_sections("cli.md") == page_sections("cli.ru.md")


@pytest.fixture(scope="module")
def generated() -> dict[str, str]:
    spec = importlib.util.spec_from_file_location(
        "gen_cli_docs", ROOT / "scripts" / "gen-cli-docs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate()


def test_committed_pages_are_current(generated):
    # генератор - источник истины; разошлись - страница молча устарела после правки флага
    for fname, text in generated.items():
        committed = (DOCS / fname).read_text(encoding="utf-8")
        assert committed == text, (
            f"{fname} устарел: перегенерируйте python scripts/gen-cli-docs.py"
        )
