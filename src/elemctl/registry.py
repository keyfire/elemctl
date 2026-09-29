"""The local registry of uploads: which build this machine uploaded, and from which code.

The platform keeps the commit of a build when the upload names it (`commit-id`, section 4.4
of the specification), but not the branch, not whether the tree had uncommitted changes and
not the directory the build was made from. A build uploaded into a new project carries no
commit at all. With several sessions deploying from one machine, a build on an application
could not be traced to the working tree it came from. So every upload elemctl makes is also
written down here, one JSON line per upload, and the listings fill the gaps of a card from
it, naming where each value came from.

A deploy counts the number of its build from here as well. The server counts on from the
highest number it has ever given in a base, and a deleted build keeps its number while the
build list no longer shows it; the registry still has the number such a build got when this
machine uploaded it (`remembered_versions`).

The registry is LOCAL: a build uploaded from another machine, from CI or by an elemctl that
had no registry yet is not in it. A registry that cannot be written costs a warning and
never the upload - the build is on the server by then - and one that cannot be read reads
as empty.

The registry keeps the newest uploads, a thousand by default: every line is an upload, and
a file nobody trimmed grew with each of them for as long as the machine deployed. What it
answers is the origin of the builds that still matter, the ones a project lists and an
application runs, and those are the recent ones.
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
#: How many uploads the registry keeps instead of DEFAULT_LIMIT; 0 keeps every one.
LIMIT_ENV = "ELEMCTL_REGISTRY_LIMIT"
#: A thousand lines are about half a megabyte, read whole by every listing that asks.
DEFAULT_LIMIT = 1000
#: The route of an upload into a project by its id: the server numbers the build itself.
ROUTE_PROJECT = "project"
#: The route of an upload without a project id, POST /projects or
#: POST /spaces/{space-id}/projects: the server finds the project by the Ид of the descriptor,
#: or creates one when no live project carries it, and the build keeps the version of its
#: archive.
ROUTE_NO_PROJECT_ID = "no-project-id"
#: The values older lines carry for today's routes. The route without a project id used to be
#: written as "vendor-name", after the vendor and the name of the manifest, which is not what
#: the server finds the project by. A registry keeps a thousand uploads, so such lines stay for
#: a long time, and they are read as the route they record.
LEGACY_ROUTES = {"vendor-name": ROUTE_NO_PROJECT_ID}


def upload_route(entry):
    """The route of a registry line, a value written by an older elemctl read as today's."""
    route = str(entry.get("route") or "") if isinstance(entry, dict) else ""
    return LEGACY_ROUTES.get(route, route)


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
    app_id=None,
    route=None,
    environ=None,
    now=None,
):
    """Write one upload down; return a warning when the registry could not take it, else "".

    dirty is True, False, or None when nothing is known about the tree - an archive
    uploaded as a file says nothing about the tree it was built from.

    app_id is the application the upload was made for: the one a deploy applies the build
    to, the throwaway one a probe creates out of it. A probe kept for a look by hand tends
    to get deploys of its own, so the build it runs stops being the probe's, while the
    application stays the one the probe created - and the cleanup recognizes it by this.

    route is the way the build went to the platform: ROUTE_PROJECT into a project by its id,
    where the server numbers the build itself, or ROUTE_NO_PROJECT_ID without a project id,
    where the build keeps the number of its archive and the count of the project goes on
    from it. That is what tells a jump in the numbering from the builds the platform
    deleted (`builds_summary`).
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
        "app-id": str(app_id) if app_id else None,
        "route": route,
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
    limit, warning = registry_limit(environ)
    try:
        trim(path, limit)
    except OSError:
        # The upload is written down; a trim that did not happen is tried by the next one.
        pass
    return warning


def registry_limit(environ=None):
    """How many uploads the registry keeps, and a warning when the variable is not a number.

    ELEMCTL_REGISTRY_LIMIT when it holds a whole number, 0 keeping every upload;
    DEFAULT_LIMIT otherwise. A value that is not a number is named rather than guessed at.
    """
    env = os.environ if environ is None else environ
    raw = (env.get(LIMIT_ENV) or "").strip()
    if not raw:
        return DEFAULT_LIMIT, ""
    if raw.isascii() and raw.isdigit():
        return int(raw), ""
    return DEFAULT_LIMIT, i18n.t(
        "registry.limit-invalid", variable=LIMIT_ENV, value=raw, default=DEFAULT_LIMIT
    )


def trim(path, limit):
    """Cut the registry back to its newest `limit` lines; return how many were dropped.

    The file is left alone until it grows past the limit by a tenth, so that a registry at
    its limit is not rewritten by every upload. Parallel sessions append to the same file,
    so it is rewritten beside itself and swapped in by a rename, and what another process
    appended while the kept lines were being written is carried over before the swap. A
    swap the system refuses - another process holds the file open - leaves the file as it
    was, and the next upload tries again. A line still being written when the file was read
    is not cut in two: it counts as appended later and is carried over whole.
    """
    if limit <= 0:
        return 0
    data = path.read_bytes()
    complete = data[: data.rfind(b"\n") + 1]
    lines = [line for line in complete.splitlines(keepends=True) if line.strip()]
    if len(lines) <= limit + max(limit // 10, 1):
        return 0
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(temp, "wb") as stream:
            stream.writelines(lines[-limit:])
            carried = _carry_over(path, stream, len(complete))
        if carried:
            os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return len(lines) - limit if carried else 0


def _carry_over(path, stream, offset):
    """Copy what was appended to path past offset into stream; False when that cannot be done.

    A file that became shorter than what was read has been trimmed by another process in
    the meantime, and its trim stands. A file still growing after a few rounds is left for
    the next upload.
    """
    for _ in range(3):
        size = path.stat().st_size
        if size < offset:
            return False
        if size == offset:
            return True
        with open(path, "rb") as source:
            source.seek(offset)
            appended = source.read(size - offset)
        stream.write(appended)
        offset += len(appended)
    return path.stat().st_size == offset


def remember_build(
    result, *, response, project_id, stand, command, app_id=None, route=None, environ=None
):
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
        app_id=app_id,
        route=route,
        environ=environ,
    )


def remembered_versions(project_id, environ=None):
    """The versions the uploads of this machine got in a project, as the registry keeps them.

    The server gives a build uploaded into a project the highest number it has ever given in
    the base plus one, and a deleted build keeps its number, while the build list shows only
    what is left. The registry still has a build this machine uploaded after it is deleted,
    whoever deleted it, and that is what a deploy counts the next number from. The stand is
    not compared: the project id is a UUID the server made, and one server reached by two
    addresses would otherwise lose half of what it remembers.
    """
    wanted = str(project_id or "").strip()
    if not wanted:
        return []
    return [
        str(entry.get("version"))
        for entry in remembered_uploads(environ=environ).values()
        if str(entry.get("project-id") or "") == wanted and entry.get("version")
    ]


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
