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


def next_version(base_version, last_version=None):
    """The next build version: "{base}-{N+1}" from the last one, otherwise "{base}-1"."""
    base = (base_version or "1.0").strip()
    if not last_version:
        return f"{base}-1"
    return f"{base}-{version_counter(last_version) + 1}"


def pick_latest(assemblies, version_key="assembly-version"):
    """Pick the latest assembly from the list by the numeric version counter."""
    best = None
    best_counter = -1
    for item in assemblies or []:
        if not isinstance(item, dict):
            continue
        counter = version_counter(item.get(version_key))
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
