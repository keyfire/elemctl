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
    monkeypatch.setattr(plugins, "plugin_commands", lambda: [])
    rc = cli.main(["plugins"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {
        "debug-adapter": [
            {"path": str(good), "has-jars": True},
            {"path": str(empty), "has-jars": False},
        ],
        "commands": [],
    }


# --- Commands of a plugin ----------------------------------------------------------

def _warm_up(context, stand="", retries=1, force=False):
    """A stand-in for a command of a plugin: it reports what it was given."""
    context.log("греем стенд")
    return {"stand": stand, "retries": retries, "force": force, "base": context.config.base_url}


def _command(**overrides):
    fields = {
        "name": "warm-up",
        "help": "прогреть стенд",
        "handler": _warm_up,
        "arguments": [
            plugins.Argument("--stand", help="имя стенда", default=""),
            plugins.Argument("--retries", type=int, default=1),
            plugins.Argument("--force", type=bool, help="не спрашивать"),
        ],
    }
    fields.update(overrides)
    return plugins.Command(**fields)


def _with_commands(monkeypatch, *commands, name="плагин"):
    ep = _StubEP(name, plugins.COMMANDS_GROUP, list(commands))
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))


def test_commands_discovered_from_a_list_and_from_a_callable(monkeypatch):
    as_list = _StubEP("а-список", plugins.COMMANDS_GROUP, [_command()])
    as_single = _StubEP("б-одна", plugins.COMMANDS_GROUP, _command(name="one"))
    as_callable = _StubEP("в-функция", plugins.COMMANDS_GROUP, lambda: [_command(name="two")])
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(as_list, as_single, as_callable))

    found = plugins.plugin_commands()

    assert [c.name for c in found] == ["warm-up", "one", "two"]
    # The source is filled in by discovery – that is what the diagnostics shows.
    assert [c.source for c in found] == ["а-список", "б-одна", "в-функция"]


def test_command_declaration_is_checked_at_discovery(monkeypatch):
    """A wrong declaration must show up at once, not when somebody runs the command."""
    cases = [
        _command(name=""),
        _command(handler="не вызываемый"),
        _command(arguments=[plugins.Argument("--when", type=list)]),
        _command(arguments=[plugins.Argument("force", type=bool)]),  # a flag as a positional
        _command(arguments=[plugins.Argument("--stand"), plugins.Argument("--stand")]),
        _command(arguments=["--stand"]),
    ]
    for broken in cases:
        _with_commands(monkeypatch, broken)
        with pytest.raises(PluginError):
            plugins.plugin_commands()


def test_entry_point_giving_something_else_is_an_error(monkeypatch):
    ep = _StubEP("плагин", plugins.COMMANDS_GROUP, 42)
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))
    with pytest.raises(PluginError, match="плагин"):
        plugins.plugin_commands()


def test_context_builds_the_client_only_when_asked(monkeypatch):
    """A command that never reaches the platform must not demand credentials."""
    built = []

    def factory(config):
        built.append(config)
        return "клиент"

    context = plugins.CommandContext("конфигурация", client_factory=factory)
    assert built == []
    assert context.client == "клиент"
    assert context.client == "клиент"  # cached, the factory is called once
    assert built == ["конфигурация"]


def test_cli_runs_a_plugin_command(monkeypatch, capsys):
    _with_commands(monkeypatch, _command())

    rc = cli.main([
        "--base-url", "https://api.test", "--client-id", "cid", "--client-secret", "s",
        "warm-up", "--stand", "dev", "--retries", "3", "--force",
    ])

    assert rc == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "stand": "dev", "retries": 3, "force": True, "base": "https://api.test",
    }
    assert "греем стенд" in captured.err  # the progress goes to stderr, as everywhere


def test_cli_plugin_command_defaults_and_failure_code(monkeypatch, capsys):
    def handler(context, stand=""):
        return {"ok": False, "stand": stand}

    _with_commands(monkeypatch, _command(
        arguments=[plugins.Argument("--stand", default="dev")], handler=handler
    ))

    rc = cli.main(["warm-up"])

    assert rc == 1  # the ok: false convention of the core reports
    assert json.loads(capsys.readouterr().out) == {"ok": False, "stand": "dev"}


def test_cli_plugin_command_with_a_positional_argument(monkeypatch, capsys):
    def handler(context, app=None):
        return {"app": app}

    _with_commands(monkeypatch, _command(
        arguments=[plugins.Argument("app", required=False)], handler=handler
    ))

    assert cli.main(["warm-up"]) == 0
    assert json.loads(capsys.readouterr().out) == {"app": None}
    assert cli.main(["warm-up", "crm-dev"]) == 0
    assert json.loads(capsys.readouterr().out) == {"app": "crm-dev"}


def test_cli_plugin_cannot_take_over_a_core_command(monkeypatch, capsys):
    _with_commands(monkeypatch, _command(name="deploy"))

    rc = cli.main(["apps", "list"])

    assert rc == 1  # the parser did not even get built – and it is a JSON error, not a traceback
    assert "deploy" in json.loads(capsys.readouterr().err)["error"]


def test_cli_plugins_diagnostics_lists_commands(monkeypatch, capsys):
    monkeypatch.setattr(plugins, "debug_adapter_paths", lambda: [])
    _with_commands(monkeypatch, _command(), _command(name="only-cli", mcp=False))

    assert cli.main(["plugins"]) == 0

    assert json.loads(capsys.readouterr().out)["commands"] == [
        {"name": "warm-up", "source": "плагин", "mcp": "warm_up"},
        {"name": "only-cli", "source": "плагин", "mcp": None},
    ]
