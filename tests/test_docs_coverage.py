"""The documentation covers what elemctl offers, and the guard that says so still bites.

Two separate failures live here. The first is coverage: a tool, a variable or an extension
the code has and the pages do not - the state this repository was actually in, with seven
MCP tools named nowhere outside the sources and the README's copy of the features drifted
from the page it came from. The second is the guard itself going quiet: a check that stops
finding anything looks exactly like a clean repository, so every class of finding is
provoked here on purpose.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("docsguard", ROOT / "scripts" / "docsguard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_documentation_covers_everything(guard):
    assert guard.check() == []


def test_every_tool_is_found_in_the_sources(guard):
    tools = guard.registered_tools()
    # the exact number moves with the tool; what must not happen is the registry reading empty
    # or losing the tools whose decorator renames them, both of which make the guard vacuous
    assert len(tools) > 20
    assert {"deploy", "probe", "build_assembly", "inspect_assembly"} <= tools


def test_variables_are_the_ones_the_code_reads(guard):
    variables = guard.env_variables()
    assert "LC_ALL" in variables, "the reader misses direct os.environ.get calls"
    assert "ELEMCTL_NO_PROXY" in variables, "the reader misses variables held in constants"
    assert "CI_PIPELINE_IID" in variables, "the reader misses variables listed in tuples"


def test_extensions_are_the_ones_the_build_packs(guard):
    extensions = guard.allowed_extensions()
    assert {".xbsl", ".yaml", ".htm"} <= extensions


def test_guard_notices_a_tool_without_a_row(guard, monkeypatch):
    original = guard.page
    monkeypatch.setattr(
        guard, "page", lambda name: original(name).replace("| `list_spaces` |", "| |")
    )
    assert any("list_spaces has no row" in problem for problem in guard.check())


def test_guard_notices_a_row_without_a_tool(guard, monkeypatch):
    original = guard.page
    monkeypatch.setattr(
        guard, "page",
        lambda name: original(name).replace(
            "| `list_spaces` |", "| `list_planets` | invented |\n| `list_spaces` |"
        ),
    )
    assert any("list_planets is documented" in problem for problem in guard.check())


def test_guard_notices_an_undocumented_variable(guard, monkeypatch):
    monkeypatch.setattr(guard, "env_variables", lambda: {"ELEMCTL_INVENTED"})
    assert any("ELEMCTL_INVENTED" in problem for problem in guard.check())


def test_guard_notices_an_extension_the_page_omits(guard, monkeypatch):
    monkeypatch.setattr(guard, "allowed_extensions", lambda: {".invented"})
    assert any(".invented" in problem for problem in guard.check())


def test_guard_notices_a_stale_readme_block(guard, monkeypatch):
    monkeypatch.setattr(guard, "injected", lambda document, marker: "an outdated copy")
    assert any("stale" in problem for problem in guard.check())


def test_guard_notices_lost_markers(guard, monkeypatch):
    monkeypatch.setattr(guard, "injected", lambda document, marker: None)
    assert any("markers are gone" in problem for problem in guard.check())


def test_guard_notices_a_stale_changelog_mirror(guard, monkeypatch):
    monkeypatch.setattr(guard, "mirror_source", lambda name: "a changelog nobody mirrored")
    assert any("mirror of CHANGELOG" in problem for problem in guard.check())


def test_guard_notices_a_page_without_a_translation(guard, monkeypatch):
    original = guard.page
    monkeypatch.setattr(guard, "site_pages", lambda: [guard.DOCS / "invented.md"])
    monkeypatch.setattr(
        guard, "page",
        lambda name: original(name) if (guard.DOCS / name).exists() else "",
    )
    assert any("invented.md: has no Russian translation" in p for p in guard.check())


def test_guard_notices_a_missing_image(guard, monkeypatch):
    original = guard.page
    monkeypatch.setattr(
        guard, "page", lambda name: original(name) + "\n![gone](no-such-diagram.svg)\n"
    )
    assert any("no-such-diagram.svg" in problem for problem in guard.check())


def test_guard_notices_a_broken_raw_link_in_the_readme(guard, monkeypatch):
    # a README embeds its images by raw URL, and that link rots without a trace when the
    # file behind it is renamed
    original = guard.repo_document
    monkeypatch.setattr(
        guard, "repo_document",
        lambda name: original(name) + f"\n![gone]({guard._RAW_PREFIX}docs/renamed.png)\n",
    )
    assert any("renamed.png" in problem for problem in guard.check())
