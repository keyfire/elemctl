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
    monkeypatch.setattr(plugins, "discover_commands", lambda: ([], []))
    rc = cli.main(["plugins"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {
        "debug-adapter": [
            {"path": str(good), "has-jars": True},
            {"path": str(empty), "has-jars": False},
        ],
        "commands": [],
        "failures": [],
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
        _command(arguments=[plugins.Argument("--stand", cli_alias="--s")]),  # alias on an option
        _command(arguments=[plugins.Argument("stand", cli_alias="page")]),  # alias without a dash
        _command(arguments=[  # alias collides with another argument's own flag
            plugins.Argument("stand", cli_alias="--force"), plugins.Argument("--force", type=bool),
        ]),
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


def _factory_for_a_newer_core():
    """The factory of a plugin written for a core that knows a field this one does not."""
    raise TypeError("Argument.__init__() got an unexpected keyword argument 'cli_alias'")


def test_a_command_factory_that_fails_is_a_plugin_error(monkeypatch):
    """Only the loading of an entry point was wrapped, and the call of its factory was not.

    A plugin that declared a field the installed core does not have yet raised a bare
    TypeError out of the factory, and the reader got a Python traceback.
    """
    ep = _StubEP("новее-ядра", plugins.COMMANDS_GROUP, _factory_for_a_newer_core)
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))

    with pytest.raises(PluginError) as refusal:
        plugins.plugin_commands()

    message = str(refusal.value)
    assert "новее-ядра" in message and "TypeError" in message and "cli_alias" in message


def test_an_adapter_factory_that_fails_is_a_plugin_error(monkeypatch):
    """The adapter group calls a factory the same way and had the same gap."""

    def broken():
        raise RuntimeError("каталог не собран")

    ep = _StubEP("адаптер", plugins.DEBUG_ADAPTER_GROUP, broken)
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))

    with pytest.raises(PluginError, match="каталог не собран"):
        plugins.debug_adapter_paths()


def test_discovery_keeps_the_healthy_plugins_and_names_the_broken_one(monkeypatch):
    good = _StubEP("а-исправный", plugins.COMMANDS_GROUP, [_command()])
    broken = _StubEP("б-новее-ядра", plugins.COMMANDS_GROUP, _factory_for_a_newer_core)
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(good, broken))

    commands, failures = plugins.discover_commands()

    assert [command.name for command in commands] == ["warm-up"]
    assert [failure.source for failure in failures] == ["б-новее-ядра"]
    assert "cli_alias" in failures[0].to_dict()["error"]


def test_a_plugin_with_one_bad_command_brings_none_of_them(monkeypatch):
    """A plugin half registered is harder to read than a plugin that did not load."""
    ep = _StubEP("плагин", plugins.COMMANDS_GROUP, [_command(), _command(name="")])
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))

    commands, failures = plugins.discover_commands()

    assert commands == []
    assert [failure.source for failure in failures] == ["плагин"]


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


@pytest.mark.parametrize("result, expected", [
    # an integer from 0 to 255 in the field is the exit code, and it wins over ok
    ({"ok": False, "exit-code": 2}, 2),
    ({"exit-code": 255}, 255),
    ({"ok": False, "exit-code": 0}, 0),
    ({"ok": True, "exit-code": 1}, 1),
    # without the field the convention of the core reports stays
    ({"ok": False}, 1),
    ({"ok": True}, 0),
    ({"stand": "dev"}, 0),
    # a value that is not a code is ignored, and ok decides again
    ({"ok": False, "exit-code": "2"}, 1),
    ({"exit-code": "2"}, 0),
    ({"ok": False, "exit-code": True}, 1),
    ({"exit-code": True}, 0),
    ({"ok": False, "exit-code": 300}, 1),
    ({"exit-code": 300}, 0),
    ({"exit-code": -1}, 0),
    ({"ok": False, "exit-code": 2.0}, 1),
    ({"ok": False, "exit-code": None}, 1),
    # only a dict result names a code
    ([{"exit-code": 2}], 0),
])
def test_cli_plugin_command_takes_the_exit_code_from_the_result(
    monkeypatch, capsys, result, expected
):
    """A command with three outcomes hands a script three codes, and no SystemExit is needed."""
    _with_commands(monkeypatch, _command(arguments=[], handler=lambda context: result))

    assert cli.main(["warm-up"]) == expected
    assert json.loads(capsys.readouterr().out) == result  # the answer itself is printed as is


def test_the_exit_code_field_is_exported_under_its_documented_name():
    # a plugin that also runs on an older core looks for this name to learn the field is read
    assert plugins.EXIT_CODE_FIELD == "exit-code"


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


def test_cli_plugin_command_with_a_cli_alias_takes_either_form(monkeypatch, capsys):
    """A positional argument with cli_alias is reachable positionally or by its key.

    wiki-get took the page only positionally, and wiki-get --page 123 failed
    with "unrecognized arguments" even though the same key works on wiki-publish.
    """
    _with_commands(monkeypatch, _command(
        name="wiki-get",
        arguments=[plugins.Argument("page", required=True, cli_alias="--page")],
        handler=lambda context, page=None: {"page": page},
    ))

    assert cli.main(["wiki-get", "123"]) == 0
    assert json.loads(capsys.readouterr().out) == {"page": "123"}
    assert cli.main(["wiki-get", "--page", "123"]) == 0
    assert json.loads(capsys.readouterr().out) == {"page": "123"}


def test_cli_plugin_command_refuses_the_alias_given_twice_or_not_at_all(monkeypatch):
    """One value, one place to put it: both forms at once, or neither of a required
    argument, is a parser refusal rather than a silent pick of one over the other."""
    _with_commands(monkeypatch, _command(
        name="wiki-get",
        arguments=[plugins.Argument("page", required=True, cli_alias="--page")],
        handler=lambda context, page=None: {"page": page},
    ))

    with pytest.raises(SystemExit):
        cli.main(["wiki-get", "1", "--page", "2"])
    with pytest.raises(SystemExit):
        cli.main(["wiki-get"])


def test_cli_plugin_command_without_a_cli_alias_still_refuses_the_key_form(monkeypatch):
    """A plugin that declares no synonym behaves exactly as before: positional only."""
    _with_commands(monkeypatch, _command(
        arguments=[plugins.Argument("app", required=False)],
        handler=lambda context, app=None: {"app": app},
    ))

    assert cli.main(["warm-up", "crm-dev"]) == 0
    with pytest.raises(SystemExit):
        cli.main(["warm-up", "--app", "crm-dev"])


def test_cli_plugin_command_alias_falls_back_to_the_declared_default(monkeypatch, capsys):
    """An optional aliased positional keeps its own default when neither form is given –
    not argparse's own None, which would silently override what the plugin declared."""
    _with_commands(monkeypatch, _command(
        arguments=[plugins.Argument("retries", type=int, default=7, cli_alias="--retries")],
        handler=lambda context, retries=None: {"retries": retries},
    ))

    assert cli.main(["warm-up"]) == 0
    assert json.loads(capsys.readouterr().out) == {"retries": 7}


def test_cli_plugin_alias_positional_says_it_is_absent_without_a_string(monkeypatch):
    """The marker for "the positional was not given" must not be a string.

    argparse runs `type` over a STRING default of an optional positional before it looks
    at what the default means, so argparse.SUPPRESS - itself a string - made an int
    argument refuse its own marker on Python 3.10: "invalid int value: '==SUPPRESS=='".
    The test above only catches that on the older interpreter; this one catches it on any.
    """
    _with_commands(monkeypatch, _command(
        arguments=[plugins.Argument("retries", type=int, default=7, cli_alias="--retries")],
    ))

    warm_up = cli._choices_of(cli.build_parser(), "command")["warm-up"]
    positional = next(a for a in warm_up._actions
                      if a.dest == "retries" and not a.option_strings)
    assert not isinstance(positional.default, str)


def test_cli_plugin_cannot_take_over_a_core_command(monkeypatch, capsys):
    """The core keeps its name, and the clash is named rather than fatal to the whole CLI."""
    monkeypatch.setattr(plugins, "debug_adapter_paths", lambda: [])
    _with_commands(monkeypatch, _command(name="deploy"), _command())

    assert cli.main(["plugins"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [command["name"] for command in payload["commands"]] == ["warm-up"]
    assert payload["failures"][0]["source"] == "плагин"
    assert "deploy" in payload["failures"][0]["error"]


def _with_a_broken_plugin(monkeypatch):
    """A healthy plugin beside one written for a newer core."""
    good = _StubEP("а-исправный", plugins.COMMANDS_GROUP, [_command()])
    broken = _StubEP("б-новее-ядра", plugins.COMMANDS_GROUP, _factory_for_a_newer_core)
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(good, broken))


def test_a_broken_plugin_leaves_the_rest_of_the_cli_working(monkeypatch, capsys):
    """A plugin written for a newer core took the whole CLI down with a Python traceback.

    The parser was never built, so no command worked, the core ones included. Now the
    plugin is left out, and it is named on stderr rather than dropped without a word.
    """
    _with_a_broken_plugin(monkeypatch)

    rc = cli.main([
        "--base-url", "https://api.test", "--client-id", "cid", "--client-secret", "s",
        "warm-up", "--stand", "dev",
    ])

    assert rc == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["stand"] == "dev"
    assert "б-новее-ядра" in captured.err and "cli_alias" in captured.err


def test_a_command_of_a_broken_plugin_is_refused_with_json(monkeypatch, capsys):
    """The command the broken plugin would have brought gets the usual JSON refusal."""
    _with_a_broken_plugin(monkeypatch)

    rc = cli.main(["wiki-get", "123"])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert "wiki-get" in payload["error"] and "б-новее-ядра" in payload["error"]
    assert [failure["source"] for failure in payload["plugin-failures"]] == ["б-новее-ядра"]
    assert "cli_alias" in payload["plugin-failures"][0]["error"]


def test_cli_plugins_diagnostics_lists_the_broken_plugins(monkeypatch, capsys):
    monkeypatch.setattr(plugins, "debug_adapter_paths", lambda: [])
    _with_a_broken_plugin(monkeypatch)

    assert cli.main(["plugins"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert [command["name"] for command in payload["commands"]] == ["warm-up"]
    assert [failure["source"] for failure in payload["failures"]] == ["б-новее-ядра"]
    # The answer carries the failures, so stderr does not repeat them.
    assert "б-новее-ядра" not in captured.err


def test_cli_plugins_diagnostics_lists_commands(monkeypatch, capsys):
    monkeypatch.setattr(plugins, "debug_adapter_paths", lambda: [])
    _with_commands(monkeypatch, _command(), _command(name="only-cli", mcp=False))

    assert cli.main(["plugins"]) == 0

    assert json.loads(capsys.readouterr().out)["commands"] == [
        {"name": "warm-up", "source": "плагин", "mcp": "warm_up"},
        {"name": "only-cli", "source": "плагин", "mcp": None},
    ]
