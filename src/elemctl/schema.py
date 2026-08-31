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

There is no full YAML parser here on purpose - elemctl has no dependencies at all.
What is read are the top-level blocks of an object description that carry
data-bearing fields, whose layout is regular in the sources of the platform.
Anything the reader does not recognize it stays silent about: the guard may not be
able to judge, but it must never invent a change that is not there.
"""

from __future__ import annotations

from . import i18n

# Bilingual sources are a declared platform capability, so every key is read in
# both spellings. The keys carrying the length of a field: Длина/Length for a
# number, МаксимальнаяДлина/MaxLength for a string.
LENGTH_KEYS = ("Длина", "МаксимальнаяДлина", "Length", "MaxLength")
ATTRIBUTES_KEYS = ("Реквизиты", "Attributes")
DIMENSIONS_KEYS = ("Измерения", "Dimensions")
RESOURCES_KEYS = ("Ресурсы", "Resources")

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


def parse_attributes(text):
    """The attributes of an object description: {key: {name, type, length}}."""
    return parse_block(text, ATTRIBUTES_KEYS)


def parse_block(text, keys):
    """One top-level block of a description: {key: {name, type, length}}.

    The key is Ид when the description has one, otherwise the name - the platform
    maps fields by Ид, so a rename under the same Ид is not a new field and must
    not read as one. Only the top-level block is read; the attributes of a tabular
    part sit deeper and are left to the compiler.
    """
    attributes = {}
    lines = text.splitlines()
    index = _find_block(lines, keys)
    if index is None:
        return attributes

    current = None
    for line in lines[index + 1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:  # the block ended - a new top-level key started
            break
        if stripped == "-":
            current = {}
            continue
        if current is None:
            continue
        key, _, value = stripped.partition(":")
        current[key.strip()] = value.strip()
        identity = _first_of(current, _ID_KEYS) or _first_of(current, _NAME_KEYS)
        if identity:
            attributes[identity] = current
    return {
        key: {
            "name": _first_of(item, _NAME_KEYS) or "",
            "type": _first_of(item, _TYPE_KEYS) or "",
            "length": _as_int(_first_of(item, LENGTH_KEYS)),
        }
        for key, item in attributes.items()
    }


def narrowing_changes(before_text, after_text, *, where=""):
    """The changes between two descriptions of one object that destroy its data.

    Returned is a list of human-readable lines; an empty list means either that
    nothing narrowed or that the reader could not judge - the caller must not read
    it as a promise that the apply is safe.
    """
    changes = []
    for kind, keys in BLOCKS:
        before = parse_block(before_text, keys)
        after = parse_block(after_text, keys)
        for key, old in before.items():
            new = after.get(key)
            if new is None:
                # A removed attribute or resource is a separate story, and the platform
                # asks about it. A removed DIMENSION is not asked about: the records
                # collapse onto the keys that are left, and the apply dies on their
                # uniqueness - after the data has already been rewritten.
                if kind == DIMENSION:
                    changes.append(i18n.t(
                        "schema.dimension-removed",
                        where=where,
                        name=old.get("name") or key,
                    ))
                continue
            name = new.get("name") or old.get("name") or key
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


def narrowing_in_tree(project_dir, read_before):
    """Every narrowing between the sources on disk and their earlier state.

    read_before(relative_path) returns the earlier text of the file or None when
    it is unknown (a new file, or the earlier state cannot be read). The caller
    supplies it: for a deploy that is `git show <commit>:<path>` of the commit the
    applied build was made from - the Console API does not hand out the contents
    of an assembly, so the sources of that commit are the only thing there is to
    compare against.
    """
    from pathlib import Path

    project_dir = Path(project_dir)
    changes = []
    for path in sorted(project_dir.rglob("*.yaml")):
        relative = path.relative_to(project_dir).as_posix()
        before = read_before(relative)
        if before is None:
            continue
        try:
            after = path.read_text(encoding="utf-8")
        except OSError:
            continue
        changes.extend(narrowing_changes(before, after, where=relative))
    return changes


# -- internals ----------------------------------------------------------------


def _find_block(lines, keys):
    """The index of the top-level line opening the block, or None."""
    wanted = tuple(f"{key}:" for key in keys)
    for index, line in enumerate(lines):
        if line.rstrip() in wanted:
            return index
    return None


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
