#!/usr/bin/env python
"""Does the documentation still cover elemctl: tools, variables, extensions, mirrors, images.

What is elemctl's own business stays here - which MCP tools it registers, which environment
variables it reads, what the archive packs, which statements about the platform have to be told
in the same words everywhere, where its mirroring script carries which page, and which documents
and folders are read for a sentence that explains a change by naming who asked for it. Everything
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
    attribution_problems,
    attribution_self_check,
    box_headlines,
    claim_problems,
    claim_texts,
    coverage_problems,
    front_description,
    image_problems,
    injected,
    injection_problems,
    jargon_problems,
    jargon_self_check,
    mirror_problems,
    pitch_problems,
    pyproject_description,
    run,
    section_body,
    site_description,
    site_pages,
    source_attribution_problems,
    source_jargon_problems,
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
    PitchItem("One-command deploy", "Развёртывание одной командой", "deploy", "развёрт"),
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


#: The statements that live in more than one place at once. The first two are here because they
#: really did drift: the correction reached the Console API sections and left the tool hints,
#: the CLI requirements and the comments in the code telling the model it replaced - one
#: document carried both at once - and the build card's address was wrong on every page for as
#: long as the command it broke. The third is the exit code of a plugin command. It is told by
#: the specification, the MCP page, the READMEs and the docstring of `Command`, and a place
#: that kept the earlier sentence - `"ok": false` gives 1 - would pass half of the rule off as
#: all of it. The fourth is the commit of an upload, which every place used to deny. The fifth
#: is the number the server gives a build uploaded into a project, which the tool hints and the
#: code comments put down to something else, and then every place counted from the build list
#: alone. The sixth is the space of an upload, which the pages and the client spelled the way
#: the server does not read. The seventh is the list of application statuses, which lacked two
#: that live checks kept meeting. The eighth is what a hole in the numbering of builds means,
#: which every place put down to the housekeeping. The ninth is the order in which the client
#: meets the 401 of a missing handler: the pages had it renewing the token first. The tenth is
#: when the housekeeping runs and what it spares, which every place left to a collector that
#: would get to a build some day. The eleventh is what identifies a project, which every place
#: put down to the vendor and the name of the manifest.
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
    Claim(
        name="a plugin command sets the exit code of the CLI in the exit-code field of its result",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/mcp.md", "docs/mcp.ru.md",
            "README.md", "README.ru.md",
            "src/elemctl/plugins.py",
        ),
        wording=("exit-code",),
        retired=(
            "gives exit code 1 in the CLI",
            "gives CLI exit code 1",
            "даёт в CLI код возврата 1",
        ),
    ),
    # The upload was believed to take no commit at all: the PascalCase names tried once were
    # ignored, and the pages, the docstrings and the message of the schema guard all said a
    # commit comes from a repository link alone. The reference spells the parameter in
    # kebab-case, and the server keeps it.
    Claim(
        name="an upload into a project names its commit in the commit-id parameter",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/platform.md", "docs/platform.ru.md",
            "src/elemctl/client.py",
        ),
        wording=("`commit-id`",),
        retired=(
            "has no `BranchName`, `CommitId` or `CommitMessage` parameters",
            "Параметров `BranchName`, `CommitId` и `CommitMessage` у метода",
            "only comes from the project's link to its repository",
            "comes from the project's repository link",
            "проставляет только связь проекта с репозиторием",
            "проставляется только связью проекта с репозиторием",
        ),
    ),
    # The server numbers a build uploaded into a project by itself. The pages said only that
    # the platform renumbers the version of the manifest, and the tool hints and the comments
    # of the code explained a version on a card by a freshly created application counting
    # from scratch - while the deploy report went on saying ok with the two versions apart.
    # Then the rule itself fell short: every place gave the highest number of the base in the
    # build list plus one, while the server counts on from the highest number it has ever
    # given. A build deleted from the top of the list keeps its number, the next upload skips
    # it, and a deploy that counted from the list alone warned about a renumbering of its own.
    Claim(
        name="the server numbers a build uploaded into a project: the base of the project "
             "descriptor and the highest number it has ever given in that base plus one",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/platform.md", "docs/platform.ru.md",
            "src/elemctl/versions.py", "src/elemctl/deploy.py",
            "src/elemctl/mcp_server.py", "src/elemctl/i18n.py",
        ),
        wording=("ever given", "когда-либо выдавал"),
        retired=(
            "renumbers the manifest version on upload",
            "перенумеровывает по-своему",
            "numbers its versions from scratch",
            "numbers the versions on its card from scratch",
            "renumbers the version string from scratch",
            "у нового приложения нумеруется заново",
            "highest number of that base plus one",
            "highest one of that base plus one",
            "наибольший номер этой базы плюс один",
        ),
    ),
    # The space went as the PascalCase SpaceId, the spelling of an older reference, and the pages
    # said so. The server reads `space-id` on an upload into a project and no space parameter at
    # all on POST /projects, so a new project goes into its space by the path.
    Claim(
        name="an upload into a project names its space in space-id, and a new project goes "
             "into a space by the path /spaces/{space-id}/projects",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/platform.md", "docs/platform.ru.md",
            "src/elemctl/client.py",
        ),
        wording=("/spaces/{space-id}/projects",),
        retired=(
            "optional `SpaceId` query parameter",
            "note that its name is in PascalCase",
            "параметром `SpaceId`, имя пишется в",
            "The space goes as SpaceId",
        ),
    ),
    # The reference gives the status of an application as a plain string, so the list of values
    # is what live checks met, and two of them were missing from it: the list ended at Creating.
    Claim(
        name="the application statuses met live include Deleting and UNKNOWN",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/platform.md", "docs/platform.ru.md",
            "src/elemctl/client.py",
        ),
        wording=("`Deleting`",),
        retired=(
            "`Frozen`, `Creating`. During",
            "`Frozen`, `Creating`.\nВо время",
        ),
    ),
    # UNKNOWN was waited on for the whole timeout, and a deploy on an application without its
    # database spent five minutes before it named the status. The pages said the wait runs out
    # its timeout on it; the wait now gives the status a minute in a row of its own.
    Claim(
        name="a wait for a status puts up with UNKNOWN for a minute in a row and then stops",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/platform.md", "docs/platform.ru.md",
            "src/elemctl/client.py",
        ),
        wording=("a minute in a row", "минуту подряд", "UNKNOWN_TIMEOUT"),
        retired=(
            "runs out its timeout on such an application",
            "идёт до конца срока",
        ),
    ),
    # A hole in the numbering of builds was a deletion, full stop. An upload by the vendor
    # and the name keeps the number of its archive, and the count of the project goes on
    # from it, so a hole can be a jump nobody deleted anything in.
    Claim(
        name="a hole in the numbering of builds is a deletion or a jump",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/mcp.md", "docs/mcp.ru.md",
            "src/elemctl/client.py", "src/elemctl/mcp_server.py",
            "src/elemctl/versions.py",
        ),
        wording=("jump", "скач"),
        retired=(
            "is a build already taken away, and the line says how many",
            "снятая сборка, и строка называет, скольких номеров не хватает",
            "уже снятая уборкой.\n",
            "которую уборка уже сняла.\n",
            "is a build the platform has deleted, and that is a FACT OF THE ANSWER",
        ),
    ),
    # The 401 of a missing handler was named only after a renewed token had got the same
    # answer, and the pages said the client renews the token first. The text is read before
    # the token is renewed now, and a place still telling the older order would describe a
    # sign-in and a second request that never happen.
    Claim(
        name="the 401 of a missing handler is recognized by its text before the token is renewed",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/platform.md", "docs/platform.ru.md",
            "src/elemctl/client.py",
        ),
        wording=(
            "before the token is renewed",
            "before a new token is asked for",
            "до обновления токена",
        ),
        retired=(
            "renews the token on a 401 and asks once more",
            "На 401 клиент обновляет токен",
            "A renewed token does not change that answer",
            "Новый токен этот ответ не меняет",
            "the token was renewed and the request repeated before that answer came back",
        ),
    ),
    # The pages said everything else goes "when the collector gets to it", which read as a
    # timer. The console deletes at one moment only, when an application of the project
    # finishes applying a build, and it spares a build uploaded by the vendor and the name:
    # such a build is protected on arrival. Checked against the source of the console and live.
    Claim(
        name="the housekeeping runs when an application of the project finishes applying a "
             "build",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/platform.md", "docs/platform.ru.md",
            "docs/mcp.md", "docs/mcp.ru.md",
            "src/elemctl/client.py", "src/elemctl/cli.py",
            "src/elemctl/mcp_server.py", "src/elemctl/i18n.py",
        ),
        wording=("finishes applying", "заканчивает применение"),
        retired=(
            "goes when the collector gets to it",
            "когда до него дойдёт очередь",
            "когда до него дойдет очередь",
        ),
    ),
    # A project was said to be identified by the vendor and the name of the manifest, not by
    # the Ид of its descriptor. The checks behind that had the two agree. The console looks an
    # upload without a project id up by the Ид, and the pair is only a constraint of the space:
    # a live check with the two taken apart put three pairs into one project and refused a
    # fresh Ид with a pair already held.
    Claim(
        name="a project is identified by the Ид of its descriptor, and the vendor and the name "
             "only have to be free",
        told_in=(
            "docs/SPEC.md", "docs/SPEC.ru.md",
            "docs/platform.md", "docs/platform.ru.md",
            "docs/index.md", "docs/index.ru.md",
            "README.md", "README.ru.md",
            "src/elemctl/client.py", "src/elemctl/probe.py", "src/elemctl/mcp_server.py",
        ),
        wording=("identified by the `Ид`", "опознается по `Ид`", "by the Ид of the", "по Ид из"),
        retired=(
            "identified by the pair `Vendor` + `Name`",
            "identified by the `Vendor` + `Name` pair",
            "identified by vendor and name",
            "опознаётся парой `Vendor` + `Name`",
            "опознается парой `Vendor` + `Name`",
            "опознаётся поставщиком и именем",
            "опознается поставщиком и именем",
            "определяется поставщиком и именем",
            "recognizes a project by the vendor and name",
            "опознаёт проект по паре поставщик плюс имя",
            "опознает проект по паре поставщик плюс имя",
            "routes it by the vendor and the name of the manifest",
            "chosen by the platform out of the vendor and the name",
            "выбирает сама платформа по поставщику и",
        ),
    ),
)


#: The Russian documents at the root. Pages are found under `docs/` by the pattern the jargon
#: check uses by default; these three are not pages and have to be named. CLAUDE.md is written
#: in English and is read all the same, because it quotes the Russian conventions and a quote is
#: where a borrowed word comes back.
RUSSIAN_DOCUMENTS = ("README.ru.md", "CHANGELOG.ru.md", "CLAUDE.md")

#: The sources whose Russian strings a person reads. The catalog is one file by design: the
#: help of the parser is routed through `t()` as well, so `--help` and every error of every
#: command are in it and nowhere else - `cli.py` has not a single Russian literal left. The
#: MCP server is the second surface and is not a catalog: its instructions and the docstring
#: of every tool travel to a client as the description of that tool, and a reader meets them
#: in a tool list the way another reader meets a page.
#:
#: The Cyrillic elsewhere in the package is the platform's vocabulary, not ours. `Проект.yaml`
#: and `Ресурсы` name files inside an archive, `Длина` and `Реквизиты` are keys of a metadata
#: file, and "занято" is matched against what the platform itself writes back. Naming those
#: files here would judge identifiers by a dictionary written about prose.
RUSSIAN_SOURCES = ("src/elemctl/i18n.py", "src/elemctl/mcp_server.py")


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
    """Every registered tool has a row, and no row names a tool that is gone.

    Both directions and the empty reader come from `coverage_problems`: the set difference was
    written out by hand here three times over, once per check, and the third copy had already
    lost the empty-reader guard the first one had. What stays is what the sources are and where
    the document is.
    """
    tools = registered_tools()
    problems: list[str] = []
    for name in ("mcp.md", "mcp.ru.md"):
        problems += coverage_problems(
            tools, set(_TOOL_ROW.findall(LAYOUT.page(name))), what="tool", where=name,
        )
    return problems


def check_environment() -> list[str]:
    """A variable the code reads and the configuration page does not describe.

    The specification carries its own table, and it is about the CONTRACT with the platform: a
    variable of the ELEMENT_ family belongs there, while the CI, locale and plugin knobs do
    not. Judged apart for that reason - a contribution with three new TLS variables passed this
    guard green while the specification knew nothing about them.

    Only one direction is judged: a page quotes the variables of the neighbouring tooling beside
    its own, and demanding a source for every one of them would make the check noise.
    """
    variables = env_variables()
    problems: list[str] = []
    for name in ("config.md", "config.ru.md"):
        problems += coverage_problems(
            variables, set(_INLINE.findall(LAYOUT.page(name))),
            what="variable", where=name, phantoms=False,
        )
    contract = {name for name in variables if name.startswith("ELEMENT_")}
    for name in ("SPEC.md", "SPEC.ru.md"):
        problems += coverage_problems(
            contract, set(_INLINE.findall(LAYOUT.page(name))),
            what="contract variable", where=name, phantoms=False,
        )
    return problems


def check_extensions() -> list[str]:
    """The archive's allowlist against what the platform page tells a reader it packs.

    One direction again: the page quotes file names and paths in the same backticks, so the
    other side of the difference is prose, not a claim about the allowlist.
    """
    extensions = allowed_extensions()
    problems: list[str] = []
    for name in ("platform.md", "platform.ru.md"):
        documented = {
            item for quoted in _EXTENSION.findall(LAYOUT.page(name))
            for item in re.findall(r"\.[a-z0-9]+", quoted)
        }
        problems += coverage_problems(
            extensions, documented, what="extension", where=name, phantoms=False,
        )
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


def check_jargon() -> list[str]:
    """Transliterated English in the Russian documentation, and the dictionary proving itself.

    The Russian edition kept drifting into English written in Cyrillic letters. An entry said
    that a "пин" had been raised after a "прогон", and the reader had to translate both before
    the sentence meant anything. The word is invisible to the person writing it, because it is
    the word that person says out loud all day, so a review does not catch it either.

    The dictionary lives in `docsguard`, with the neighbouring repositories that are written the
    same way; what stays here is which documents of this one are Russian. The self-check runs
    beside the pages rather than in the test suite alone: a root that loses a letter finds
    nothing and reads exactly like a repository in order, and a pinned version would keep that
    silence here for as long as the tag stays where it is.

    The pages are half of the reading. The help of a command and the text of an error are
    Russian as well, and they live in the sources rather than under `docs/`: they reach a
    terminal the moment somebody runs the tool. Same reader, other surface, one dictionary.
    """
    return (jargon_self_check()
            + jargon_problems(LAYOUT, documents=RUSSIAN_DOCUMENTS)
            + source_jargon_problems(LAYOUT, RUSSIAN_SOURCES))


#: The documents outside `docs/` in both editions - the two a reader of GitHub and of PyPI
#: meets first, the history, the notes for a contributor and the note about where the tool came
#: from. The pages of `docs/` the guard collects by itself.
ATTRIBUTION_DOCUMENTS = ("README.md", "README.ru.md", "CHANGELOG.md", "CHANGELOG.ru.md",
                         "CLAUDE.md", "ORIGIN.md")

#: The folders whose comments and docstrings are read: everything written in Python here. That
#: is the difference from the jargon list above, where two named files hold every Russian
#: sentence a person meets. A sentence explaining a decision needs no catalog and can be written
#: in any file - in the neighbouring repository all three that were found by hand were in the
#: docstrings of tests.
ATTRIBUTION_SOURCES = ("src", "scripts", "tests", "tools")


def check_attribution() -> list[str]:
    """No page and no comment explains a change by naming the person who asked for it.

    The repository has one author, so a sentence about who asked gives the reader nothing to act
    on and suggests the code was written for somebody else. What belongs there is what the
    previous behaviour or text got wrong.

    The table lives in `docsguard` and catches a turn of phrase rather than a word, because an
    owner is also a word of the subject - an object has one, and so does a build. What stays
    here is the scope: both editions of the documents outside `docs/`, and the folders whose
    comments are read. The self-check runs beside the pages for the same reason the dictionary's
    does: a pinned version that had quietly stopped judging would look from here exactly like a
    repository in order.
    """
    return (attribution_self_check()
            + attribution_problems(LAYOUT, documents=ATTRIBUTION_DOCUMENTS)
            + source_attribution_problems(LAYOUT, ATTRIBUTION_SOURCES))


CHECKS = (check_tools, check_environment, check_extensions, check_claims, check_mirrors,
          check_translations, check_images, check_pitches, check_jargon, check_attribution)


def problems() -> list[str]:
    """Every finding of every check - what the test suite asserts on."""
    found: list[str] = []
    for check in CHECKS:
        found.extend(check())
    return found


if __name__ == "__main__":
    sys.exit(run(CHECKS, title="docsguard"))
