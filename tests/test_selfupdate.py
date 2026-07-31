"""self-update tests: updating by unpacking the wheel with no network (urllib is mocked)."""

from __future__ import annotations

import io
import json
import os
import zipfile

import pytest

import elemctl
from elemctl import cli, selfupdate


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


def test_self_update_extracts_wheel(monkeypatch, tmp_path):
    """The wheel is unpacked into site-packages; the old package and dist-info are removed."""
    site = tmp_path / "site-packages"
    (site / "elemctl").mkdir(parents=True)
    (site / "elemctl" / "__init__.py").write_text('__version__ = "0.0.1"\n', encoding="utf-8")
    (site / "elemctl-0.0.1.dist-info").mkdir()
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: site)
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v: ("http://pypi/elemctl.whl", "9.9.9"))
    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9")))

    old, new = selfupdate.self_update(log=lambda *a: None)

    assert new == "9.9.9" and old == elemctl.__version__
    assert '__version__ = "9.9.9"' in (site / "elemctl" / "__init__.py").read_text(encoding="utf-8")
    assert not (site / "elemctl-0.0.1.dist-info").exists()  # the old dist-info is gone
    assert (site / "elemctl-9.9.9.dist-info").exists()


def test_self_update_noop_when_current(monkeypatch, tmp_path):
    """When the PyPI version equals the current one and no version is asked for – nothing is downloaded."""
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v: ("http://pypi/x.whl", elemctl.__version__))

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
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v: ("http://pypi/x.whl", "9.9.9"))
    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9")))

    selfupdate.self_update(log=lambda *a: None)

    assert json.loads(meta.read_text(encoding="utf-8"))["main_package"]["package_version"] == "9.9.9"


def test_cli_self_update(monkeypatch, capsys):
    monkeypatch.setattr(selfupdate, "self_update", lambda version=None, log=print, stop_busy=False: ("0.5.0", "0.6.0"))
    rc = cli.main(["self-update"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"updated": True, "from": "0.5.0", "to": "0.6.0"}


# --- занятая установка: что бы ни случилось, прежняя версия остаётся на месте ---------------
#
# Ровно этот отказ и случился при выпуске 0.19.0: pip упёрся в занятый живой MCP-сессией
# elemctl.exe, успел удалить пакет и не поставил новый – `elemctl --version` ответил
# ModuleNotFoundError. Порядок перенесён из движка, где он уже обкатан.


def _install(monkeypatch, tmp_path, payload=None):
    site = tmp_path / "site-packages"
    (site / "elemctl").mkdir(parents=True)
    (site / "elemctl" / "__init__.py").write_text('__version__ = "0.0.1"\n', encoding="utf-8")
    (site / "elemctl-0.0.1.dist-info").mkdir()
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: site)
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v: ("http://pypi/elemctl.whl", "9.9.9"))
    monkeypatch.setattr(
        selfupdate.urllib.request, "urlopen",
        lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9") if payload is None else payload),
    )
    return site


def test_busy_installation_is_refused_before_anything_is_removed(monkeypatch, tmp_path):
    """Переименование – ворота: файл занят, а удалять ещё нечего."""
    site = _install(monkeypatch, tmp_path)
    original = selfupdate.Path.rename

    def refuse(self, target):
        if self.name == "elemctl":
            raise OSError(13, "Файл занят другим процессом")
        return original(self, target)

    monkeypatch.setattr(selfupdate.Path, "rename", refuse)
    monkeypatch.setattr(selfupdate, "holders", lambda: [{"pid": 4242, "name": "elemctl.exe"}])

    with pytest.raises(elemctl.errors.ElemctlError) as error:
        selfupdate.self_update(log=lambda *a: None)

    message = str(error.value)
    assert "elemctl.exe" in message and "4242" in message and "--stop-holders" in message
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
    """Ошибиться здесь – значит предложить снять ЧУЖОЙ процесс."""
    monkeypatch.setattr(
        selfupdate, "_process_listing",
        lambda: [
            (11, 1, "elemctl.exe", "elemctl mcp"),
            (12, 1, "python.exe", "python.exe -m elemctl mcp"),
            (13, 1, "python.exe", "python.exe -m http.server"),
            # Клиент агента несёт команду сервера в своей строке запуска – но держателем
            # не является: снять его было бы худшей из ошибок.
            (14, 1, "claude.exe", "claude.exe --mcp-server elemctl mcp"),
        ],
    )
    assert {item["pid"] for item in selfupdate.holders()} == {11, 12}


def test_holders_exclude_own_process_tree(monkeypatch):
    """Обёртка pipx, запустившая команду, и её дерево – не держатели.

    Живой отказ 28.07: `--stop-holders` снял собственный родительский `elemctl.exe`,
    Job Object лаунчера утянул за ним и сам обновляющий процесс – обновление оборвалось
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
    """Answer the index and the JSON metadata separately; returns the list of asked urls."""
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
        assert meta is not None, "the JSON metadata must not be asked at all"
        return _FakeResp(json.dumps(meta).encode("utf-8"))

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", urlopen)
    return asked


def test_wheel_url_reads_the_simple_index(monkeypatch):
    asked = _serve(monkeypatch, _simple_payload(
        "elemctl-0.22.0-py3-none-any.whl",
        "elemctl-0.23.0-py3-none-any.whl",
        "elemctl-0.23.0.tar.gz",
    ))

    url, version = selfupdate._wheel_url(None)

    assert version == "0.23.0" and url.endswith("elemctl-0.23.0-py3-none-any.whl")
    assert asked == [selfupdate.PYPI_SIMPLE]


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
    assert asked == [selfupdate.PYPI_SIMPLE, selfupdate.PYPI_LATEST]


def test_a_version_the_index_does_not_carry_is_named_as_such(monkeypatch):
    """A readable index is the answer: no second guess at the lagging JSON."""
    _serve(monkeypatch, _simple_payload("elemctl-0.23.0-py3-none-any.whl"))
    with pytest.raises(Exception, match="версия"):
        selfupdate._wheel_url("9.9.9")
