"""The local registry of uploads: which build this machine uploaded, and from which code.

The platform keeps the commit of a build when the upload names it (`commit-id`, section 4.4
of the specification), but not the branch, not whether the tree had uncommitted changes and
not the directory the build was made from. A build uploaded into a new project carries no
commit at all. With several sessions deploying from one machine, a build on an application
could not be traced to the working tree it came from. So every upload elemctl makes is also
written down here, one JSON line per upload, and the listings fill the gaps of a card from
it, naming where each value came from.

The registry is LOCAL: a build uploaded from another machine, from CI or by an elemctl that
had no registry yet is not in it. A registry that cannot be written costs a warning and
never the upload - the build is on the server by then - and one that cannot be read reads
as empty.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import i18n

#: Where the registry lives instead of the place the operating system gives to a user's data.
DATA_DIR_ENV = "ELEMCTL_DATA_DIR"
#: One line per upload, appended: parallel sessions of one machine add to the same file, and an
#: append of one short line does not lose the line another process wrote meanwhile, the way a
#: rewrite of the whole file would.
REGISTRY_FILE = "uploads.jsonl"


def data_dir(environ=None, *, platform=None):
    """The directory elemctl keeps what it remembers between runs in.

    ELEMCTL_DATA_DIR when it is set. Otherwise %LOCALAPPDATA%\\elemctl on Windows - the
    local, not the roaming, profile, since what is remembered is this machine's - and
    $XDG_STATE_HOME/elemctl elsewhere, ~/.local/state/elemctl by default: the XDG base
    directory for a history of actions.
    """
    env = os.environ if environ is None else environ
    explicit = (env.get(DATA_DIR_ENV) or "").strip()
    if explicit:
        return Path(explicit)
    system = sys.platform if platform is None else platform
    if system.startswith("win"):
        base = (env.get("LOCALAPPDATA") or "").strip()
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "elemctl"
    base = (env.get("XDG_STATE_HOME") or "").strip()
    return (Path(base) if base else Path.home() / ".local" / "state") / "elemctl"


def registry_path(environ=None):
    """The file of the registry."""
    return data_dir(environ) / REGISTRY_FILE


def remember_upload(
    *,
    assembly_id,
    project_id,
    version,
    branch,
    commit,
    dirty,
    project_dir,
    file,
    stand,
    command,
    environ=None,
    now=None,
):
    """Write one upload down; return a warning when the registry could not take it, else "".

    dirty is True, False, or None when nothing is known about the tree - an archive
    uploaded as a file says nothing about the tree it was built from.
    """
    # Imported here: the package imports the client before it defines its version, and the
    # client imports this module.
    from . import __version__

    entry = {
        "assembly-id": str(assembly_id or ""),
        "project-id": str(project_id or ""),
        "version": str(version or ""),
        "branch": str(branch or ""),
        "commit": str(commit or ""),
        "dirty": None if dirty is None else bool(dirty),
        "project-dir": str(project_dir) if project_dir else None,
        "file": str(file) if file else None,
        "stand": str(stand or ""),
        "command": command,
        "uploaded-at": (now or datetime.now().astimezone()).isoformat(timespec="seconds"),
        "elemctl": __version__,
    }
    path = None
    try:
        path = registry_path(environ)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except (OSError, RuntimeError, ValueError) as error:
        # RuntimeError: Path.home() of an environment that has no home directory at all.
        return i18n.t("registry.write-failed", path=path or DATA_DIR_ENV, error=error)
    return ""


def remember_build(result, *, response, project_id, stand, command, environ=None):
    """remember_upload for a build this very run made and uploaded.

    result is the BuildResult: the branch, the commit, the state of the tree and the
    directory come from it. response is the answer of the upload: the id of the build and
    the version the platform gave it, which may differ from the one the build wrote.
    """
    from .client import extract_assembly_id, extract_project_id

    answer = response if isinstance(response, dict) else {}
    dirty_files = result.dirty_files
    return remember_upload(
        assembly_id=extract_assembly_id(answer),
        project_id=project_id or extract_project_id(answer),
        version=answer.get("assembly-version") or answer.get("project-version") or result.version,
        branch=result.branch,
        commit=result.commit,
        dirty=None if dirty_files is None else bool(dirty_files),
        project_dir=result.project_dir,
        file=result.file,
        stand=stand,
        command=command,
        environ=environ,
    )


def remembered_uploads(assembly_ids=None, environ=None):
    """The remembered uploads by assembly id, the last line of an id winning.

    assembly_ids narrows the answer to those ids. A missing or unreadable registry and a
    broken line read as nothing remembered: the listings go on with what the platform says.
    """
    try:
        text = registry_path(environ).read_text(encoding="utf-8", errors="replace")
    except (OSError, RuntimeError, ValueError):
        return {}
    wanted = None if assembly_ids is None else {str(item) for item in assembly_ids if item}
    found = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("assembly-id") or "")
        if key and (wanted is None or key in wanted):
            found[key] = entry
    return found
