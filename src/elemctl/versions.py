"""Build versions: numeric comparison and auto-increment.

A build version has the form "{base}-{counter}", for example "1.0-42". Versions
have to be compared by the numeric counter after the last hyphen: "1.0-10" is
newer than "1.0-9", although lexicographically the order is the opposite.
"""

from __future__ import annotations


def version_counter(version):
    """The numeric counter of a version – the suffix after the last hyphen.

    For a version without a hyphen or with a non-numeric suffix 0 is returned.
    """
    text = str(version or "")
    head, sep, tail = text.rpartition("-")
    if not sep:
        return 0
    try:
        return int(tail)
    except ValueError:
        return 0


def version_base(version):
    """The base of a version - the text before the last hyphen ("" without one)."""
    text = str(version or "")
    head, sep, _tail = text.rpartition("-")
    return head if sep else ""


def next_version(base_version, last_version=None):
    """The next build version: "{base}-{N+1}" from the last build of the same base.

    Without a last build - or with a last build of ANOTHER base - the answer is
    "{base}-1": a project bumped to a new base version starts counting again, whatever
    counters the old base reached.
    """
    base = (base_version or "1.0").strip()
    if not last_version or version_base(last_version) != base:
        return f"{base}-1"
    return f"{base}-{version_counter(last_version) + 1}"


def pick_latest(assemblies, version_key="assembly-version", base_version=None):
    """Pick the latest assembly from the list by the numeric version counter.

    With base_version only the assemblies of that base take part ("1.0.2-7" for the
    base "1.0.2"): the counter of one base says nothing about another, and a stray high
    number of an old base must not push the numbering of a freshly bumped project.
    None when nothing qualifies.
    """
    base = (base_version or "").strip()
    best = None
    best_counter = -1
    for item in assemblies or []:
        if not isinstance(item, dict):
            continue
        version = item.get(version_key)
        if base and version_base(version) != base:
            continue
        counter = version_counter(version)
        if counter > best_counter:
            best = item
            best_counter = counter
    return best


def newest_first(assemblies):
    """The assemblies sorted newest first, ready for a limited listing.

    The primary key is the created stamp: the platform writes ISO-8601 in one
    time zone, which sorts chronologically as text. The numeric version counter
    breaks the ties and orders the cards that carry no stamp at all - those go
    after the stamped ones. Non-dict items are dropped: there is nothing to sort
    them by, and every consumer reads the cards as dictionaries anyway.
    """
    items = [item for item in assemblies or [] if isinstance(item, dict)]
    return sorted(
        items,
        key=lambda item: (
            str(item.get("created") or ""),
            version_counter(item.get("assembly-version")),
        ),
        reverse=True,
    )
