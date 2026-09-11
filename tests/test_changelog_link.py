"""The step that writes a pull request link into the changelog and rebuilds the mirrors.

The failure this script exists for: the link arrives in a commit of its own, the generated
pages are rebuilt by another command, and the second half was forgotten - `main` went red on
the documentation guard. So the test asks for both halves of one run: the link where it belongs
and nowhere else, and the rebuild called every time.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "changelog-link.py"

spec = importlib.util.spec_from_file_location("changelog_link", SCRIPT)
changelog_link = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changelog_link)


CHANGELOG = """# Changelog

Notable changes, newest first.

## Unreleased

### Added
- **A short entry.** Nothing to see here.

### Fixed
- **An entry that is already linked.** It came from an earlier pull request.
  ([#3](https://github.com/keyfire/elemctl/pull/3))

## 2026-09-11 – 0.39.0

### Added
- **An entry of a released day.** Its link was written long ago.
  ([#5](https://github.com/keyfire/elemctl/pull/5))
- **A released entry nobody linked.** From before the rule - history, not an unfinished change.
"""


def linked(text, number=12):
    return changelog_link.add_link(text, number, "keyfire/elemctl")


def test_the_link_goes_to_the_link_less_entries_of_the_topmost_section():
    text, added = linked(CHANGELOG)

    assert added == 1
    assert "- **A short entry.** Nothing to see here. " \
           "([#12](https://github.com/keyfire/elemctl/pull/12))" in text


def test_an_entry_that_already_carries_a_link_is_left_alone():
    """A second link would say the change came from two pull requests."""
    text, _ = linked(CHANGELOG)

    assert text.count("/pull/12") == 1
    assert "/pull/3)" in text


def test_a_released_section_is_history_and_stays_untouched():
    """Entries from before the pull request rule are not unfinished - they are the past."""
    text, _ = linked(CHANGELOG)

    assert "- **A released entry nobody linked.** From before the rule - history, not an " \
           "unfinished change.\n" in text


def test_a_long_entry_takes_the_link_on_a_line_of_its_own():
    """The changelog is wrapped to a width, and an appended link is 48 characters of it."""
    long_entry = CHANGELOG.replace(
        "- **A short entry.** Nothing to see here.",
        "- **A long entry.** It runs over two lines, the way a real one does, and the\n"
        "  second line ends far enough to the right that no link fits after it.",
    )

    text, added = linked(long_entry)

    assert added == 1
    assert "\n  ([#12](https://github.com/keyfire/elemctl/pull/12))\n" in text
    assert all(len(line) <= changelog_link.WIDTH for line in text.split("\n"))


def test_both_editions_are_linked_and_the_pages_rebuilt(tmp_path, monkeypatch):
    """One run covers the whole step - that is the point of having the script at all."""
    for name in changelog_link.EDITIONS:
        (tmp_path / name).write_text(CHANGELOG, encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("Done", (), {"returncode": 0, "stdout": "CHANGELOG.md -> docs/changelog.md",
                                 "stderr": ""})()

    monkeypatch.setattr(changelog_link, "ROOT", tmp_path)

    assert changelog_link.main(["12"], run=fake_run) == 0

    for name in changelog_link.EDITIONS:
        assert "/pull/12" in (tmp_path / name).read_text(encoding="utf-8")
    # One step, and it is the one that rebuilds every generated page: calling a single
    # generator here is how the other one became a thing to remember
    assert calls and calls[0][0] == list(changelog_link.REBUILD)
    assert calls[0][0][-1] == "scripts/rebuild-docs.py"
    assert calls[0][1]["cwd"] == str(tmp_path)
    # The generators name the Russian pages they write; with the system code page the reader
    # thread died on the first Cyrillic byte and the output vanished, exit code 0 and all
    assert calls[0][1]["encoding"] == "utf-8"


def test_a_rebuild_that_did_not_happen_is_an_error(tmp_path, monkeypatch):
    """A missing node must not look like a finished step - that is the whole failure again."""
    for name in changelog_link.EDITIONS:
        (tmp_path / name).write_text(CHANGELOG, encoding="utf-8")

    def fake_run(command, **kwargs):
        raise OSError("node not found")

    monkeypatch.setattr(changelog_link, "ROOT", tmp_path)

    assert changelog_link.main(["12"], run=fake_run) == 1


def test_the_pages_are_rebuilt_even_when_no_entry_needed_a_link(tmp_path, monkeypatch):
    """Running it twice is not a mistake: the second run still proves the pages are current."""
    already = CHANGELOG.replace(
        "Nothing to see here.",
        "Nothing to see here. ([#12](https://github.com/keyfire/elemctl/pull/12))",
    )
    for name in changelog_link.EDITIONS:
        (tmp_path / name).write_text(already, encoding="utf-8")
    calls = []
    monkeypatch.setattr(changelog_link, "ROOT", tmp_path)

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Done", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    assert changelog_link.main(["12"], run=fake_run) == 0
    assert calls == [list(changelog_link.REBUILD)]


@pytest.mark.parametrize("name", changelog_link.EDITIONS)
def test_the_repository_changelog_is_read_as_entries(name):
    """The block reader against the real file: a parser that finds nothing proves nothing."""
    lines = (ROOT / name).read_text(encoding="utf-8").split("\n")
    start, end = changelog_link.top_section(lines)
    blocks = changelog_link.entry_blocks(lines, start, end)

    assert blocks, f"{name}: no entry found in the topmost section"
    for first, last in blocks:
        assert lines[first].startswith("- ")
        assert lines[last].strip()
