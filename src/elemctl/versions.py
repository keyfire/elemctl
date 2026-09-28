"""Build versions: numeric comparison and auto-increment.

A build version has the form "{base}-{counter}", for example "1.0-42". Versions
have to be compared by the numeric counter after the last hyphen: "1.0-10" is
newer than "1.0-9", although lexicographically the order is the opposite.

The server hands those numbers out itself when a build is uploaded into a project:
the base is the Версия of the project descriptor and the number the highest one it has
ever given in that base plus one, whatever version the archive was built with. A
deleted build keeps its number: the build list no longer shows it, and the server
counts on from it all the same. So the auto-increment below is a guess at the server's
number. A deploy makes it from the build list and from the local registry of uploads
(`highest_version`), which remembers the numbers the uploads of this machine got; a build
uploaded from elsewhere and deleted since is out of sight of both.
"""

from __future__ import annotations


def version_counter(version):
    """The numeric counter of a version - the suffix after the last hyphen.

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


def server_may_keep(version, base_version):
    """Whether an upload into a project can leave the build under the version it was built with.

    The server numbers a build uploaded into a project itself and does not read the version of
    the archive at all: the base is the Версия of the project descriptor, the number the
    highest one it has ever given in that base plus one. A version can come out of that rule
    only when its base is the project's own and its tail is a number - and even then only when
    that number happens to be the next one. False is certain, True is a maybe.
    """
    text = str(version or "").strip()
    tail = text.rpartition("-")[2]
    return (
        bool(version_base(text))
        and version_base(text) == str(base_version or "").strip()
        and tail.isascii()
        and tail.isdigit()
    )


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


def highest_version(versions, base_version):
    """The version with the highest number among plain version strings of one base, or "".

    The strings are what the local registry of uploads keeps. A version of another base, or
    one whose tail is not a number - the throwaway version of a probe, say - takes no part:
    the server counts every base on its own, and only a number moves its count.
    """
    base = str(base_version or "").strip()
    best, best_counter = "", 0
    for version in versions or []:
        text = str(version or "").strip()
        if version_base(text) != base:
            continue
        counter = version_counter(text)
        if counter > best_counter:
            best, best_counter = text, counter
    return best


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


def missing_counters(assemblies, version_key="assembly-version"):
    """How many build numbers the listing has NOT got - what says its housekeeping has run.

    The platform hands out the numbers itself, one after another within a base version
    ("1.0.2-1", "1.0.2-2", ...), so the numbers of a base run unbroken while nothing is taken
    away and nothing comes by the vendor and the name. A hole in them - or a base whose first
    numbers are simply not there - is a build the platform has deleted, or a jump: a number
    nobody had, because the build above it brought its own from the archive. The count cannot
    tell the two apart; `numbering_holes` gives the holes themselves, for a caller that can.

    The proof only works one way, and only as a yes or no. Gaps say the listing is not
    everything the project ever numbered; an unbroken run says nothing beyond itself - the
    last build of a base can be deleted without leaving a hole. And the COUNT is not a count
    of deleted builds: a number can also be one nobody ever used, the way a live project ended
    up with a build numbered 1.0.1-19001 because the auto-increment of the day took the
    counters of another base (fixed in 0.38.0) - the whole run below it was never built, and
    counting those numbers as losses would make twenty thousand of them. A version the platform
    did not number this way (no hyphen, a non-numeric tail) takes no part at all.
    """
    seen = {}
    for item in assemblies or []:
        if not isinstance(item, dict):
            continue
        version = item.get(version_key)
        counter = version_counter(version)
        if counter <= 0:
            continue
        seen.setdefault(version_base(version), set()).add(counter)
    # Within a base the numbers run 1..max, so what is absent is the difference between the
    # highest number and how many of them the listing actually carries.
    return sum(max(counters) - len(counters) for counters in seen.values())


def numbering_holes(assemblies, version_key="assembly-version"):
    """Every hole in the numbering of a listing: [(the build below or None, the build above)].

    The hole is what lies between two builds of one base whose numbers do not follow one
    another, or below the lowest build of a base that does not start at 1 - and then there is
    no build below it. What a hole means the numbers cannot say. It is a build the platform
    deleted when the numbers were handed out one by one, and it is a number nobody ever had
    when the build above it brought its number from the archive: an upload by the vendor and
    the name keeps the version it is given, and the next upload into the project counts on
    from it. The created stamps of the two builds cannot tell the two apart either - the
    server hands numbers out as fast as uploads come, ten a second in a live check. Telling
    them apart is the caller's, by what it knows of the build above.
    """
    by_base = {}
    for item in assemblies or []:
        if not isinstance(item, dict):
            continue
        version = item.get(version_key)
        counter = version_counter(version)
        if counter > 0:
            by_base.setdefault(version_base(version), {}).setdefault(counter, item)
    holes = []
    for numbered in by_base.values():
        counters = sorted(numbered)
        below = None
        for counter in counters:
            expected = version_counter(below.get(version_key)) + 1 if below else 1
            if counter > expected:
                holes.append((below, numbered[counter]))
            below = numbered[counter]
    return holes


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
