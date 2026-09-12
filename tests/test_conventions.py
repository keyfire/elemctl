"""Conventions of the sources that no single test of a feature would ever notice.

A convention nobody wrote down is a convention every new file gets to rediscover, and this file
holds four that were.

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

The third is the stdin of a started PROCESS, and it is the quietest of the four. elemctl ships
an MCP server that speaks over stdin, and a child started without a word about stdin inherits
that handle. On Windows the child then cannot reach its own exit: git did the work of
`status --porcelain` in milliseconds and sat holding the pipe, so the parent waited out the whole
timeout and the build reported that git was unavailable and the working tree unknown. A fresh
interpreter behaves the same way, and that is what a self-update checks itself with. Nothing here
ever writes to a child, so `stdin=subprocess.DEVNULL` costs nothing and closes the class.

The fourth is the NAME of a test. A test that arrives under the name of an existing one takes
its place: Python keeps the last definition, pytest collects what the module ended up with, and
the number of tests goes up, because the newcomer was added. Nothing in the run says the older
test has stopped running. It happened in the shared package while the newline convention above
was being written there.

The reading of the sources is not elemctl's business and does not live here: the engine and the
bridge start processes, write their pages and name their tests exactly the same way and have the
same silent failures waiting, so all three checks and the readers under them come from the
shared `docsguard` package. They read with `ast` rather than with a regular expression, because the call that
started the first of them is written `(run or subprocess.run)(...)` and a check looking for the
text `subprocess.run(` at the head of a call would have passed over the one that mattered.

What stays here is the list of FOLDERS. Which of them hold code that starts processes, which of
them write files that outlive the run, and which of them pytest collects tests from are facts
about this repository and nothing the shared package could know.
"""

from __future__ import annotations

import ast
import codecs
from pathlib import Path

from docsguard import (
    Layout,
    process_encoding_problems,
    process_starts,
    python_sources,
    read_text,
    shadowed_test_problems,
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

#: The folders of the stdin convention: the SHIPPED package alone. A server speaking over stdin
#: is what makes an inherited handle fatal, and that is elemctl itself - a generator, a tool or
#: a test runs from a console, where stdin is a console and a child may have it.
SERVER_FOLDERS = ("src",)

#: The folders of the test-name convention: the one pytest collects tests from.
TEST_FOLDERS = ("tests",)


def test_every_process_read_as_text_names_its_encoding():
    """The convention itself: no call decodes with whatever code page the machine has."""
    assert process_encoding_problems(LAYOUT, FOLDERS) == []


def test_the_reader_finds_the_calls_it_is_meant_to_judge():
    """A detector that finds nothing passes every repository, this one included."""
    found = [
        path.relative_to(ROOT).as_posix()
        for path in python_sources(LAYOUT, FOLDERS)
        if process_starts(ast.parse(read_text(path)))
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
        if text_writes(ast.parse(read_text(path)))
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


def stdin_problems_in(source: str, where: str) -> list[str]:
    """The process starts of one file that let the child inherit this process's stdin.

    A call that hands the child something to read - `input=` or an `stdin=` of its own - has
    answered the question and is left alone; what is caught is the call that never asks.
    """
    problems = []
    for call in process_starts(ast.parse(source)):
        if any(keyword.arg in ("stdin", "input") for keyword in call.keywords):
            continue
        problems.append(f"{where}:{call.lineno}: a process is started without saying what its "
                        "stdin is, so it inherits the one the server speaks over")
    return problems


def test_no_process_of_the_tool_inherits_the_stdin_of_its_parent():
    """The convention itself: a child of the MCP server can always reach its own exit."""
    problems = []
    for path in python_sources(LAYOUT, SERVER_FOLDERS):
        problems += stdin_problems_in(read_text(path), path.relative_to(ROOT).as_posix())

    assert problems == []


def test_a_process_started_without_a_word_about_stdin_is_caught():
    """The provocation - and the two shapes that have thought about it."""
    silent = 'import subprocess\nsubprocess.run(["git", "log"], capture_output=True)\n'
    closed = ('import subprocess\nsubprocess.run(["git", "log"], capture_output=True,'
              ' stdin=subprocess.DEVNULL)\n')
    fed = 'import subprocess\nsubprocess.run(["git", "hash-object", "--stdin"], input=blob)\n'

    assert len(stdin_problems_in(silent, "silent.py")) == 1
    assert stdin_problems_in(closed, "closed.py") == []
    assert stdin_problems_in(fed, "fed.py") == []


def test_no_test_here_is_shadowed_by_a_namesake():
    """The convention itself: every test this repository names is a test that still runs."""
    assert shadowed_test_problems(LAYOUT, TEST_FOLDERS) == []


def test_the_shared_test_name_check_still_bites(tmp_path):
    """A pinned version that had stopped judging looks from here like a repository in order."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_twice.py").write_text(
        "def test_one():\n    pass\n\n\ndef test_one():\n    pass\n",
        encoding="utf-8", newline="")

    problems = shadowed_test_problems(Layout(root=tmp_path), TEST_FOLDERS)

    assert len(problems) == 1
    assert "tests/test_twice.py:5" in problems[0]


def test_a_source_with_a_byte_order_mark_is_judged_rather_than_crashed_on(tmp_path):
    """The readers above parse what they read, and a mark at the head of a file used to raise.

    Editors on Windows write the mark without being asked and no diff shows it. Read as plain
    `utf-8` it stays in the text as a character `ast.parse` refuses, so a single such file left
    the whole check with no findings from any file at all.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "marked.py").write_bytes(
        codecs.BOM_UTF8 + b"import subprocess\nsubprocess.run(command, text=True)\n")

    problems = process_encoding_problems(Layout(root=tmp_path), ("src",))

    assert len(problems) == 1
    assert "src/marked.py:2" in problems[0]
