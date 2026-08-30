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


def test_guard_notices_a_page_showing_the_readme_png(guard, monkeypatch):
    # the page has to embed the SVG - it carries both palettes; the PNG has one baked in, and a
    # reader in the light theme gets a dark picture (that is how it looked on the neighbouring
    # edt-bridge site)
    original = guard.page
    monkeypatch.setattr(
        guard, "page",
        lambda name: original(name).replace("architecture.ru.svg)", "architecture.ru.png)"),
    )
    assert any("architecture.ru.png follows no theme" in problem for problem in guard.check())


def test_guard_notices_a_broken_raw_link_in_the_readme(guard, monkeypatch):
    # a README embeds its images by raw URL, and that link rots without a trace when the
    # file behind it is renamed
    original = guard.repo_document
    monkeypatch.setattr(
        guard, "repo_document",
        lambda name: original(name) + f"\n![gone]({guard._RAW_PREFIX}docs/renamed.png)\n",
    )
    assert any("renamed.png" in problem for problem in guard.check())


def test_guard_notices_a_feature_missing_from_one_annotation(guard, monkeypatch):
    # the failure this check exists for: the block on the page names a capability and the
    # one-liners around it - which is what a search engine and an AI answer quote - do not
    surfaces = guard.pitch_surfaces()
    surfaces["ru"]["docs/index.ru.md"] = surfaces["ru"]["docs/index.ru.md"].replace("пробник", "")
    monkeypatch.setattr(guard, "pitch_surfaces", lambda: surfaces)
    problems = guard.pitch_problems()
    assert len(problems) == 1
    assert "docs/index.ru.md" in problems[0]


def test_guard_notices_a_headline_no_row_names(guard, monkeypatch):
    original = guard.box_headlines
    monkeypatch.setattr(
        guard, "box_headlines",
        lambda name, heading: original(name, heading) + ["Invented feature"],
    )
    assert any("Invented feature" in problem for problem in guard.pitch_problems())


def test_guard_notices_a_row_the_page_dropped(guard, monkeypatch):
    original = guard.box_headlines
    monkeypatch.setattr(
        guard, "box_headlines",
        lambda name, heading: [h for h in original(name, heading) if h not in ("Dumps", "Дампы")],
    )
    assert any("Dumps" in problem for problem in guard.pitch_problems())


def test_the_annotations_are_read_as_annotations(guard):
    # an extractor quietly returning a whole file would make every word check above vacuous
    for locale, group in guard.pitch_surfaces().items():
        for where, text in group.items():
            assert 80 < len(text) < 600, f"{locale} {where}: {len(text)} characters"
