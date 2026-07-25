"""Bilingual output: catalog integrity and language selection.

The catalog is assembled out of the MESSAGES dictionary when the i18n module is imported,
so these checks cover every user-facing message of elemctl.
"""

from __future__ import annotations

import re
import string
from pathlib import Path

import pytest

from elemctl import i18n

_FORMATTER = string.Formatter()


def _fields(template: str) -> list[str]:
    """Field names of a template. A doubled brace is a literal and yields no field."""
    return sorted({name for _, name, _, _ in _FORMATTER.parse(template) if name})


@pytest.fixture(autouse=True)
def _restore_lang():
    """These tests move the language around; the rest of the suite expects Russian."""
    yield
    i18n.set_lang("ru")


# --- Catalog integrity ------------------------------------------------------------------

def test_catalog_is_not_empty():
    assert i18n.registered_keys()


def test_every_key_carries_every_language():
    for key in i18n.registered_keys():
        entry = i18n.translations(key)
        for lang in i18n.LANGS:
            assert entry.get(lang, "").strip(), f"{key}: нет текста '{lang}'"


def test_placeholders_are_the_same_in_every_language():
    """A field present in one language and missing in another is a KeyError at runtime."""
    for key in i18n.registered_keys():
        entry = i18n.translations(key)
        fields = {lang: _fields(entry[lang]) for lang in i18n.LANGS}
        distinct = {tuple(v) for v in fields.values()}
        assert len(distinct) == 1, f"{key}: плейсхолдеры различаются между языками: {fields}"


def test_every_template_can_be_formatted():
    """Catches a stray brace: t() always formats, so a literal brace has to be doubled."""
    for key in i18n.registered_keys():
        entry = i18n.translations(key)
        for lang in i18n.LANGS:
            template = entry[lang]
            dummy = dict.fromkeys(_fields(template), "X")
            try:
                template.format(**dummy)
            except (IndexError, KeyError, ValueError) as exc:
                pytest.fail(f"{key} [{lang}]: {type(exc).__name__}: {exc} || {template}")


def test_field_names_are_plain_ascii_identifiers():
    """Every field is an ASCII identifier; a Cyrillic 'field' usually means an undoubled brace."""
    for key in i18n.registered_keys():
        for lang in i18n.LANGS:
            for name in _fields(i18n.translations(key)[lang]):
                assert name.isascii() and name.isidentifier(), f"{key} [{lang}]: странное поле '{name}'"


def test_translations_actually_differ_between_languages():
    """Guards against an 'en' copied over from 'ru': most messages have to differ."""
    same = [
        key
        for key in i18n.registered_keys()
        if i18n.translations(key)["ru"] == i18n.translations(key)["en"]
    ]
    # A one-off match is possible (a short technical string, say), but not en masse.
    assert len(same) <= 1, f"слишком много одинаковых в обоих языках: {same}"


# --- Lookup ---------------------------------------------------------------------------

def test_unknown_key_is_returned_as_is():
    assert i18n.t("нет.такого.ключа") == "нет.такого.ключа"


def test_fields_are_substituted():
    i18n.set_lang("en")
    assert i18n.t("cli.build-file-not-found", path="/tmp/x.xasm") == "build file not found: /tmp/x.xasm"


def test_language_switches_between_ru_and_en():
    i18n.set_lang("ru")
    assert i18n.t("deploy.verify-failed") == "проверка НЕ пройдена"
    i18n.set_lang("en")
    assert i18n.t("deploy.verify-failed") == "verification FAILED"


def test_register_rejects_a_missing_language():
    with pytest.raises(i18n.MessageError, match="no translation"):
        i18n.register({"тест.ключ": {"ru": "текст"}})


def test_register_rejects_a_conflicting_redefinition():
    i18n.register({"тест.повтор": {"ru": "текст", "en": "text"}})
    i18n.register({"тест.повтор": {"ru": "текст", "en": "text"}})  # identical – allowed
    with pytest.raises(i18n.MessageError, match="already registered"):
        i18n.register({"тест.повтор": {"ru": "другое", "en": "other"}})


# --- Language selection -----------------------------------------------------------------

def test_set_lang_rejects_an_unknown_language():
    with pytest.raises(i18n.MessageError, match="Unknown language"):
        i18n.set_lang("de")


def test_env_is_used_when_nothing_is_pinned(monkeypatch):
    i18n.set_lang(None)
    monkeypatch.setenv("ELEMCTL_LANG", "en")
    assert i18n.current_lang() == "en"


def test_pinned_language_wins_over_env(monkeypatch):
    monkeypatch.setenv("ELEMCTL_LANG", "en")
    i18n.set_lang("ru")
    assert i18n.current_lang() == "ru"


def test_falls_back_to_russian(monkeypatch):
    i18n.set_lang(None)
    monkeypatch.delenv("ELEMCTL_LANG", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.setattr(i18n._locale, "getlocale", lambda *a: (None, None))
    assert i18n.current_lang() == i18n.DEFAULT_LANG == "ru"


def test_system_locale_is_recognised(monkeypatch):
    i18n.set_lang(None)
    monkeypatch.delenv("ELEMCTL_LANG", raising=False)
    monkeypatch.setattr(i18n._locale, "getlocale", lambda *a: ("English_United States", "1252"))
    assert i18n.current_lang() == "en"


# --- Prescan of --lang in argv (the help is built before parsing) -----------------------

def test_lang_from_argv_reads_separate_value():
    assert i18n.lang_from_argv(["--lang", "en", "apps", "list"]) == "en"


def test_lang_from_argv_reads_equals_form():
    assert i18n.lang_from_argv(["--lang=ru", "deploy"]) == "ru"


def test_lang_from_argv_is_none_without_flag():
    assert i18n.lang_from_argv(["apps", "list"]) is None


def test_lang_from_argv_rejects_unknown_value():
    # An unknown language is not pinned – argparse rejects it later with its own message.
    assert i18n.lang_from_argv(["--lang", "de"]) is None


def test_lang_from_argv_ignores_dangling_flag():
    assert i18n.lang_from_argv(["apps", "--lang"]) is None


def test_no_russian_string_literals_outside_the_catalog():
    """User-facing strings live in the catalog, not as literals in the modules.

    A Russian literal built into a module bypasses the catalog, so `--lang en`
    keeps printing Russian to an English-speaking user. The check walks the AST
    of every module and looks for Cyrillic in string constants that are neither
    docstrings nor platform identifiers.

    The exceptions are deliberate: the catalog itself holds the translations,
    and mcp_server keeps the Russian tool descriptions and the INSTRUCTIONS
    literal the agent reads.
    """
    import ast

    # Platform keys, file names and property values quoted as they are.
    platform_literals = {
        "Проект.yaml", "Assembly.yaml", "Подсистема.yaml", "Ресурсы", "Глобально",
        "ВПодсистеме", "Имя", "Поставщик", "Версия", "ВидПроекта", "Библиотека",
        "ВидЭлемента", "ОбластьВидимости", "РежимСовместимости", "Представление",
        "библиотека", "приложение",
    }
    package = Path(i18n.__file__).parent
    offenders = []
    for module in sorted(package.glob("*.py")):
        if module.name in ("i18n.py", "mcp_server.py"):
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings or node.value.strip() in platform_literals:
                continue
            if re.search(r"[А-Яа-яЁё]", node.value):
                offenders.append(f"{module.name}:{node.lineno}: {node.value[:60]}")
    assert not offenders, "Russian literals outside the catalog:\n" + "\n".join(offenders)
