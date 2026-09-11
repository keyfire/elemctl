#!/usr/bin/env python
"""Does the documentation still cover elemctl: tools, variables, extensions, mirrors, images.

What is elemctl's own business stays here - which MCP tools it registers, which environment
variables it reads, what the archive packs, which statements about the platform have to be told
in the same words everywhere, and where its mirroring script carries which page. Everything
underneath (reading a page, the block between the injection markers, the annotations a
repository states about itself, the machinery behind the claim table, the runner) comes from the
`docsguard` package, which three repositories were keeping in triplicate until the copies
drifted.

Run: `python scripts/check_docs.py`; the exit code is what CI reads.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from docsguard import (
    Claim,
    Layout,
    PitchItem,
    box_headlines,
    claim_problems,
    claim_texts,
    front_description,
    image_problems,
    injected,
    injection_problems,
    mirror_problems,
    pitch_problems,
    pyproject_description,
    run,
    section_body,
    site_description,
    site_pages,
    translation_problems,
)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "elemctl"
SYNC = ROOT / "scripts" / "sync-docs.mjs"

LAYOUT = Layout(
    root=ROOT,
    docs=ROOT / "docs",
    site_config=ROOT / "site" / "blume.config.ts",
    pyproject=ROOT / "pyproject.toml",
    #: A README on GitHub cannot embed a page-relative path, so images go by their raw URL -
    #: which is exactly the kind of link that rots silently when a file is renamed.
    raw_prefix="https://raw.githubusercontent.com/keyfire/elemctl/main/",
)

#: A tool is registered by the decorator; the name is its argument or the function's own.
_TOOL = re.compile(r"@server\.tool\(([^)]*)\)\s*\n\s*def\s+(\w+)")
_TOOL_NAME_ARG = re.compile(r'name\s*=\s*"([a-z_]+)"')
#: A row of the tool table: the first cell holds the name and nothing else.
_TOOL_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|", re.M)
#: A variable is "read by the code" where it is asked for...
_ENV_READ = re.compile(r'os\.environ(?:\.get\(|\[)\s*"([A-Z][A-Z0-9_]+)"')
#: ...or where it is declared as a name of ours to be read later through a constant.
_ENV_DECLARED = re.compile(r'"((?:ELEMENT|ELEMCTL|CI|GITHUB|BUILD)_[A-Z0-9_]+)"')
_INLINE = re.compile(r"`([A-Z][A-Z0-9_]+)`")
_EXTENSION = re.compile(r"`([^`]*)`")
_INJECTION = re.compile(
    r"\{\s*from:\s*'([^']+)',\s*section:\s*'([^']+)',\s*into:\s*'([^']+)',\s*marker:\s*'([^']+)'"
)
_MIRROR = re.compile(r"\bfrom:\s*'([^']+)',\s*\n\s*to:\s*'([^']+)'")

#: A headline of the features block - the English page, the Russian page - and the word that
#: has to stand for it in the short annotations of that language. The block is the full list,
#: but a search engine, PyPI and an AI answer quote the one-liners instead, and those drift on
#: their own. A row with no words is a headline deliberately kept out of the annotations - the
#: reason belongs beside it.
PITCH_ITEMS = (
    PitchItem("Applications", "Приложения", "application", "приложени"),
    # Uploading, listing and deleting a build is the mechanics of the same work; the annotation
    # carries "builds from source", the row below.
    PitchItem("Projects and builds", "Проекты и сборки", None, None),
    PitchItem("Build from sources", "Сборка из исходников", "from source", "из исходников"),
    PitchItem("One-command deploy", "Деплой одной командой", "deploy", "деплой"),
    PitchItem("Compilation check without risking the application",
              "Проверка компиляции без риска для приложения", "probe", "пробник"),
    # The rest are reasons to keep elemctl, not reasons to pick it up: they belong on the page
    # and in the README, which carries the whole block right under the lede, not in one line.
    PitchItem("User lists", "Списки пользователей", None, None),
    PitchItem("Development-environment branches", "Ветки среды разработки", None, None),
    PitchItem("Dumps", "Дампы", None, None),
    PitchItem("MCP server", "MCP-сервер", "MCP", "MCP"),
    PitchItem("Plugins", "Плагины", None, None),
    PitchItem("Self-update", "Обновление", None, None),
    PitchItem("In VS Code", "В VS Code", None, None),
)


#: The statements that live in more than one place at once. Both of them are here because they
#: really did drift: the correction reached the Console API sections and left the tool hints,
#: the CLI requirements and the comments in the code telling the model it replaced - one
#: document carried both at once - and the build card's address was wrong on every page for as
#: long as the command it broke.
CLAIMS = (
    Claim(
        name="the platform deletes the builds nobody uses, whatever their age",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/platform.md", "docs/platform.ru.md",
            "docs/mcp.md", "docs/mcp.ru.md",
            "README.md", "README.ru.md",
            "src/elemctl/client.py", "src/elemctl/cli.py",
            "src/elemctl/mcp_server.py", "src/elemctl/i18n.py",
        ),
        wording=("nobody uses", "никто не пользуется"),
        retired=(
            "store limit", "limited number of builds", "capped builds",
            "предел хранения", "ограниченное число сборок", "вытесня",
        ),
    ),
    Claim(
        name="a build card is addressed by its version, and the id of a card is not an address",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/platform.md", "docs/platform.ru.md",
            "src/elemctl/client.py", "src/elemctl/mcp_server.py",
        ),
        wording=("assemblies/{version}", "assemblies/{:Version}"),
        retired=(
            "assemblies/{assembly-id}",
            "addresses a build only by uuid",
            "адресует сборку только uuid",
        ),
    ),
)


def searched_texts() -> dict[str, str]:
    """Everywhere a superseded wording could be hiding: the pages, the READMEs, the sources.

    The changelog and its mirrors are left out on purpose: an entry about a correction QUOTES
    the model it corrected, and that quote is the record of the fix, not a relapse. The tests
    are out for the same reason - a guard's own provocation has to spell the wording out.
    """
    return claim_texts(
        LAYOUT,
        exclude=("changelog*",),
        documents=("README.md", "README.ru.md"),
        sources=("src/elemctl/*.py",),
    )


def registered_tools() -> set[str]:
    text = (SRC / "mcp_server.py").read_text(encoding="utf-8")
    names = set()
    for arguments, function in _TOOL.findall(text):
        explicit = _TOOL_NAME_ARG.search(arguments)
        names.add(explicit.group(1) if explicit else function)
    return names


def env_variables() -> set[str]:
    names: set[str] = set()
    for path in sorted(SRC.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        names |= set(_ENV_READ.findall(text))
        names |= set(_ENV_DECLARED.findall(text))
    return names


def allowed_extensions() -> set[str]:
    """The archive allowlist - the set build.py actually packs by."""
    text = (SRC / "build.py").read_text(encoding="utf-8")
    block = re.search(r"ALLOWED_EXTENSIONS\s*=\s*\{([^}]*)\}", text, re.S)
    return set(re.findall(r'"(\.[a-z0-9]+)"', block.group(1))) if block else set()


def check_tools() -> list[str]:
    tools = registered_tools()
    if not tools:
        return ["no MCP tool found in the sources - has the registration changed?"]
    problems = []
    for name in ("mcp.md", "mcp.ru.md"):
        listed = set(_TOOL_ROW.findall(LAYOUT.page(name)))
        for missing in sorted(tools - listed):
            problems.append(f"{name}: {missing} has no row in the tool table")
        for phantom in sorted(listed - tools):
            problems.append(f"{name}: {phantom} is documented but not registered")
    return problems


def check_environment() -> list[str]:
    """A variable the code reads and the configuration page does not describe.

    The specification carries its own table, and it is about the CONTRACT with the platform: a
    variable of the ELEMENT_ family belongs there, while the CI, locale and plugin knobs do
    not. Judged apart for that reason - a contribution with three new TLS variables passed this
    guard green while the specification knew nothing about them.
    """
    variables = env_variables()
    problems = []
    for name in ("config.md", "config.ru.md"):
        documented = set(_INLINE.findall(LAYOUT.page(name)))
        for missing in sorted(variables - documented):
            problems.append(f"{name}: {missing} is read by the code and documented nowhere")
    contract = {name for name in variables if name.startswith("ELEMENT_")}
    for name in ("SPEC.md", "SPEC.ru.md"):
        documented = set(_INLINE.findall(LAYOUT.page(name)))
        for missing in sorted(contract - documented):
            problems.append(
                f"{name}: {missing} is part of the platform contract and the specification "
                "does not name it"
            )
    return problems


def check_extensions() -> list[str]:
    extensions = allowed_extensions()
    problems = []
    for name in ("platform.md", "platform.ru.md"):
        documented = {
            item for quoted in _EXTENSION.findall(LAYOUT.page(name))
            for item in re.findall(r"\.[a-z0-9]+", quoted)
        }
        for missing in sorted(extensions - documented):
            problems.append(f"{name}: the archive takes {missing} and the page does not say so")
    return problems


def check_claims() -> list[str]:
    """One fact, one wording - in every place that states it.

    A statement about the platform lives in the specification, on the Console API page, in the
    MCP page, in the README and in the docstrings of the code at once, and it gets corrected in
    one of them. Both times this happened the rest stayed behind: the pages told the new model
    and the tool hints, the requirements and the comments the old one - inside one document.
    The mechanics of that judgement are shared with the neighbouring repositories, which have
    the same shape of documentation and the same defect waiting; what stays here is the table.
    """
    return claim_problems(LAYOUT, CLAIMS, searched_texts())


def check_mirrors() -> list[str]:
    """The injections and mirrors the sync script declares are the ones that still hold.

    Read from the script rather than listed here: a mirror added there and forgotten here would
    be exactly the copy that goes stale unnoticed.
    """
    sync = SYNC.read_text(encoding="utf-8")
    injections = _INJECTION.findall(sync)
    if not injections:
        return ["sync-docs.mjs: no injection found - has the layout changed?"]
    problems = injection_problems(LAYOUT, [
        (document, marker, Path(source).name, section)
        for source, section, document, marker in injections
    ])
    problems += mirror_problems(LAYOUT, [
        (Path(mirrored).name, source) for source, mirrored in _MIRROR.findall(sync)
    ])
    if problems:
        # The finding says "regenerate the mirrors" and the reader has to go looking for how.
        # Naming the command here costs a line and saves that walk - and for the case this
        # keeps happening in, the changelog link, one command does both halves of the step.
        problems.append(
            "rebuild the generated pages with `python scripts/rebuild-docs.py`; when the "
            "change is a pull request link in the changelog, "
            "`python scripts/changelog-link.py <number>` writes it into both editions and "
            "rebuilds them in one run"
        )
    return problems


def check_translations() -> list[str]:
    published = site_pages(LAYOUT)
    if not published:
        return ["blume.config.ts: no page is published - has the exclude list changed?"]
    return translation_problems(LAYOUT, published)


def check_images() -> list[str]:
    return image_problems(
        LAYOUT,
        [path.name for path in site_pages(LAYOUT)],
        documents=["README.md", "README.ru.md"],
        prefer_svg=True,
    )


def surfaces() -> dict[str, dict[str, str]]:
    """The one-line annotations, by locale - what is quoted instead of the page being read.

    The README ledes are not here on purpose: the README carries the whole features block,
    injected from the page, a few lines under them.
    """
    return {
        "en": {
            "site/blume.config.ts": site_description(LAYOUT),
            "docs/index.md": front_description(LAYOUT, "index.md"),
            "pyproject.toml": pyproject_description(LAYOUT),
        },
        "ru": {"docs/index.ru.md": front_description(LAYOUT, "index.ru.md")},
    }


def check_pitches() -> list[str]:
    return pitch_problems(
        PITCH_ITEMS,
        {"en": box_headlines(LAYOUT, "index.md", "Features"),
         "ru": box_headlines(LAYOUT, "index.ru.md", "Возможности")},
        surfaces(),
        pages={"en": "index.md", "ru": "index.ru.md"},
    )


CHECKS = (check_tools, check_environment, check_extensions, check_claims, check_mirrors,
          check_translations, check_images, check_pitches)


def problems() -> list[str]:
    """Every finding of every check - what the test suite asserts on."""
    found: list[str] = []
    for check in CHECKS:
        found.extend(check())
    return found


if __name__ == "__main__":
    sys.exit(run(CHECKS, title="docsguard"))
