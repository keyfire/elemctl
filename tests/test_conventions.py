"""Conventions of the sources that no single test of a feature would ever notice.

A convention nobody wrote down is a convention every new file gets to rediscover. This one was
rediscovered the hard way: every process this repository starts asks for text and names the
encoding, a new script did not, and the failure was SILENT - the output of the generator was
decoded with the code page of the console, the Russian page names turned into replacement
characters, the text was lost, and the exit code went on saying that everything had gone well.

Read with `ast` rather than with a regular expression: the call that started it is written
`(run or subprocess.run)(...)`, so a check that looked for the text `subprocess.run(` at the
head of a call would have passed over exactly the one that mattered.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Everything written in Python here: what is shipped, what generates the pages, what guards
#: them and the tests themselves - a convention that stops at the test folder is half a
#: convention, and it was a test helper that carried one of the first two offenders.
FOLDERS = ("src", "scripts", "tests", "tools")

#: The functions of `subprocess` that start a process.
STARTERS = frozenset({"run", "Popen", "call", "check_call", "check_output"})
#: The keywords that turn the streams into text. Any of them, and the bytes have to be decoded
#: by somebody - so the encoding has to be said out loud.
TEXT_FLAGS = ("text", "universal_newlines")


def sources() -> list[Path]:
    """Every Python file of the repository, in a stable order."""
    found: list[Path] = []
    for folder in FOLDERS:
        found.extend(sorted((ROOT / folder).rglob("*.py")))
    return found


def process_starts(tree: ast.AST) -> list[ast.Call]:
    """The calls that start a process, however the callable is spelled at the call site.

    The whole callable expression is searched, not just its head: `(run or subprocess.run)(...)`
    is a process start, and that shape is what a runner seam for the tests looks like.
    """
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for inner in ast.walk(node.func):
            if (
                isinstance(inner, ast.Attribute)
                and inner.attr in STARTERS
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "subprocess"
            ):
                calls.append(node)
                break
    return calls


def asks_for_text(call: ast.Call) -> bool:
    """Does the call want str back - by `text=`, by `universal_newlines=` or by `encoding=`."""
    for keyword in call.keywords:
        if keyword.arg in TEXT_FLAGS and not (
            isinstance(keyword.value, ast.Constant) and keyword.value.value is False
        ):
            return True
        if keyword.arg == "encoding":
            return True
    return False


def problems_in(source: str, where: str) -> list[str]:
    """The process starts of one file that ask for text and do not name the encoding."""
    problems = []
    for call in process_starts(ast.parse(source)):
        if not asks_for_text(call):
            continue  # bytes in, bytes out - nothing is being decoded
        if not any(keyword.arg == "encoding" for keyword in call.keywords):
            problems.append(f"{where}:{call.lineno}: a process is read as text without "
                            'encoding="utf-8"')
    return problems


def test_every_process_read_as_text_names_its_encoding():
    """The convention itself: no call decodes with whatever code page the machine has."""
    problems = []
    for path in sources():
        problems += problems_in(path.read_text(encoding="utf-8"),
                                path.relative_to(ROOT).as_posix())

    assert problems == []


def test_the_reader_finds_the_calls_it_is_meant_to_judge():
    """A detector that finds nothing passes every repository, this one included."""
    found = [
        path.relative_to(ROOT).as_posix()
        for path in sources()
        if process_starts(ast.parse(path.read_text(encoding="utf-8")))
    ]

    assert len(found) > 4
    assert "src/elemctl/build.py" in found


def test_a_call_that_asks_for_text_without_an_encoding_is_caught():
    """The provocation, in both shapes the repository writes a process start in."""
    plain = "import subprocess\nsubprocess.run(command, capture_output=True, text=True)\n"
    seam = "import subprocess\n(run or subprocess.run)(command, text=True)\n"

    assert len(problems_in(plain, "plain.py")) == 1
    # the shape the failure came in: the callable is chosen at the call site, and a check
    # reading the head of the call would have looked straight past it
    assert len(problems_in(seam, "seam.py")) == 1


def test_a_call_that_decodes_nothing_is_left_alone():
    """Bytes in, bytes out: there is no encoding to name, and demanding one would be noise."""
    bytes_only = "import subprocess\nsubprocess.run(command, capture_output=True, check=True)\n"
    spelled = ('import subprocess\nsubprocess.run(command, capture_output=True, text=True, '
               'encoding="utf-8")\n')

    assert problems_in(bytes_only, "bytes.py") == []
    assert problems_in(spelled, "spelled.py") == []
