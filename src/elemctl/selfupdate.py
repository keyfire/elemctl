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
   point. The processes are then listed by pid and command line, and the command stops and
   says who to close. A process is ours by the name of its executable or by an interpreter
   running our modules - an editor or an agent that merely mentions elemctl in its arguments
   is never offered for stopping.
2. **Only servers are stopped.** `--stop-holders` ends the servers (`elemctl mcp`): they live
   as long as their client and keep running the old code anyway. A running command of another
   session is somebody's work in progress - a wait for a pipeline, say - so it is named and
   left alone, and when it keeps the files busy the update is refused with the advice to wait
   for it. `--stop-holders=all` stops the commands too, and such a command ends without a
   result.
3. **A failure rolls back.** The previous installation is kept aside until the new one has
   been PROVEN to import in a separate process (the current one still runs the old code in
   memory and cannot judge). Anything unexpected puts the old installation back.

Only the elemctl package itself is updated, not its extras; the exe stubs in Scripts are left
alone - they call whatever is in site-packages on the next run. The core has no external
dependencies, so the download and the unpacking are standard library only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
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
#: ... and a plain interpreter counts only when it RUNS our code: `-m elemctl...` or our console
#: script handed to it as a file. The command line alone is not enough: an editor or an agent
#: mentions elemctl in its arguments (a path, a config file) without holding anything, and such
#: a process must never be offered for stopping.
_PACKAGE = "elemctl"
#: `python`, `python3.12`, `pythonw`, the `py` launcher and the like.
_INTERPRETER = re.compile(r"(?:python|pythonw|pypy|pyw|py)(?:\d+(?:\.\d+)*[a-z]?)?")
#: What makes a holder a server: the subcommand, or the module of the server run directly.
_SERVER_COMMANDS = frozenset({"mcp"})
_SERVER_MODULES = frozenset({"elemctl.mcp_server"})
#: The modules that run the command line itself - their subcommand tells what they are.
_CLI_MODULES = frozenset({"elemctl", "elemctl.cli", "elemctl.__main__"})
#: How much of a command line a message quotes: enough to recognize the command.
_LINE_LIMIT = 200

#: What `--stop-holders` stops: the servers alone, or every holder, the running commands of
#: other sessions included.
STOP_SERVERS, STOP_ALL = "servers", "all"
STOP_MODES = (STOP_SERVERS, STOP_ALL)
#: The two kinds of a holder. A server lives as long as its client and keeps running the old
#: code after the update, so ending it belongs to the update; a command is somebody's work.
SERVER, COMMAND = "server", "command"


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
    """Is this process one of ours - a server or a command that may hold the installation?

    The wrong answer here is not a missed holder but an offer to kill someone else's process,
    so the check is by our own executable name, or by an interpreter running our code.
    """
    return bool(holder_kind(name, command_line))


def holder_kind(name: str, command_line: str) -> str:
    """SERVER or COMMAND for a process of ours, "" for anything else.

    A server is what an update has to end: `elemctl mcp` lives as long as its client and keeps
    running the old code. Anything else of ours is a command, and a command of another session
    is never ended by default: the wrong answer here kills that work with no verdict. So a
    server is recognized positively, by its subcommand or its module, and whatever is not
    certain stays a command.
    """
    found = _runs(name, command_line)
    if found is None:
        return ""
    what, args = found
    if what.startswith("-m "):
        module = what[3:]
        if module in _SERVER_MODULES:
            return SERVER
        if module not in _CLI_MODULES:
            return COMMAND
    return SERVER if _subcommand(args) in _SERVER_COMMANDS else COMMAND


def _runs(name: str, command_line: str) -> tuple[str, list[str]] | None:
    """What of ours a process runs and the arguments after it; None when nothing of ours.

    The first is our console script (`elemctl`) or, for an interpreter, `-m` with the module
    (`-m elemctl.mcp_server`). An interpreter handed our console script as a file (the launcher
    of a venv starts `python.exe ...\\Scripts\\elemctl.exe mcp`) runs the script. `-c` code, a
    script of somebody else's and a module of another package are not ours, whatever their
    arguments mention.
    """
    words = _words(command_line)
    own = _base(name)
    if own in _HOLDER_EXECUTABLES:
        start = next((index + 1 for index, word in enumerate(words) if _base(word) == own), 1)
        return own, words[start:]
    if not _INTERPRETER.fullmatch(own):
        return None
    # The arguments start after the interpreter's own word. A listing that lost the quotes
    # (ps, a joined psutil list) splits a path with spaces, and the interpreter ends it.
    index = next((position + 1 for position, word in enumerate(words)
                  if _INTERPRETER.fullmatch(_base(word))), 1)
    while index < len(words):
        word = words[index]
        if word == "-" or not word.startswith("-"):
            break
        if word.startswith("--"):
            index += 2 if word == "--check-hash-based-pycs" else 1
            continue
        letters = word[1:]  # a cluster of one-letter options: `-P`, `-uB`, `-Xutf8`, `-m module`
        for position, letter in enumerate(letters):
            rest = letters[position + 1:]
            if letter == "c":
                return None
            if letter == "m":
                module = (rest or (words[index + 1] if index + 1 < len(words) else "")).lower()
                if module != _PACKAGE and not module.startswith(_PACKAGE + "."):
                    return None
                return f"-m {module}", words[index + (1 if rest else 2):]
            if letter in "XW":
                index += 0 if rest else 1  # the value is the rest of the word or the next one
                break
        index += 1
    if index >= len(words) or words[index] == "-":
        return None
    script = _base(words[index])
    return (script, words[index + 1:]) if script in _HOLDER_EXECUTABLES else None


def _subcommand(args: list[str]) -> str:
    """The subcommand of an elemctl command line: the first word past the global options."""
    from .cli import _GLOBAL_OPTIONS  # noqa: PLC0415 - the grammar of the command line is the CLI's

    index = 0
    while index < len(args):
        word = args[index]
        if word == "--":
            return ""
        if word in _GLOBAL_OPTIONS:
            index += 2
        elif word.startswith("-"):
            index += 1
        else:
            return word.lower()
    return ""


def _words(command_line: str) -> list[str]:
    """The words of a command line, the double quotes around a path taken off.

    Not a shell parser: a process listing is read here, not a command run, and the words only
    have to show the program, its module and the subcommand.
    """
    words: list[str] = []
    word: list[str] = []
    quoted = started = False
    for char in command_line or "":
        if char == '"':
            quoted, started = not quoted, True
        elif char.isspace() and not quoted:
            if started:
                words.append("".join(word))
            word, started = [], False
        else:
            word.append(char)
            started = True
    if started:
        words.append("".join(word))
    return words


def _base(path: str) -> str:
    """The file name a word or a process name points at, lowercased and without `.exe`.

    Both separators count whatever the system: a listing from Windows is read by the tests
    on any of them.
    """
    name = re.split(r"[\\/]", (path or "").strip())[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


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
    """Live processes of ours that may hold the installation.

    Each is {"pid", "ppid", "name", "kind", "command_line"}, the kind being SERVER or COMMAND
    (`holder_kind`). Best effort by design: the answer only makes the message useful ("close
    these"), it is never a precondition - the gate is the rename below. Our own process tree is
    excluded: offering the shim that started this very command would end the update midway.
    """
    rows = _process_listing()
    family = _family_pids(rows)
    found = []
    for pid, ppid, name, line in rows:
        kind = "" if pid in family else holder_kind(name, line)
        if kind:
            found.append({"pid": pid, "ppid": ppid, "name": name, "kind": kind,
                          "command_line": " ".join(line.split())})
    return found


def _launches(processes: list[dict]) -> list[dict]:
    """One process per launch: those whose parent is not on the list.

    A console script on Windows runs as a chain - the launcher, the interpreter it starts and,
    in a venv made by uv, the base interpreter under that one - all with nearly the same
    command line. The head of the chain names the launch; the rest are its parts.
    """
    pids = {item["pid"] for item in processes}
    return [item for item in processes if item.get("ppid") not in pids]


def _described(process: dict) -> str:
    """The pid and the command line of a process, the way a message names it."""
    line = process.get("command_line") or process.get("name") or i18n.t("selfupdate.process")
    if len(line) > _LINE_LIMIT:
        line = line[: _LINE_LIMIT - 3].rstrip() + "..."
    return f"pid {process['pid']} – {line}"


def _listed(processes: list[dict]) -> str:
    return "; ".join(_described(item) for item in processes)


def _end(pid: int) -> str:
    """Stop one process: "" when it ended or was gone already, the reason when it was not."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                                    stdin=subprocess.DEVNULL, timeout=30)
            # 128 is "not found": the launcher stopped a moment ago took its interpreter along.
            if result.returncode not in (0, 128):
                return f"taskkill {result.returncode}"
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return ""
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)
    return ""


def stop_holders(processes: list[dict], log) -> list[dict]:
    """End the listed processes; returns those that survived.

    A launch gets one line, the one of its head (see `_launches`): the parts of the chain go
    with it and need no line of their own.
    """
    heads = {item["pid"] for item in _launches(processes)}
    alive = []
    for process in processes:
        error = _end(int(process["pid"]))
        if error:
            alive.append({**process, "error": error})
            log(i18n.t("selfupdate.stop-failed", process=_described(process), error=error))
        elif process["pid"] in heads:
            stopped = ("selfupdate.command-stopped" if process.get("kind") == COMMAND
                       else "selfupdate.server-stopped")
            log(i18n.t(stopped, process=_described(process)))
    return alive


def _stop_for_update(stop: str, log) -> None:
    """End what `stop` covers, and name the running commands it leaves alone."""
    busy = holders()
    ending = [item for item in busy if stop == STOP_ALL or item.get("kind") == SERVER]
    if ending:
        stop_holders(ending, log)
    for item in _launches([item for item in busy if item not in ending]):
        log(i18n.t("selfupdate.command-spared", process=_described(item)))


def _holders_message(processes: list[dict], stop: str = "") -> str:
    """Who holds the installation and what to do about it, the servers apart from the commands.

    A server can be closed or stopped with `--stop-holders`. A command is somebody's work, so
    the advice is to wait for it, and the way to stop it anyway is named with its price. What
    the mode of this run was meant to stop and is still listed did not go: closing it by hand is
    the advice left. With nothing listed, the message says so honestly.
    """
    servers = _launches([item for item in processes if item.get("kind") != COMMAND])
    commands = _launches([item for item in processes if item.get("kind") == COMMAND])
    if not servers and not commands:
        return f"{i18n.t('selfupdate.holders-unknown')}. {i18n.t('selfupdate.advice-servers')}"
    parts = []
    if servers:
        parts.append(i18n.t("selfupdate.holders", list=_listed(servers)))
        parts.append(i18n.t("selfupdate.advice-close" if stop else "selfupdate.advice-servers"))
    if commands:
        parts.append(i18n.t("selfupdate.holders-commands", list=_listed(commands)))
        parts.append(i18n.t(
            "selfupdate.advice-close" if stop == STOP_ALL else "selfupdate.advice-commands"
        ))
    return ". ".join(parts)


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


def self_update(version: str | None = None, log=print, *, stop: str = "") -> tuple[str, str]:
    """Update elemctl in site-packages by unpacking the wheel. Return (before, after).

    `stop` is what `--stop-holders` asked for: STOP_SERVERS ends the servers holding the
    installation and names the running commands without touching them, STOP_ALL ends the
    commands as well, and "" ends nothing.
    """
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

    if stop:
        _stop_for_update(stop, log)

    try:
        moved = _move_aside(site)
    except OSError as error:
        raise ElemctlError(
            i18n.t("selfupdate.busy", error=error, holders=_holders_message(holders(), stop))
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
