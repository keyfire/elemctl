"""Detecting the schema changes that destroy data.

The platform recreates the data of an object when an apply NARROWS a field:
observed on a live stand, where a catalog came out empty after a "repair" build
put the lengths back within the limits. Widening keeps the data, so the dangerous
class is narrow: a smaller length or a changed type.

There is no full YAML parser here on purpose - elemctl has no dependencies at all.
What is read is the top-level `Реквизиты:` block of an object description, whose
layout is regular in the sources of the platform. Anything the reader does not
recognize it stays silent about: the guard may not be able to judge, but it must
never invent a change that is not there.
"""

from __future__ import annotations

from . import i18n

# The keys carrying the length of a field. The platform spells it both ways:
# Длина for a number, МаксимальнаяДлина for a string.
LENGTH_KEYS = ("Длина", "МаксимальнаяДлина")
ATTRIBUTES_KEY = "Реквизиты"


def parse_attributes(text):
    """The attributes of an object description: {key: {name, type, length}}.

    The key is Ид when the description has one, otherwise the name - the platform
    maps attributes by Ид, so a rename under the same Ид is not a new attribute and
    must not read as one. Only the top-level block is read; the attributes of a
    tabular part sit deeper and are left to the compiler.
    """
    attributes = {}
    lines = text.splitlines()
    index = _find_block(lines)
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
        identity = current.get("Ид") or current.get("Имя")
        if identity:
            attributes[identity] = current
    return {
        key: {
            "name": item.get("Имя", ""),
            "type": item.get("Тип", ""),
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
    before = parse_attributes(before_text)
    after = parse_attributes(after_text)
    changes = []
    for key, old in before.items():
        new = after.get(key)
        if new is None:
            continue  # a removed attribute is a separate story, and the platform asks about it
        name = new.get("name") or old.get("name") or key
        if old["type"] and new["type"] and old["type"] != new["type"]:
            changes.append(i18n.t(
                "schema.type-changed",
                where=where,
                name=name,
                before=old["type"],
                after=new["type"],
            ))
        if old["length"] and new["length"] and new["length"] < old["length"]:
            changes.append(i18n.t(
                "schema.length-narrowed",
                where=where,
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


def _find_block(lines):
    """The index of the top-level `Реквизиты:` line, or None."""
    for index, line in enumerate(lines):
        if line.rstrip() == f"{ATTRIBUTES_KEY}:":
            return index
    return None


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
