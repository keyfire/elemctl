"""Plugin system tests: discovering the debug adapter through entry points.

No real plugin package is installed – the entry points are replaced with stubs and the
adapter directories are assembled in temporary folders.
"""

from __future__ import annotations

import json
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from elemctl import cli, plugins
from elemctl.errors import PluginError


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(plugins.ENV_DISABLE, raising=False)


def _make_adapter_dir(path: Path, jar="com.e1c.g5rt.debugger.adapter-9.2.8-1.jar") -> Path:
    """An adapter directory: <path>/repo/<adapter jar> plus a third-party jar next to it."""
    repo = path / "repo"
    repo.mkdir(parents=True)
    (repo / jar).write_bytes(b"")
    (repo / "netty-common-4.1.0.jar").write_bytes(b"")
    return path


class _StubEP:
    """An entry point with a ready-made object – no real package installed."""

    value = "стаб"

    def __init__(self, name, group, target):
        self.name = name
        self.group = group
        self._target = target

    def load(self):
        return self._target


def _fake_entry_points(*eps):
    def fake(group):
        return [ep for ep in eps if ep.group == group]

    return fake


# --- Discovering the adapter directory --------------------------------------------

def test_no_plugins_no_path(monkeypatch):
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points())
    assert plugins.debug_adapter_paths() == []
    assert plugins.debug_adapter_path() is None


def test_path_and_callable_targets(tmp_path, monkeypatch):
    as_path = _StubEP("а-путь", plugins.DEBUG_ADAPTER_GROUP, tmp_path / "прямой")
    as_callable = _StubEP(
        "б-функция", plugins.DEBUG_ADAPTER_GROUP, lambda: tmp_path / "через-функцию"
    )
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(as_path, as_callable))
    assert plugins.debug_adapter_paths() == [tmp_path / "прямой", tmp_path / "через-функцию"]


def test_first_dir_with_adapter_jars_wins(tmp_path, monkeypatch):
    empty = tmp_path / "пустой"  # comes first by entry-point name, but holds no jar
    empty.mkdir()
    good = _make_adapter_dir(tmp_path / "с-адаптером")
    ep_empty = _StubEP("а-пустой", plugins.DEBUG_ADAPTER_GROUP, empty)
    ep_good = _StubEP("б-адаптер", plugins.DEBUG_ADAPTER_GROUP, good)
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep_empty, ep_good))
    assert plugins.debug_adapter_path() == good


def test_dir_without_repo_ignored(tmp_path, monkeypatch):
    ep = _StubEP("адаптер", plugins.DEBUG_ADAPTER_GROUP, tmp_path)  # no repo/ subdirectory
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))
    assert plugins.debug_adapter_path() is None


def test_repo_without_adapter_jar_ignored(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "netty-common-4.1.0.jar").write_bytes(b"")  # third-party jars are there, the adapter is not
    ep = _StubEP("адаптер", plugins.DEBUG_ADAPTER_GROUP, tmp_path)
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))
    assert plugins.debug_adapter_path() is None


def test_broken_entry_point_raises(monkeypatch):
    ep = EntryPoint("битая", "нет_такого_модуля", plugins.DEBUG_ADAPTER_GROUP)
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))
    with pytest.raises(PluginError, match="битая"):
        plugins.debug_adapter_paths()


def test_no_plugins_env_disables(tmp_path, monkeypatch):
    good = _make_adapter_dir(tmp_path / "с-адаптером")
    ep = _StubEP("адаптер", plugins.DEBUG_ADAPTER_GROUP, good)
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))
    monkeypatch.setenv(plugins.ENV_DISABLE, "1")
    assert plugins.disabled()
    assert plugins.debug_adapter_paths() == []
    assert plugins.debug_adapter_path() is None


@pytest.mark.parametrize("value,expected", [("", False), ("0", False), ("no", False), ("1", True)])
def test_disable_flag_parsing(monkeypatch, value, expected):
    monkeypatch.setenv(plugins.ENV_DISABLE, value)
    assert plugins.disabled() is expected


# --- CLI ---------------------------------------------------------------------------

def test_cli_debug_adapter_found(tmp_path, monkeypatch, capsys):
    good = _make_adapter_dir(tmp_path / "с-адаптером")
    monkeypatch.setattr(plugins, "debug_adapter_path", lambda: good)
    rc = cli.main(["debug-adapter"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {
        "path": str(good),
        "found": True,
        "adapter-class": plugins.ADAPTER_MAIN_CLASS,
    }


def test_cli_debug_adapter_not_found(monkeypatch, capsys):
    monkeypatch.setattr(plugins, "debug_adapter_path", lambda: None)
    rc = cli.main(["debug-adapter"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"path": None, "found": False}


def test_cli_plugins_diagnostics(tmp_path, monkeypatch, capsys):
    good = _make_adapter_dir(tmp_path / "с-адаптером")
    empty = tmp_path / "пустой"
    empty.mkdir()
    monkeypatch.setattr(plugins, "debug_adapter_paths", lambda: [good, empty])
    rc = cli.main(["plugins"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {
        "debug-adapter": [
            {"path": str(good), "has-jars": True},
            {"path": str(empty), "has-jars": False},
        ]
    }
