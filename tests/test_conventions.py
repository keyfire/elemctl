"""Conventions of the sources that no single test of a feature would ever notice.

A convention nobody wrote down is a convention every new file gets to rediscover, and this file
holds two that were.

The first was rediscovered the hard way: every process this repository starts asks for text and
names the encoding, a new script did not, and the failure was SILENT - the output of the
generator was decoded with the code page of the console, the Russian page names turned into
replacement characters, the text was lost, and the exit code went on saying that everything had
gone well.

The second is the line ending of a file this repository WRITES. `scripts/gen-cli-docs.py` and
`scripts/release-notes.py` pass `newline=""`; `scripts/changelog-link.py` did not, so on Windows
it handed back both changelog editions with every line changed - and the mirrors it rebuilds in
the same breath took the change with them. `core.autocrlf=input` hides that locally, which is
the whole trouble: on a machine without it, four whole files go to a public repository as one
line-ending change nobody asked for.

The reading of the sources is not elemctl's business and does not live here: the engine and the
bridge start processes and write their pages exactly the same way and have the same silent
failures waiting, so both checks and the readers under them come from the shared `docsguard`
package. They read with `ast` rather than with a regular expression, because the call that
started the first of them is written `(run or subprocess.run)(...)` and a check looking for the
text `subprocess.run(` at the head of a call would have passed over the one that mattered.

What stays here is the list of FOLDERS. Which of them hold code that starts processes, and which
of them write files that outlive the run, are facts about this repository and nothing the shared
package could know.
"""

from __future__ import annotations

import ast
from pathlib import Path

from docsguard import (
    Layout,
    process_encoding_problems,
    process_starts,
    python_sources,
    text_write_newline_problems,
    text_writes,
)

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = Layout(root=ROOT)

#: Everything written in Python here: what is shipped, what generates the pages, what guards
#: them and the tests themselves - a convention that stops at the test folder is half a
#: convention, and it was a test helper that carried one of the first two offenders.
FOLDERS = ("src", "scripts", "tests", "tools")

#: The folders of the newline convention, and deliberately a shorter list: a test writes into a
#: temporary directory that is gone when the run ends - nothing it writes is committed, shipped
#: or compared between machines, and a fixture carrying the other line ending on purpose is a
#: test in its own right. What belongs here is the code whose writes OUTLIVE the run.
WRITING_FOLDERS = ("src", "scripts", "tools")


def test_every_process_read_as_text_names_its_encoding():
    """The convention itself: no call decodes with whatever code page the machine has."""
    assert process_encoding_problems(LAYOUT, FOLDERS) == []


def test_the_reader_finds_the_calls_it_is_meant_to_judge():
    """A detector that finds nothing passes every repository, this one included."""
    found = [
        path.relative_to(ROOT).as_posix()
        for path in python_sources(LAYOUT, FOLDERS)
        if process_starts(ast.parse(path.read_text(encoding="utf-8")))
    ]

    assert len(found) > 4
    assert "src/elemctl/build.py" in found


def test_the_shared_check_still_bites(tmp_path):
    """The guard comes from a pinned package, and a pin is raised by hand.

    A version that had stopped judging would look from here exactly like a repository in order,
    which is the whole failure this file exists to prevent - so the provocation is made against
    the installed package, on sources of its own.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "offender.py").write_text(
        "import subprocess\nsubprocess.run(command, capture_output=True, text=True)\n",
        encoding="utf-8")

    problems = process_encoding_problems(Layout(root=tmp_path), ("src",))

    assert len(problems) == 1
    assert "src/offender.py:2" in problems[0]


def test_every_text_file_written_here_names_its_newline():
    """The convention itself: no generator hands back a file with every line changed."""
    assert text_write_newline_problems(LAYOUT, WRITING_FOLDERS) == []


def test_the_writes_reader_finds_the_calls_it_is_meant_to_judge():
    """A detector that finds nothing passes every repository, this one included."""
    found = [
        path.relative_to(ROOT).as_posix()
        for path in python_sources(LAYOUT, WRITING_FOLDERS)
        if text_writes(ast.parse(path.read_text(encoding="utf-8")))
    ]

    assert len(found) > 3
    # The generator the convention was found broken in: it rewrites both changelog editions.
    assert "scripts/changelog-link.py" in found


def test_the_shared_newline_check_still_bites(tmp_path):
    """A pinned version that had stopped judging looks from here like a repository in order."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "offender.py").write_text(
        'from pathlib import Path\nPath("page.md").write_text(text, encoding="utf-8")\n',
        encoding="utf-8", newline="")

    problems = text_write_newline_problems(Layout(root=tmp_path), ("scripts",))

    assert len(problems) == 1
    assert "scripts/offender.py:2" in problems[0]
