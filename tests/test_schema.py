"""Tests of the destructive-schema-change detector (no network, no platform)."""

from __future__ import annotations

from elemctl.schema import (
    narrowing_changes,
    parse_attributes,
    parse_block,
    parse_tabular_parts,
    removals,
    review_tree,
)

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


# -- the English spellings of the descriptor keys ---------------------------------

BEFORE_EN = """\
ElementKind: Catalog
Name: Subscribers
Attributes:
    -
        Name: Description
    -
        Id: a2b3c4d5-e6f7-4081-9a2b-3c4d5e6f7a81
        Name: CopyId
        Type: String
        MaxLength: 128
    -
        Id: b1b3c4d5-e6f7-4081-9a2b-3c4d5e6f7a82
        Name: Code
        Type: Number
        Length: 12
Forms:
    - Main
"""


def test_english_keys_are_read_on_a_par_with_the_russian_ones():
    """An English description is guarded too - the platform applies it just the same."""
    attributes = parse_attributes(BEFORE_EN)
    key = "a2b3c4d5-e6f7-4081-9a2b-3c4d5e6f7a81"
    assert attributes[key]["name"] == "CopyId"
    assert attributes[key]["length"] == 128
    assert "Description" in attributes
    assert "Main" not in attributes

    after = BEFORE_EN.replace("MaxLength: 128", "MaxLength: 64")
    changes = narrowing_changes(BEFORE_EN, after, where="Subscribers.yaml")
    assert len(changes) == 1
    assert "CopyId" in changes[0] and "128" in changes[0] and "64" in changes[0]


def test_a_translation_of_the_description_does_not_blind_the_guard():
    """The spellings switch, the Ид stays - a narrowing across the translation is seen.

    A project translated to English keeps the Ид of every attribute, so the guard
    maps the old Russian attribute onto its English self and still judges the
    lengths - the translation must not silently turn the check off. The type
    spellings are two names of one type (Строка = String), so the translation
    alone reports nothing.
    """
    after = BEFORE_EN.replace("MaxLength: 128", "MaxLength: 64")
    changes = narrowing_changes(BEFORE, after)
    assert len(changes) == 1
    assert "128" in changes[0] and "64" in changes[0]


def test_a_pure_translation_is_silent():
    """Translating a description changes no schema - the guard must not refuse it."""
    assert narrowing_changes(BEFORE, BEFORE_EN) == []
    # Nor name a removal: the standard Наименование has no Ид and becomes Description,
    # so across a translation only an Ид can say that an element is gone.
    assert removals(BEFORE, BEFORE_EN) == []


# -- registers: the records are keyed by the dimensions -------------------------

REGISTER = """\
ВидЭлемента: РегистрСведений
Ид: c7e72c67-35e8-4f24-adb6-39a729fda0db
Имя: СостоянияЗаказов
Измерения:
    -
        Ид: 9608ce45-3dd9-4e25-9437-5d61a0bbe4f9
        Имя: Пользователь
        Тип: Пользователи.Ссылка?
    -
        Ид: 89fb9e11-7d37-4f81-9361-4b7ef5576c89
        Имя: КлючОповещения
        Тип: Строка
        МаксимальнаяДлина: 50
Ресурсы:
    -
        Ид: e4fb211e-bad1-4dfa-98db-a5b0abbc701e
        Имя: ЗакрытоUtc
        Тип: ДатаВремя
"""


def test_a_changed_dimension_type_is_reported_with_its_consequence():
    """The platform converts the records, the values collapse and the keys stop being unique."""
    after = REGISTER.replace("Тип: Пользователи.Ссылка?", "Тип: Строка")
    changes = narrowing_changes(REGISTER, after, where="СостоянияЗаказов.yaml")
    assert len(changes) == 1
    assert "измерение" in changes[0] and "Пользователь" in changes[0]
    assert "неуникальности" in changes[0]


def test_a_removed_dimension_is_reported():
    after = REGISTER.replace(
        """    -
        Ид: 89fb9e11-7d37-4f81-9361-4b7ef5576c89
        Имя: КлючОповещения
        Тип: Строка
        МаксимальнаяДлина: 50
""",
        "",
    )
    changes = narrowing_changes(REGISTER, after, where="СостоянияЗаказов.yaml")
    assert len(changes) == 1
    assert "КлючОповещения" in changes[0] and "удалено" in changes[0]


def test_a_narrowed_dimension_length_is_reported():
    after = REGISTER.replace("МаксимальнаяДлина: 50", "МаксимальнаяДлина: 20")
    changes = narrowing_changes(REGISTER, after, where="СостоянияЗаказов.yaml")
    assert len(changes) == 1
    assert "измерение" in changes[0] and "50" in changes[0] and "20" in changes[0]


def test_a_changed_resource_type_is_reported_as_a_resource():
    after = REGISTER.replace("Тип: ДатаВремя", "Тип: Строка")
    changes = narrowing_changes(REGISTER, after, where="СостоянияЗаказов.yaml")
    assert len(changes) == 1
    assert "ресурс" in changes[0] and "ЗакрытоUtc" in changes[0]


def test_a_removed_resource_is_named_but_does_not_refuse():
    """Only a removed dimension refuses: it breaks the apply. A resource is simply gone."""
    after = REGISTER.replace(
        """    -
        Ид: e4fb211e-bad1-4dfa-98db-a5b0abbc701e
        Имя: ЗакрытоUtc
        Тип: ДатаВремя
""",
        "",
    )
    assert narrowing_changes(REGISTER, after) == []
    lines = removals(REGISTER, after, where="СостоянияЗаказов.yaml")
    assert len(lines) == 1
    assert "ресурс ЗакрытоUtc" in lines[0] and "СостоянияЗаказов" in lines[0]


def test_a_register_untouched_reports_nothing():
    assert narrowing_changes(REGISTER, REGISTER) == []


def test_a_renamed_dimension_under_the_same_id_is_not_a_removal():
    after = REGISTER.replace("Имя: КлючОповещения", "Имя: КодОповещения")
    assert narrowing_changes(REGISTER, after) == []


def test_an_added_dimension_is_not_reported_as_a_change():
    """Adding a key is the platform's own business - the guard judges losses only."""
    after = REGISTER.replace(
        "Ресурсы:",
        """    -
        Ид: 11111111-2222-4333-8444-555555555555
        Имя: Раздел
        Тип: Строка
Ресурсы:""",
    )
    assert narrowing_changes(REGISTER, after) == []


def test_the_english_spelling_of_the_dimension_block_is_read():
    before = """\
ElementKind: InformationRegister
Name: ClosedNotices
Dimensions:
    -
        Id: 9608ce45-3dd9-4e25-9437-5d61a0bbe4f9
        Name: NoticeKey
        Type: String
        MaxLength: 50
"""
    after = before.replace("Type: String", "Type: Number")
    changes = narrowing_changes(before, after, where="ClosedNotices.yaml")
    assert len(changes) == 1
    assert "NoticeKey" in changes[0]


# -- tabular parts: the server removes one with its rows and asks nothing ----------

TASKS = """\
ВидЭлемента: Справочник
Ид: 6f1d2c3b-4a59-4e68-8d7c-1b2a3c4d5e6f
Имя: Задачи
Реквизиты:
    -
        Имя: Наименование
        Длина: 250
    -
        Ид: 7a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d
        Имя: Срок
        Тип: Дата
ТабличныеЧасти:
    -
        Ид: 8b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e
        Имя: Шаги
        Реквизиты:
            -
                Ид: 9c4d5e6f-7a8b-4c9d-8e1f-2a3b4c5d6e7f
                Имя: Шаг
                Тип: Строка
                МаксимальнаяДлина: 100
            -
                Ид: 0d5e6f7a-8b9c-4d0e-9f2a-3b4c5d6e7f80
                Имя: Готово
                Тип: Булево
    -
        Ид: 1e6f7a8b-9c0d-4e1f-8a3b-4c5d6e7f8091
        Имя: Исполнители
        Реквизиты:
            -
                Ид: 2f7a8b9c-0d1e-4f2a-9b4c-5d6e7f809102
                Имя: Исполнитель
                Тип: Строка
Интерфейс:
    Объект:
        Форма: КарточкаЗадачи
"""

PERFORMERS = """\
    -
        Ид: 1e6f7a8b-9c0d-4e1f-8a3b-4c5d6e7f8091
        Имя: Исполнители
        Реквизиты:
            -
                Ид: 2f7a8b9c-0d1e-4f2a-9b4c-5d6e7f809102
                Имя: Исполнитель
                Тип: Строка
"""

DONE = """\
            -
                Ид: 0d5e6f7a-8b9c-4d0e-9f2a-3b4c5d6e7f80
                Имя: Готово
                Тип: Булево
"""


def test_tabular_parts_are_read_with_their_own_attributes():
    parts = parse_tabular_parts(TASKS)
    steps = parts["8b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e"]
    assert steps["name"] == "Шаги"
    assert {item["name"] for item in steps["attributes"].values()} == {"Шаг", "Готово"}
    assert steps["attributes"]["9c4d5e6f-7a8b-4c9d-8e1f-2a3b4c5d6e7f"]["length"] == 100
    assert len(parts) == 2


def test_the_attributes_of_a_tabular_part_are_not_the_object_attributes():
    """The top-level block ends where ТабличныеЧасти begins."""
    names = {item["name"] for item in parse_attributes(TASKS).values()}
    assert names == {"Наименование", "Срок"}


def test_a_removed_tabular_part_is_named_with_its_object_and_does_not_refuse():
    """The case that lost the rows: applied without a question, and the guard said nothing."""
    after = TASKS.replace(PERFORMERS, "")

    lines = removals(TASKS, after, where="Основное/Задачи.yaml")

    assert lines == [
        "Основное/Задачи.yaml: снимается табличная часть Исполнители объекта Задачи – "
        "строки будут удалены"
    ]
    # A removal is a deliberate edit, like a removed attribute: named, not refused.
    assert narrowing_changes(TASKS, after) == []


def test_a_removed_attribute_of_a_remaining_tabular_part_is_named():
    after = TASKS.replace(DONE, "")

    lines = removals(TASKS, after, where="Задачи.yaml")

    assert len(lines) == 1
    assert "реквизит Готово" in lines[0] and "табличной части Шаги" in lines[0]
    assert "объекта Задачи" in lines[0]
    assert narrowing_changes(TASKS, after) == []


def test_removing_every_tabular_part_drops_the_block_and_is_still_seen():
    after = TASKS[: TASKS.index("ТабличныеЧасти:")] + TASKS[TASKS.index("Интерфейс:"):]

    lines = removals(TASKS, after)

    assert len(lines) == 2
    assert any("Шаги" in line for line in lines) and any("Исполнители" in line for line in lines)


def test_a_removed_attribute_of_the_object_is_named_too():
    after = TASKS.replace(
        "    -\n        Ид: 7a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d\n        Имя: Срок\n"
        "        Тип: Дата\n",
        "",
    )

    lines = removals(TASKS, after)

    assert len(lines) == 1 and "реквизит Срок объекта Задачи" in lines[0]
    assert narrowing_changes(TASKS, after) == []


def test_a_narrowed_attribute_of_a_tabular_part_refuses_like_any_other():
    after = TASKS.replace("МаксимальнаяДлина: 100", "МаксимальнаяДлина: 50")

    changes = narrowing_changes(TASKS, after, where="Задачи.yaml")

    assert len(changes) == 1
    assert "Шаги.Шаг" in changes[0] and "100" in changes[0] and "50" in changes[0]


def test_a_changed_type_inside_a_tabular_part_refuses():
    after = TASKS.replace("Тип: Булево", "Тип: Строка")
    changes = narrowing_changes(TASKS, after)
    assert len(changes) == 1 and "Шаги.Готово" in changes[0]


def test_a_renamed_tabular_part_under_the_same_id_keeps_its_rows():
    after = TASKS.replace("Имя: Исполнители", "Имя: Участники")
    assert removals(TASKS, after) == []


def test_a_part_recreated_under_the_same_name_is_a_removal():
    """The platform maps a part by Ид: a new Ид under the old name starts it empty."""
    after = TASKS.replace(
        "Ид: 1e6f7a8b-9c0d-4e1f-8a3b-4c5d6e7f8091", "Ид: 3a8b9c0d-1e2f-4a3b-8c5d-6e7f80910213"
    )
    lines = removals(TASKS, after)
    assert len(lines) == 1 and "Исполнители" in lines[0]


def test_an_untouched_description_names_nothing():
    assert removals(TASKS, TASKS) == []
    assert narrowing_changes(TASKS, TASKS) == []


TASKS_EN = """\
ElementKind: Catalog
Id: 6f1d2c3b-4a59-4e68-8d7c-1b2a3c4d5e6f
Name: Tasks
Attributes:
    -
        Name: Description
        Length: 250
TabularParts:
    -
        Id: 8b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e
        Name: Steps
        Attributes:
            -
                Id: 9c4d5e6f-7a8b-4c9d-8e1f-2a3b4c5d6e7f
                Name: Step
                Type: String
                MaxLength: 100
    -
        Id: 1e6f7a8b-9c0d-4e1f-8a3b-4c5d6e7f8091
        Name: Performers
        Attributes:
            -
                Id: 2f7a8b9c-0d1e-4f2a-9b4c-5d6e7f809102
                Name: Performer
                Type: String
"""


def test_english_tabular_parts_are_read_on_a_par_with_the_russian_ones():
    parts = parse_tabular_parts(TASKS_EN)
    assert {part["name"] for part in parts.values()} == {"Steps", "Performers"}

    after = TASKS_EN[: TASKS_EN.index("    -\n        Id: 1e6f7a8b")]
    lines = removals(TASKS_EN, after, where="Tasks.yaml")
    assert len(lines) == 1 and "Performers" in lines[0] and "Tasks" in lines[0]

    narrowed = TASKS_EN.replace("MaxLength: 100", "MaxLength: 40")
    changes = narrowing_changes(TASKS_EN, narrowed)
    assert len(changes) == 1 and "Steps.Step" in changes[0]


def test_a_translated_description_keeps_its_tabular_parts():
    """The spellings switch, the Ид stays: a translation removes nothing."""
    russian = TASKS.replace(DONE, "")  # the English twin has no Готово either
    russian = russian.replace(
        "    -\n        Ид: 7a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d\n        Имя: Срок\n"
        "        Тип: Дата\n",
        "",
    )
    assert removals(russian, TASKS_EN) == []
    assert narrowing_changes(russian, TASKS_EN) == []


def test_an_item_with_its_first_key_on_the_dash_line_is_read():
    """A file edited by hand writes `- Имя: ...`; the platform writes a bare dash."""
    text = (
        "Имя: Задачи\n"
        "ТабличныеЧасти:\n"
        "  - Ид: 8b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e\n"
        "    Имя: Шаги\n"
        "    Реквизиты:\n"
        "      - Имя: Шаг\n"
        "        Тип: Строка\n"
        "        МаксимальнаяДлина: 100\n"
    )
    parts = parse_tabular_parts(text)
    steps = parts["8b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e"]
    assert steps["name"] == "Шаги"
    assert steps["attributes"]["Шаг"]["length"] == 100


def test_a_nested_list_inside_an_attribute_does_not_become_an_attribute():
    """A list under an attribute's own key belongs to that attribute, not to the block."""
    text = (
        "Имя: Статусы\n"
        "Реквизиты:\n"
        "    -\n"
        "        Ид: 4b9c0d1e-2f3a-4b4c-9d6e-7f8091021324\n"
        "        Имя: Этап\n"
        "        Тип: Строка\n"
        "        Варианты:\n"
        "            -\n"
        "                Имя: Черновик\n"
        "            -\n"
        "                Имя: Готово\n"
    )
    assert {item["name"] for item in parse_block(text, ("Реквизиты",)).values()} == {"Этап"}


def test_a_comment_after_the_block_key_does_not_hide_the_block():
    text = TASKS.replace("ТабличныеЧасти:\n", "ТабличныеЧасти: # строки задачи\n")
    assert len(parse_tabular_parts(text)) == 2


def test_a_block_in_a_form_the_reader_does_not_take_is_not_read_as_emptied():
    """The guard must not invent a change: an unreadable block is not a removal of everything."""
    flow = TASKS[: TASKS.index("ТабличныеЧасти:")] + "ТабличныеЧасти: [Шаги, Исполнители]\n"
    assert removals(TASKS, flow) == []

    emptied = TASKS[: TASKS.index("ТабличныеЧасти:")] + "ТабличныеЧасти: []\n"
    assert len(removals(TASKS, emptied)) == 2


def test_review_tree_collects_both_kinds_across_the_files(tmp_path):
    (tmp_path / "Основное").mkdir()
    (tmp_path / "Основное" / "Задачи.yaml").write_text(
        TASKS.replace(PERFORMERS, "").replace("МаксимальнаяДлина: 100", "МаксимальнаяДлина: 80"),
        encoding="utf-8",
    )
    earlier = {"Основное/Задачи.yaml": TASKS}

    review = review_tree(tmp_path, earlier.get)

    assert len(review.changes) == 1 and "Шаги.Шаг" in review.changes[0]
    assert len(review.removals) == 1 and "Исполнители" in review.removals[0]
