#!/usr/bin/env python
"""Write a pull request link into the newest changelog entries and rebuild the mirrors.

Every entry of the changelog ends with a link to the pull request it came from, and that link
can only be written once the pull request exists - so it arrives in a commit of its own, after
the entry. Two actions, and the tree is only right after both: the second one - rebuilding the
generated pages with `scripts/rebuild-docs.py` - is the one that kept being forgotten, and
`main` went red on the documentation guard for it.

They are one command now:

    python scripts/changelog-link.py 12

The link goes to every entry of the TOPMOST section of both editions that carries none yet, and
every generated page is rebuilt in the same run. Older sections are never touched: an entry from
before the pull request rule is not unfinished, it is history.

Exit code 1 when the pages could not be rebuilt - a rebuild that did not happen must not look
like a finished step.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Both editions take the link: a Russian entry without one is as unfinished as an English one.
EDITIONS = ("CHANGELOG.md", "CHANGELOG.ru.md")
#: The one step that rebuilds every generated page - the command reference and the mirrors
#: both. Named rather than repeated here: a second list of generators is a second thing to
#: forget, which is the failure this script was written for.
REBUILD = ROOT / "scripts" / "rebuild-docs.py"
DEFAULT_REPO = "keyfire/elemctl"
#: The width the changelog is wrapped to; a link that does not fit goes on a line of its own,
#: indented like a continuation line - the way the long entries already carry it.
WIDTH = 100
INDENT = "  "


def link(number: int, repo: str = DEFAULT_REPO) -> str:
    """The link as an entry ends with it: `([#12](https://github.com/keyfire/elemctl/pull/12))`."""
    return f"([#{number}](https://github.com/{repo}/pull/{number}))"


def top_section(lines: list[str]) -> tuple[int, int] | None:
    """The body of the topmost `## ` section as a half-open range of line numbers.

    The topmost section is the one being worked on - `## Unreleased` between releases, the day's
    heading after one. What is below it has been released and linked already.
    """
    start = next((i for i, line in enumerate(lines) if line.startswith("## ")), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines)
    )
    return start + 1, end


def entry_blocks(lines: list[str], start: int, end: int) -> list[tuple[int, int]]:
    """The entries of a section: (first line, last line) of every `- ` bullet, inclusive.

    An entry runs from its bullet to the last line that belongs to it - the continuation lines
    are indented, and the block ends at the next bullet, at a `###` subheading or at a blank
    line. The last line is where the link is appended, so trailing blanks are trimmed off.
    """
    blocks: list[tuple[int, int]] = []
    opened: int | None = None

    def close(at: int) -> None:
        nonlocal opened
        last = at - 1
        while last > opened and not lines[last].strip():
            last -= 1
        blocks.append((opened, last))
        opened = None

    for i in range(start, end):
        line = lines[i]
        if line.startswith("- "):
            if opened is not None:
                close(i)
            opened = i
        elif opened is not None and (not line.strip() or line.startswith("#")):
            close(i)
    if opened is not None:
        close(end)
    return blocks


def add_link(text: str, number: int, repo: str = DEFAULT_REPO, *, width: int = WIDTH):
    """The text with the link appended to every link-less entry of the topmost section.

    Returns the new text and how many entries took the link. An entry that already carries one
    is left alone - a second link would say the change came from two pull requests.
    """
    lines = text.split("\n")
    span = top_section(lines)
    if span is None:
        return text, 0
    start, end = span
    mark = link(number, repo)
    added = 0
    # From the bottom up: an inserted line shifts everything below it, and the blocks above
    # keep their numbers that way.
    for first, last in reversed(entry_blocks(lines, start, end)):
        if "/pull/" in "\n".join(lines[first:last + 1]):
            continue
        if len(lines[last]) + 1 + len(mark) <= width:
            lines[last] = f"{lines[last]} {mark}"
        else:
            lines.insert(last + 1, f"{INDENT}{mark}")
        added += 1
    return "\n".join(lines), added


def write_links(root: Path, number: int, repo: str = DEFAULT_REPO) -> dict[str, int]:
    """Both editions linked in place; the answer is how many entries each of them took."""
    taken: dict[str, int] = {}
    for name in EDITIONS:
        path = root / name
        text = path.read_text(encoding="utf-8")
        linked, added = add_link(text, number, repo)
        if added:
            path.write_text(linked, encoding="utf-8", newline="")
        taken[name] = added
    return taken


def rebuild_step():
    """The one rebuild step, loaded as a module.

    Imported rather than started as another Python process: a nested script writes its output
    in the console code page while the parent reads it as UTF-8, and the Russian page names
    come back as replacement characters - the very mangling the generators are careful about.
    Loaded by path because a file name with a hyphen is no import name.
    """
    spec = importlib.util.spec_from_file_location("rebuild_docs", REBUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rebuild_pages(root: Path, run=None) -> tuple[bool, str]:
    """Every generated page rebuilt by the one step; (did it work, what it said).

    `run` is the process runner, the test's way in - a default bound at definition time would
    leave the real generators running under it. A generator that cannot start at all is
    reported by the step like any other failure instead of raising: the answer the caller needs
    is the same - the pages are not rebuilt and the commit is not ready.
    """
    return rebuild_step().rebuild(root, run)


def main(argv=None, run=None) -> int:
    parser = argparse.ArgumentParser(
        description="Append a pull request link to the newest changelog entries and rebuild "
                    "the mirrored pages."
    )
    parser.add_argument("number", type=int, help="the pull request number")
    parser.add_argument("--repo", default=DEFAULT_REPO,
                        help=f"owner/repository of the pull request (default: {DEFAULT_REPO})")
    parser.add_argument("--no-sync", action="store_true",
                        help="do not rebuild the generated pages (for a tree where node is "
                             "unavailable - they then have to be rebuilt by hand)")
    args = parser.parse_args(argv)

    taken = write_links(ROOT, args.number, args.repo)
    for name, added in taken.items():
        print(f"{name}: {added} entry(ies) linked to #{args.number}")
    if not any(taken.values()):
        print("no entry was waiting for a link - every one of them carries it already")
    if args.no_sync:
        return 0

    ok, output = rebuild_pages(ROOT, run)
    if output:
        print(output)
    if not ok:
        print("the generated pages were NOT rebuilt - run `python scripts/rebuild-docs.py` "
              "yourself before committing", file=sys.stderr)
        return 1
    print("stage the changelog editions together with the pages they were rebuilt into")
    return 0


if __name__ == "__main__":
    sys.exit(main())
