"""elemctl extension points: what external packages add to the core.

Two entry point groups, and the core declares neither of them in its own
pyproject.toml – it only reads them:

- "elemctl.debug_adapter" – the directory of the platform debug adapter. The
  public elemctl does not ship the proprietary jar files of the 1C:Element
  adapter; the value of the entry point is either a path (Path/str) or a function
  without arguments that returns one. The path is a directory containing a repo/
  subdirectory with the adapter jars (the ready-made value of
  xbslDebug.adapterPath for the keyfire.xbsl-debug VS Code extension).
- "elemctl.commands" – commands of the plugin. The value is a Command, a list of
  them, or a function without arguments returning either. ONE declaration gives
  both surfaces: the core builds a CLI subcommand and an MCP tool out of it, and
  knows nothing about what the command does. That is where a command belongs when
  it is about someone's own environment – internal circuits, other systems,
  stands – and therefore has no place in a public core.

The declaration in the pyproject.toml of the plugin package:

    [project.entry-points."elemctl.debug_adapter"]
    package-name = "my_package:adapter_root"

    [project.entry-points."elemctl.commands"]
    package-name = "my_package.commands:commands"

The ELEMCTL_NO_PLUGINS=1 environment variable turns plugin discovery off – a run
with the regular capabilities of the core only.

A failure to load an entry point is an error (PluginError), not a silent skip: a
tool that quietly lost a plugin would leave the user without debugging and without
an explanation of the reason.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

from . import i18n
from .errors import PluginError

DEBUG_ADAPTER_GROUP = "elemctl.debug_adapter"
COMMANDS_GROUP = "elemctl.commands"
ENV_DISABLE = "ELEMCTL_NO_PLUGINS"

# The argument types a command may declare. The set is deliberately small: every
# one of them has to survive both argparse and a JSON schema of an MCP tool.
ARGUMENT_TYPES = (str, int, float, bool)

# The main class of the platform's Java debug adapter; the VS Code extension runs it
# as a stdio DAP over the classpath from the adapter directory.
ADAPTER_MAIN_CLASS = "com.e1c.g5rt.debugger.adapter.App"

_FALSY = {"", "0", "false", "no"}


def disabled() -> bool:
    """Whether plugin discovery is turned off (ELEMCTL_NO_PLUGINS)."""
    return os.environ.get(ENV_DISABLE, "").strip().lower() not in _FALSY


def _points(group: str) -> list[EntryPoint]:
    if disabled():
        return []
    return sorted(entry_points(group=group), key=lambda ep: ep.name)


def _load(ep: EntryPoint):
    try:
        return ep.load()
    except Exception as exc:
        raise PluginError(i18n.t(
            "plugins.entry-point-failed",
            name=ep.name, group=ep.group, value=ep.value, error=exc,
        )) from exc


def debug_adapter_paths() -> list[Path]:
    """Debug adapter directories declared by external packages (ordered by entry point name).

    The value of an entry point is a path or a function without arguments that returns
    a path. The directory is not validated here (whether the adapter jars are in place) –
    that is what debug_adapter_path does; the full list is needed for diagnostics (the
    plugins command).
    """
    paths: list[Path] = []
    for ep in _points(DEBUG_ADAPTER_GROUP):
        target = _load(ep)
        if callable(target):
            target = target()
        paths.append(Path(target))
    return paths


def has_adapter_jars(path: Path) -> bool:
    """Whether the directory has a repo/ subdirectory with the platform debug adapter jars."""
    repo = path / "repo"
    if not repo.is_dir():
        return False
    return any(repo.glob("com.e1c.g5rt.debugger.adapter*.jar"))


def debug_adapter_path() -> Path | None:
    """The first declared adapter directory with jars inside; None when there is no plugin.

    The returned path is the ready-made adapterPath value for the VS Code extension:
    a directory containing a repo/ subdirectory with the adapter jar files.
    """
    for path in debug_adapter_paths():
        if has_adapter_jars(path):
            return path
    return None


# -- commands of a plugin -------------------------------------------------------


@dataclass
class Argument:
    """An argument of a plugin command – one declaration for both surfaces.

    name – "--stand" for an option or "stand" for a positional argument; the CLI
    gets it as it is, the MCP tool gets the same name with the dashes stripped and
    the inner ones turned into underscores (argparse does exactly that for dest).
    type – one of ARGUMENT_TYPES; bool means a flag (store_true in the CLI, a
    boolean with a default of False in MCP), so a positional argument cannot be
    one. required works for options; a positional argument is required unless it
    has required=False, which makes it optional (nargs="?").
    """

    name: str
    help: str = ""
    type: type = str
    default: object = None
    required: bool = False
    choices: tuple = ()

    @property
    def is_option(self) -> bool:
        return self.name.startswith("-")

    @property
    def dest(self) -> str:
        """The name of the value: what argparse puts into the namespace."""
        return self.name.lstrip("-").replace("-", "_")

    @property
    def value_default(self):
        """The default of the value: False for a flag, otherwise the declared one."""
        if self.type is bool:
            return bool(self.default)
        return self.default


@dataclass
class Command:
    """A command of a plugin: a CLI subcommand and an MCP tool from one declaration.

    handler is called as handler(context, **values), where context is a
    CommandContext and values are the arguments by their dest. The returned value
    has to be JSON-serializable: the CLI prints it, the MCP tool returns it. A
    result that is a dict with "ok": False gives exit code 1 in the CLI – the same
    convention the reports of deploy and probe follow.

    mcp=False leaves the command in the CLI only (for one that makes no sense to
    an agent – an interactive one, say). source is filled in by discovery: the
    name of the entry point the command arrived through.
    """

    name: str
    help: str
    handler: object
    arguments: list = field(default_factory=list)
    mcp: bool = True
    mcp_name: str = ""
    source: str = ""

    @property
    def tool_name(self) -> str:
        """The name of the MCP tool: the explicit one or the command name with underscores."""
        return self.mcp_name or self.name.replace("-", "_")

    def validate(self, where=""):
        """Check the declaration; a violation is a PluginError naming the source.

        The check is made at discovery time rather than at the moment of a call:
        a plugin that declares a command wrongly must be visible right away, not
        when somebody happens to run it.
        """
        if not self.name or not isinstance(self.name, str):
            raise PluginError(i18n.t("plugins.command-name-required", where=where))
        if not callable(self.handler):
            raise PluginError(
                i18n.t("plugins.command-handler-required", where=where, name=self.name)
            )
        seen = set()
        for argument in self.arguments:
            if not isinstance(argument, Argument):
                raise PluginError(i18n.t(
                    "plugins.not-an-argument", where=where, name=self.name, value=argument
                ))
            if argument.type not in ARGUMENT_TYPES:
                raise PluginError(i18n.t(
                    "plugins.argument-type-unsupported",
                    where=where, name=self.name, argument=argument.name,
                    type=getattr(argument.type, "__name__", argument.type),
                    supported=", ".join(t.__name__ for t in ARGUMENT_TYPES),
                ))
            if argument.type is bool and not argument.is_option:
                raise PluginError(i18n.t(
                    "plugins.flag-must-be-option",
                    where=where, name=self.name, argument=argument.name,
                ))
            if argument.dest in seen:
                raise PluginError(i18n.t(
                    "plugins.argument-duplicate",
                    where=where, name=self.name, argument=argument.dest,
                ))
            seen.add(argument.dest)
        return self


class CommandContext:
    """What a plugin command gets from the core: the configuration, a client, progress.

    The client is built on the first request and cached: a command that never
    reaches the platform (a local check, work with files) must not demand
    connection credentials. log is a callback for progress lines – in the CLI it
    goes to stderr, in MCP it is collected into the log field of the answer.
    """

    def __init__(self, config, *, client=None, client_factory=None, log=None):
        self.config = config
        self._client = client
        self._client_factory = client_factory
        self._log = log or (lambda message: None)

    @property
    def client(self):
        """The platform client of this environment."""
        if self._client is None:
            if self._client_factory is None:
                raise PluginError(i18n.t("plugins.no-client"))
            self._client = self._client_factory(self.config)
        return self._client

    def log(self, message):
        """Report a progress line."""
        self._log(str(message))


def plugin_commands() -> list[Command]:
    """Commands declared by external packages (ordered by entry point name).

    The value of an entry point is a Command, a list of them or a function
    without arguments returning either. Every command is validated right here –
    see Command.validate.
    """
    commands: list[Command] = []
    for ep in _points(COMMANDS_GROUP):
        target = _load(ep)
        if not isinstance(target, Command) and callable(target):
            target = target()
        items = [target] if isinstance(target, Command) else target
        if isinstance(items, (str, bytes)) or not hasattr(items, "__iter__"):
            raise PluginError(i18n.t("plugins.not-commands", name=ep.name, value=items))
        for item in items:
            if not isinstance(item, Command):
                raise PluginError(i18n.t("plugins.not-commands", name=ep.name, value=item))
            item.source = ep.name
            commands.append(item.validate(where=ep.name))
    return commands
