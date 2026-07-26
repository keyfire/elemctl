"""Tests of the destructive-schema-change detector (no network, no platform)."""

from __future__ import annotations

from elemctl.schema import narrowing_changes, parse_attributes

BEFORE = """\
ВидЭлемента: Справочник
Имя: Абоненты
Реквизиты:
    -
        Имя: Наименование
    -
        Ид: a2b3c4d5-e6f7-4081-9a2b-3c4d5e6f7a81
        Имя: ИдКопии
        Тип: Строка
        МаксимальнаяДлина: 128
    -
        Ид: b1b3c4d5-e6f7-4081-9a2b-3c4d5e6f7a82
        Имя: Код
        Тип: Число
        Длина: 12
Формы:
    - Основная
"""


def test_attributes_are_keyed_by_id_so_a_rename_is_not_a_new_attribute():
    """The platform maps attributes by Ид - a rename under the same Ид keeps the data."""
    attributes = parse_attributes(BEFORE)
    key = "a2b3c4d5-e6f7-4081-9a2b-3c4d5e6f7a81"
    assert attributes[key]["name"] == "ИдКопии"
    assert attributes[key]["length"] == 128
    assert attributes["b1b3c4d5-e6f7-4081-9a2b-3c4d5e6f7a82"]["length"] == 12
    # An attribute with no Ид is keyed by its name.
    assert "Наименование" in attributes


def test_the_block_ends_at_the_next_top_level_key():
    """`Формы:` is not an attribute - the block must not swallow the rest of the file."""
    assert "Основная" not in parse_attributes(BEFORE)


def test_a_narrowed_length_is_reported():
    after = BEFORE.replace("МаксимальнаяДлина: 128", "МаксимальнаяДлина: 64")
    changes = narrowing_changes(BEFORE, after, where="Абоненты.yaml")
    assert len(changes) == 1
    assert "ИдКопии" in changes[0] and "128" in changes[0] and "64" in changes[0]


def test_a_widened_length_is_silent():
    """Widening keeps the data - it is not the dangerous class."""
    after = BEFORE.replace("МаксимальнаяДлина: 128", "МаксимальнаяДлина: 256")
    assert narrowing_changes(BEFORE, after) == []


def test_a_changed_type_is_reported():
    after = BEFORE.replace("Тип: Число\n        Длина: 12", "Тип: Строка\n        Длина: 12")
    changes = narrowing_changes(BEFORE, after)
    assert len(changes) == 1 and "Код" in changes[0]


def test_a_rename_under_the_same_id_is_silent():
    after = BEFORE.replace("Имя: ИдКопии", "Имя: ИдентификаторКопии")
    assert narrowing_changes(BEFORE, after) == []


def test_an_unchanged_description_is_silent():
    assert narrowing_changes(BEFORE, BEFORE) == []


def test_a_description_without_attributes_is_silent():
    """No block - nothing to judge; the guard keeps quiet rather than inventing a change."""
    assert parse_attributes("ВидЭлемента: КомпонентИнтерфейса\nИмя: Форма\n") == {}
    assert narrowing_changes("Имя: Форма\n", "Имя: Форма\n") == []
