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
| `list_apps` | list of applications; the deleted ones are hidden unless `include_deleted` asks for them, `name` filters by a substring of the name on the client and `status` by the status word; the answer carries the counters and a `summary` line next to `applications`, `brief` (the default) keeps id, name, status, uri and the applied version |
| `find_app` | find an application by its exact name: the id and a `found` flag; deleted ones are skipped unless `include_deleted` is set |
| `get_app` | application card: status, uri, the actual project version; `applied-build` carries the branch and the commit of the build it runs, from the build card or from the local registry of uploads |
| `create_app` | create an application; with only a `project_id` the source is the project's latest build. The answer carries `sign-in` – the way in; `verify` waits for the application and checks the build it really runs |
| `ensure_app` | create an application by name only if it does not exist yet; an existing one is not recreated (`created: false`); `verify` checks the build the application really runs |
| `start_app` | start the application |
| `stop_app` | stop the application |
| `delete_app` | delete the application. This cannot be undone: the data is lost, and a recreated application gets a different URL |
| `list_app_tasks` | tasks of the applications; `app_id` is an optional filter |
| `debug_info` | debug-session data: `debug-token` and `debug-address` (debugging must be enabled on the server) |
| `list_spaces` | list of spaces |
| `list_projects` | list of projects; `name` filters by a substring of the name on the client, the deleted ones are hidden unless `include_deleted` is set; `brief` (the default) – id, name, project kind, space, application count, deletion flag |
| `list_builds` | a project's builds, newest first; the answer is an object `{total, shown, summary, builds}`; `limit` (default 10, 0 – all), `brief` (the default) keeps id, versions, date, branch and commit, and names where the branch and the commit came from: the card or the local registry of uploads |
| `get_build` | the whole card of one build; `version` is the build's version (`1.0-42`), an id is accepted too and resolved through the listing |
| `build_assembly` | build a `.xasm`/`.xlib` archive from the sources locally (does not talk to the platform) |
| `inspect_assembly` | parse a built archive: manifest, project properties, subsystems and global types with qualified names (local) |
| `deploy` | the whole cycle from sources, with a check that the build was applied; the verdict is `ok`, the details are `problems` and `log`; a server that is still starting is waited out for up to `server_start_timeout` seconds (900 by default) |
| `probe` | check the compilation with the server compiler without touching the working application; errors with file, line and column, cleans up after itself |
| `apply_build` | apply an uploaded build to the application by its id |
| `verify_deploy` | verify the apply actually took effect: failed tasks, the applied build, the availability of the uri |
| `list_user_lists` | user lists; `name` filters by a substring of the presentation |
| `configure_user_list` | self-registration and password sign-in; without the flags it only reports the current state |
| `list_branches` | list of development-environment branches; the `project_id` and `name` filters are optional |
| `merge_branch` | accept the changes of a development-environment branch |
| `debug_adapter` | the path to the platform debug adapter from a plugin; a missing plugin is an answer (`found: false`), not an error (local) |

The tools a plugin brings stand next to these, described below.

A single environment is not a limit. Every tool that talks to the platform takes an optional `env_file`, a path to another installation's `.env`. One server then serves both the cloud and a local installation, with no restart under different credentials.

`list_apps` returns brief cards by default: id, name, status, uri, applied version. Full cards of a whole space run to tens of thousands of characters in an agent's response, so ask for them with `brief=false`. The `name` parameter filters by a case-insensitive substring, and it does so on the client because the platform ignores the query parameter. The `status` parameter filters by the whole status word. Deleted applications stay hidden until `include_deleted` asks for them: a stand a few months old answers with hundreds of cards of which a handful are alive. Nothing is cut silently. The answer carries `total` (how many cards the platform gave), `live` (how many of those are not deleted), `shown` and a ready `summary` line such as "7 live of 324", with the cards themselves under `applications`.

`list_projects` behaves the same way and returns id, name, project kind, space, application count and the deletion flag. Its `name` filters by a substring too, and projects marked deleted stay hidden until `include_deleted` is set: a stand a few months old keeps hundreds of them against a handful of live ones.

`list_builds` answers with brief cards as well, holding id, versions, date, branch and commit, and with the ten newest builds unless `limit` says otherwise; 0 lifts the cut. The cards sit under `builds`, next to the counters `total` (how many builds the platform returned) and `shown`, plus a `summary` line. The platform's listing is not the project's whole history: it deletes the builds nobody uses, whatever their age. The build an application runs, the project's first build and a release build stay. The listing has no pages, and `summary` says plainly that what you see is the remainder of the history. It reads that off the answer itself: the platform hands out the numbers of one base version consecutively, so a number missing from the listing is a build already taken away.

`get_build` hands back one card whole and is addressed by the build version. An id is accepted as well and looked up in the listing, because the address the method understands is the version, not the id of a card.

`get_app`, `delete_app`, `start_app`, `stop_app` and `debug_info` accept the application id (UUID) or its exact name. A value that is not a UUID is resolved through the list, and several matches are an error rather than a guess.

`create_app` and `ensure_app` add a `sign-in` field to the answer: the address and the account that gets into a freshly created application. That account comes from the control panel, the accounts used in other applications do not work there, and an agent sees only the JSON. The `verify` parameter of both waits for the application and checks that it really runs the build that was asked for: the platform rolls a failed apply back without a word, and a created application used to be reported ready on trust. The report lands in the `verify` field of the answer. The waiting costs minutes, so such a call belongs in a background `elemctl` run. A wait that breaks off does not lose the application: the answer keeps its id, and the `wait-error` field says what broke.

A `version_id` the project no longer lists is refused before anything is created. The platform deletes the builds nobody uses and answers a create from a deleted one with a bare 400. The refusal names that cause and the build a running application of the project runs. The project is `project_id`, or the stand's `ELEMENT_PROJECT_ID` when the parameter is empty.

## Plugins


elemctl discovers external packages through `importlib.metadata` entry points. Its own `pyproject.toml` declares nothing about plugins, and it reads them on demand. Non-publishable vendor artifacts then live in a separate package, and the elemctl core stays clean and public.

**`elemctl.debug_adapter`**: a plugin package declares the directory of the platform debug adapter. Those are proprietary 1C jars and elemctl does not ship them. The entry-point value is a path, or a zero-argument callable that returns one. The path points to a directory holding a `repo/` subdirectory with the adapter jars.

**`elemctl.commands`**: a plugin package brings commands of its own. The entry-point value is a `Command`, a list of them, or a zero-argument callable returning either. One declaration covers both surfaces: elemctl builds a CLI subcommand and an MCP tool with a proper schema out of it, and knows nothing about what the command does. That is where a command belongs when it is about your own environment: internal circuits, other systems, your stands. A public core is no place for it.

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

The result of a handler has to be JSON-serializable: the CLI prints it, the MCP tool returns it. The exit code of the CLI comes from the result too. An integer from 0 to 255 in the `exit-code` field becomes the exit code as it is, so a command with three outcomes can hand a script "no differences", "differences" and "a step failed" as 0, 1 and 2. Without that field, a dict result with `"ok": false` ends with exit code 1, the same convention the `deploy` and `probe` reports follow. When the field disagrees with `ok`, the field decides. A string, `true` or 300 is not a code, and the CLI goes by `ok` instead. The MCP tool returns the field with the rest of the result. Do not call `sys.exit` in a handler to get a code: the same function runs inside the MCP server, where the call would never be answered and the server would stop. Argument types are `str`, `int`, `float` and `bool` for a flag. elemctl adds `env_file` to the MCP tool itself, so a plugin command reaches other environments exactly like the core tools do. A command may not take over a name the core already occupies: such a command is left out. So is a plugin that fails to load, one written for a newer core for instance. elemctl names them on stderr and in `elemctl plugins` and keeps working with the rest.

A positional argument may add a CLI-only key synonym: `Argument("page", cli_alias="--page")` accepts both `elemctl wiki-get 123` and `elemctl wiki-get --page 123`. The MCP tool schema keeps the one `page` parameter it always had – `cli_alias` only changes what the CLI parser accepts, nothing about the declared arguments themselves. The two forms are mutually exclusive: the parser refuses both at once, and refuses neither when the argument is required. A plugin that declares no `cli_alias` behaves exactly as before.

```bash
# the adapter path from the installed plugin (for the VS Code extension):
# {"path": "...", "found": true} or {"path": null, "found": false}
elemctl debug-adapter

# what the plugins bring – adapter directories and commands
elemctl plugins
```

The adapter itself, those proprietary 1C jars, is extracted from the platform distribution by `tools/extract_adapter.py`. Point `xbsl.debug.adapterPath` at the resulting directory by hand, or build the plugin package from it. The script is not shipped in the package distribution.

`ELEMCTL_NO_PLUGINS=1` turns plugin discovery off: only the core capabilities are left.

## VS Code


A companion extension integrates elemctl into the editor:

- [XBSL](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl) (the
  [xbsl](https://github.com/keyfire/xbsl) project) – highlighting, linting, the form designer
  and the metadata tree. The *XBSL: deploy the project* button runs `elemctl deploy` as a
  terminal task and verifies the apply. The same extension debugs 1C:Element applications
  with the platform's DAP adapter, whose session data comes from `elemctl apps debug`.
  Debugging used to be a separate *XBSL Debug* extension living in the elemctl repository.
  Since XBSL 0.57 it is part of the one extension, and the repository keeps only the
  elemctl side of it.

It is also published to [Open VSX](https://open-vsx.org/namespace/keyfire).
