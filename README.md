# Elemctl

**English** · [Русский](https://github.com/keyfire/elemctl/blob/main/README.ru.md)

**Documentation: [docs.keyfire.ru/elemctl](https://docs.keyfire.ru/elemctl/)**

A command-line tool, MCP server and Python library for managing applications on the **1C:Enterprise.Element** cloud platform (1cmycloud.com) through Console API v2.

elemctl runs an application's whole life on the platform, and you never have to open the web console. It creates the application, builds a `.xasm`/`.xlib` archive from project sources, uploads that build and applies it. Then it checks that the apply really happened, because the platform can roll back without saying so. A probe checks compilation and leaves the working application alone. Other commands handle development-environment branches, dumps and the technology version.

One engine, three ways to reach it. The `elemctl` command works in a terminal and in CI. The MCP server serves AI agents: Claude Code and other MCP clients. The `elemctl` Python module goes into scripts of your own.

*elemctl is a CLI tool, MCP server and Python library for the 1C:Enterprise.Element (1cmycloud) Console API: manage applications, upload builds, deploy with a verified apply and check compilation with a probe. The CLI output is plain JSON.*

Development notes and updates (in Russian): the [1C × AI: engineering workshop](https://t.me/ceh_1c_ai) Telegram channel.

![How elemctl is wired](https://raw.githubusercontent.com/keyfire/elemctl/main/docs/architecture.png)

## Features

<!-- features:start -->

- **Applications**: list, view details, create, start, stop and delete. Read the
  technology version and debug-session data (`apps debug`). Save the application
  build with `apps export` or an applied extension build with `apps export-extension`.
  Extension export requires Console API 2.1. Name filtering runs on the client;
  `--brief` selects short cards. Address an application by its id or exact name.
- **Projects and builds**: upload `.xasm`/`.xlib` archives, list and delete builds.
- **Build from sources**: package a directory containing `Проект.yaml` and modules
  into an archive with a manifest and git metadata. The version is taken from an
  explicit flag, the latest build counter or a CI run number: `CI_PIPELINE_IID`,
  `GITHUB_RUN_NUMBER`, `BUILD_NUMBER`. It is also included in the command result.
  Both Russian descriptor keys and English `Name`/`Vendor`/`Version` are supported.
  Applications, libraries and extensions use the same build process. An extension
  uses the manifest version required by the server to process it.
- **One-command deploy**: build -> upload -> apply -> restart -> **verify the apply**.
  Uncommitted project changes are reported in `dirty`. With `--require-clean`, the
  command stops if the working tree contains such changes.
- **Compilation check** (`elemctl probe`): compile sources on the server in a temporary
  application. Errors include the file, line and column. Objects created for the
  check are deleted afterwards. The working application is unchanged:
  `ELEMENT_APP_ID` and `ELEMENT_PROJECT_ID` are not used for this check.
- **User lists** (`elemctl user-lists`): configure self-registration and password sign-in.
  Address a list by its id, presentation or associated application.
- **Development-environment branches**: list, create, bind to an application and merge.
- **Dumps**: create and check readiness.
- **MCP server**: elemctl operations are available as tools for AI agents, including
  Claude Code and other MCP clients.
- **Plugins**: external packages are discovered through `importlib.metadata` entry
  points. They can provide the 1C:Element debug adapter (`elemctl debug-adapter`)
  and additional commands. Each `Command` declaration produces a CLI subcommand
  and an MCP tool. Environment-specific commands can be kept in a separate package.
- **Self-update**: `elemctl self-update` unpacks the wheel to update the package,
  including when `elemctl.exe` is in use. Updating with pipx or pip in that case
  can damage the installation. `--stop-holders` stops MCP servers using the package;
  commands running in other sessions continue.
- **In VS Code**: use the [XBSL](https://github.com/keyfire/xbsl) extension for deployment
  and debugging. The deploy button calls `elemctl deploy`; debug-session data is
  requested with `elemctl apps debug`.

### Checking that the build was applied

When applying a project fails, the 1C:Element server rolls the application back to
the previous build without reporting the rollback. The resulting status can be
`Running`, so the status alone cannot confirm deployment. `elemctl deploy` checks:

1. Application tasks with an `Error` or `Failed` status started after deployment
   began. Earlier errors are ignored.
2. The actual project version in `source.project-version`. It must match the uploaded build.
3. The application uri with an HTTP health request. The result is recorded in
   `uri-status` and does not affect deployment success. Responses 401 and 403 are
   valid for applications that require authentication.

The `deploy` exit code is zero only after the build apply has been confirmed.

<!-- features:end -->

## Installation

<!-- installation:start -->

```bash
pipx install elemctl            # or: pip install elemctl
pip install "elemctl[mcp]"      # with the MCP server
```

You need Python 3.10 or newer. The core and the CLI have no external dependencies: the standard library is enough.

<!-- installation:end -->

## Configuration

<!-- configuration:start -->

elemctl takes the connection credentials from environment variables or from a `.env` file in the current directory. Environment variables take precedence over values in the file.

| Variable | Purpose |
|---|---|
| `ELEMENT_BASE_URL` | the server base URL starting with `http://` or `https://`, e.g. `https://1cmycloud.com` |
| `ELEMENT_CLIENT_ID` | Client-Id used to obtain a token |
| `ELEMENT_CLIENT_SECRET` | Client-Secret |
| `ELEMENT_APP_ID` | default application (optional) |
| `ELEMENT_PROJECT_ID` | default project (optional) |
| `ELEMENT_SPACE_ID` | default space (optional) |
| `ELEMENT_CA_FILE` | additional PEM CA bundle for a private cloud (optional) |
| `ELEMENT_TLS_STRICT` | strict RFC 5280 certificate checks; `true` by default |
| `ELEMENT_TLS_VERIFY` | certificate and hostname verification; `true` by default |

Client-Id and Client-Secret are issued in the 1cmycloud control panel, in the Console API integrations section. A file template is [.env.example](https://github.com/keyfire/elemctl/blob/main/.env.example).

### Configuring with `.env`

Copy the template into the directory from which you will run `elemctl`:

```bash
cp .env.example .env
```

Then fill in at least the server address, Client-Id and Client-Secret:

```dotenv
ELEMENT_BASE_URL=https://1cmycloud.com
ELEMENT_CLIENT_ID=client-id
ELEMENT_CLIENT_SECRET=client-secret
```

Without `--env-file`, the tool looks for a file named exactly `.env` in the
**current working directory**. That is not necessarily the project directory,
and not the directory `elemctl` is installed into. The `elemctl` repository
excludes `.env` from Git. If you create one in another repository, add `.env`
to its `.gitignore` to keep credentials out of commits and logs.

If the configuration is stored elsewhere, specify its path. An absolute path is
more reliable for the MCP server, background jobs and CI:

```bash
elemctl --env-file /opt/elemctl/cloud.env apps list
```

The option is also accepted after the command:

```bash
elemctl apps list --env-file /opt/elemctl/cloud.env
```

A relative path is resolved from the current working directory. Separate files
allow connections to several installations without changing process variables:

```bash
elemctl --env-file ./env/public-cloud.env apps list
elemctl --env-file ./env/local-cloud.env apps list
```

Example for a local cloud with a trusted but legacy internal CA that Python 3.13
rejects under strict RFC 5280 checks:

```dotenv
ELEMENT_BASE_URL=https://cloud.internal.example
ELEMENT_CLIENT_ID=client-id
ELEMENT_CLIENT_SECRET=client-secret
ELEMENT_TLS_STRICT=false
```

For an internal CA that is trusted but rejected by Python 3.13 with
`Basic Constraints of CA cert not marked critical`, set
`ELEMENT_TLS_STRICT=false`. Certificate-chain, validity, signature and hostname
verification all stay on. Only OpenSSL's strict RFC 5280 profile is relaxed.
Where you can, fix or reissue the CA certificate instead.

Use `ELEMENT_CA_FILE=/path/to/internal-ca.pem` when the private CA is not in the
system trust store. `ELEMENT_TLS_VERIFY=false` turns off both certificate and
hostname verification. It is a last resort, and only for an isolated test
network. With verification off, every command prints a warning to stderr while
stdout contains only the response, preserving valid JSON for pipeline processing. Boolean
values accept `true`/`false`, `yes`/`no`, `on`/`off`, or `1`/`0`.

`ELEMCTL_NO_PROXY` sends requests without the environment's proxy. Use it when
an internal address is unreachable through the proxy or the proxy replaces the
server certificate. TLS verification remains enabled. If the direct connection
fails with `CERTIFICATE_VERIFY_FAILED`, configure a trusted CA or the `ELEMENT_TLS_*`
options.

`ELEMCTL_NO_PROXY` can also be set in the connection's `.env` file. An
environment variable takes precedence when both are present. This allows one MCP
server to serve several installations through `env_file`. The server handles
one call at a time, and each file's setting applies only to requests for its
installation.

File changes take effect on the next call without restarting the server if the
file's modification time or size changes. The client cache key includes
`env_file` and these two attributes.
When `env_file` is absent, the server uses its own `--env-file` or the `.env` in
the current working directory. Changing access permissions without changing the
file's modification time or size does not refresh the cached client.

This behavior applies to `elemctl mcp`. When an application passes a `Config`
object directly to the server without a file, the configuration remains fixed
for the lifetime of the process.

### Behaviour of the tool

`ELEMCTL_LANG`, `ELEMCTL_NO_PLUGINS`, `ELEMCTL_DATA_DIR` and `ELEMCTL_REGISTRY_LIMIT`
are read only from environment variables. They are not read from a connection's
`.env` file. `ELEMCTL_NO_PROXY` supports both sources, as described above.

| Variable | Purpose |
|---|---|
| `ELEMCTL_LANG` | language of the messages and the help (`ru`, `en`); the `--lang` flag takes precedence |
| `ELEMCTL_NO_PROXY` | set it to bypass the environment's proxy for every call (loopback and private addresses are bypassed anyway); also readable from the stand's `.env` |
| `ELEMCTL_NO_PLUGINS` | do not look for plugins: work with the core capabilities only |
| `ELEMCTL_DATA_DIR` | the directory of the local registry of uploads; by default `%LOCALAPPDATA%\elemctl` on Windows and `$XDG_STATE_HOME/elemctl` (`~/.local/state/elemctl`) elsewhere |
| `ELEMCTL_REGISTRY_LIMIT` | how many uploads the local registry of uploads keeps; 1000 by default, `0` keeps every one |

### The local registry of uploads

The server stores the commit of a build uploaded to an existing project.
elemctl records additional upload details in the local `uploads.jsonl` file.
Each record contains the build and project identifiers, version, branch, commit,
uncommitted-change status, source directory, installation, command and upload
time. The registry is updated by `deploy`, `builds upload` and `probe`.

`builds list --brief` and `apps get` use the registry to fill in a branch or
commit missing from the build card on the server. The source of each value is
reported. The local file does not contain builds uploaded from another machine,
from CI or by a version of elemctl without a registry.

A registry write failure produces a warning and does not cancel the upload.
The file can be deleted; only this machine's upload history is removed. By
default, the registry keeps the last 1000 uploads. `ELEMCTL_REGISTRY_LIMIT`
sets another limit; `0` removes it. When the number of records exceeds the
limit by 10%, the next upload trims the file to the most recent records.

### The CI environment

The build uses standard CI variables. When these are set, a version can be determined without a separate flag or source changes:

| Variable | Purpose |
|---|---|
| `CI_PIPELINE_IID` | run number; the build version suffix comes from it when there is neither `--build-version` nor a previous build |
| `GITHUB_RUN_NUMBER` | the same, second in order |
| `BUILD_NUMBER` | the same, third in order; the first numeric value is used |
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
# --wait waits for the application AND verifies the build it really runs
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

Every command writes JSON to stdout, and progress of long-running operations goes to stderr. An error comes back as a JSON object with an `error` field and exit code 1.

The `--json` flag guarantees machine-readable output and can be used in any
position. While the command runs, its stdout is redirected to stderr. The real
stdout therefore contains only the JSON result; plugin and library output goes
to stderr. Parse the complete stream with `json.load`. With `--json`, error
messages go to stderr and stdout is empty on failure.

The `--quiet` flag disables progress messages and warnings on stderr. It can be
used in any position. Result and error formats and their destination streams
remain unchanged. When the two streams are combined, only the result is printed.

`apps list` and `builds list` print count and truncation notes after the result.
Other stderr messages have no guaranteed order. Parse stdout separately from stderr.

For the full list of commands run `elemctl --help`, and for one group `elemctl apps --help`, `elemctl deploy --help` and so on.

<!-- quickstart:end -->

## Language

<!-- language:start -->

Error and progress messages, and the `--help` text, come in Russian and English. The JSON result is language-neutral. The language is picked in this order: `--lang ru|en`, then the `ELEMCTL_LANG` env var, then the system locale (`LC_ALL`, then `LANG`), then Russian. `--lang` is read before the parser is built, so `elemctl --lang en --help` prints English help.

<!-- language:end -->

## MCP server

<!-- mcp:start -->

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

<!-- mcp:end -->

## Plugins

<!-- plugins:start -->

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

<!-- plugins:end -->

## VS Code

<!-- vscode:start -->

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

`list_apps()` returns applications that are not marked as deleted. Deleted
applications remain in the server list with status `Deleted`; a long-running
installation can contain hundreds of these entries. Pass `include_deleted=True`
for the complete list. `list_apps_counted()` returns the same list in `items`
and the `total`, `live` and `shown` counters used by the CLI and MCP tool.

To check compilation without touching the working application, run the same
cycle the `probe` command does:

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

`.xasm` for an application and `.xlib` for a library are both ZIP archives:

```
Assembly.yaml            # manifest: ProjectKind, Vendor, Name, Version, ...
{vendor}/{name}/...      # project files: .yaml, .xbsl, resources
```

The project directory must follow the `{repo}/{vendor}/{name}/Проект.yaml` layout, because paths inside the archive are built relative to the repository root. The `ВидПроекта` field in `Проект.yaml` specifies whether the project is an application or a library. When an application references libraries whose source projects sit under the same repository root, their files and transitive local dependencies are included in the application archive. A referenced library whose sources are not present locally remains an external dependency of the 1C:Element application.

<!-- buildformat:end -->

## Limitations and status

<!-- limitations:start -->

- The tool is **unofficial** and is not affiliated with 1C Company. The Console API
  may change without notice.
- elemctl uses the documented Console API v2. Internal management-console APIs are
  neither used nor described.
- With some server configurations, an application created from `--project-id`
  alone contains no project data. To create it from a build, run
  `elemctl apps create <name> --project-id <id> --latest-build`. The `create_app`
  MCP tool selects the latest build automatically. Run `elemctl deploy` after creation.
- When creation results in `Error`, the server returns the general message
  "Неизвестная ошибка. Обратитесь к администратору". Compilation error files,
  lines and columns are recorded in the application task. `apps create --wait`
  and `apps ensure` print those details after the general message, as `deploy`
  and `verify` do. After a failed apply, rollback can leave the application
  `Running`. Therefore `--wait` also verifies the applied build and returns exit
  code 1 if it differs from the requested build. `--no-verify` disables that
  check and only waits for the application.
- Compilation runs on the server when a build is applied, so it requires an
  application. `probe` creates a temporary application without changing the
  working one. A check takes several minutes, comparable to creating an
  application. Run it before deployment or in CI.
- A 1C:Element project is identified by `Ид` in `Проект.yaml`. A build uploaded
  without a project id is assigned to the project with that `Ид`, regardless of
  the manifest's `Vendor` + `Name` pair. The project is renamed using the build
  metadata. `builds upload` reports the selected project and warns about a rename.
  If a new `Ид` uses a pair already assigned to another project, the server returns 409.
- Sign in to a new application with a control-panel account. The application has
  its own empty user list, password sign-in is disabled and no account service
  is connected. Accounts from other applications are unavailable even after
  connecting their user list and enabling local sign-in. `apps create` and
  `apps ensure` describe the sign-in method in `sign-in` and in stderr.
- Deleted applications remain in the server list with status `Deleted` and
  their former `id`. `apps get` and `deploy` return 404 for that id. `apps find`
  and `apps ensure` skip deleted applications. Use `apps find --include-deleted`
  to include them in a search.
- If the development environment contains unpublished changes, deleting the
  application through the API returns HTTP 400 `FAILED_PRECONDITION`. The Console
  API has no forced deletion. Use the control panel; elemctl also describes this
  condition in the error message.

- Recreating an application, meaning delete and then create, changes its URL. External settings tied to that address, an OIDC redirect for instance, will need updating. The Console API has no "soft" wipe of application data; that is done in the management console.

<!-- limitations:end -->

## Origin and legal notes

The code is written from scratch against the platform's external interface specification. [ORIGIN.md](ORIGIN.md) describes the process and the guarantees. Trademarks and the absence of affiliation with 1C Company are covered in the [NOTICE](NOTICE) file.

## License

[MIT](LICENSE)
