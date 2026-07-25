"""The command reference (docs/cli*.md) and its generator.

Defects that once lived in the reference all at the same time and escaped the eye:
arguments with no help, English descriptions in the Russian version, subcommand
sections lost by the parsing, and a page silently going stale after a flag was edited.
Each item is held down by a test of its own.
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
    """(command path, parser) for the whole subcommand tree."""
    yield path, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from walk(sub, f"{path} {name}")


def actions_with_help(parser: argparse.ArgumentParser):
    """Help entries of a parser: both the arguments and the items of the subcommand list."""
    for action in parser._actions:
        if action.help == argparse.SUPPRESS:
            continue
        if isinstance(action, argparse._SubParsersAction):
            for choice in action._choices_actions:
                yield choice.dest, choice.help
        else:
            yield action.dest, action.help


def test_every_argument_has_help():
    # a bare APP_ID without a single word in the table – exactly how the empty cell looked
    for path, parser in walk(cli.build_parser()):
        for dest, help_text in actions_with_help(parser):
            assert help_text and help_text.strip(), f"{path}: аргумент {dest} без help"


def test_russian_help_is_russian():
    # argparse's own texts (-h, group titles) come out in English unless they are
    # translated; we catch that by the absence of Cyrillic in any description of the Russian build
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
    # the language changes the texts but not the shape: the set of commands and arguments must match
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
    # page sections are generated per command and per subcommand; the root is the common-flags section
    return {path for path, _ in walk(cli.build_parser()) if path != "elemctl"}


def test_pages_cover_every_subcommand():
    # group subcommands (apps get, builds upload) used to drop out of the parsing entirely:
    # 17 sections instead of 46 – and not a single page said a word about it
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
    # the generator is the source of truth; a divergence means the page went stale silently
    # after a flag was edited
    for fname, text in generated.items():
        committed = (DOCS / fname).read_text(encoding="utf-8")
        assert committed == text, (
            f"{fname} устарел: перегенерируйте python scripts/gen-cli-docs.py"
        )
