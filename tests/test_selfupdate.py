"""self-update tests: updating by unpacking the wheel with no network (urllib is mocked)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import urllib.error
import zipfile
from http.client import IncompleteRead

import pytest

import elemctl
from elemctl import cli, i18n, selfupdate


def _fake_wheel(version: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("elemctl/__init__.py", f'__version__ = "{version}"\n')
        archive.writestr(f"elemctl-{version}.dist-info/METADATA", f"Version: {version}\n")
    return buf.getvalue()


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _IncompleteResp(_FakeResp):
    """A response whose body ends before urllib has read it all."""

    def read(self):
        raise IncompleteRead(b"", 1)


def test_self_update_extracts_wheel(monkeypatch, tmp_path):
    """The wheel is unpacked into site-packages; the old package and dist-info are removed."""
    site = tmp_path / "site-packages"
    (site / "elemctl").mkdir(parents=True)
    (site / "elemctl" / "__init__.py").write_text('__version__ = "0.0.1"\n', encoding="utf-8")
    (site / "elemctl-0.0.1.dist-info").mkdir()
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: site)
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v, log=None: ("http://pypi/elemctl.whl", "9.9.9"))
    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9")))

    old, new = selfupdate.self_update(log=lambda *a: None)

    assert new == "9.9.9" and old == elemctl.__version__
    assert '__version__ = "9.9.9"' in (site / "elemctl" / "__init__.py").read_text(encoding="utf-8")
    assert not (site / "elemctl-0.0.1.dist-info").exists()  # the old dist-info is gone
    assert (site / "elemctl-9.9.9.dist-info").exists()


def test_self_update_noop_when_current(monkeypatch, tmp_path):
    """When the PyPI version equals the current one and no version is asked for - nothing is downloaded."""
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v, log=None: ("http://pypi/x.whl", elemctl.__version__))

    def boom(*a, **k):
        raise AssertionError("скачивание не должно происходить")

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", boom)
    old, new = selfupdate.self_update(log=lambda *a: None)
    assert old == new == elemctl.__version__


def test_updates_pipx_metadata(monkeypatch, tmp_path):
    """package_version in pipx_metadata.json is updated when the venv is a pipx one."""
    site = tmp_path / "venv" / "Lib" / "site-packages"
    (site / "elemctl").mkdir(parents=True)
    (site / "elemctl" / "__init__.py").write_text("x\n", encoding="utf-8")
    meta = tmp_path / "venv" / "pipx_metadata.json"
    meta.write_text(json.dumps({"main_package": {"package": "elemctl", "package_version": "0.0.1"}}), encoding="utf-8")
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: site)
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v, log=None: ("http://pypi/x.whl", "9.9.9"))
    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9")))

    selfupdate.self_update(log=lambda *a: None)

    assert json.loads(meta.read_text(encoding="utf-8"))["main_package"]["package_version"] == "9.9.9"


def test_cli_self_update(monkeypatch, capsys):
    monkeypatch.setattr(selfupdate, "self_update", lambda version=None, log=print, stop="": ("0.5.0", "0.6.0"))
    rc = cli.main(["self-update"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"updated": True, "from": "0.5.0", "to": "0.6.0"}


@pytest.mark.parametrize(
    ("argv", "stop"),
    [
        ([], ""),
        (["--stop-holders"], selfupdate.STOP_SERVERS),
        (["--stop-holders=servers"], selfupdate.STOP_SERVERS),
        (["--stop-holders=all"], selfupdate.STOP_ALL),
        (["--stop-holders", "all"], selfupdate.STOP_ALL),
        (["--stop-holders", "--version", "9.9.9"], selfupdate.STOP_SERVERS),
    ],
)
def test_the_bare_flag_stops_the_servers_and_all_has_to_be_named(monkeypatch, capsys, argv, stop):
    """A running command of another session is ended only when the call says so by name."""
    asked = {}

    def update(version=None, log=print, stop=""):
        asked["stop"] = stop
        return "0.5.0", "0.5.0"

    monkeypatch.setattr(selfupdate, "self_update", update)
    assert cli.main(["self-update", *argv]) == 0
    assert asked["stop"] == stop


def test_an_unknown_stop_mode_is_refused_by_the_parser(capsys):
    with pytest.raises(SystemExit) as refusal:
        cli.main(["self-update", "--stop-holders=everything"])
    assert refusal.value.code == 2
    assert "everything" in capsys.readouterr().err


# --- занятая установка: что бы ни случилось, прежняя версия остаётся на месте ---------------
#
# Ровно этот отказ и случился при выпуске 0.19.0: pip упёрся в занятый живой MCP-сессией
# elemctl.exe, успел удалить пакет и не поставил новый - `elemctl --version` ответил
# ModuleNotFoundError. Порядок перенесён из движка, где он уже обкатан.


def _install(monkeypatch, tmp_path, payload=None):
    site = tmp_path / "site-packages"
    (site / "elemctl").mkdir(parents=True)
    (site / "elemctl" / "__init__.py").write_text('__version__ = "0.0.1"\n', encoding="utf-8")
    (site / "elemctl-0.0.1.dist-info").mkdir()
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: site)
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v, log=None: ("http://pypi/elemctl.whl", "9.9.9"))
    monkeypatch.setattr(
        selfupdate.urllib.request, "urlopen",
        lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9") if payload is None else payload),
    )
    return site


def test_busy_installation_is_refused_before_anything_is_removed(monkeypatch, tmp_path):
    """Переименование - ворота: файл занят, а удалять ещё нечего."""
    site = _install(monkeypatch, tmp_path)
    original = selfupdate.Path.rename

    def refuse(self, target):
        if self.name == "elemctl":
            raise OSError(13, "Файл занят другим процессом")
        return original(self, target)

    monkeypatch.setattr(selfupdate.Path, "rename", refuse)
    monkeypatch.setattr(selfupdate, "holders", lambda: [
        {"pid": 4242, "ppid": 1, "name": "elemctl.exe", "kind": selfupdate.SERVER,
         "command_line": "elemctl mcp"},
    ])

    with pytest.raises(elemctl.errors.ElemctlError) as error:
        selfupdate.self_update(log=lambda *a: None)

    message = str(error.value)
    assert "pid 4242 – elemctl mcp" in message and "--stop-holders" in message
    assert '__version__ = "0.0.1"' in (site / "elemctl" / "__init__.py").read_text(encoding="utf-8")


def test_broken_archive_rolls_back(monkeypatch, tmp_path):
    site = _install(monkeypatch, tmp_path, payload=b"not a zip archive")
    with pytest.raises(elemctl.errors.ElemctlError, match="возвращена на место"):
        selfupdate.self_update(log=lambda *a: None)
    assert '__version__ = "0.0.1"' in (site / "elemctl" / "__init__.py").read_text(encoding="utf-8")
    assert not list(site.glob("*" + selfupdate._BACKUP_SUFFIX))


def test_install_that_does_not_import_rolls_back(monkeypatch, tmp_path):
    """Проверка идёт ОТДЕЛЬНЫМ процессом: текущий держит старый код в памяти."""
    site = _install(monkeypatch, tmp_path)
    monkeypatch.setattr(selfupdate, "verify_install", lambda s: "")
    with pytest.raises(elemctl.errors.ElemctlError, match="не импортируется"):
        selfupdate.self_update(log=lambda *a: None)
    assert '__version__ = "0.0.1"' in (site / "elemctl" / "__init__.py").read_text(encoding="utf-8")


def test_successful_update_leaves_no_backup(monkeypatch, tmp_path):
    site = _install(monkeypatch, tmp_path)
    selfupdate.self_update(log=lambda *a: None)
    assert not list(site.glob("*" + selfupdate._BACKUP_SUFFIX))
    assert '__version__ = "9.9.9"' in (site / "elemctl" / "__init__.py").read_text(encoding="utf-8")


def test_holders_are_our_own_processes_only(monkeypatch):
    """Ошибиться здесь - значит предложить снять ЧУЖОЙ процесс."""
    monkeypatch.setattr(
        selfupdate, "_process_listing",
        lambda: [
            (11, 1, "elemctl.exe", "elemctl mcp"),
            (12, 1, "python.exe", "python.exe -m elemctl mcp"),
            (13, 1, "python.exe", "python.exe -m http.server"),
            # Клиент агента несёт команду сервера в своей строке запуска - но держателем
            # не является: снять его было бы худшей из ошибок.
            (14, 1, "claude.exe", "claude.exe --mcp-server elemctl mcp"),
        ],
    )
    assert {item["pid"] for item in selfupdate.holders()} == {11, 12}


def test_holders_exclude_own_process_tree(monkeypatch):
    """Обёртка pipx, запустившая команду, и её дерево - не держатели.

    Живой отказ 28.07: `--stop-holders` снял собственный родительский `elemctl.exe`,
    Job Object программы запуска утянул за ним и сам обновляющий процесс - обновление оборвалось
    на полпути. Свои: предки (обёртка и её родитель) и потомки; чужая сессия с тем же
    именем остаётся держателем.
    """
    own = os.getpid()
    monkeypatch.setattr(
        selfupdate, "_process_listing",
        lambda: [
            (70, 1, "explorer.exe", "explorer.exe"),          # предок-не-держатель
            (77, 70, "elemctl.exe", "elemctl self-update"),   # наша обёртка pipx
            (own, 77, "python.exe", "python -m elemctl self-update"),
            (88, own, "elemctl.exe", "elemctl helper"),       # наш потомок
            (11, 1, "elemctl.exe", "elemctl mcp"),            # чужая сессия MCP
        ],
    )
    assert {item["pid"] for item in selfupdate.holders()} == {11}


def test_family_pids_survives_a_parent_loop(monkeypatch):
    """Кольцо в ppid (битый листинг или переиспользованный pid) не должно зациклить обход."""
    own = os.getpid()
    rows = [
        (own, 50, "python.exe", "python -m elemctl self-update"),
        (50, 51, "elemctl.exe", "elemctl self-update"),
        (51, 50, "cmd.exe", "cmd"),  # кольцо 50 <-> 51
    ]
    assert selfupdate._family_pids(rows) == {own, 50, 51}


# -- servers and commands --------------------------------------------------------------------
#
# `--stop-holders` of one session once ended a command of another one that was waiting for a
# pipeline, and that command died with exit code 1 and no verdict. The update has to end the
# servers - they outlive it on the old code anyway - and nothing else unless asked by name.

SERVER, COMMAND = selfupdate.SERVER, selfupdate.COMMAND


@pytest.mark.parametrize(
    ("name", "line", "kind"),
    [
        # the launcher an MCP client starts, and the interpreters the venv chain runs under it
        ("elemctl.exe", "elemctl mcp", SERVER),
        ("python.exe", r'"C:\venv\Scripts\python.exe"  "C:\bin\elemctl.exe" mcp', SERVER),
        ("elemctl.exe", "elemctl --env-file demo.env mcp", SERVER),
        ("elemctl.exe", "elemctl --lang=en mcp", SERVER),
        ("python3", "/usr/bin/python3 -m elemctl mcp", SERVER),
        ("python3", "/usr/bin/python3 -m elemctl.mcp_server", SERVER),
        ("python3.12", "/opt/py/bin/python3.12 -X utf8 -m elemctl --quiet mcp", SERVER),
        ("elemctl", "/usr/bin/python3 /home/u/.local/bin/elemctl mcp", SERVER),
        # a path with spaces, its quotes lost by the listing
        ("python.exe", r"C:\Program Files\Python\python.exe -m elemctl mcp", SERVER),
        # commands: the same launch shapes with another subcommand
        ("elemctl.exe", r'"C:\bin\elemctl.exe" mr-create --from-step merge', COMMAND),
        ("python.exe",
         r'"C:\venv\Scripts\python.exe"  "C:\bin\elemctl.exe" mr-create --from-step merge', COMMAND),
        ("elemctl.exe", "elemctl deploy demo-app --env-file mcp.env", COMMAND),
        # the value of a global option is not the subcommand
        ("elemctl.exe", "elemctl --env-file mcp apps list", COMMAND),
        ("python3", "/usr/bin/python3 -m elemctl apps list", COMMAND),
        ("python.exe", "python.exe -Pm elemctl self-update", COMMAND),
        ("elemctl", "/home/u/.local/bin/elemctl builds upload app.xasm", COMMAND),
        # ours, but what it runs cannot be told: a command, never a server
        ("elemctl.exe", "", COMMAND),
        # not ours, whatever the arguments mention
        ("claude.exe", "claude.exe --mcp-server elemctl mcp", ""),
        ("python.exe", "python.exe -m http.server", ""),
        ("python.exe", 'python.exe -c "import elemctl; elemctl.run()" mcp', ""),
        ("python.exe", r"python.exe tools\watch.py --tool C:\bin\elemctl.exe mcp", ""),
        ("Code.exe", r"Code.exe --folder-uri file:///c:/work/elemctl", ""),
    ],
)
def test_a_server_is_told_from_a_command_by_its_command_line(name, line, kind):
    assert selfupdate.holder_kind(name, line) == kind
    assert selfupdate.is_holder(name, line) is bool(kind)


def _listing(monkeypatch):
    """A machine running an MCP session and, in another session, a command waiting for a pipeline.

    Both are console scripts started through the launcher of a venv made by uv: the launcher,
    the interpreter of the venv and the base interpreter under it.
    """
    monkeypatch.setattr(
        selfupdate, "_process_listing",
        lambda: [
            (10, 1, "claude.exe", "claude.exe"),
            (11, 10, "elemctl.exe", "elemctl mcp"),
            (12, 11, "python.exe", r'"C:\venv\Scripts\python.exe"  "C:\bin\elemctl.exe" mcp'),
            (13, 12, "python.exe", r'"C:\venv\Scripts\python.exe"  "C:\bin\elemctl.exe" mcp'),
            (20, 1, "pwsh.exe", "pwsh.exe"),
            (21, 20, "elemctl.exe", r'"C:\bin\elemctl.exe" mr-create --from-step merge'),
            (22, 21, "python.exe",
             r'"C:\venv\Scripts\python.exe"  "C:\bin\elemctl.exe" mr-create --from-step merge'),
        ],
    )


def test_holders_carry_the_kind_and_the_command_line(monkeypatch):
    _listing(monkeypatch)
    found = {item["pid"]: item for item in selfupdate.holders()}
    assert {pid: item["kind"] for pid, item in found.items()} == {
        11: SERVER, 12: SERVER, 13: SERVER, 21: COMMAND, 22: COMMAND,
    }
    # the double space the launcher leaves between the words is not repeated in a message
    assert found[22]["command_line"] == (
        r'"C:\venv\Scripts\python.exe" "C:\bin\elemctl.exe" mr-create --from-step merge'
    )
    assert found[22]["ppid"] == 21


def _ended(monkeypatch):
    """Record the pids the update asks to stop, stopping nothing."""
    ended: list[int] = []
    monkeypatch.setattr(selfupdate, "_end", lambda pid: ended.append(pid) or "")
    return ended


def _system_stops(monkeypatch, gone=(), failing=()):
    """Stand in for taskkill and kill: `gone` answer "not found", `failing` refuse."""
    ended: list[int] = []

    def fake_run(command, **kwargs):
        assert command[0] == "taskkill" and command[-1] == "/F"
        pid = int(command[command.index("/PID") + 1])
        ended.append(pid)
        code = 128 if pid in gone else 1 if pid in failing else 0
        return subprocess.CompletedProcess(command, code)

    def fake_kill(pid, sig):
        ended.append(pid)
        if pid in gone:
            raise ProcessLookupError(pid)
        if pid in failing:
            raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(selfupdate.subprocess, "run", fake_run)
    monkeypatch.setattr(selfupdate.os, "kill", fake_kill)
    return ended


def test_stop_holders_ends_the_servers_and_leaves_the_commands_running(monkeypatch, tmp_path):
    site = _install(monkeypatch, tmp_path)
    _listing(monkeypatch)
    ended = _ended(monkeypatch)
    said: list[str] = []

    old, new = selfupdate.self_update(log=said.append, stop=selfupdate.STOP_SERVERS)

    assert new == "9.9.9" and '__version__ = "9.9.9"' in (
        site / "elemctl" / "__init__.py").read_text(encoding="utf-8")
    assert sorted(ended) == [11, 12, 13]
    text = "\n".join(said)
    # one line for the stopped session, one for the command left alone - pid and command line
    assert "остановлен сервер: pid 11 – elemctl mcp" in text
    assert "pid 12" not in text and "pid 13" not in text
    assert (r'не трогаю идущую команду: pid 21 – "C:\bin\elemctl.exe" mr-create --from-step merge'
            in text)
    assert "pid 22" not in text


def test_a_command_holding_the_files_ends_in_a_refusal_that_names_it(monkeypatch, tmp_path):
    site = _install(monkeypatch, tmp_path)
    _listing(monkeypatch)
    ended = _ended(monkeypatch)
    original = selfupdate.Path.rename

    def refuse(self, target):
        if self.name == "elemctl":
            raise PermissionError(13, "The process cannot access the file")
        return original(self, target)

    monkeypatch.setattr(selfupdate.Path, "rename", refuse)

    with pytest.raises(elemctl.errors.ElemctlError) as error:
        selfupdate.self_update(log=lambda *a: None, stop=selfupdate.STOP_SERVERS)

    message = str(error.value)
    assert r'Идут команды: pid 21 – "C:\bin\elemctl.exe" mr-create --from-step merge' in message
    assert "дождитесь конца команд и повторите" in message and "--stop-holders=all" in message
    assert "НЕ ТРОНУТА" in message
    assert 21 not in ended and 22 not in ended  # the command lives on
    assert '__version__ = "0.0.1"' in (site / "elemctl" / "__init__.py").read_text(encoding="utf-8")
    assert not list(site.glob("*" + selfupdate._BACKUP_SUFFIX))


def test_stop_holders_all_ends_the_commands_too(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path)
    _listing(monkeypatch)
    ended = _ended(monkeypatch)
    said: list[str] = []

    selfupdate.self_update(log=said.append, stop=selfupdate.STOP_ALL)

    assert sorted(ended) == [11, 12, 13, 21, 22]
    text = "\n".join(said)
    assert r'остановлена команда: pid 21 – "C:\bin\elemctl.exe" mr-create --from-step merge' in text
    assert "не трогаю" not in text


def test_without_the_flag_nothing_is_stopped(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path)
    _listing(monkeypatch)
    ended = _ended(monkeypatch)
    selfupdate.self_update(log=lambda *a: None)
    assert ended == []


def test_stop_holders_tells_a_process_it_could_not_end(monkeypatch):
    """A process that is gone already counts as ended; a refusal is named, not taken for a stop."""
    ended = _system_stops(monkeypatch, gone={12}, failing={21})
    said: list[str] = []
    processes = [
        {"pid": 11, "ppid": 1, "kind": SERVER, "command_line": "elemctl mcp"},
        {"pid": 12, "ppid": 11, "kind": SERVER, "command_line": "python elemctl mcp"},
        {"pid": 21, "ppid": 1, "kind": COMMAND, "command_line": "elemctl deploy"},
    ]
    alive = selfupdate.stop_holders(processes, said.append)
    assert ended == [11, 12, 21]
    assert [item["pid"] for item in alive] == [21]
    assert said[0] == "остановлен сервер: pid 11 – elemctl mcp"
    assert said[1].startswith("не удалось остановить pid 21 – elemctl deploy: ")
    assert len(said) == 2


def test_refusals_advise_by_the_kind_of_holder(monkeypatch):
    server = {"pid": 11, "ppid": 1, "kind": SERVER, "command_line": "elemctl mcp"}
    command = {"pid": 21, "ppid": 1, "kind": COMMAND, "command_line": "elemctl deploy demo-app"}
    both = selfupdate._holders_message([server, command])
    assert both.index("Держат установку серверы: pid 11 – elemctl mcp") < both.index(
        "либо запустите с --stop-holders") < both.index("Идут команды: pid 21") < both.index(
        "дождитесь конца команд")
    # asked to stop the servers and they are still listed: closing them by hand is what is left
    assert "Закройте их и повторите. Идут команды" in selfupdate._holders_message(
        [server, command], selfupdate.STOP_SERVERS)
    assert selfupdate._holders_message([command], selfupdate.STOP_ALL).endswith(
        "Закройте их и повторите")
    assert selfupdate._holders_message([]).startswith("Определить держателей не удалось")
    long = {**command, "command_line": "elemctl deploy " + "x" * 400}
    assert selfupdate._holders_message([long]).count("x") < 200


def test_messages_of_the_holders_are_in_english_too(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path)
    _listing(monkeypatch)
    _ended(monkeypatch)
    i18n.set_lang("en")
    said: list[str] = []
    selfupdate.self_update(log=said.append, stop=selfupdate.STOP_SERVERS)
    message = selfupdate._holders_message(selfupdate.holders())
    # the lines about processes only: the line naming the site quotes a path of the machine
    text = "\n".join(line for line in said if "pid" in line) + "\n" + message
    assert "stopped the server: pid 11" in text
    assert "leaving a running command alone: pid 21" in text
    assert "Servers holding the installation" in text and "wait for the commands to finish" in text
    assert not any("а" <= char <= "я" for char in text.lower())


# -- the file list comes from the simple index ---------------------------------------------
#
# Ported from the toolkit engine, where the failure was caught live on 31.07.2026: right
# after a release the JSON metadata of PyPI still answered with the previous version, so
# `self-update` said "already current" - and with an explicit version, "no wheel", because
# the file list was read from that same lagging document.


def _simple_payload(*names: str, yanked: tuple[str, ...] = ()) -> bytes:
    """A PEP 691 answer of the simple index for the given file names."""
    return json.dumps({
        "meta": {"api-version": "1.1"},
        "files": [
            {"filename": name, "url": f"http://pypi/{name}", "yanked": name in yanked}
            for name in names
        ],
    }).encode("utf-8")


def _serve(monkeypatch, index: bytes | None, meta: dict | None = None) -> list[str]:
    """Answer the index and the JSON summary; returns the list of asked urls.

    The page of any other version answers 404, the way the page of an unpublished one does:
    the latest version is also looked for past the listings (test_selfupdate_latest.py).
    """
    asked: list[str] = []

    def urlopen(target, timeout=0):
        url = getattr(target, "full_url", target)
        asked.append(url)
        if url == selfupdate.PYPI_SIMPLE:
            accept = getattr(target, "headers", {}).get("Accept")
            assert accept == selfupdate.SIMPLE_ACCEPT, "without the header the index answers HTML"
            if index is None:
                raise OSError("index unreachable")
            return _FakeResp(index)
        if url == selfupdate.PYPI_LATEST and meta is not None:
            return _FakeResp(json.dumps(meta).encode("utf-8"))
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", urlopen)
    return asked


def _pages_after(version: str) -> list[str]:
    """The addresses of the next patch, minor and major pages, in the order they are asked."""
    return [selfupdate.PYPI_VERSION.format(version=v) for v in selfupdate._next_versions(version)]


def test_wheel_url_reads_the_simple_index(monkeypatch):
    asked = _serve(monkeypatch, _simple_payload(
        "elemctl-0.22.0-py3-none-any.whl",
        "elemctl-0.23.0-py3-none-any.whl",
        "elemctl-0.23.0.tar.gz",
    ))

    url, version = selfupdate._wheel_url(None)

    assert version == "0.23.0" and url.endswith("elemctl-0.23.0-py3-none-any.whl")
    # The index answers for the files; the summary and the next pages are asked beside it.
    assert asked == [selfupdate.PYPI_SIMPLE, selfupdate.PYPI_LATEST, *_pages_after("0.23.0")]


def test_a_fresh_release_is_installable_while_the_json_still_lags(monkeypatch):
    """The very failure this port exists for: the index has 0.23.0, the JSON still says 0.22.0."""
    lagging = {"info": {"version": "0.22.0"},
               "urls": [{"filename": "elemctl-0.22.0-py3-none-any.whl", "url": "http://pypi/old.whl"}]}
    asked = _serve(monkeypatch, _simple_payload("elemctl-0.23.0-py3-none-any.whl"), meta=lagging)

    url, version = selfupdate._wheel_url("0.23.0")

    assert version == "0.23.0" and url.endswith("elemctl-0.23.0-py3-none-any.whl")
    assert asked == [selfupdate.PYPI_SIMPLE]


def test_yanked_and_pre_release_files_never_win_the_latest_race(monkeypatch):
    _serve(monkeypatch, _simple_payload(
        "elemctl-0.22.0-py3-none-any.whl",
        "elemctl-0.23.0-py3-none-any.whl",
        "elemctl-0.24.0rc1-py3-none-any.whl",
        yanked=("elemctl-0.23.0-py3-none-any.whl",),
    ))
    assert selfupdate._wheel_url(None)[1] == "0.22.0"


def test_release_ranking_is_numeric_not_lexicographic():
    files = [{"filename": f"elemctl-{v}-py3-none-any.whl", "version": v}
             for v in ("0.9.0", "0.23.0", "0.23.0.post1")]
    assert selfupdate._latest_release(files) == "0.23.0.post1"
    assert selfupdate._release_key("0.24.0rc1") is None
    assert selfupdate._version_of("elemctl-0.23.0.tar.gz") == "0.23.0"


def test_an_index_without_pep691_falls_back_to_the_json(monkeypatch):
    """A mirror that answers HTML (or is unreachable) must not break the update."""
    meta = {"info": {"version": "0.22.0"},
            "urls": [{"filename": "elemctl-0.22.0-py3-none-any.whl", "url": "http://pypi/pure.whl"}]}
    asked = _serve(monkeypatch, None, meta=meta)

    assert selfupdate._wheel_url(None) == ("http://pypi/pure.whl", "0.22.0")
    assert asked == [selfupdate.PYPI_SIMPLE, selfupdate.PYPI_LATEST, *_pages_after("0.22.0")]


def test_incomplete_simple_index_falls_back_to_json_metadata(monkeypatch):
    """A broken simple-index response keeps the JSON metadata fallback available."""
    metadata = {
        "info": {"version": "0.22.0"},
        "urls": [{"filename": "elemctl-0.22.0-py3-none-any.whl", "url": "http://pypi/pure.whl"}],
    }

    def urlopen(target, timeout=0):
        if getattr(target, "full_url", target) == selfupdate.PYPI_SIMPLE:
            return _IncompleteResp(b"")
        return _FakeResp(json.dumps(metadata).encode("utf-8"))

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", urlopen)

    assert selfupdate._wheel_url(None) == ("http://pypi/pure.whl", "0.22.0")


def test_incomplete_json_metadata_is_a_reported_update_error(monkeypatch):
    """A broken metadata response becomes the regular PyPI connectivity error."""
    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", lambda *args, **kwargs: _IncompleteResp(b""))

    with pytest.raises(elemctl.errors.ElemctlError, match="PyPI"):
        selfupdate._fetch_json(selfupdate.PYPI_LATEST)


def test_incomplete_wheel_download_leaves_the_installation_untouched(monkeypatch, tmp_path):
    """A broken wheel response stops before the installed package is moved aside."""
    site = _install(monkeypatch, tmp_path)
    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", lambda *args, **kwargs: _IncompleteResp(b""))

    with pytest.raises(elemctl.errors.ElemctlError, match="скачать колесо"):
        selfupdate.self_update(log=lambda *args: None)

    assert '__version__ = "0.0.1"' in (site / "elemctl" / "__init__.py").read_text(encoding="utf-8")


def test_a_version_the_index_does_not_carry_is_named_as_such(monkeypatch):
    """The index lagging is possible, so the page of the version is asked; its 404 is the answer."""
    asked = _serve(monkeypatch, _simple_payload("elemctl-0.23.0-py3-none-any.whl"))
    with pytest.raises(Exception, match="версия"):
        selfupdate._wheel_url("9.9.9")
    assert asked == [selfupdate.PYPI_SIMPLE, selfupdate.PYPI_VERSION.format(version="9.9.9")]
