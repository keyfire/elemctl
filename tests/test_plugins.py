"""Plugin system tests: discovering the debug adapter through entry points.

No real plugin package is installed - the entry points are replaced with stubs and the
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
    """An entry point with a ready-made object - no real package installed."""

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
    # The source is filled in by discovery - that is what the diagnostics shows.
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


# --- A plugin argument and the global options of the core ----------------------------

# Read from cli, the same place the check reads them from, and never copied here.
GLOBAL_OPTIONS = cli._GLOBAL_OPTIONS + cli._GLOBAL_FLAGS


@pytest.mark.parametrize("option", GLOBAL_OPTIONS)
def test_a_plugin_option_may_not_take_a_global_option(monkeypatch, option):
    """The CLI moves a global option in front of the subcommand and parses it itself.

    `warm-up --timeout 5` of a plugin that declared its own `--timeout` reached neither
    side: the core took the value, and the default of the plugin's option overwrote it.
    """
    _with_commands(monkeypatch, _command(arguments=[plugins.Argument(option)]))

    with pytest.raises(PluginError) as refusal:
        plugins.plugin_commands()

    message = str(refusal.value)
    assert f"общего ключа elemctl {option}." in message
    assert "warm-up" in message and "плагин" in message


@pytest.mark.parametrize("argument", [
    plugins.Argument("timeout"),
    plugins.Argument("env-file", required=False),
    plugins.Argument("--env_file"),
], ids=["positional-timeout", "positional-env-file", "option-env_file"])
def test_a_plugin_argument_may_not_share_the_value_name_of_a_global_option(
    monkeypatch, argument
):
    """A subcommand writes its values into the namespace of the root parser.

    A positional argument named `timeout` handed its value to the core as the timeout of
    every request, and an `env_file` would be the second one of the MCP tool.
    """
    _with_commands(monkeypatch, _command(arguments=[argument]))

    with pytest.raises(PluginError) as refusal:
        plugins.plugin_commands()

    assert f"аргумент {argument.name} " in str(refusal.value)


def test_a_cli_alias_may_not_take_a_global_option(monkeypatch):
    """`warm-up --quiet dev` switched the progress off and passed dev positionally."""
    _with_commands(monkeypatch, _command(
        arguments=[plugins.Argument("stand", required=False, cli_alias="--quiet")]
    ))

    with pytest.raises(PluginError) as refusal:
        plugins.plugin_commands()

    assert "stand (cli_alias --quiet)" in str(refusal.value)


def test_the_global_options_are_read_from_the_cli(monkeypatch):
    """An option the core adds is refused to a plugin at once: there is no copy to update."""
    monkeypatch.setattr(cli, "_GLOBAL_OPTIONS", cli._GLOBAL_OPTIONS + ("--region",))
    _with_commands(monkeypatch, _command(arguments=[plugins.Argument("--region")]))

    with pytest.raises(PluginError, match="--region"):
        plugins.plugin_commands()


def test_names_near_a_global_option_stay_free(monkeypatch, capsys):
    """Only a global option itself is taken: a prefix of one and a longer name are not.

    `--base` is a prefix of `--base-url`, and a real plugin declares it.
    """
    _with_commands(monkeypatch, _command(
        arguments=[
            plugins.Argument("--base"),
            plugins.Argument("--timeout-seconds", type=int),
            plugins.Argument("--json-out"),
            plugins.Argument("stand", required=False, cli_alias="--stand"),
        ],
        handler=lambda context, **values: values,
    ))

    assert cli.main([
        "warm-up", "--base", "demo-app", "--timeout-seconds", "5", "--json-out", "a.json", "dev",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "base": "demo-app", "timeout_seconds": 5, "json_out": "a.json", "stand": "dev",
    }


# --- A plugin argument and the names the CLI keeps beside a command ---------------------

# Read off the parser, the same place the check reads them from. The global options have
# a check and a message of their own above.
CLI_NAMES = sorted(cli.plugin_namespace()[0] - {plugins.Argument(o).dest for o in GLOBAL_OPTIONS})


def test_the_cli_keeps_the_names_a_plugin_broke_the_call_with():
    assert {"handler", "command", "plugin_command"} <= set(CLI_NAMES)
    assert cli.plugin_namespace()[1] == ("-h", "--help")


@pytest.mark.parametrize("name", CLI_NAMES)
def test_a_plugin_argument_may_not_take_a_value_name_the_cli_keeps(monkeypatch, name):
    """A plugin command is parsed into the namespace of the whole CLI.

    A positional `handler` replaced the function main calls with the string the user typed,
    and the call ended in `TypeError: 'str' object is not callable`.
    """
    _with_commands(monkeypatch, _command(arguments=[plugins.Argument(name)]))

    with pytest.raises(PluginError) as refusal:
        plugins.plugin_commands()

    message = str(refusal.value)
    assert f"хранит значение под именем {name}," in message
    assert "warm-up" in message and "плагин" in message


def test_an_option_is_refused_by_its_value_name_as_well(monkeypatch):
    _with_commands(monkeypatch, _command(arguments=[plugins.Argument("--plugin-command")]))

    with pytest.raises(PluginError, match="под именем plugin_command,"):
        plugins.plugin_commands()


@pytest.mark.parametrize("argument", [
    plugins.Argument("--help"),
    plugins.Argument("-h", type=bool),
    plugins.Argument("stand", required=False, cli_alias="--help"),
], ids=["option-help", "flag-h", "alias-help"])
def test_a_plugin_may_not_declare_the_help_of_its_subcommand(monkeypatch, argument):
    """The subparser answers -h and --help itself, and argparse refused the second one with a
    bare ArgumentError while the parser of the whole CLI was being built."""
    _with_commands(monkeypatch, _command(arguments=[argument]))

    with pytest.raises(PluginError) as refusal:
        plugins.plugin_commands()

    assert "объявляет ключ " in str(refusal.value)
    assert "-h, --help" in str(refusal.value)


def test_a_plugin_that_declares_help_is_named_and_the_core_keeps_working(monkeypatch, capsys):
    monkeypatch.setattr(plugins, "debug_adapter_paths", lambda: [])
    _with_commands(monkeypatch, _command(arguments=[plugins.Argument("--help")]))

    assert cli.main(["plugins"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["commands"] == []
    assert "--help" in payload["failures"][0]["error"]


def test_a_positional_handler_no_longer_ends_the_call_in_a_type_error(monkeypatch, capsys):
    _with_commands(monkeypatch, _command(
        arguments=[plugins.Argument("handler")], handler=lambda context, **values: values
    ))

    assert cli.main(["warm-up", "demo-app"]) == 1

    refusal = json.loads(capsys.readouterr().err)
    assert "warm-up" in refusal["error"] and "handler" in refusal["plugin-failures"][0]["error"]


def test_the_names_are_read_off_the_parser(monkeypatch):
    """A value the core starts to keep beside a command is refused to a plugin at once."""
    build_parser = cli.build_parser

    def with_region(discover=None):
        parser = build_parser(discover)
        parser.set_defaults(region="eu")
        return parser

    monkeypatch.setattr(cli, "build_parser", with_region)
    cli.plugin_namespace.cache_clear()
    try:
        _with_commands(monkeypatch, _command(arguments=[plugins.Argument("--region")]))
        with pytest.raises(PluginError, match="под именем region,"):
            plugins.plugin_commands()
    finally:
        cli.plugin_namespace.cache_clear()


def test_a_plugin_that_takes_a_global_option_is_named_and_the_core_keeps_working(
    monkeypatch, capsys
):
    monkeypatch.setattr(plugins, "debug_adapter_paths", lambda: [])
    _with_commands(monkeypatch, _command(), _command(
        name="with-timeout", arguments=[plugins.Argument("--timeout", type=float)]
    ))

    assert cli.main(["plugins"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["commands"] == []  # all or nothing: the whole entry point is left out
    assert [failure["source"] for failure in payload["failures"]] == ["плагин"]
    assert "--timeout" in payload["failures"][0]["error"]


def test_a_plugin_env_file_no_longer_stops_the_mcp_server(monkeypatch, capsys):
    """The core adds env_file to every tool of a plugin, and a plugin's own made two of them.

    The signature of the tool could not be built ("duplicate parameter name"), and the
    ValueError took the whole server down with every tool of the core.
    """
    pytest.importorskip("mcp.server", reason="the elemctl[mcp] extra is not installed")
    import asyncio

    from elemctl import mcp_server

    _with_commands(monkeypatch, _command(arguments=[plugins.Argument("--env-file")]))

    server = mcp_server.create_server()

    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert "deploy" in names and "warm_up" not in names
    assert "--env-file" in capsys.readouterr().err


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


def test_cli_tells_the_command_it_runs_as_a_subcommand(monkeypatch, capsys):
    """A plugin used to guess the surface from the shape of context.log."""
    _with_commands(monkeypatch, _command(
        arguments=[], handler=lambda context: {"surface": context.surface}
    ))

    assert cli.main(["warm-up"]) == 0
    assert json.loads(capsys.readouterr().out) == {"surface": "cli"}


def test_the_surfaces_are_exported_under_their_documented_names():
    # a plugin compares context.surface with these, and one on an older core finds no attribute
    assert (plugins.SURFACE_CLI, plugins.SURFACE_MCP) == ("cli", "mcp")
    assert plugins.CommandContext("конфигурация").surface is None  # built by hand: not said


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
    """An optional aliased positional keeps its own default when neither form is given -
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


# --- A multiple option ---------------------------------------------------------------

def _attach_command(*arguments, handler=None):
    """A command that takes files: it reports the list it was given."""
    return _command(
        name="wiki-attach",
        arguments=list(arguments) or [plugins.Argument("--file", multiple=True)],
        handler=handler or (lambda context, **values: values),
    )


def test_cli_plugin_multiple_option_keeps_every_value(monkeypatch, capsys):
    """A single option given seven times kept the seventh value and dropped six without a word.

    A command asked to upload seven files uploaded one, and its report named that one alone.
    """
    _with_commands(monkeypatch, _attach_command())

    assert cli.main(["wiki-attach", "--file", "a.png", "--file", "b.png", "--file", "a.png"]) == 0
    # in the order of the command line and with the repeats kept: what to make of a repeat is
    # the business of the command
    assert json.loads(capsys.readouterr().out) == {"file": ["a.png", "b.png", "a.png"]}

    assert cli.main(["wiki-attach"]) == 0
    assert json.loads(capsys.readouterr().out) == {"file": []}


def test_cli_plugin_multiple_option_replaces_its_default(monkeypatch, capsys):
    """argparse appends to a default list: the default here is taken only when the key is absent."""
    _with_commands(monkeypatch, _attach_command(
        plugins.Argument("--file", multiple=True, default=("readme.md",)),
    ))

    assert cli.main(["wiki-attach"]) == 0
    assert json.loads(capsys.readouterr().out) == {"file": ["readme.md"]}
    assert cli.main(["wiki-attach", "--file", "a.png"]) == 0
    assert json.loads(capsys.readouterr().out) == {"file": ["a.png"]}


def test_cli_plugin_multiple_option_checks_every_value(monkeypatch, capsys):
    """The type and the choices apply to each value, and required means at least one."""
    _with_commands(monkeypatch, _attach_command(
        plugins.Argument("--line", type=int, multiple=True, required=True),
        plugins.Argument("--status", multiple=True, choices=("done", "open")),
    ))

    assert cli.main(["wiki-attach", "--line", "3", "--line", "12", "--status", "done"]) == 0
    assert json.loads(capsys.readouterr().out) == {"line": [3, 12], "status": ["done"]}
    for refused in (
        ["wiki-attach"],
        ["wiki-attach", "--line", "3", "--line", "x"],
        ["wiki-attach", "--line", "3", "--status", "done", "--status", "lost"],
    ):
        with pytest.raises(SystemExit):
            cli.main(refused)


def test_cli_plugin_multiple_option_hands_every_call_a_list_of_its_own(monkeypatch, capsys):
    """A handler that appends to the list it got must not pass the items to the next call."""

    def handler(context, file):
        file.append("added.png")
        return {"file": file}

    _with_commands(monkeypatch, _attach_command(
        plugins.Argument("--file", multiple=True, default=["readme.md"]), handler=handler,
    ))

    for _ in range(2):
        assert cli.main(["wiki-attach"]) == 0
        assert json.loads(capsys.readouterr().out) == {"file": ["readme.md", "added.png"]}


def test_cli_plugin_multiple_option_says_so_in_its_help(monkeypatch, capsys):
    _with_commands(monkeypatch, _attach_command(
        plugins.Argument("--file", help="файл к загрузке", multiple=True),
        plugins.Argument("--mask", multiple=True),
    ))

    with pytest.raises(SystemExit):
        cli.main(["wiki-attach", "--help"])

    text = " ".join(capsys.readouterr().out.split())
    assert "файл к загрузке (ключ можно повторить, по значению на каждый)" in text
    assert "--mask MASK (ключ можно повторить" in text


def test_a_flag_may_not_be_multiple(monkeypatch):
    """A flag given twice says no more than a flag given once."""
    _with_commands(monkeypatch, _command(
        arguments=[plugins.Argument("--force", type=bool, multiple=True)],
    ))

    with pytest.raises(PluginError) as refusal:
        plugins.plugin_commands()

    message = str(refusal.value)
    assert "--force" in message and "повторяемым (multiple), а это флаг" in message


@pytest.mark.parametrize("argument", [
    plugins.Argument("files", multiple=True),
    plugins.Argument("files", multiple=True, required=True),
    plugins.Argument("files", multiple=True, cli_alias="--file"),
], ids=["optional", "required", "aliased"])
def test_a_positional_argument_may_be_multiple(monkeypatch, argument):
    """A positional argument used to be refused: it had no key to repeat. It takes its values
    one after another now, and a cli_alias key is repeated the way an option is."""
    _with_commands(monkeypatch, _command(arguments=[argument]))

    assert plugins.plugin_commands()[0].arguments == [argument]


@pytest.mark.parametrize("default", ["a.png", 3, {"a.png"}])
@pytest.mark.parametrize("name", ["--file", "file"])
def test_a_multiple_argument_takes_a_list_for_its_default(monkeypatch, name, default):
    """list("a.png") would hand the command five one-letter files."""
    _with_commands(monkeypatch, _command(
        arguments=[plugins.Argument(name, multiple=True, default=default)],
    ))

    with pytest.raises(PluginError) as refusal:
        plugins.plugin_commands()

    assert name in str(refusal.value) and repr(default) in str(refusal.value)


def test_a_plugin_on_an_older_core_can_tell_multiple_is_there():
    # the check the documentation tells a plugin to make before declaring a multiple option
    assert hasattr(plugins.Argument, "multiple")
    assert plugins.Argument("--file").multiple is False


def test_a_plugin_on_an_older_core_can_tell_a_positional_may_be_multiple():
    # hasattr(Argument, "multiple") also holds on a core that refuses a multiple positional
    # argument, so the documentation points a plugin at this name instead
    assert plugins.POSITIONAL_MULTIPLE is True


# --- A multiple positional argument --------------------------------------------------

def _pages_command(*arguments, handler=None):
    """A command that takes pages: it reports the values it was given."""
    return _command(
        name="wiki-get",
        arguments=list(arguments) or [
            plugins.Argument("page", type=int, required=True, multiple=True, cli_alias="--page"),
            plugins.Argument("--stand", default=""),
        ],
        handler=handler or (lambda context, **values: values),
    )


@pytest.mark.parametrize("argv", [
    ["123", "456", "123"],
    ["--page", "123", "--page", "456", "--page", "123"],
    ["--stand", "dev", "123", "456", "123"],
    ["123", "456", "123", "--stand", "dev"],
    ["--page", "123", "--stand", "dev", "--page", "456", "--page", "123"],
])
def test_cli_plugin_multiple_positional_takes_every_value_in_either_form(
    monkeypatch, capsys, argv
):
    """A positional argument with a key synonym took one value, and a repeated key kept the
    last of them: "--page 123 --page 456" asked for two pages and got the second one."""
    _with_commands(monkeypatch, _pages_command())

    assert cli.main(["wiki-get", *argv]) == 0

    # in the order of the command line and with the repeats kept, the way an option keeps them
    result = json.loads(capsys.readouterr().out)
    assert result["page"] == [123, 456, 123]
    assert result["stand"] == ("dev" if "--stand" in argv else "")


def test_cli_plugin_multiple_positional_hands_one_value_as_a_list(monkeypatch, capsys):
    _with_commands(monkeypatch, _pages_command())

    for argv in (["7"], ["--page", "7"]):
        assert cli.main(["wiki-get", *argv]) == 0
        assert json.loads(capsys.readouterr().out) == {"page": [7], "stand": ""}


@pytest.mark.parametrize("argv", [["123", "--page", "456"], ["--page", "456", "123"]])
def test_cli_plugin_multiple_positional_refuses_both_forms_at_once(monkeypatch, capsys, argv):
    """One list, one place to put it: the values of the two forms are not merged."""
    _with_commands(monkeypatch, _pages_command())

    with pytest.raises(SystemExit):
        cli.main(["wiki-get", *argv])

    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("argument", [
    plugins.Argument("page", required=True, multiple=True, cli_alias="--page"),
    plugins.Argument("page", required=True, multiple=True),
], ids=["aliased", "positional-only"])
def test_cli_plugin_multiple_positional_needs_a_value_when_required(
    monkeypatch, capsys, argument
):
    _with_commands(monkeypatch, _pages_command(argument))

    with pytest.raises(SystemExit):
        cli.main(["wiki-get"])

    assert "required" in capsys.readouterr().err


@pytest.mark.parametrize("cli_alias", ["", "--page"], ids=["positional-only", "aliased"])
def test_cli_plugin_multiple_positional_falls_back_to_its_default(
    monkeypatch, capsys, cli_alias
):
    """An optional argument given no value hands over its default as a list of its own, so a
    handler that changes the list it got cannot hand the change over to the next call."""

    def handler(context, page, stand):
        page.append(0)
        return {"page": page}

    _with_commands(monkeypatch, _pages_command(
        plugins.Argument("page", type=int, multiple=True, default=(1,), cli_alias=cli_alias),
        plugins.Argument("--stand", default=""),
        handler=handler,
    ))

    for _ in range(2):
        assert cli.main(["wiki-get"]) == 0
        assert json.loads(capsys.readouterr().out) == {"page": [1, 0]}
    # the command line replaces the default rather than adding to it
    assert cli.main(["wiki-get", "5", "6"]) == 0
    assert json.loads(capsys.readouterr().out) == {"page": [5, 6, 0]}


@pytest.mark.parametrize("cli_alias", ["", "--status"], ids=["positional-only", "aliased"])
def test_cli_plugin_multiple_positional_checks_every_value(monkeypatch, capsys, cli_alias):
    """The type and the choices apply to each value of either form.

    Before Python 3.14 argparse also checks the absence marker of an optional "*" positional
    against the choices, and an argument given no value was refused: "invalid choice:
    '==SUPPRESS=='". CI runs the suite on 3.10 and 3.12, where that happens.
    """
    _with_commands(monkeypatch, _pages_command(
        plugins.Argument("status", multiple=True, choices=("done", "open"), cli_alias=cli_alias),
        plugins.Argument("--line", type=int, multiple=True),
    ))

    assert cli.main(["wiki-get"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": [], "line": []}
    assert cli.main(["wiki-get", "open", "done", "--line", "3"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": ["open", "done"], "line": [3]}

    refused = [["done", "lost"]]
    if cli_alias:
        refused.append(["--status", "done", "--status", "lost"])
    for argv in refused:
        with pytest.raises(SystemExit):
            cli.main(["wiki-get", *argv])
        assert "'lost'" in capsys.readouterr().err

    _with_commands(monkeypatch, _pages_command(
        plugins.Argument("page", type=int, multiple=True, cli_alias=cli_alias and "--page"),
    ))
    with pytest.raises(SystemExit):
        cli.main(["wiki-get", "3", "x"])
    assert "invalid int value: 'x'" in capsys.readouterr().err


def test_cli_plugin_multiple_positional_says_so_in_its_help(monkeypatch, capsys):
    _with_commands(monkeypatch, _pages_command(
        plugins.Argument("page", help="страница", required=True, multiple=True, cli_alias="--page"),
        plugins.Argument("tag", multiple=True),
    ))

    with pytest.raises(SystemExit):
        cli.main(["wiki-get", "--help"])

    text = " ".join(capsys.readouterr().out.split())
    assert "страница (можно назвать несколько значений через пробел)" in text
    assert "tag (можно назвать несколько значений через пробел)" in text
    assert ("то же, что позиционный аргумент page (ключ можно повторить, по значению на каждый)"
            in text)


def test_cli_plugin_positional_without_multiple_still_takes_one_value(monkeypatch, capsys):
    """An argument that does not declare the field takes one value in either form: the
    positional form refuses a second one, and a repeated key refuses a different one, like
    any key of one value. It used to keep the last of them."""
    _with_commands(monkeypatch, _pages_command(
        plugins.Argument("page", type=int, required=True, cli_alias="--page"),
    ))

    assert cli.main(["wiki-get", "123"]) == 0
    assert json.loads(capsys.readouterr().out) == {"page": 123}
    assert cli.main(["wiki-get", "--page", "123", "--page", "123"]) == 0
    assert json.loads(capsys.readouterr().out) == {"page": 123}
    with pytest.raises(SystemExit) as refusal:
        cli.main(["wiki-get", "--page", "123", "--page", "456"])
    assert refusal.value.code == 2
    assert ('ключ --page принимает одно значение, а повторен с разными: "123" и "456"'
            in capsys.readouterr().err)
    with pytest.raises(SystemExit):
        cli.main(["wiki-get", "123", "456"])
    assert "unrecognized arguments: 456" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["7", "--page", "7"], ["--page", "7", "7"]])
def test_cli_plugin_alias_and_positional_stay_exclusive_with_the_same_value(
    monkeypatch, capsys, argv
):
    """The two forms of one argument are refused together, whatever the values: the rule of
    a repeated key compares the occurrences of one key and does not reach across the pair."""
    _with_commands(monkeypatch, _pages_command(
        plugins.Argument("page", type=int, required=True, cli_alias="--page"),
    ))

    with pytest.raises(SystemExit) as refusal:
        cli.main(["wiki-get", *argv])

    assert refusal.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("argv, key, first, second", [
    (["--stand", "dev", "--stand", "prod"], "--stand", "dev", "prod"),
    (["--stand=dev", "--stand", "prod"], "--stand", "dev", "prod"),
    (["--retries", "3", "--retries=4"], "--retries", "3", "4"),
])
def test_cli_plugin_option_refuses_a_repetition_with_another_value(
    monkeypatch, capsys, argv, key, first, second
):
    """A plugin command is parsed by the parser of the core, so its keys of one value fall
    under the same rule as the keys of the core, and the command is not called."""
    called = []
    _with_commands(monkeypatch, _command(handler=lambda context, **values: called.append(values)))

    with pytest.raises(SystemExit) as refusal:
        cli.main(["warm-up", *argv])

    assert refusal.value.code == 2
    assert (f'ключ {key} принимает одно значение, а повторен с разными: "{first}" и "{second}"'
            in capsys.readouterr().err)
    assert called == []


def test_cli_plugin_option_repeated_with_the_same_value_and_a_repeated_flag_pass(
    monkeypatch, capsys
):
    _with_commands(monkeypatch, _command())

    assert cli.main([
        "--base-url", "https://api.test",
        "warm-up", "--stand", "dev", "--stand=dev", "--retries", "3", "--retries", "03",
        "--force", "--force",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "stand": "dev", "retries": 3, "force": True, "base": "https://api.test",
    }


def test_cli_plugin_option_with_choices_takes_one_value(monkeypatch, capsys):
    _with_commands(monkeypatch, _command(
        arguments=[plugins.Argument("--step", choices=("build", "check"))],
        handler=lambda context, step=None: {"step": step},
    ))

    assert cli.main(["warm-up", "--step", "check", "--step", "check"]) == 0
    assert json.loads(capsys.readouterr().out) == {"step": "check"}
    with pytest.raises(SystemExit):
        cli.main(["warm-up", "--step", "build", "--step", "check"])
    assert '"build" и "check"' in capsys.readouterr().err


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
