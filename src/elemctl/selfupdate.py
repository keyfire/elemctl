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

PYPI_VERSION = "https://pypi.org/pypi/elemctl/{version}/json"
PYPI_LATEST = "https://pypi.org/pypi/elemctl/json"

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


def _wheel_url(version: str | None) -> tuple[str, str]:
    """The URL and the exact version of the py3-none-any wheel on PyPI (latest or the given one)."""
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


def _process_listing() -> list[tuple[int, str, str]]:
    """(pid, name, command line) from the system tools; an empty list when they are unavailable."""
    if sys.platform == "win32":
        command = [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress",
        ]
    else:
        command = ["ps", "-eo", "pid=,comm=,args="]
    try:
        out = subprocess.run(
            command, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    if sys.platform != "win32":
        rows = []
        for line in out.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) == 3 and parts[0].isdigit():
                rows.append((int(parts[0]), parts[1], parts[2]))
        return rows
    try:
        data = json.loads(out or "[]")
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        (int(item.get("ProcessId") or 0), str(item.get("Name") or ""),
         str(item.get("CommandLine") or ""))
        for item in data
    ]


def holders() -> list[dict]:
    """Live processes that look like holders of the installation: {"pid", "name"}.

    Best effort by design: the answer only makes the message useful ("close these"), it is
    never a precondition - the gate is the rename below.
    """
    own = os.getpid()
    return [
        {"pid": pid, "name": name}
        for pid, name, line in _process_listing()
        if pid != own and is_holder(name, line)
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
