#!/usr/bin/env python
"""Fail when the documentation stops covering what elemctl actually offers.

The command reference is generated (scripts/gen-cli-docs.py) and cannot go stale, and a test
of its own holds it down. Everything else is written by hand, and hand-written pages drift in
a way nobody notices. Every class of finding below is one this repository was actually in:

* seven MCP tools – `apply_build`, `build_assembly`, `find_app`, `inspect_assembly`,
  `list_app_tasks`, `list_branches`, `list_spaces` – were named nowhere but the sources;
* `ELEMCTL_NO_PLUGINS` and the CI variables the build reads were absent from the settings
  page, and the row for `ELEMCTL_NO_PROXY` had fallen out of the table into a paragraph;
* `.htm` was in the archive allowlist and not in the list of extensions on the platform page;
* the README's copy of the features, the quick start and the limitations had drifted from the
  page they were copied from – in both directions at once.

    python scripts/docsguard.py

Checks, all of them cheap enough to run on every commit:

* every MCP tool the server registers has a row on docs/mcp.md AND docs/mcp.ru.md;
* no row names a tool the server no longer registers;
* every environment variable the code reads is documented on both settings pages;
* every extension of the archive allowlist is named on both platform pages;
* the sections injected into the READMEs match their source pages, and the mirrored
  changelog pages match the root CHANGELOG (scripts/sync-docs.mjs was run);
* every page has a translation, and every image a page embeds exists in the repository.

The exit code is what CI reads: 0 clean, 1 with findings printed one per line.
"""

from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SRC = ROOT / "src" / "elemctl"
SYNC = ROOT / "scripts" / "sync-docs.mjs"
BLUME = ROOT / "site" / "blume.config.ts"

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
_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
#: A README on GitHub cannot embed a page-relative path, so images go by their raw URL -
#: which is exactly the kind of link that rots silently when a file is renamed.
_RAW_PREFIX = "https://raw.githubusercontent.com/keyfire/elemctl/main/"
_INJECTION = re.compile(
    r"\{\s*from:\s*'([^']+)',\s*section:\s*'([^']+)',\s*into:\s*'([^']+)',\s*marker:\s*'([^']+)'"
)
_MIRROR = re.compile(r"\bfrom:\s*'([^']+)',\s*\n\s*to:\s*'([^']+)'")


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
    """The archive allowlist – the set build.py actually packs by."""
    text = (SRC / "build.py").read_text(encoding="utf-8")
    block = re.search(r"ALLOWED_EXTENSIONS\s*=\s*\{([^}]*)\}", text, re.S)
    return set(re.findall(r'"(\.[a-z0-9]+)"', block.group(1))) if block else set()


def site_pages() -> list[Path]:
    """The pages the site actually publishes – blume.config.ts says which are left out."""
    config = BLUME.read_text(encoding="utf-8")
    block = re.search(r"exclude:\s*\[([^\]]*)\]", config, re.S)
    patterns = re.findall(r'"([^"]+)"', block.group(1)) if block else []
    return [
        path for path in sorted(DOCS.glob("*.md"))
        if not any(fnmatch.fnmatch(path.name, pattern.removeprefix("**/")) for pattern in patterns)
    ]


def page(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def repo_document(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def page_body(name: str) -> str:
    """A page without its frontmatter and without the generator notes."""
    text = re.sub(r"^---\n[\s\S]*?\n---\n", "", page(name))
    return re.sub(r"<!--[\s\S]*?-->\n?", "", text).strip()


def section_body(name: str, section: str) -> str | None:
    """The body of one `## Section` of a page – what a README embeds."""
    lines = page(name).split("\n")
    try:
        start = lines.index(f"## {section}")
    except ValueError:
        return None
    rest = lines[start + 1:]
    end = next((i for i, line in enumerate(rest) if line.startswith("## ")), len(rest))
    return "\n".join(rest[:end]).strip()


def injected(document: str, marker: str) -> str | None:
    """The block scripts/sync-docs.mjs writes into a repository document."""
    text = (ROOT / document).read_text(encoding="utf-8")
    open_tag, close_tag = f"<!-- {marker}:start -->", f"<!-- {marker}:end -->"
    if open_tag not in text or close_tag not in text:
        return None
    return text.split(open_tag, 1)[1].split(close_tag, 1)[0].strip()


def mirror_source(name: str) -> str:
    """A root document the way a mirrored page carries it: no H1, no language switcher."""
    lines = [
        line for line in (ROOT / name).read_text(encoding="utf-8").split("\n")
        if not line.startswith(("**English**", "**Английская", "[English]"))
    ]
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is not None and lines[first].startswith("# "):
        del lines[first]
    return "\n".join(lines).strip()


def check() -> list[str]:
    problems: list[str] = []

    tools = registered_tools()
    if not tools:
        return ["no MCP tool found in the sources - has the registration changed?"]
    for name in ("mcp.md", "mcp.ru.md"):
        listed = set(_TOOL_ROW.findall(page(name)))
        for missing in sorted(tools - listed):
            problems.append(f"{name}: {missing} has no row in the tool table")
        for phantom in sorted(listed - tools):
            problems.append(f"{name}: {phantom} is documented but not registered")

    variables = env_variables()
    for name in ("config.md", "config.ru.md"):
        documented = set(_INLINE.findall(page(name)))
        for missing in sorted(variables - documented):
            problems.append(f"{name}: {missing} is read by the code and documented nowhere")

    extensions = allowed_extensions()
    for name in ("platform.md", "platform.ru.md"):
        documented = {
            item for quoted in _EXTENSION.findall(page(name))
            for item in re.findall(r"\.[a-z0-9]+", quoted)
        }
        for missing in sorted(extensions - documented):
            problems.append(f"{name}: the archive takes {missing} and the page does not say so")

    sync = SYNC.read_text(encoding="utf-8")
    injections = _INJECTION.findall(sync)
    if not injections:
        problems.append("sync-docs.mjs: no injection found - has the layout changed?")
    for source, section, document, marker in injections:
        block = injected(document, marker)
        expected = section_body(Path(source).name, section)
        if block is None:
            problems.append(f"{document}: the {marker} markers are gone")
        elif expected is None:
            problems.append(f"{source}: the section \"## {section}\" is gone")
        elif block != expected:
            problems.append(
                f"{document}: the {marker} block is stale - run node scripts/sync-docs.mjs"
            )

    for source, mirrored in _MIRROR.findall(sync):
        if page_body(Path(mirrored).name) != mirror_source(source):
            problems.append(
                f"{mirrored}: the mirror of {source} is stale - run node scripts/sync-docs.mjs"
            )

    published = site_pages()
    if not published:
        problems.append("blume.config.ts: no page is published - has the exclude list changed?")
    for path in published:
        if ".ru." in path.name:
            continue
        if not (DOCS / path.name.replace(".md", ".ru.md")).exists():
            problems.append(f"{path.name}: has no Russian translation")

    documents = [(path.name, page(path.name)) for path in published]
    documents += [(name, repo_document(name)) for name in ("README.md", "README.ru.md")]
    for name, text in documents:
        for href in _IMAGE.findall(text):
            if href.startswith(_RAW_PREFIX):
                target = ROOT / href[len(_RAW_PREFIX):]
            elif href.startswith(("http://", "https://")):
                continue
            else:
                target = (DOCS / href).resolve()
            if not target.exists():
                problems.append(f"{name}: the image {href} is not in the repository")
                continue
            # A page must show the SVG, which carries both palettes; the PNG next to it has one
            # baked in and belongs to the README, where GitHub follows no theme at all.
            if name.endswith(".md") and name not in ("README.md", "README.ru.md") \
                    and target.suffix == ".png" and target.with_suffix(".svg").exists():
                problems.append(
                    f"{name}: {target.name} follows no theme - the page needs "
                    f"{target.with_suffix('.svg').name}, the PNG belongs to the README"
                )

    return problems


def main() -> int:
    problems = check()
    if problems:
        print("\n".join(problems))
        print(f"\ndocsguard: {len(problems)} finding(s)")
        return 1
    print("docsguard: the documentation covers every tool, variable, extension and image")
    return 0


if __name__ == "__main__":
    sys.exit(main())
