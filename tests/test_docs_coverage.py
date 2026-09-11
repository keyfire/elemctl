"""The documentation covers what elemctl offers, and the guard that says so still bites.

Two separate failures live here. The first is coverage: a tool, a variable, an extension or an
image that the code has and the pages do not. The second is the guard itself going quiet - a
check that stops finding anything looks exactly like a clean repository, so every class of
finding is provoked here on purpose.

The provocation is made on a COPY of the pages rather than by patching the guard's insides:
since the shared parts moved into the `docsguard` package, a patched name in this module would
not be the one the check calls, and the sabotage would prove nothing while still passing.
"""

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location(
        "elemctl_check_docs", ROOT / "scripts" / "check_docs.py")
    mod = importlib.util.module_from_spec(spec)
    # Registered before it runs: a module loaded from a path this way is not in sys.modules, and
    # a dataclass inside it then fails to resolve its own annotations while being built.
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[spec.name]
        raise
    return mod


@pytest.fixture()
def sabotage(guard, tmp_path, monkeypatch):
    """Run the guard over a COPY of the pages (and, when asked, of the root documents)."""
    def run(edit=lambda name, text: text, *, documents: dict[str, str] | None = None,
            extra: dict[str, str] | None = None):
        docs = tmp_path / "docs"
        shutil.copytree(ROOT / "docs", docs)
        root = ROOT
        if documents is not None:
            root = tmp_path
            for name in ("README.md", "README.ru.md", "CHANGELOG.md", "CHANGELOG.ru.md",
                         "pyproject.toml"):
                shutil.copy(ROOT / name, tmp_path / name)
            # The claims name source files as well, and a copy without them would turn every
            # claim into a finding about a place the repository has not got.
            shutil.copytree(ROOT / "src", tmp_path / "src")
            for name, text in documents.items():
                (tmp_path / name).write_text(text, encoding="utf-8")
        for name, text in (extra or {}).items():
            (docs / name).write_text(text, encoding="utf-8")
        for path in sorted(docs.glob("*.md")):
            path.write_text(edit(path.name, path.read_text(encoding="utf-8")), encoding="utf-8")
        monkeypatch.setattr(
            guard, "LAYOUT",
            guard.Layout(root=root, docs=docs, site_config=guard.LAYOUT.site_config,
                         pyproject=guard.LAYOUT.pyproject, raw_prefix=guard.LAYOUT.raw_prefix),
        )
        return guard.problems()
    return run


def test_documentation_covers_everything(guard):
    assert guard.problems() == []


def test_every_tool_is_found_in_the_sources(guard):
    tools = guard.registered_tools()
    assert len(tools) > 10
    assert "list_apps" in tools and "deploy" in tools


def test_variables_are_the_ones_the_code_reads(guard):
    variables = guard.env_variables()
    assert "ELEMENT_BASE_URL" in variables and "ELEMENT_APP_ID" in variables


def test_extensions_are_the_ones_the_build_packs(guard):
    extensions = guard.allowed_extensions()
    assert ".yaml" in extensions and ".xbsl" in extensions


def test_guard_notices_a_tool_without_a_row(sabotage):
    found = sabotage(lambda name, text: text.replace("| `list_spaces` |", "|  |"))
    assert "mcp.md: the tool list_spaces is named nowhere here" in found
    assert "mcp.ru.md: the tool list_spaces is named nowhere here" in found


def test_guard_notices_a_row_without_a_tool(sabotage):
    found = sabotage(
        lambda name, text: text + "\n| `list_planets` | a tool nobody registered |\n"
        if name in ("mcp.md", "mcp.ru.md") else text)
    assert any("list_planets is named here as a tool" in problem for problem in found)


def test_guard_notices_an_undocumented_variable(guard, monkeypatch):
    monkeypatch.setattr(guard, "env_variables", lambda: {"ELEMCTL_INVENTED"})
    assert any("ELEMCTL_INVENTED" in problem for problem in guard.problems())


def test_a_variable_of_the_contract_is_asked_of_the_specification_as_well(guard, monkeypatch):
    # the failure this second pass exists for: three new TLS variables passed the guard green
    # because the configuration page described them and the specification knew nothing
    monkeypatch.setattr(guard, "env_variables", lambda: {"ELEMENT_INVENTED"})
    named = [problem for problem in guard.check_environment() if "ELEMENT_INVENTED" in problem]

    assert len(named) == 4
    assert any(problem.startswith("SPEC.md: the contract variable") for problem in named)
    assert any(problem.startswith("SPEC.ru.md: the contract variable") for problem in named)


def test_guard_notices_an_extension_the_page_omits(guard, monkeypatch):
    monkeypatch.setattr(guard, "allowed_extensions", lambda: {".invented"})
    assert any(".invented" in problem for problem in guard.problems())


@pytest.mark.parametrize(
    "reader, pages",
    [
        ("registered_tools", ("mcp.md", "mcp.ru.md")),
        ("env_variables", ("config.md", "config.ru.md", "SPEC.md", "SPEC.ru.md")),
        ("allowed_extensions", ("platform.md", "platform.ru.md")),
    ],
)
def test_a_reader_that_has_stopped_finding_anything_is_a_finding(guard, monkeypatch, reader,
                                                                 pages):
    """The third failure of a coverage check, and the one it used to be blind to.

    A reader whose set comes back empty finds no gap and reads exactly like a repository in
    order - the check has simply been passing for free since the shape it knew changed. Only
    the tool reader used to say so, and it said it once for both pages; the variables and the
    extensions had no such guard at all. All three come from `coverage_problems` now, so all
    three say it, per page.
    """
    monkeypatch.setattr(guard, reader, set)
    found = guard.problems()

    for page in pages:
        assert any(problem.startswith(f"{page}: no ") and "the sources" in problem
                   for problem in found), page


def test_guard_notices_a_stale_readme_block(sabotage):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    stale = readme.replace("<!-- features:end -->", "an outdated copy\n<!-- features:end -->")
    found = sabotage(documents={"README.md": stale})
    assert any("no longer matches" in problem for problem in found)


def test_guard_notices_lost_markers(sabotage):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    found = sabotage(documents={"README.md": readme.replace("<!-- features:start -->", "")})
    assert any("markers" in problem for problem in found)


def test_guard_notices_a_stale_changelog_mirror(sabotage):
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    found = sabotage(documents={"CHANGELOG.md": changelog + "\na line nobody mirrored\n"})
    assert any("changelog" in problem.lower() for problem in found)


def test_guard_notices_a_place_that_stopped_telling_a_shared_claim(sabotage):
    # the failure the claim table exists for: a correction reaches the pages and leaves the tool
    # hints, the requirements and the comments in the code telling the model it replaced
    found = sabotage(
        lambda name, text: text.replace("никто не пользуется", "никто не трогает")
        if name == "mcp.ru.md" else text)
    assert any("docs/mcp.ru.md" in problem and "nobody uses" in problem for problem in found)


def test_guard_notices_the_superseded_wording_coming_back(sabotage):
    # a page that copied the old sentence, or one the correction simply never reached
    found = sabotage(
        lambda name, text: text + "\nAPI адресует сборку ТОЛЬКО UUID.\n"
        if name == "platform.ru.md" else text)
    assert any("docs/platform.ru.md" in problem and "superseded" in problem for problem in found)


def test_guard_notices_a_claim_that_names_a_place_it_has_not_got(guard, monkeypatch):
    # a renamed file must not turn a claim into a check of nothing
    invented = guard.Claim(name="invented", told_in=("docs/no-such-page.md",), wording=("x",))
    monkeypatch.setattr(guard, "CLAIMS", (invented,))
    assert any("no-such-page.md" in problem for problem in guard.check_claims())


def test_a_claim_is_a_fact_told_in_several_places(guard):
    # one place is just a sentence - the table is for what is said in many and corrected in one
    assert guard.CLAIMS
    for claim in guard.CLAIMS:
        assert len(claim.told_in) > 1, claim.name
        assert claim.wording and claim.retired, claim.name


def test_a_stale_mirror_names_the_command_that_rebuilds_it(sabotage):
    # "regenerate the mirrors" left the reader looking for how, and the mirror that goes stale
    # is almost always the changelog one - where a single command does the whole step
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    found = sabotage(documents={"CHANGELOG.md": changelog + "\na line nobody mirrored\n"})
    assert any("changelog-link.py" in problem for problem in found)


def test_guard_notices_a_page_without_a_translation(sabotage):
    found = sabotage(extra={"invented.md": "---\ntitle: \"Invented\"\n---\n\ntext\n"})
    assert any("invented.md: has no invented.ru.md" in problem for problem in found)


def test_guard_notices_a_missing_image(sabotage):
    found = sabotage(
        lambda name, text: text + "\n![gone](no-such-diagram.svg)\n"
        if name == "index.md" else text)
    assert any("no-such-diagram.svg" in problem for problem in found)


def test_guard_notices_a_page_showing_the_readme_png(sabotage):
    # the page has to embed the SVG - it carries both palettes; the PNG has one baked in, and a
    # reader in the light theme gets a dark picture (that is how it looked on the neighbouring
    # site for a while)
    found = sabotage(
        lambda name, text: text.replace("architecture.ru.svg)", "architecture.ru.png)"))
    assert any("architecture.ru.png follows no theme" in problem for problem in found)


def test_guard_notices_a_broken_raw_link_in_the_readme(guard, sabotage):
    # a README embeds its images by raw URL, and that link rots without a trace when the file
    # behind it is renamed
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    broken = readme + f"\n![gone]({guard.LAYOUT.raw_prefix}docs/renamed.png)\n"
    found = sabotage(documents={"README.md": broken})
    assert any("renamed.png" in problem for problem in found)


def test_guard_notices_a_feature_missing_from_one_annotation(guard, monkeypatch):
    # the failure this check exists for: the block on the page names a capability and the
    # one-liners around it - which is what a search engine and an AI answer quote - do not
    surfaces = guard.surfaces()
    surfaces["ru"]["docs/index.ru.md"] = surfaces["ru"]["docs/index.ru.md"].replace("пробник", "")
    monkeypatch.setattr(guard, "surfaces", lambda: surfaces)
    problems = guard.check_pitches()
    assert len(problems) == 1
    assert "docs/index.ru.md" in problems[0]


def test_guard_notices_a_headline_no_row_names(sabotage):
    found = sabotage(
        lambda name, text: text.replace("\n## Install", "\n- **Invented feature** - nothing.\n\n## Install")
        if name == "index.md" else text)
    assert any("Invented feature" in problem for problem in found)


def test_guard_notices_a_row_the_page_dropped(sabotage):
    found = sabotage(lambda name, text: text.replace("- **Dumps**", "- **Dumped**"))
    assert any("Dumps" in problem for problem in found)


def test_the_annotations_are_read_as_annotations(guard):
    # an extractor quietly returning a whole file would make every word check above vacuous
    for locale, group in guard.surfaces().items():
        for where, text in group.items():
            assert 80 < len(text) < 600, f"{locale} {where}: {len(text)} characters"
