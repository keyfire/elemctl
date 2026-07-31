"""Safe update of an installed elemctl by unpacking the wheel.

The regular `pipx upgrade` / `pip install --upgrade` break the installation on Windows when
`elemctl.exe` is held by a running MCP server (`elemctl mcp`): pip removes the old version,
fails to unpack the new one and says nothing about the empty space it leaves - the next
`elemctl --version` answers `ModuleNotFoundError`. That is not a theory: it happened during
the 0.19.0 release, on the very machine that publishes the package.

So this command is built the way the toolkit's engine one is (the order was proven there
first):

1. **Holders are named before anything is touched.** The package directory is renamed first -
   a rename fails fast while a file inside is open, and nothing has been removed at that
   point. The processes are then listed by name and pid; `--stop-holders` ends them, otherwise
   the command stops and says who to close. A process is ours by the name of its executable or
   by an interpreter running our modules - an editor or an agent that merely mentions elemctl
   in its arguments is never offered for stopping.
2. **A failure rolls back.** The previous installation is kept aside until the new one has
   been PROVEN to import in a separate process (the current one still runs the old code in
   memory and cannot judge). Anything unexpected puts the old installation back.

Only the elemctl package itself is updated, not its extras; the exe stubs in Scripts are left
alone - they call whatever is in site-packages on the next run. The core has no external
dependencies, so the download and the unpacking are standard library only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

from . import __version__, i18n
from .errors import ElemctlError

#: Where the files come from. The simple index (PEP 691) is served straight from the upload,
#: while the JSON metadata below is a cache that lags behind a release by minutes - see
#: `_wheel_url`. The JSON is kept as the fallback for an index that does not speak PEP 691.
PYPI_SIMPLE = "https://pypi.org/simple/elemctl/"
PYPI_VERSION = "https://pypi.org/pypi/elemctl/{version}/json"
PYPI_LATEST = "https://pypi.org/pypi/elemctl/json"
#: The same URL answers an HTML page unless JSON is asked for by name.
SIMPLE_ACCEPT = "application/vnd.pypi.simple.v1+json"

#: What belongs to the elemctl wheel in site-packages.
_OWNED_PATTERNS = ("elemctl", "elemctl-*.dist-info")
#: Suffix of the directory kept aside while the new version is being proven.
_BACKUP_SUFFIX = ".elemctl-selfupdate-backup"
#: Our own executables - a holder is recognized by the PROCESS NAME first.
_HOLDER_EXECUTABLES = frozenset({"elemctl"})
#: ... and a plain interpreter counts only when it RUNS our modules. The command line alone is
#: not enough: an editor or an agent mentions elemctl in its arguments (a path, a config file)
#: without holding anything, and such a process must never be offered for stopping.
_HOLDER_MODULES = ("elemctl.mcp_server", "elemctl mcp", "-m elemctl")
_INTERPRETERS = ("python", "python3", "pythonw", "py", "pypy", "pypy3")


def _site_packages() -> Path:
    """The directory the package is installed into (site-packages in a real installation)."""
    return Path(__file__).resolve().parent.parent


def _fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ElemctlError(i18n.t("selfupdate.version-not-found")) from error
        raise ElemctlError(i18n.t("selfupdate.pypi-http-error", status=error.code)) from error
    except OSError as error:
        raise ElemctlError(i18n.t("selfupdate.pypi-unreachable", error=error)) from error


def _simple_files() -> list[dict]:
    """Files of the project from the simple index: `{"filename", "url", "version"}` each.

    Empty list when the index cannot be read as JSON (a mirror that answers HTML, a network
    failure) - the caller then falls back to the JSON metadata, which reports the outage in
    its own words. Yanked files are dropped here: a yanked release must not win the "latest"
    race nor be installed by name.
    """
    request = urllib.request.Request(PYPI_SIMPLE, headers={"Accept": SIMPLE_ACCEPT})
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            data = json.load(resp)
    except (OSError, ValueError):
        return []
    files = []
    for item in data.get("files") or []:
        name, url = str(item.get("filename") or ""), str(item.get("url") or "")
        if not name or not url or item.get("yanked"):
            continue
        version = _version_of(name)
        if version:
            files.append({"filename": name, "url": url, "version": version})
    return files


def _version_of(filename: str) -> str:
    """Version segment of a distribution file name; "" when the name is not one of ours."""
    for suffix in (".whl", ".tar.gz", ".zip"):
        if filename.lower().endswith(suffix):
            parts = filename[: -len(suffix)].split("-")
            return parts[1] if len(parts) > 1 else ""
    return ""


def _release_key(version: str) -> tuple[tuple[int, ...], int] | None:
    """Sort key of a plain release (`0.23.0` -> `((0, 23, 0), 0)`); None for anything else.

    Deliberately narrow: only digits and an optional `.postN` are ranked, so a pre-release or
    a dev build can never be picked as the latest version by accident.
    """
    head, _, post = version.partition(".post")
    if post and not post.isdigit():
        return None
    parts = head.split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts), int(post or 0)


def _latest_release(files: list[dict]) -> str:
    """The newest plain release among the files; "" when none of them ranks."""
    ranked = []
    for version in {item["version"] for item in files if item["filename"].lower().endswith(".whl")}:
        key = _release_key(version)
        if key is not None:
            ranked.append((key, version))
    return max(ranked)[1] if ranked else ""


def _wheel_url(version: str | None) -> tuple[str, str]:
    """The URL and the exact version of the py3-none-any wheel (latest, or the given one).

    The file list is taken from the SIMPLE index, not from the JSON metadata. Caught on the
    engine of the toolkit on 31.07.2026 and true here for the same reason: the JSON is a
    cache that catches up minutes after an upload, so right after a release the command
    answers "already current" - or, with an explicit version, "no wheel", because the files
    are read from that same lagging document. The JSON stays as the fallback for an index
    that does not answer PEP 691 (and it is the one that reports an outage in words).
    """
    files = _simple_files()
    if files:
        target = version or _latest_release(files)
        entries = [
            item for item in files
            if item["version"] == target and item["filename"].endswith("-py3-none-any.whl")
        ]
        if target and entries:
            return entries[0]["url"], target
        if version:  # the index is readable and simply does not carry this version
            raise ElemctlError(i18n.t("selfupdate.version-not-found"))
    data = _fetch_json(PYPI_VERSION.format(version=version) if version else PYPI_LATEST)
    resolved = data["info"]["version"]
    for entry in data["urls"]:
        if entry["filename"].endswith("-py3-none-any.whl"):
            return entry["url"], resolved
    raise ElemctlError(i18n.t("selfupdate.no-wheel", version=resolved))


# -- holders -------------------------------------------------------------------------------


def is_holder(name: str, command_line: str) -> bool:
    """Is this process one of ours - and therefore worth offering for a stop?

    The wrong answer here is not a missed holder but an offer to kill someone else's process,
    so the check is by our own executable name, or by an interpreter running our modules.
    """
    stem = Path((name or "").strip()).stem.lower()
    if stem in _HOLDER_EXECUTABLES:
        return True
    if stem not in _INTERPRETERS:
        return False
    lowered = (command_line or "").lower()
    return any(marker in lowered for marker in _HOLDER_MODULES)


def _process_listing() -> list[tuple[int, int, str, str]]:
    """(pid, ppid, name, command line) from the system tools; an empty list when they are unavailable."""
    if sys.platform == "win32":
        command = [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress",
        ]
    else:
        command = ["ps", "-eo", "pid=,ppid=,comm=,args="]
    try:
        out = subprocess.run(
            command, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    if sys.platform != "win32":
        rows = []
        for line in out.splitlines():
            parts = line.strip().split(None, 3)
            if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit():
                rows.append((int(parts[0]), int(parts[1]), parts[2], parts[3]))
        return rows
    try:
        data = json.loads(out or "[]")
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        (int(item.get("ProcessId") or 0), int(item.get("ParentProcessId") or 0),
         str(item.get("Name") or ""), str(item.get("CommandLine") or ""))
        for item in data
    ]


def _family_pids(rows: list[tuple[int, int, str, str]]) -> set[int]:
    """Pids of our own process tree: self, ancestors and descendants.

    The command started via the pipx shim runs as a python child of an `elemctl.exe`
    launcher - by name that launcher looks exactly like a holder, but stopping it kills
    the running command itself (the launcher's job object takes the child down with it).
    Ancestors and descendants are excluded wholesale; a reused pid can only put an extra
    process into the set, which errs on the safe side - a skipped holder, never a killed
    stranger.
    """
    own = os.getpid()
    parent_of = {pid: ppid for pid, ppid, _name, _line in rows}
    children_of: dict[int, list[int]] = {}
    for pid, ppid, _name, _line in rows:
        children_of.setdefault(ppid, []).append(pid)
    family = {own}
    cursor = own
    for _hop in range(64):  # bounded walk: a broken listing must not loop forever
        cursor = parent_of.get(cursor, 0)
        if cursor <= 0 or cursor in family:
            break
        family.add(cursor)
    queue = [own]
    while queue:
        for child in children_of.get(queue.pop(), ()):
            if child not in family:
                family.add(child)
                queue.append(child)
    return family


def holders() -> list[dict]:
    """Live processes that look like holders of the installation: {"pid", "name"}.

    Best effort by design: the answer only makes the message useful ("close these"), it is
    never a precondition - the gate is the rename below. Our own process tree is excluded:
    offering the shim that started this very command would end the update midway.
    """
    rows = _process_listing()
    family = _family_pids(rows)
    return [
        {"pid": pid, "name": name}
        for pid, _ppid, name, line in rows
        if pid not in family and is_holder(name, line)
    ]


def stop_holders(processes: list[dict], log) -> list[dict]:
    """End the listed processes; returns those that survived."""
    alive = []
    for process in processes:
        pid = int(process["pid"])
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=30)
            else:
                os.kill(pid, 15)
            log(i18n.t("selfupdate.holder-stopped", name=process.get("name") or "", pid=pid))
        except (OSError, subprocess.SubprocessError) as error:
            alive.append({**process, "error": str(error)})
    return alive


def _holders_message(processes: list[dict]) -> str:
    """Who to close - by name and pid, or an honest "could not tell"."""
    if not processes:
        return i18n.t("selfupdate.holders-unknown")
    listed = ", ".join(
        f"{item.get('name') or i18n.t('selfupdate.process')} (pid {item['pid']})"
        for item in processes
    )
    return i18n.t("selfupdate.holders", list=listed)


# -- moving aside, restoring, verifying ------------------------------------------------------


def _move_aside(site: Path) -> list[tuple[Path, Path]]:
    """Move the current installation aside. Raises while a file inside is open."""
    moved: list[tuple[Path, Path]] = []
    try:
        for pattern in _OWNED_PATTERNS:
            for path in sorted(site.glob(pattern)):
                if path.name.endswith(_BACKUP_SUFFIX):
                    continue
                backup = path.with_name(path.name + _BACKUP_SUFFIX)
                shutil.rmtree(backup, ignore_errors=True)
                path.rename(backup)
                moved.append((path, backup))
    except OSError:
        _restore(moved)
        raise
    return moved


def _restore(moved: list[tuple[Path, Path]]) -> None:
    """Put the previous installation back (the new files, if any, are removed first)."""
    for path, backup in moved:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
        try:
            backup.rename(path)
        except OSError:
            pass


def _drop_backups(moved: list[tuple[Path, Path]]) -> None:
    for _path, backup in moved:
        shutil.rmtree(backup, ignore_errors=True)


def verify_install(site: Path) -> str:
    """The version a FRESH interpreter reports, or "" when the package does not import.

    A separate process on purpose: the current one holds the old code in memory and would
    report success no matter what happened on disk.
    """
    code = "import elemctl, sys; sys.stdout.write(elemctl.__version__)"
    env = {**os.environ, "PYTHONPATH": str(site)}
    try:
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
            cwd=str(site), env=env, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def self_update(version: str | None = None, log=print, *, stop_busy: bool = False) -> tuple[str, str]:
    """Update elemctl in site-packages by unpacking the wheel. Return (before, after)."""
    url, target = _wheel_url(version)
    if version is None and target == __version__:
        log(i18n.t("selfupdate.already-current", version=__version__))
        return __version__, __version__

    site = _site_packages()
    log(i18n.t("selfupdate.downloading", version=target))
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            blob = resp.read()
    except OSError as error:
        raise ElemctlError(i18n.t("selfupdate.download-failed", error=error)) from error

    if stop_busy:
        busy = holders()
        if busy:
            stop_holders(busy, log)

    try:
        moved = _move_aside(site)
    except OSError as error:
        raise ElemctlError(
            i18n.t("selfupdate.busy", error=error, holders=_holders_message(holders()))
        ) from error

    log(i18n.t("selfupdate.unpacking", path=site))
    try:
        with zipfile.ZipFile(BytesIO(blob)) as archive:
            archive.extractall(site)
    except (OSError, zipfile.BadZipFile) as error:
        _restore(moved)
        raise ElemctlError(i18n.t("selfupdate.unpack-failed", error=error)) from error

    installed = verify_install(site)
    if installed != target:
        _restore(moved)
        reason = (
            i18n.t("selfupdate.reason-version", version=installed)
            if installed
            else i18n.t("selfupdate.reason-no-import")
        )
        raise ElemctlError(
            i18n.t("selfupdate.unverified", reason=reason, version=__version__)
        )
    _drop_backups(moved)

    _update_pipx_metadata(site, target, log)
    log(i18n.t("selfupdate.done", before=__version__, after=target))
    return __version__, target


def _update_pipx_metadata(site: Path, version: str, log) -> None:
    """Fix package_version in pipx_metadata.json (otherwise pipx list shows the old version)."""
    meta = site.parent.parent / "pipx_metadata.json"  # <venv>/Lib/site-packages -> <venv>
    if not meta.is_file():
        return
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        main = data.get("main_package") or {}
        if main.get("package") == "elemctl":
            main["package_version"] = version
            meta.write_text(json.dumps(data, indent=4), encoding="utf-8")
            log(i18n.t("selfupdate.metadata-updated"))
    except (OSError, ValueError):
        pass
