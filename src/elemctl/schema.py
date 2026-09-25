"""Detecting the schema changes that destroy data.

The platform recreates the data of an object when an apply NARROWS a field: a
catalog comes out empty after a "repair" build that puts the lengths back within
the limits. Widening keeps the data, so the dangerous
class is narrow: a smaller length or a changed type.

A register is the sharper case. Its records are keyed BY THE DIMENSIONS, so
changing the type of one - or removing it - does not merely empty the object: the
platform converts the existing records to the new type, the values collapse, and
the apply then fails on their uniqueness. That failure rolls the application back
silently, and a probe cannot foresee it either - a throwaway application has no
records to convert. The previous schema is what the answer needs, and only a
deploy has it.

A removal is a different story. Taking an attribute, a resource or a tabular part
out of the sources is a deliberate edit, and the server applies it without a
question: the data of the removed element goes with it, the rows of a tabular part
included. So a removal does not stop a deploy the way a narrowing does, but it is
named - `removals` says what the apply takes away, before it is applied.

There is no full YAML parser here on purpose - elemctl has no dependencies at all.
What is read are the top-level blocks of an object description that carry
data-bearing fields, and the tabular parts with their own attributes; their layout
is regular in the sources of the platform. Anything the reader does not recognize
it stays silent about: the guard may not be able to judge, but it must never invent
a change that is not there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import i18n

# Bilingual sources are a declared platform capability, so every key is read in
# both spellings. The keys carrying the length of a field: Длина/Length for a
# number, МаксимальнаяДлина/MaxLength for a string.
LENGTH_KEYS = ("Длина", "МаксимальнаяДлина", "Length", "MaxLength")
ATTRIBUTES_KEYS = ("Реквизиты", "Attributes")
DIMENSIONS_KEYS = ("Измерения", "Dimensions")
RESOURCES_KEYS = ("Ресурсы", "Resources")
# A tabular part is an item of this block, and its own attributes sit in a Реквизиты
# (Attributes) block nested inside the item.
TABULAR_KEYS = ("ТабличныеЧасти", "TabularParts")

# The blocks read out of a description, and the kind each one is reported as. A
# dimension is singled out because the consequences of touching it differ: the
# records are keyed by it.
ATTRIBUTE, DIMENSION, RESOURCE = "attribute", "dimension", "resource"
BLOCKS = (
    (ATTRIBUTE, ATTRIBUTES_KEYS),
    (DIMENSION, DIMENSIONS_KEYS),
    (RESOURCE, RESOURCES_KEYS),
)

_ID_KEYS = ("Ид", "Id")
_NAME_KEYS = ("Имя", "Name")
_TYPE_KEYS = ("Тип", "Type")

# The primitive type names in both spellings: a translated description names the
# SAME type, not a change. Only the pairs the platform declares are listed;
# anything else (reference types included) is compared verbatim - the guard must
# not guess.
_TYPE_SPELLINGS = {
    "String": "Строка",
    "Number": "Число",
    "Boolean": "Булево",
    "Date": "Дата",
    "DateTime": "ДатаВремя",
    "Time": "Время",
}

# A comment after the key of a block: `ТабличныеЧасти: # пояснение`.
_TRAILING_COMMENT = re.compile(r"\s+#.*$")


@dataclass
class SchemaReview:
    """What an apply would do to the data, file by file.

    changes - the narrowings that recreate data or break the apply; a deploy refuses
    them unless told otherwise. removals - the data-bearing elements the sources no
    longer have; their data goes with them, and a deploy names them without stopping.
    """

    changes: list = field(default_factory=list)
    removals: list = field(default_factory=list)


def parse_attributes(text):
    """The attributes of an object description: {key: {name, type, length}}."""
    return parse_block(text, ATTRIBUTES_KEYS)


def parse_block(text, keys):
    """One top-level block of a description: {key: {name, type, length}}.

    The key is Ид when the description has one, otherwise the name - the platform
    maps fields by Ид, so a rename under the same Ид is not a new field and must
    not read as one. Only the top-level block is read; the attributes of a tabular
    part are read by parse_tabular_parts.
    """
    lines = text.splitlines()
    index = _find_block(lines, keys)
    if index is None:
        return {}
    return _fields(item for item, _ in _list_items(_block_lines(lines, index)))


def parse_tabular_parts(text):
    """The tabular parts of an object description: {key: {name, attributes}}.

    A part is keyed the way a field is: by Ид when it has one, otherwise by the name.
    attributes are the part's own fields, {key: {name, type, length}} as parse_block
    gives them.
    """
    lines = text.splitlines()
    index = _find_block(lines, TABULAR_KEYS)
    if index is None:
        return {}
    parts = {}
    for item, blocks in _list_items(_block_lines(lines, index)):
        identity = _identity(item)
        if not identity:
            continue
        nested = next((blocks[key] for key in ATTRIBUTES_KEYS if key in blocks), [])
        inline = _first_of(item, ATTRIBUTES_KEYS)
        parts[identity] = {
            "id": _first_of(item, _ID_KEYS) or "",
            "name": _first_of(item, _NAME_KEYS) or identity,
            # None - the attributes are written in a form this reader does not take, and
            # then nothing is said about them; an explicit empty list is no attributes.
            "attributes": (
                None if inline not in (None, "[]")
                else _fields(fields for fields, _ in _list_items(nested))
            ),
        }
    return parts


def narrowing_changes(before_text, after_text, *, where=""):
    """The changes between two descriptions of one object that destroy its data.

    Returned is a list of human-readable lines; an empty list means either that
    nothing narrowed or that the reader could not judge - the caller must not read
    it as a promise that the apply is safe. The attributes of a tabular part are
    judged like the top-level ones and named with the part: `Шаги.Описание`.
    """
    changes = []
    by_id = _translated(before_text, after_text)
    for kind, keys in BLOCKS:
        before = parse_block(before_text, keys)
        after = parse_block(after_text, keys)
        if kind == DIMENSION and _readable(after_text, keys):
            # A removed DIMENSION is not a plain removal: the records collapse onto the
            # keys that are left, and the apply dies on their uniqueness - after the data
            # has already been rewritten.
            for key, old in _missing(before, after, by_id=by_id):
                changes.append(i18n.t(
                    "schema.dimension-removed",
                    where=where,
                    name=old.get("name") or key,
                ))
        changes.extend(_narrowed(before, after, kind=kind, where=where))
    before_parts = parse_tabular_parts(before_text)
    after_parts = parse_tabular_parts(after_text)
    for key, old_part in before_parts.items():
        new_part = after_parts.get(key)
        if new_part is None:
            continue  # the part itself is gone: that is a removal, not a narrowing
        prefix = (new_part["name"] or old_part["name"]) + "."
        changes.extend(_narrowed(
            old_part["attributes"] or {}, new_part["attributes"] or {},
            kind=ATTRIBUTE, where=where, prefix=prefix,
        ))
    return changes


def removals(before_text, after_text, *, where=""):
    """The data-bearing elements the new description no longer has, as report lines.

    An attribute, a resource, a tabular part, an attribute of a tabular part that stays.
    An element counts as removed when its key is gone - the Ид, or the name of an element
    that has none. The platform maps elements by Ид, so a rename under the same Ид keeps
    the data, while an element re-created under the same name gets a new Ид and loses
    it. A removed dimension is not here - narrowing_changes judges it, because it breaks
    the apply itself.
    """
    lines = []
    owner = _object_name(after_text) or _object_name(before_text) or where
    # A translated description renames every element without an Ид - the standard
    # Наименование becomes Description - so across a translation only an Ид can say that an
    # element is gone.
    by_id = _translated(before_text, after_text)
    for keys, message in (
        (ATTRIBUTES_KEYS, "schema.attribute-removed"),
        (RESOURCES_KEYS, "schema.resource-removed"),
    ):
        if not _readable(after_text, keys):
            continue
        before = parse_block(before_text, keys)
        after = parse_block(after_text, keys)
        for key, old in _missing(before, after, by_id=by_id):
            lines.append(i18n.t(
                message, where=where, object=owner, name=old.get("name") or key
            ))
    if not _readable(after_text, TABULAR_KEYS):
        return lines
    before_parts = parse_tabular_parts(before_text)
    after_parts = parse_tabular_parts(after_text)
    for key, old_part in before_parts.items():
        new_part = after_parts.get(key)
        if new_part is None:
            if by_id and not old_part["id"]:
                continue  # an Ид-less part cannot be followed across a translation
            lines.append(i18n.t(
                "schema.tabular-part-removed", where=where, object=owner,
                part=old_part["name"],
            ))
            continue
        if old_part["attributes"] is None or new_part["attributes"] is None:
            continue
        for attribute_key, old in _missing(
            old_part["attributes"], new_part["attributes"], by_id=by_id
        ):
            lines.append(i18n.t(
                "schema.tabular-attribute-removed", where=where, object=owner,
                part=new_part["name"] or old_part["name"],
                name=old.get("name") or attribute_key,
            ))
    return lines


def review_tree(project_dir, read_before):
    """Every narrowing and every removal between the sources on disk and their earlier state.

    read_before(relative_path) returns the earlier text of the file or None when
    it is unknown (a new file, or the earlier state cannot be read). The caller
    supplies it: for a deploy that is `git show <commit>:<path>` of the commit the
    applied build was made from - the Console API does not hand out the contents
    of an assembly, so the sources of that commit are the only thing there is to
    compare against.
    """
    from pathlib import Path

    project_dir = Path(project_dir)
    review = SchemaReview()
    for path in sorted(project_dir.rglob("*.yaml")):
        relative = path.relative_to(project_dir).as_posix()
        before = read_before(relative)
        if before is None:
            continue
        try:
            after = path.read_text(encoding="utf-8")
        except OSError:
            continue
        review.changes.extend(narrowing_changes(before, after, where=relative))
        review.removals.extend(removals(before, after, where=relative))
    return review


# -- internals ----------------------------------------------------------------


def _find_block(lines, keys):
    """The index of the top-level line opening the block, or None."""
    wanted = tuple(f"{key}:" for key in keys)
    for index, line in enumerate(lines):
        if _TRAILING_COMMENT.sub("", line.rstrip()) in wanted:
            return index
    return None


def _readable(text, keys):
    """False when the block is there but written in a form this reader does not take.

    A removal is read off what a block no longer has, so a block the reader cannot parse
    would look emptied and invent a removal of everything in it. An absent block and an
    explicit `[]` are readable: everything that was there is gone.
    """
    for line in text.splitlines():
        if _indent(line):
            continue
        key, colon, value = _TRAILING_COMMENT.sub("", line.rstrip()).partition(":")
        if colon and key.strip() in keys:
            return value.strip() in ("", "[]")
    return True


def _block_lines(lines, index):
    """The lines of the block opened at index: everything indented deeper than its key.

    Blank lines and comments are dropped here, so nothing below has to skip them.
    """
    base = _indent(lines[index])
    block = []
    for line in lines[index + 1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _indent(line) <= base:
            break
        block.append(line)
    return block


def _list_items(block):
    """The items of a YAML list block: [(fields, blocks)] of every item.

    fields are the item's own `key: value` pairs, blocks the nested blocks a bare
    `key:` opens, as their lines. Both spellings of an item are read: the platform
    writes a bare `-` with the keys under it, and a file edited by hand often puts the
    first key right after the dash.
    """
    dashes = [_indent(line) for line in block if _is_dash(line)]
    if not dashes:
        return []
    level = min(dashes)
    items = []
    current = None
    for line in block:
        indent = _indent(line)
        if indent == level and _is_dash(line):
            current = []
            items.append(current)
            rest = line.strip()[1:]
            if rest.strip():
                # The first key sits on the dash line: moved to the column it starts at,
                # where the keys under it are aligned.
                column = indent + 1 + len(rest) - len(rest.lstrip())
                current.append(" " * column + rest.strip())
        elif indent > level and current is not None:
            current.append(line)
        else:
            current = None
    return [_split_item(item) for item in items]


def _split_item(lines):
    """An item's own `key: value` pairs and the nested blocks a bare `key:` opens."""
    fields, blocks = {}, {}
    if not lines:
        return fields, blocks
    level = min(_indent(line) for line in lines)
    opened = None
    for line in lines:
        if _indent(line) == level:
            key, colon, value = line.strip().partition(":")
            if not colon:
                opened = None
                continue
            value = value.strip()
            if value:
                fields[key.strip()] = _unquote(value)
                opened = None
            else:
                opened = blocks.setdefault(key.strip(), [])
        elif opened is not None:
            opened.append(line)
    return fields, blocks


def _fields(items):
    """{key: {name, type, length}} out of the fields of list items."""
    result = {}
    for item in items:
        identity = _identity(item)
        if identity:
            result[identity] = {
                "id": _first_of(item, _ID_KEYS) or "",
                "name": _first_of(item, _NAME_KEYS) or "",
                "type": _first_of(item, _TYPE_KEYS) or "",
                "length": _as_int(_first_of(item, LENGTH_KEYS)),
            }
    return result


def _narrowed(before, after, *, kind, where, prefix=""):
    """The type changes and the narrowed lengths between two sets of fields."""
    changes = []
    for key, old in before.items():
        new = after.get(key)
        if new is None:
            continue
        name = prefix + (new.get("name") or old.get("name") or key)
        if (
            old["type"] and new["type"]
            and _canonical_type(old["type"]) != _canonical_type(new["type"])
        ):
            changes.append(i18n.t(
                "schema.dimension-type-changed" if kind == DIMENSION
                else "schema.type-changed",
                where=where,
                kind=_kind_word(kind),
                name=name,
                before=old["type"],
                after=new["type"],
            ))
        if old["length"] and new["length"] and new["length"] < old["length"]:
            changes.append(i18n.t(
                "schema.length-narrowed",
                where=where,
                kind=_kind_word(kind),
                name=name,
                before=old["length"],
                after=new["length"],
            ))
    return changes


def _missing(before, after, *, by_id=False):
    """The items of before whose key after no longer has; by_id - only those with an Ид."""
    return [
        (key, item) for key, item in before.items()
        if key not in after and (item.get("id") or not by_id)
    ]


def _translated(before_text, after_text):
    """Whether the two descriptions are written in different languages of the keys."""
    before, after = _language(before_text), _language(after_text)
    return bool(before and after and before != after)


def _language(text):
    """The spelling of the keys: "ru", "en", or "" when the description names no object."""
    for line in text.splitlines():
        if _indent(line):
            continue
        key = line.partition(":")[0].strip()
        if key in _NAME_KEYS:
            return "ru" if key == _NAME_KEYS[0] else "en"
    return ""


def _object_name(text):
    """The name of the object a description is about: its top-level Имя (Name)."""
    for line in text.splitlines():
        if _indent(line):
            continue
        key, colon, value = line.partition(":")
        if colon and key.strip() in _NAME_KEYS and value.strip():
            return _unquote(value.strip())
    return ""


def _identity(item):
    return _first_of(item, _ID_KEYS) or _first_of(item, _NAME_KEYS)


def _is_dash(line):
    stripped = line.strip()
    return stripped == "-" or stripped.startswith("- ")


def _indent(line):
    return len(line) - len(line.lstrip())


def _unquote(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _kind_word(kind):
    """The word a field of this kind is called by in a report."""
    return i18n.t(f"schema.kind-{kind}")


def _canonical_type(value):
    """One spelling for the two names of a primitive type; the rest stay as written."""
    return _TYPE_SPELLINGS.get(value, value)


def _first_of(item, keys):
    for key in keys:
        if key in item:
            return item[key]
    return None


def _as_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
