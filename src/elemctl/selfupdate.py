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
from .transport import _NETWORK_FAILURES

#: Where the files come from. Two of these LIST the releases, the simple index (PEP 691) and
#: the JSON summary, and the CDN caches both of them node by node, so either may name the
#: previous release for minutes after a new one is out. The page of one version is the fresh
#: document: nobody asks for it before the release exists. See `_latest_wheel`.
PYPI_SIMPLE = "https://pypi.org/simple/elemctl/"
PYPI_VERSION = "https://pypi.org/pypi/elemctl/{version}/json"
PYPI_LATEST = "https://pypi.org/pypi/elemctl/json"
#: The same URL answers an HTML page unless JSON is asked for by name.
SIMPLE_ACCEPT = "application/vnd.pypi.simple.v1+json"
#: The only wheel elemctl ships: the package is pure Python.
_WHEEL_SUFFIX = "-py3-none-any.whl"
#: How many releases past the listings the version pages are followed (`_newer_on_pages`).
#: Two releases inside one window of lag are rare already, and every round costs three requests.
_PAGE_ROUNDS = 3

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
    """One JSON document of PyPI; every way of not getting it is an ElemctlError in words.

    A body that is not JSON (a proxy's error page, a mirror that answers HTML) counts as an
    unreachable PyPI rather than surfacing as a traceback of the decoder. JSON of another
    shape than an object reads as an empty document.
    """
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ElemctlError(i18n.t("selfupdate.version-not-found")) from error
        raise ElemctlError(i18n.t("selfupdate.pypi-http-error", status=error.code)) from error
    except _NETWORK_FAILURES + (ValueError,) as error:
        raise ElemctlError(i18n.t("selfupdate.pypi-unreachable", error=error)) from error
    return data if isinstance(data, dict) else {}


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
    except _NETWORK_FAILURES + (ValueError,):
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


def _newest(*versions: str) -> str:
    """The newest plain release among the versions; "" when none of them ranks."""
    ranked = [(key, version) for version in versions
              if version and (key := _release_key(version)) is not None]
    return max(ranked)[1] if ranked else ""


def _latest_release(files: list[dict]) -> str:
    """The newest plain release among the wheels of the files; "" when none of them ranks."""
    return _newest(*{item["version"] for item in files
                     if item["filename"].lower().endswith(".whl")})


def _wheels(entries: list, version: str) -> list[dict]:
    """The pure-Python wheels of one version among file entries, the yanked ones left out.

    An entry of the simple index carries its version already; an entry of a JSON document
    does not, so the version is read off the file name for both.
    """
    return [
        item for item in entries or []
        if isinstance(item, dict)
        and str(item.get("filename") or "").endswith(_WHEEL_SUFFIX)
        and _version_of(str(item.get("filename"))) == version
        and item.get("url") and not item.get("yanked")
    ]


def _next_versions(version: str) -> list[str]:
    """The numbers the release after `version` may carry: the next patch, minor and major.

    `0.44.0` gives `0.44.1`, `0.45.0` and `1.0.0`. A post-release steps from its base, and a
    version that does not rank gives nothing to ask about.
    """
    key = _release_key(version)
    if key is None:
        return []
    parts = list(key[0])
    bumped = []
    for index in range(len(parts) - 1, -1, -1):
        step = parts[:index] + [parts[index] + 1] + [0] * (len(parts) - index - 1)
        bumped.append(".".join(str(part) for part in step))
    return bumped


def _page_wheels(version: str) -> list[dict]:
    """The wheels the page of one version lists; empty when PyPI does not know the version.

    Quiet on purpose. This is a look past the listings, and a 404 is its usual answer, so no
    failure here may stop an update the listings already allow. A yanked release does not
    count, and neither does a page that names another version than the one asked for.
    """
    try:
        with urllib.request.urlopen(PYPI_VERSION.format(version=version), timeout=30) as resp:
            data = json.load(resp)
    except _NETWORK_FAILURES + (ValueError,):  # HTTPError, the 404 included, is an OSError
        return []
    info = data.get("info") if isinstance(data, dict) else None
    if not isinstance(info, dict) or info.get("yanked") or info.get("version") != version:
        return []
    return _wheels(data.get("urls"), version)


def _newer_on_pages(version: str) -> tuple[str, list[dict]]:
    """A release newer than `version` that only its own page shows so far: (version, wheels).

    The listings lag behind a release while the page of the new version does not: nobody asked
    the CDN for it before it existed, so its first answer comes from PyPI itself. The pages of
    the next patch, minor and major are asked, the newest one found wins, and the look goes on
    from it in case two releases fell into one window of lag. ("", []) when nothing newer is
    published.

    The CDN keeps a 404 of such a page for about a minute (measured on the engine of the
    toolkit: one request in four at 15-second steps missed the cache). That is the price: an
    explicit `--version` asked in the minute after a look like this one, and before the
    release, may be told the version is not there, and the next minute settles it.
    """
    found, wheels, current = "", [], version
    for _round in range(_PAGE_ROUNDS):
        step, step_wheels = "", []
        for candidate in _next_versions(current):
            listed = _page_wheels(candidate)
            if listed and _newest(step, candidate) == candidate:
                step, step_wheels = candidate, listed
        if not step:
            break
        found, wheels, current = step, step_wheels, step
    return found, wheels


def _wheel_url(version: str | None, log=None) -> tuple[str, str]:
    """The URL and the exact version of the py3-none-any wheel (latest, or the given one).

    Files are looked up in the SIMPLE index first. Caught on the engine of the toolkit on
    31.07.2026: the JSON summary is a cache that catches up minutes after an upload. The
    index lags too, though: on 23.09.2026 it named the previous release of the engine for
    more than half an hour, while the page of the new version listed every file. So a
    version named explicitly and missing from the index is looked up on its own page, and
    only a 404 there means the version does not exist. The latest version is not taken from
    one listing either, see `_latest_wheel`; `log` hears when the sources disagree.
    """
    files = _simple_files()
    if version is None:
        target, wheels = _latest_wheel(files, log or (lambda _message: None))
        return wheels[0]["url"], target
    entries = _wheels(files, version)
    if entries:
        return entries[0]["url"], version
    data = _fetch_json(PYPI_VERSION.format(version=version))
    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    resolved = str(info.get("version") or version)
    entries = _wheels(data.get("urls"), resolved)
    if not entries:
        raise ElemctlError(i18n.t("selfupdate.no-wheel", version=resolved))
    return entries[0]["url"], resolved


def _latest_wheel(files: list[dict], log) -> tuple[str, list[dict]]:
    """The newest release and its wheels, asked of every source PyPI has.

    The engine of the toolkit showed the failure live on 24.09.2026: two minutes after a
    release the command answered "already current" with the previous version, while an
    explicit `--version` went through at once. The latest version came from the simple index
    alone, and the index still listed the release before. elemctl read it the same way. Both
    listings are cached node by node, and each of them has been seen lagging while the other
    was fresh. So:

    1. both listings are read, the simple index and the JSON summary, and the newer of their
       answers is taken;
    2. the pages of the next versions are asked (`_newer_on_pages`): a release the listings
       do not show yet is there already;
    3. when the sources disagree, `log` hears one line naming what each of them said, so an
       answer given the minute after a release is not taken for a settled fact.

    The failure is raised only when neither listing answers, in the words of the summary.
    """
    listed = _latest_release(files)
    try:
        summary = _fetch_json(PYPI_LATEST)
    except ElemctlError:
        if not files:
            raise
        summary = {}
    info = summary.get("info") if isinstance(summary.get("info"), dict) else {}
    summarized = _newest(str(info.get("version") or ""))
    best = _newest(listed, summarized)
    paged, paged_wheels = _newer_on_pages(best) if best else ("", [])
    target = paged or best
    if paged or (listed and summarized and listed != summarized):
        said = [
            i18n.t(key, version=version)
            for key, version in (
                ("selfupdate.source-simple", listed),
                ("selfupdate.source-summary", summarized),
                ("selfupdate.source-page", paged),
            )
            if version
        ]
        log(i18n.t("selfupdate.sources-differ", sources="; ".join(said), version=target))
    wheels = paged_wheels if paged else _wheels(files, target)
    if not wheels and target and summarized == target:
        wheels = _wheels(summary.get("urls"), target)
    if not target or not wheels:
        raise ElemctlError(i18n.t("selfupdate.no-wheel", version=target or "?"))
    return target, wheels


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
            command, capture_output=True, text=True, timeout=30, encoding="utf-8",
            errors="replace", stdin=subprocess.DEVNULL,
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
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                               stdin=subprocess.DEVNULL, timeout=30)
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
        # stdin=DEVNULL: started from the MCP server, an interpreter that inherits the
        # stdin the client speaks over never reaches its own exit on Windows.
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
            cwd=str(site), env=env, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def self_update(version: str | None = None, log=print, *, stop_busy: bool = False) -> tuple[str, str]:
    """Update elemctl in site-packages by unpacking the wheel. Return (before, after)."""
    url, target = _wheel_url(version, log=log)
    if version is None and target == __version__:
        log(i18n.t("selfupdate.already-current", version=__version__))
        return __version__, __version__
    if version is None and _newest(target, __version__) == __version__:
        # A release installed by its number a minute ago is newer than what every source
        # names yet: without this the plain command would "update" back to the release before.
        log(i18n.t("selfupdate.newer-installed", installed=__version__, latest=target))
        return __version__, __version__

    site = _site_packages()
    log(i18n.t("selfupdate.downloading", version=target))
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            blob = resp.read()
    except _NETWORK_FAILURES as error:
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
            meta.write_text(json.dumps(data, indent=4), encoding="utf-8", newline="")
            log(i18n.t("selfupdate.metadata-updated"))
    except (OSError, ValueError):
        pass
