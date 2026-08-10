---
title: "MCP server and editors"
description: "Driving elemctl from an AI agent over MCP, plus plugins and the VS Code extension."
sidebar:
  label: MCP and editors
  order: 4
---

## MCP server


The server exposes platform operations as MCP tools (stdio transport):

```bash
pip install "elemctl[mcp]"
claude mcp add elemctl -- elemctl mcp
```

The server reads connection credentials from the same `ELEMENT_*` variables / `.env`.

### Tools

| Tool | What it does |
|---|---|
| `list_apps` | list of applications; `name` filters by a substring of the name on the client, `brief` (the default) keeps id, name, status, uri and the applied version |
| `find_app` | find an application by its exact name: the id and a `found` flag; deleted ones are skipped unless `include_deleted` is set |
| `get_app` | application card: status, uri, the actual project version |
| `create_app` | create an application; with only a `project_id` the source is the project's latest build. The answer carries `sign-in` – the way in |
| `ensure_app` | create an application by name only if it does not exist yet; an existing one is not recreated (`created: false`) |
| `start_app` | start the application |
| `stop_app` | stop the application |
| `delete_app` | delete the application. IRREVERSIBLE: the data is lost, and a recreated application gets a different URL |
| `list_app_tasks` | tasks of the applications; `app_id` is an optional filter |
| `debug_info` | debug-session data: `debug-token` and `debug-address` (debugging must be enabled on the server) |
| `list_spaces` | list of spaces |
| `list_projects` | list of projects; `brief` (the default) – id, name, project kind, space, application count, deletion flag |
| `list_builds` | list of a project's builds |
| `build_assembly` | build a `.xasm`/`.xlib` archive from the sources locally (does not talk to the platform) |
| `inspect_assembly` | parse a built archive: manifest, project properties, subsystems and global types with qualified names (local) |
| `deploy` | the whole cycle from sources with the honest apply verification; the verdict is `ok`, the details are `problems` and `log` |
| `probe` | check the compilation with the server compiler WITHOUT touching the working application; errors with file, line and column, cleans up after itself |
| `apply_build` | apply an uploaded build to the application by its id |
| `verify_deploy` | verify the apply actually took effect: failed tasks, the applied build, the availability of the uri |
| `list_user_lists` | user lists; `name` filters by a substring of the presentation |
| `configure_user_list` | self-registration and password sign-in; without the flags it only reports the current state |
| `list_branches` | list of development-environment branches; the `project_id` and `name` filters are optional |
| `merge_branch` | accept the changes of a development-environment branch |
| `debug_adapter` | the path to the platform debug adapter from a plugin; a missing plugin is an answer (`found: false`), not an error (local) |

The tools a plugin brings stand next to these (see below).

A single environment is not a limit: every tool that talks to the platform takes an optional `env_file` - a path to another installation's `.env`. One server thus serves both the cloud and a local installation without a restart with different credentials. `list_apps` returns brief cards by default (id, name, status, uri, applied version): full cards of a whole space are tens of thousands of characters in an agent's response - pass `brief=false` for them; its `name` parameter filters by a case-insensitive substring on the client (the platform ignores the query parameter). `list_projects` behaves the same way (id, name, project kind, space, application count, deletion flag). `get_app`, `delete_app`, `start_app`, `stop_app` and `debug_info` accept the application id (UUID) or its exact name - a non-UUID value is resolved through the list, and several matches are an error rather than a guess. `create_app` and `ensure_app` add a `sign-in` field to the answer – the address and the account that gets into a freshly created application (a CONTROL PANEL one; the accounts of an external provider do not work there) – because an agent sees only the JSON.

## Plugins


elemctl discovers external packages through `importlib.metadata` entry points: it declares nothing about plugins in its own `pyproject.toml` and reads them on demand. This keeps non-publishable vendor artifacts in a separate package while the elemctl core stays clean and public.

**`elemctl.debug_adapter`** – a plugin package declares the directory of the platform debug adapter (proprietary 1C jars, not shipped with elemctl). The entry-point value is a path or a zero-argument callable returning a path; the path points to a directory that contains a `repo/` subdirectory with the adapter jars.

**`elemctl.commands`** – a plugin package brings commands of its own. The entry-point value is a `Command`, a list of them, or a zero-argument callable returning either. ONE declaration gives both surfaces: elemctl builds a CLI subcommand out of it and an MCP tool with a proper schema, and knows nothing about what the command does. That is where a command belongs when it is about your own environment – internal circuits, other systems, your stands – and therefore has no place in a public core.

```toml
# a plugin package's pyproject.toml
[project.entry-points."elemctl.debug_adapter"]
name = "my_package:adapter_root"     # () -> Path to the directory containing repo/

[project.entry-points."elemctl.commands"]
name = "my_package.commands:commands"   # () -> list[Command]
```

```python
# my_package/commands.py
from elemctl.plugins import Argument, Command

def warm_up(context, stand="", force=False):
    context.log(f"warming up {stand}")          # progress: stderr in the CLI, the log field in MCP
    card = context.client.get_app(stand)        # the client is built on first use
    return {"ok": True, "status": card.get("status")}

def commands():
    return [Command(
        name="warm-up",
        help="open the admin page of a fresh stand",
        handler=warm_up,
        arguments=[Argument("--stand", help="the application"), Argument("--force", type=bool)],
    )]
```

The result of a handler has to be JSON-serializable: the CLI prints it, the MCP tool returns it. A result that is a dict with `"ok": false` gives exit code 1 in the CLI – the same convention the reports of `deploy` and `probe` follow. Argument types are `str`, `int`, `float` and `bool` (a flag); `env_file` is added to the MCP tool by elemctl, so a plugin command reaches other environments exactly like the core tools do. A command may not take over a name the core already occupies – that is an error, not a silent override.

```bash
# the adapter path from the installed plugin (for the VS Code extension):
# {"path": "...", "found": true} or {"path": null, "found": false}
elemctl debug-adapter

# what the plugins bring – adapter directories and commands
elemctl plugins
```

The adapter itself (proprietary 1C jars) is extracted from the platform distribution by `tools/extract_adapter.py` – into a directory for a manual `xbsl.debug.adapterPath`, or for building the plugin package. The script is not shipped in the package distribution.

Plugin discovery is disabled by `ELEMCTL_NO_PLUGINS=1` (a run with the core capabilities only).

## VS Code


A companion extension integrates elemctl into the editor:

- [XBSL](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl) (the
  [xbsl](https://github.com/keyfire/xbsl) project) – highlighting, linting, the form designer,
  the metadata tree, the *XBSL: deploy the project* button that runs `elemctl deploy` as a
  terminal task with the apply verification, and debugging 1C:Element applications with the
  platform's DAP adapter, whose session data comes from `elemctl apps debug`. Debugging used
  to be a separate *XBSL Debug* extension living in the elemctl repository; since XBSL 0.57 it
  is part of the one extension, and the repository keeps only the elemctl side of it.

It is also published to [Open VSX](https://open-vsx.org/namespace/keyfire).
