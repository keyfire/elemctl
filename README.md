# Elemctl

**English** · [Русский](https://github.com/keyfire/elemctl/blob/main/README.ru.md)

**Documentation: [docs.keyfire.ru/elemctl](https://docs.keyfire.ru/elemctl/)**

A command-line tool, MCP server and Python library for managing applications on the **1C:Enterprise.Element** cloud platform (1cmycloud.com) through Console API v2.

elemctl covers an application's lifecycle on the platform without the web console: create an application, build a `.xasm`/`.xlib` build archive from project sources, upload the build, apply it to the application and make sure the apply actually happened (the platform can silently roll back), and manage development-environment branches, dumps and the technology version. The same engine is available in three ways: the `elemctl` command for the terminal and CI, an MCP server for AI agents (Claude Code and other MCP clients), and the `elemctl` Python module for your own scripts.

*elemctl is a CLI tool, MCP server and Python library for the 1C:Enterprise.Element (1cmycloud) Console API: manage applications, upload builds and deploy with honest apply verification. The CLI output is plain JSON.*

Development notes and updates (in Russian): the [1C × AI: engineering workshop](https://t.me/ceh_1c_ai) Telegram channel.

![How elemctl is wired](https://raw.githubusercontent.com/keyfire/elemctl/main/docs/architecture.png)

## Features

<!-- features:start -->

- **Applications**: list (with a client-side name filter and `--brief` cards), details, create, start, stop, delete, technology version, debug-session data (`apps debug`). Commands addressing one application accept its id or its exact name.
- **Projects and builds**: upload `.xasm`/`.xlib`, list builds, delete.
- **Build from sources**: package a project directory (`Проект.yaml` + modules) into a build archive with a manifest and git metadata. The version comes from the flag, the last build's counter or the CI run number in the environment (`CI_PIPELINE_IID` / `GITHUB_RUN_NUMBER` / `BUILD_NUMBER`), and the output carries it as a field. Descriptors written with English key spellings (`Name`/`Vendor`/`Version`) are read as well as Russian ones.
- **One-command deploy**: build -> upload -> apply -> restart -> **verification that the apply actually took effect**. Uncommitted changes of the project directory are reported (`dirty` in the report); `--require-clean` aborts on a dirty tree.
- **Compilation check without risking the application** (`elemctl probe`): the sources are compiled by the SERVER through a throwaway application, the errors come back with file, line and column, and the probe removes what it created. The working application is out of reach on purpose – `ELEMENT_APP_ID` and `ELEMENT_PROJECT_ID` are not used.
- **User lists**: the sign-in settings a control panel usually holds – self-registration and signing in with a login and a password (`elemctl user-lists`). The list is addressed by id, by presentation or by the application whose own list it is.
- **Development-environment branches**: list, create, bind to an application, merge.
- **Dumps**: create and check readiness.
- **MCP server**: the same operations exposed as tools for AI agents (Claude Code and other MCP clients).
- **Plugins**: `importlib.metadata` entry points – an external package supplies the platform debug adapter (`elemctl debug-adapter`) and commands of its own without bloating the core. One `Command` declaration becomes both a CLI subcommand and an MCP tool, so a command that knows about your own environment lives in your package rather than in a public core.
- **Self-update**: `elemctl self-update` – update the package by unpacking the wheel, even while `elemctl.exe` is held by a running MCP server (where plain pipx/pip would break the install).
- **In VS Code**: deploy and debugging live in the [XBSL](https://github.com/keyfire/xbsl) extension – it calls elemctl: `elemctl deploy` behind the deploy button, `elemctl apps debug` for the debug-session coordinates.

### Honest apply verification

A platform quirk: if a project apply fails, the platform **silently rolls back** the application to the previous build – the `Running` status says nothing about whether the deploy succeeded. `elemctl deploy` therefore does not trust the status and, after the deploy, checks:

1. application tasks with the `Error`/`Failed` status that started after the deploy began (old errors from the history are ignored);
2. the application's actual project version (`source.project-version`) – it must match the build that was just uploaded;
3. the application uri's availability via a health-check HTTP request (informational, the `uri-status` field in the report: 401/403 are normal for closed applications).

The `deploy` exit code is zero only if the build was actually applied.

<!-- features:end -->

## Installation

<!-- installation:start -->

```bash
pipx install elemctl            # or: pip install elemctl
pip install "elemctl[mcp]"      # with the MCP server
```

Python 3.10+ is required. The core and CLI have no external dependencies (standard library only).

<!-- installation:end -->

## Configuration

<!-- configuration:start -->

Connection credentials are taken from environment variables or from a `.env` file in the current directory (environment variables take priority):

| Variable | Purpose |
|---|---|
| `ELEMENT_BASE_URL` | the platform base URL, e.g. `https://1cmycloud.com` |
| `ELEMENT_CLIENT_ID` | Client-Id used to obtain a token |
| `ELEMENT_CLIENT_SECRET` | Client-Secret |
| `ELEMENT_APP_ID` | default application (optional) |
| `ELEMENT_PROJECT_ID` | default project (optional) |
| `ELEMENT_SPACE_ID` | default space (optional) |

Client-Id/Client-Secret are issued in the 1cmycloud control panel (the Console API integrations section). A file template is [.env.example](https://github.com/keyfire/elemctl/blob/main/.env.example).

### Behaviour of the tool

These are set through the environment only – a connection `.env` is not their place:

| Variable | Purpose |
|---|---|
| `ELEMCTL_LANG` | language of the messages and the help (`ru`, `en`); the `--lang` flag wins over it |
| `ELEMCTL_NO_PROXY` | set it to bypass the environment's proxy for every call (loopback and private addresses are bypassed anyway) |
| `ELEMCTL_NO_PLUGINS` | do not look for plugins: a run with the core capabilities only |

### The CI environment

The build declares no variables of its own, but it reads the ones CI sets itself – which is why a pipeline needs neither a version flag nor an edit of the sources:

| Variable | Purpose |
|---|---|
| `CI_PIPELINE_IID` | run number; the build version suffix comes from it when there is neither `--build-version` nor a previous build |
| `GITHUB_RUN_NUMBER` | the same, second in order |
| `BUILD_NUMBER` | the same, third in order (the first NUMERIC value wins) |
| `CI_COMMIT_BRANCH` | the branch name for the manifest when git is in a detached `HEAD` |
| `CI_COMMIT_REF_NAME` | the same, second in order |
| `GITHUB_REF_NAME` | the same, third in order; the value `HEAD` is discarded and the field stays empty |

<!-- configuration:end -->

## Quick start

<!-- quickstart:start -->

```bash
# list applications
elemctl apps list

# application details (status, uri, actual project version)
elemctl apps get <app-id>

# create the application only if it does not exist yet:
# {"id": ..., "created": true|false, "sign-in": ...} - the last field is the way in
elemctl apps ensure acme-crm-dev --project-id <project-id> --latest-build --wait

# full deploy cycle from sources with apply verification
elemctl deploy --app-id <app-id> --project-id <project-id> --project-dir acme/crm

# compile the sources on the server without touching the working application:
# ok, plus errors with file, line and column; cleans up after itself
elemctl probe --project-dir acme/crm

# debug-session data: {"debug-token": ..., "debug-address": ...}
# (debugging must be enabled on the server: config/debug.yml enabled: true)
elemctl apps debug <app-id>

# only build the .xasm archive, without uploading it anywhere
elemctl build --project-dir acme/crm --output ./dist

# parse a built archive: manifest, subsystems, global types with qualified names
elemctl inspect ./dist/e1c-CurrencyConverter-2.0.xlib

# forbid signing in by password and self-registration in the application's user list
elemctl user-lists password-login --app crm-dev --disable
elemctl user-lists self-registration --app crm-dev --disable

# merge changes from a development-environment branch
elemctl branches merge <branch-id>
```

All commands output JSON to stdout; progress of long-running operations goes to stderr. Errors are returned as a JSON object with an `error` field and exit code 1.

For the full list of commands: `elemctl --help`, and by group: `elemctl apps --help`, `elemctl deploy --help`, etc.

<!-- quickstart:end -->

## Language

<!-- language:start -->

Error and progress messages, and the `--help` text, come in Russian and English (the JSON result is language-neutral). The language is picked by `--lang ru|en` > the `ELEMCTL_LANG` env var > the system locale (`LC_ALL`, then `LANG`) > Russian; `--lang` is read before the parser is built, so `elemctl --lang en --help` prints English help.

<!-- language:end -->

## MCP server

<!-- mcp:start -->

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
| `list_builds` | list of a project's builds, newest first; `limit` (default 10, 0 – all), `brief` (the default) keeps id, versions, date, branch and commit |
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

A single environment is not a limit: every tool that talks to the platform takes an optional `env_file` - a path to another installation's `.env`. One server thus serves both the cloud and a local installation without a restart with different credentials. `list_apps` returns brief cards by default (id, name, status, uri, applied version): full cards of a whole space are tens of thousands of characters in an agent's response - pass `brief=false` for them; its `name` parameter filters by a case-insensitive substring on the client (the platform ignores the query parameter). `list_projects` behaves the same way (id, name, project kind, space, application count, deletion flag), and so does `list_builds` (id, versions, date, branch, commit) - which on top of that answers with the ten newest assemblies unless `limit` says otherwise (0 lifts the cut): a long-lived project holds assemblies by the thousand. `get_app`, `delete_app`, `start_app`, `stop_app` and `debug_info` accept the application id (UUID) or its exact name - a non-UUID value is resolved through the list, and several matches are an error rather than a guess. `create_app` and `ensure_app` add a `sign-in` field to the answer – the address and the account that gets into a freshly created application (a CONTROL PANEL one; the accounts of an external provider do not work there) – because an agent sees only the JSON.

<!-- mcp:end -->

## Plugins

<!-- plugins:start -->

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

<!-- plugins:end -->

## VS Code

<!-- vscode:start -->

A companion extension integrates elemctl into the editor:

- [XBSL](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl) (the
  [xbsl](https://github.com/keyfire/xbsl) project) – highlighting, linting, the form designer,
  the metadata tree, the *XBSL: deploy the project* button that runs `elemctl deploy` as a
  terminal task with the apply verification, and debugging 1C:Element applications with the
  platform's DAP adapter, whose session data comes from `elemctl apps debug`. Debugging used
  to be a separate *XBSL Debug* extension living in the elemctl repository; since XBSL 0.57 it
  is part of the one extension, and the repository keeps only the elemctl side of it.

It is also published to [Open VSX](https://open-vsx.org/namespace/keyfire).

<!-- vscode:end -->

## Use as a library

<!-- library:start -->

```python
from elemctl import Config, ElementClient
from elemctl.deploy import deploy_from_sources

client = ElementClient(Config.from_env())
apps = client.list_apps()

report = deploy_from_sources(
    client,
    app_id="...",
    project_id="...",
    project_dir="acme/crm",
    log=print,
)
assert report.ok, report.problems
```

A compilation check that does not touch the working application – the same cycle
the `probe` command runs:

```python
from elemctl.probe import probe_project

report = probe_project(client, project_dir="acme/crm", log=print)
for error in report.errors:
    print(f"{error['file']}:{error['line']}:{error['column']} {error['message']}")
assert report.ok, report.messages
```

<!-- library:end -->

## Build format

<!-- buildformat:start -->

`.xasm` (application) and `.xlib` (library) are a ZIP archive:

```
Assembly.yaml            # manifest: ProjectKind, Vendor, Name, Version, ...
{vendor}/{name}/...      # project files: .yaml, .xbsl, resources
```

The project directory must follow the `{repo}/{vendor}/{name}/Проект.yaml` layout – paths inside the archive are built relative to the repository root. The project kind (application/library) is determined by the `ВидПроекта` field in `Проект.yaml`. When an application references libraries whose source projects are present under the same repository root, their files are included in the application archive automatically (including transitive local dependencies). A referenced library that is not present locally remains an external platform dependency.

<!-- buildformat:end -->

## Limitations and status

<!-- limitations:start -->

- The tool is **unofficial** and not affiliated with 1C Company; the Console API may change without notice.
- Only the documented Console API v2 is used – the tool does not call or describe the platform console's internal APIs.
- Creating an application from `--project-id` alone produces, on some platform configurations, an empty skeleton without project data. The reliable path is a build source: `elemctl apps create <name> --project-id <id> --latest-build` (the `create_app` MCP tool substitutes the latest build automatically), followed by `elemctl deploy` after creation.
- An application created with an `Error` status is described by the platform only as "Неизвестная ошибка. Обратитесь к администратору"; the details - files, lines and columns of the compilation errors - live in the application's task. `apps create --wait` and `apps ensure` print them after the generic text, the way `deploy` and `verify` have long done, so there is no need to dig through the server log.
- There is no way to compile the sources without creating something on the platform: compilation is the server's and it happens when a build is applied. That is what `probe` is for – it takes the hit on a throwaway application instead of the working one. A probe run costs as long as creating an application does (minutes), so it belongs before a deploy or in CI, not in a per-keystroke loop.
- A platform project is identified by the `Vendor` + `Name` pair of the manifest, not by the `Ид` of `Проект.yaml`: a build upload without a project id lands in the project that already owns the pair, and a second project for the same pair is refused with a 409.
- A freshly created application is signed in to with a CONTROL PANEL account: it gets its OWN, empty user list, password sign-in is off and no account service is attached, so the accounts used to sign in to other applications do not work here – and neither connecting another application's user list nor enabling the local sign-in changes it. `apps create` and `apps ensure` say so themselves: the `sign-in` field of the answer plus the same on stderr.
- Deleted applications remain in the platform's list with a `Deleted` status and their former `id`, on which `apps get` and `deploy` return 404. `apps find` and `apps ensure` skip them; to restore the previous search behavior, use `apps find --include-deleted`.
- The platform will not let you delete an application that has unpublished changes in the development environment (HTTP 400 `FAILED_PRECONDITION`), and there is no forced deletion in the Console API – only through the control panel; elemctl points this out in the error message.
- Recreating an application (delete + create) changes its URL – external settings tied to the address (OIDC redirect, etc.) will need to be updated. There is no "soft" wipe of application data in the Console API; it is done in the management console.

<!-- limitations:end -->

## Origin and legal notes

The code is written from scratch against the platform's external interface specification – the process and guarantees are described in [ORIGIN.md](ORIGIN.md). Trademarks and the absence of affiliation with 1C Company are covered in the [NOTICE](NOTICE) file.

## License

[MIT](LICENSE)
