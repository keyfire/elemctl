# elemctl

**English** · [Русский](https://github.com/keyfire/elemctl/blob/main/README.ru.md)

A command-line tool, MCP server and Python library for managing applications on the **1C:Enterprise.Element** cloud platform (1cmycloud.com) through Console API v2.

elemctl covers an application's lifecycle on the platform without the web console: create an application, build a `.xasm`/`.xlib` build archive from project sources, upload the build, apply it to the application and make sure the apply actually happened (the platform can silently roll back), and manage development-environment branches, dumps and the technology version. The same engine is available in three ways: the `elemctl` command for the terminal and CI, an MCP server for AI agents (Claude Code and other MCP clients), and the `elemctl` Python module for your own scripts.

*elemctl is a CLI tool, MCP server and Python library for the 1C:Enterprise.Element (1cmycloud) Console API: manage applications, upload builds and deploy with honest apply verification. The CLI output is plain JSON.*

Development notes and updates (in Russian): the [1C × AI: engineering workshop](https://t.me/ceh_1c_ai) Telegram channel.

## Features

- **Applications**: list, details, create, start, stop, delete, technology version, debug-session data (`apps debug`).
- **Projects and builds**: upload `.xasm`/`.xlib`, list builds, delete.
- **Build from sources**: package a project directory (`Проект.yaml` + modules) into a build archive with a manifest and git metadata, with automatic version increment.
- **One-command deploy**: build -> upload -> apply -> restart -> **verification that the apply actually took effect**.
- **Development-environment branches**: list, create, bind to an application, merge.
- **Dumps**: create and check readiness.
- **MCP server**: the same operations exposed as tools for AI agents (Claude Code and other MCP clients).
- **Plugins**: `importlib.metadata` entry points – an external package supplies the platform debug adapter (`elemctl debug-adapter`) without bloating the core.
- **Self-update**: `elemctl self-update` – update the package by unpacking the wheel, even while `elemctl.exe` is held by a running MCP server (where plain pipx/pip would break the install).
- **VS Code extension (debugging)**: a companion in [`editors/vscode`](editors/vscode) – debug 1C:Enterprise.Element (XBSL) applications in plain VS Code through the platform's built-in debug adapter; it obtains the debug-session coordinates via `elemctl apps debug`.

### Honest apply verification

A platform quirk: if a project apply fails, the platform **silently rolls back** the application to the previous build – the `Running` status says nothing about whether the deploy succeeded. `elemctl deploy` therefore does not trust the status and, after the deploy, checks:

1. application tasks with the `Error`/`Failed` status that started after the deploy began (old errors from the history are ignored);
2. the application's actual project version (`source.project-version`) – it must match the build that was just uploaded;
3. the application uri's availability via a health-check HTTP request (informational, the `uri-status` field in the report: 401/403 are normal for closed applications).

The `deploy` exit code is zero only if the build was actually applied.

## Installation

```bash
pipx install elemctl            # or: pip install elemctl
pip install "elemctl[mcp]"      # with the MCP server
```

Python 3.10+ is required. The core and CLI have no external dependencies (standard library only).

## Configuration

Connection credentials are taken from environment variables or from a `.env` file in the current directory (environment variables take priority):

| Variable | Purpose |
|---|---|
| `ELEMENT_BASE_URL` | the platform base URL, e.g. `https://1cmycloud.com` |
| `ELEMENT_CLIENT_ID` | Client-Id used to obtain a token |
| `ELEMENT_CLIENT_SECRET` | Client-Secret |
| `ELEMENT_APP_ID` | default application (optional) |
| `ELEMENT_PROJECT_ID` | default project (optional) |
| `ELEMENT_SPACE_ID` | default space (optional) |

Client-Id/Client-Secret are issued in the 1cmycloud control panel (the Console API integrations section). A file template is [.env.example](.env.example).

## Quick start

```bash
# list applications
elemctl apps list

# application details (status, uri, actual project version)
elemctl apps get <app-id>

# create the application only if it does not exist yet: {"id": ..., "created": true|false}
elemctl apps ensure acme-crm-dev --project-id <project-id> --latest-build --wait

# full deploy cycle from sources with apply verification
elemctl deploy --app-id <app-id> --project-id <project-id> --project-dir acme/crm

# debug-session data: {"debug-token": ..., "debug-address": ...}
# (debugging must be enabled on the server: config/debug.yml enabled: true)
elemctl apps debug <app-id>

# only build the .xasm archive, without uploading it anywhere
elemctl build --project-dir acme/crm --output ./dist

# parse a built archive: manifest, subsystems, global types with qualified names
elemctl inspect ./dist/e1c-CurrencyConverter-2.0.xlib

# merge changes from a development-environment branch
elemctl branches merge <branch-id>
```

All commands output JSON to stdout; progress of long-running operations goes to stderr. Errors are returned as a JSON object with an `error` field and exit code 1.

For the full list of commands: `elemctl --help`, and by group: `elemctl apps --help`, `elemctl deploy --help`, etc.

## Language

Error and progress messages, and the `--help` text, come in Russian and English (the JSON result is language-neutral). The language is picked by `--lang ru|en` > the `ELEMCTL_LANG` env var > the system locale > Russian; `--lang` is read before the parser is built, so `elemctl --lang en --help` prints English help.

## MCP server

The server exposes platform operations as MCP tools (stdio transport):

```bash
pip install "elemctl[mcp]"
claude mcp add elemctl -- elemctl mcp
```

The server reads connection credentials from the same `ELEMENT_*` variables / `.env`. Among the tools: `list_apps`, `get_app`, `deploy` (with an `ok` field in the response), `verify_deploy`, `list_builds`, `merge_branch` and others.

A single environment is not a limit: every tool that talks to the platform takes an optional `env_file` - a path to another installation's `.env`. One server thus serves both the cloud and a local installation without a restart with different credentials. `list_apps` returns brief cards by default (id, name, status, uri, applied version): full cards of a whole space are tens of thousands of characters in an agent's response - pass `brief=false` for them.

## Plugins

elemctl discovers external packages through `importlib.metadata` entry points: it declares nothing about plugins in its own `pyproject.toml` and reads them on demand. This keeps non-publishable vendor artifacts in a separate package while the elemctl core stays clean and public.

One group is currently supported – **`elemctl.debug_adapter`**: a plugin package declares the directory of the platform debug adapter (proprietary 1C jars, not shipped with elemctl). The entry-point value is a path or a zero-argument callable returning a path; the path points to a directory that contains a `repo/` subdirectory with the adapter jars.

```toml
# a plugin package's pyproject.toml
[project.entry-points."elemctl.debug_adapter"]
name = "my_package:adapter_root"     # () -> Path to the directory containing repo/
```

```bash
# the adapter path from the installed plugin (for the VS Code extension):
# {"path": "...", "found": true} or {"path": null, "found": false}
elemctl debug-adapter

# which plugins are visible – install diagnostics
elemctl plugins
```

The adapter itself (proprietary 1C jars) is extracted from the platform distribution by `tools/extract_adapter.py` – into a directory for a manual `xbslDebug.adapterPath`, or for building the plugin package. The script is not shipped in the package distribution.

Plugin discovery is disabled by `ELEMCTL_NO_PLUGINS=1` (a run with the core capabilities only).

## VS Code

Two companion extensions integrate elemctl into the editor:

- [XBSL](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl) (the
  [xbsl-lint](https://github.com/keyfire/xbsl-lint) project) – highlighting, linting, a form
  preview, and the *XBSL: deploy the project* button that runs `elemctl deploy` as a terminal
  task with the apply verification.
- [XBSL Debug](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl-debug) (lives
  in this repository, [`editors/vscode`](editors/vscode)) – debugging 1C:Element applications
  with the platform's DAP adapter; the debug session data comes from `elemctl apps debug`.

Both are also published to [Open VSX](https://open-vsx.org/namespace/keyfire).

## Use as a library

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

## Build format

`.xasm` (application) and `.xlib` (library) are a ZIP archive:

```
Assembly.yaml            # manifest: ProjectKind, Vendor, Name, Version, ...
{vendor}/{name}/...      # project files: .yaml, .xbsl, resources
```

The project directory must follow the `{repo}/{vendor}/{name}/Проект.yaml` layout – paths inside the archive are built relative to the repository root. The project kind (application/library) is determined by the `ВидПроекта` field in `Проект.yaml`.

## Limitations and status

- The tool is **unofficial** and not affiliated with 1C Company; the Console API may change without notice.
- Only the documented Console API v2 is used – the tool does not call or describe the platform console's internal APIs.
- Creating an application from `--project-id` alone produces, on some platform configurations, an empty skeleton without project data. The reliable path is a build source: `elemctl apps create <name> --project-id <id> --latest-build` (the `create_app` MCP tool substitutes the latest build automatically), followed by `elemctl deploy` after creation.
- An application created with an `Error` status is described by the platform only as "Неизвестная ошибка. Обратитесь к администратору"; the details - files, lines and columns of the compilation errors - live in the application's task. `apps create --wait` and `apps ensure` print them after the generic text, the way `deploy` and `verify` have long done, so there is no need to dig through the server log.
- Deleted applications remain in the platform's list with a `Deleted` status and their former `id`, on which `apps get` and `deploy` return 404. `apps find` and `apps ensure` skip them; to restore the previous search behavior, use `apps find --include-deleted`.
- The platform will not let you delete an application that has unpublished changes in the development environment (HTTP 400 `FAILED_PRECONDITION`), and there is no forced deletion in the Console API – only through the control panel; elemctl points this out in the error message.
- Recreating an application (delete + create) changes its URL – external settings tied to the address (OIDC redirect, etc.) will need to be updated. There is no "soft" wipe of application data in the Console API; it is done in the management console.

## Origin and legal notes

The code is written from scratch against the platform's external interface specification – the process and guarantees are described in [ORIGIN.md](ORIGIN.md). Trademarks and the absence of affiliation with 1C Company are covered in the [NOTICE](NOTICE) file.

## License

[MIT](LICENSE)
