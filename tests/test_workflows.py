"""What the workflows install from git - and why that is a decision rather than a default.

The shared documentation guard is a repository of its own, installed from git because it runs
in checks and is never shipped to a user. Installed from `@main` it also arrives whenever that
repository moves: a run here goes red with no commit of ours behind it, which is a red run
nobody reads, and the order of merging - the shared package first, this repository second - has
to be carried in somebody's head.

So the reference is a tag, and it is the SAME tag everywhere. A suite passing against one
version of the guard while the publication run judges the documentation by another is the kind
of difference nobody goes looking for.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

#: An install of the shared guard, whatever it is pinned to:
#: `pip install "git+https://github.com/<owner>/docsguard@<reference>"`.
_DOCSGUARD = re.compile(r"git\+https://github\.com/[\w.-]+/docsguard@([^\"'\s]+)")
#: A released tag of it: v0.3.0 and the like. A branch or a bare commit is not one - a branch
#: moves under the run, and a commit says nothing about what changed.
_TAG = re.compile(r"^v\d+\.\d+\.\d+$")


def installs() -> list[tuple[str, str]]:
    """Every place a workflow installs the shared guard: (workflow, the reference it asks for)."""
    found: list[tuple[str, str]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        found += [(path.name, reference) for reference in _DOCSGUARD.findall(text)]
    return found


def test_the_workflows_do_install_the_shared_guard():
    """A test about pins proves nothing once nothing installs the package any more."""
    found = installs()

    assert len(found) >= 2
    assert {"ci.yml", "pypi-publish.yml"} <= {name for name, _ in found}


def test_every_install_names_a_tag():
    """`@main` is the default that made someone else's commit turn this repository red."""
    loose = [(name, reference) for name, reference in installs() if not _TAG.match(reference)]

    assert loose == []


def test_every_workflow_names_the_same_tag():
    """The suite and the publication have to judge the documentation by the same guard."""
    pinned = {reference for _, reference in installs()}

    assert len(pinned) == 1, f"the workflows have drifted apart: {sorted(pinned)}"


def test_the_documented_way_to_raise_the_pin_is_written_down():
    """The order used to live in somebody's head; a convention nobody wrote down is no convention."""
    conventions = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert "## The shared guard" in conventions
    assert "docsguard" in conventions.split("## The shared guard", 1)[1]
