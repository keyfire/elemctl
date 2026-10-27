---
title: "MCP server and editors"
description: "Driving elemctl from an AI agent over MCP, plus plugins and the VS Code extension."
sidebar:
  label: MCP and editors
  order: 4
---

## MCP server


The MCP server exposes tools for managing 1C:Element applications through the
Console API. It uses the stdio transport:

```bash
pip install "elemctl[mcp]"
claude mcp add elemctl -- elemctl mcp
```

The server reads connection credentials from the same `ELEMENT_*` variables / `.env`.

### Tools

| Tool | What it does |
|---|---|
| `list_apps` | List applications with name and status filters. |
| `find_app` | Find an application by its exact name. Returns its id and `found`; set `include_deleted` to include deleted entries. |
| `get_app` | Get the application status, uri and actual project version. `applied-build` contains the branch and commit from the build card or local upload registry. |
| `create_app` | Create an application. With only `project_id`, the latest build is selected; `sign-in` describes access and `verify` waits and checks the applied build. |
| `ensure_app` | Create an application by name if it does not exist. Returns `created: false` for an existing application; `verify` checks the applied build. |
| `start_app` | Start an application. |
| `stop_app` | Stop an application. |
| `delete_app` | Permanently delete an application and its data. Recreating it produces a different URL. |
| `list_app_tasks` | List application tasks, optionally filtered by `app_id`. |
| `debug_info` | Get `debug-token` and `debug-address` for debugging. Debugging must be enabled on the server. |
| `list_spaces` | List spaces. |
| `list_projects` | List projects with an optional name filter. |
| `list_builds` | List project builds with an optional count limit. |
| `get_build` | Get a complete build card by `version`, such as `1.0-42`, or an id resolved through the build list. |
| `build_assembly` | Build a `.xasm`/`.xlib` archive locally from sources without contacting the 1C:Element server. |
| `inspect_assembly` | Read an archive manifest, project properties, subsystems and global types with qualified names. This is a local operation. |
| `deploy` | Build, upload and apply sources, then verify the result. `ok` reports success; `problems` and `log` contain details. |
| `probe` | Check compilation in a temporary application. Errors include the file, line and column; created objects are removed unless `keep` is set. |
| `probe_cleanup` | Delete a temporary probe application, its build and its project if empty. `app_id` accepts one id or a list; each application has a separate report. |
| `apply_build` | Apply an uploaded build to an application by the build id. |
| `verify_deploy` | Check failed tasks, the actual applied build and uri availability. An extension build is checked against the application extensions. |
| `list_user_lists` | List user lists, optionally filtered by a presentation substring in `name`. |
| `configure_user_list` | Configure self-registration and password sign-in. Without flags, return the current state. |
| `list_app_users` | List users with their user list, id, presentation, administrator and token-access flags, plus a total. The Console API does not return a login. |
| `token_access` | Read a user's token access to HTTP services or change it with `enabled`. `user` also accepts a list. |
| `export_app` | Save the running application build to a file. Save applied extensions separately with `export_extension`. |
| `export_extension` | Save an applied extension build to a file. Requires Console API 2.1; `extension` accepts the extension id, or its project id, name or presentation. |
| `list_branches` | List development-environment branches with optional `project_id` and `name` filters. |
| `merge_branch` | Merge changes from a development-environment branch. |
| `debug_adapter` | Get the 1C:Element debug-adapter path from a plugin. This is local; a missing plugin returns `found: false`. |

The parameters of `list_apps`, `list_projects` and `list_builds` are described below.

Plugins can add tools of their own. See [Plugins](#plugins) for their
configuration.

Tools that access the 1C:Element server accept the optional `env_file` parameter with
the path to another installation's `.env`. One server can access both a cloud
and a local installation without a restart.

By default, `list_apps` returns brief cards with the id, name, status, URI and
applied version. Set `brief=false` to receive full cards. For a large number of
applications, the full response can contain tens of thousands of characters.

The `name` parameter filters by a case-insensitive substring on the client,
because the Console API ignores the query parameter. The `status` parameter
matches the complete status value. Set `include_deleted` to include deleted
applications. The response contains the `applications` cards, the `total`,
`live` and `shown` counters, and a `summary` line such as "7 live of 324".

By default, `list_projects` returns brief cards with the id, name, project kind,
space, application count and deletion flag. Set `brief=false` for full cards. Its `name` parameter filters by a substring. Set
`include_deleted` to include projects marked as deleted.

By default, `list_builds` returns the ten newest builds. Set `limit` to change
the count; `0` removes the limit. A brief card contains the id, versions, date,
branch and commit. Set `brief=false` for full cards. The source of the branch and commit, either the build card on the server
or the local upload registry, is also reported. The response includes `builds`,
the `total` and `shown`
counters, and a `summary` line.

The build list on the server is not a complete project history. When an application finishes applying a build, the server
removes unused builds regardless of their age. It
retains builds used by running applications, the build with the highest number
of its base version, release builds and builds uploaded without a project id.
The latter include the project's first build. The list is not paginated.

Build numbers for one base version are assigned consecutively. A missing number
can indicate a deleted build or a numbering jump. A build uploaded without a
project id keeps the version of its archive, and numbering continues from it.
If the local registry contains such an upload above a gap, `summary` identifies
the gap as a jump. If the gap contains an upload from this machine into the
project, `summary` reports both a jump and a deletion.

Builds of extension projects are not removed automatically. They can be deleted
manually, and `summary` identifies a gap in their numbers as a deletion.

`get_build` returns one complete card. The Console API method is addressed by
build version. When an id is supplied, the version is first resolved through the build list.

`get_app`, `delete_app`, `start_app`, `stop_app` and `debug_info` accept an
application id (UUID) or exact name. A value that is not UUID-shaped is looked up
in the list. Multiple matches produce an error.

### Application creation and verification

`create_app` and `ensure_app` return `sign-in` with the application address and
the account used to sign in. This is a control-panel account; accounts from other
applications are unavailable in the new application.

`verify` waits for the application and checks the actual applied build. The server
can roll back a failed apply without reporting the rollback, so application
readiness alone does not confirm the requested build. The check result is recorded
in `verify`. Waiting takes several minutes; use a background `elemctl` invocation.
If waiting is interrupted, the response retains the created application id and
records the cause in `wait-error`.

Before creation, `version_id` is checked against the builds of `project_id`.
If `project_id` is omitted, the installation's `ELEMENT_PROJECT_ID` is used.
If that project has no such build, the other projects are searched: an upload
without a project id may have been assigned elsewhere. In that case, the project
from configuration is replaced with the build's project. An explicitly supplied,
nonmatching `project_id` produces an error naming the build's project.

If no project contains the build, creation is not attempted. The server deletes
builds nobody uses, and creating from a deleted build returns HTTP 400. The
elemctl error describes the cause and reports the build used by a running
application of the project.

### Deployment and temporary applications

For `deploy`, `allow_data_loss` permits changes rejected by the schema check:
narrowing, a type change or removal of an entire catalog. It corresponds to
`--allow-data-loss` in the CLI. If the server is starting, the wait is limited
to `server_start_timeout` seconds, 900 by default. Optional `expected_app_name`
and `expected_app_uri` check the deployment target before building.

With `keep`, `probe` retains the objects it creates and includes a cleanup command in the report when an application id is available; otherwise `command` is null. `probe_cleanup` also removes objects left after interrupted cleanup.
The local upload registry identifies probe applications, including those with
custom names and versions, and records builds deployed into them. Builds are
removed only from the probe's own project; the project is deleted only when empty. The client checks whether a build is used by another live application only when the local registry has remembered builds for the probe. If none are recorded and the probe is identified by name or version, that check is not performed.
An application not associated with a probe is rejected. For an `app_id` list,
an error for one application does not stop processing the others.

### Access and export

Without token access, an HTTP-service request returns 500 "Token access is denied".
`token_access` reads the flag again after changing it. An empty `user` selects the
account used by elemctl. With a user list, each user has a separate result; an
error for one does not stop the others.

For `export_app` and `export_extension`, an empty `output` selects the MCP server's
current directory and the name `{Name} {Version}.xasm`. A method unavailable on
the server produces an explicit unsupported-method error. If `extension` matches
no extension, the error lists the application's extensions.

## Plugins


elemctl discovers external packages through `importlib.metadata` entry points.
Plugins are loaded on demand and do not need to be declared in the core
`pyproject.toml`. Private components can be distributed in a separate package.

**`elemctl.debug_adapter`**: a plugin package declares the directory of the 1C:Element debug adapter. Those are proprietary 1C jars and elemctl does not ship them. The entry-point value is a path, or a zero-argument callable that returns one. The path points to a directory holding a `repo/` subdirectory with the adapter jars.

**`elemctl.commands`**: a plugin package adds commands. The entry-point value
can be a `Command`, a list of commands or a zero-argument callable returning
either. Each declaration creates a CLI subcommand and an MCP tool with an
argument schema. Commands for internal systems and installations can be kept
in a separate package.

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
    # context.surface says which of them called: "cli" or "mcp"
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

### Plugin command results

A handler result must be JSON-serializable. The CLI writes it to stdout; MCP
returns it to the caller. An integer from 0 to 255 in `exit-code` sets the CLI
exit code. For example, a three-outcome command can return 0 (no differences),
1 (differences) or 2 (step failed).

A valid `exit-code` takes precedence over `ok`. If the field is missing or invalid,
such as a string, `true` or 300, `ok` is used: a dictionary with `"ok": false`
produces exit code 1, as `deploy` and `probe` reports do. MCP returns `exit-code`
with the rest of the result.

Do not use `sys.exit` in a handler to set the exit code. The same handler runs
inside the MCP server, where `sys.exit` would stop the server without answering the request.

`context.surface` contains `"cli"` or `"mcp"`. Use it to select different output
detail for the terminal and MCP. For compatibility with a core that lacks the
field, read `getattr(context, "surface", None)`.

### Plugin command arguments

Supported types are `str`, `int`, `float` and `bool` for flags. `env_file` is added
to the MCP tool automatically, so plugin commands can address other installations
in the same way as core tools.

A positional argument can have a CLI option alias:
`Argument("page", cli_alias="--page")` accepts `elemctl wiki-get 123` or
`elemctl wiki-get --page 123`. The MCP schema retains one `page` parameter;
`cli_alias` changes only command-line parsing. Using both forms together is
rejected. For a required argument, omitting both is also an error. Without
`cli_alias`, the argument remains positional.

`Argument("--file", multiple=True)` accepts multiple values:
`elemctl wiki-attach --file a.png --file b.png` passes `["a.png", "b.png"]`
to the handler in command-line order. If the option is absent, the declared
default is passed as a list, or `[]`. MCP uses an array of the declared type.
Without `multiple`, repeating a key with different values is rejected. A `bool`
flag cannot be repeatable. A repeatable argument's default must be a list, tuple or `None`.

Positional arguments can also accept multiple values:
`Argument("page", multiple=True, cli_alias="--page")` accepts
`elemctl wiki-get 123 456` or `elemctl wiki-get --page 123 --page 456`.
Both pass `["123", "456"]` to the handler. The forms cannot be mixed.
`required=True` requires at least one value. An optional argument without values
passes the declared default as a list, or `[]`. MCP retains one array parameter.

### Plugin compatibility

A command that conflicts with a core command name is not registered. A plugin
that fails to load, including one requiring a newer core, is skipped. These
plugins are reported on stderr and in `elemctl plugins`; the others remain available.

To support a core without repeatable arguments, check `hasattr(Argument, "multiple")`
before using them. Without the field, a plugin declaring it cannot load.
Some core versions provide `multiple` only for options: a repeatable positional
argument raises `PluginError` and excludes the plugin. Check that capability
using `getattr(plugins, "POSITIONAL_MULTIPLE", False)` from `elemctl.plugins`.

```bash
# the adapter path from the installed plugin (for the VS Code extension):
# {"path": "...", "found": true} or {"path": null, "found": false}
elemctl debug-adapter

# what the plugins bring – adapter directories and commands
elemctl plugins
```

The adapter itself, those proprietary 1C jars, is extracted from the 1C:Element distribution by `tools/extract_adapter.py`. Point `xbsl.debug.adapterPath` at the resulting directory by hand, or build the plugin package from it. The script is not shipped in the package distribution.

`ELEMCTL_NO_PLUGINS=1` disables plugin discovery. Only core capabilities are available.

## VS Code


A companion extension integrates elemctl into the editor:

- [XBSL](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl) (the
  [xbsl](https://github.com/keyfire/xbsl) project) – highlighting, linting, the form designer
  and the metadata tree. The *XBSL: deploy the project* button runs `elemctl deploy` as a
  terminal task and verifies the apply. The same extension debugs 1C:Element applications
  with the 1C:Element DAP adapter, whose session data comes from `elemctl apps debug`.
  Debugging used to be a separate *XBSL Debug* extension living in the elemctl repository.
  Since XBSL 0.57 it is part of the one extension, and the repository keeps only the
  elemctl side of it.

It is also published to [Open VSX](https://open-vsx.org/namespace/keyfire).
