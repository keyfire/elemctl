"""elemctl extension points: external packages bring in the platform debug adapter.

The public elemctl does not ship the proprietary jar files of the 1C:Element debug
adapter. An external plugin package declares the adapter directory through the
"elemctl.debug_adapter" entry point group – the value points either to a path
(Path/str) or to a function without arguments that returns a path. The path is a
directory containing a repo/ subdirectory with the adapter jar files (the ready-made
value of xbslDebug.adapterPath for the keyfire.xbsl-debug VS Code extension).

The declaration in the pyproject.toml of the plugin package:

    [project.entry-points."elemctl.debug_adapter"]
    package-name = "my_package:adapter_root"

The ELEMCTL_NO_PLUGINS=1 environment variable turns plugin discovery off – a run
with the regular capabilities of the core only.

A failure to load an entry point is an error (PluginError), not a silent skip: a
tool that quietly lost a plugin would leave the user without debugging and without
an explanation of the reason.
"""

from __future__ import annotations

import os
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

from . import i18n
from .errors import PluginError

DEBUG_ADAPTER_GROUP = "elemctl.debug_adapter"
ENV_DISABLE = "ELEMCTL_NO_PLUGINS"

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
