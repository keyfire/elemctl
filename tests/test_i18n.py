"""Двуязычный вывод: целостность каталога и выбор языка.

Каталог собирается из словаря MESSAGES при импорте модуля i18n, поэтому проверки
покрывают каждое пользовательское сообщение elemctl.
"""

from __future__ import annotations

import string

import pytest

from elemctl import i18n

_FORMATTER = string.Formatter()


def _fields(template: str) -> list[str]:
    """Имена полей шаблона. Удвоенная скобка – литерал и полей не даёт."""
    return sorted({name for _, name, _, _ in _FORMATTER.parse(template) if name})


@pytest.fixture(autouse=True)
def _restore_lang():
    """Эти тесты двигают язык; остальная сюита ожидает русский."""
    yield
    i18n.set_lang("ru")


# --- Целостность каталога -------------------------------------------------------------

def test_catalog_is_not_empty():
    assert i18n.registered_keys()


def test_every_key_carries_every_language():
    for key in i18n.registered_keys():
        entry = i18n.translations(key)
        for lang in i18n.LANGS:
            assert entry.get(lang, "").strip(), f"{key}: нет текста '{lang}'"


def test_placeholders_are_the_same_in_every_language():
    """Поле, которое есть в одном языке и отсутствует в другом, – это KeyError в рантайме."""
    for key in i18n.registered_keys():
        entry = i18n.translations(key)
        fields = {lang: _fields(entry[lang]) for lang in i18n.LANGS}
        distinct = {tuple(v) for v in fields.values()}
        assert len(distinct) == 1, f"{key}: плейсхолдеры различаются между языками: {fields}"


def test_every_template_can_be_formatted():
    """Ловит лишнюю скобку: t() всегда форматирует, поэтому литеральная скобка удваивается."""
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
    """Все поля – ASCII-идентификаторы; кириллическое 'поле' обычно означает неудвоенную скобку."""
    for key in i18n.registered_keys():
        for lang in i18n.LANGS:
            for name in _fields(i18n.translations(key)[lang]):
                assert name.isascii() and name.isidentifier(), f"{key} [{lang}]: странное поле '{name}'"


def test_translations_actually_differ_between_languages():
    """Защита от 'en', скопированного из 'ru': большинство сообщений должно различаться."""
    same = [
        key
        for key in i18n.registered_keys()
        if i18n.translations(key)["ru"] == i18n.translations(key)["en"]
    ]
    # Единичные совпадения возможны (например, короткие технические строки), но не массово.
    assert len(same) <= 1, f"слишком много одинаковых в обоих языках: {same}"


# --- Поиск ----------------------------------------------------------------------------

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
    i18n.register({"тест.повтор": {"ru": "текст", "en": "text"}})  # идентичное – можно
    with pytest.raises(i18n.MessageError, match="already registered"):
        i18n.register({"тест.повтор": {"ru": "другое", "en": "other"}})


# --- Выбор языка ----------------------------------------------------------------------

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
