---
title: "Elemctl"
description: "A CLI, MCP server and library for the 1C:Element Console API: applications, builds from source, one-command deploys that verify the change actually landed, and a probe that compiles sources on the server without touching the working application."
sidebar:
  label: Home
  order: 1
---

A command-line tool, MCP server and Python library for managing **1C:Element** applications on the cloud service (1cmycloud.com) through Console API v2.

elemctl manages applications throughout their lifecycle. It creates applications,
builds `.xasm`/`.xlib` archives from project sources, uploads builds and applies
them. After deployment, `deploy` verifies the result: the server can roll back to the
previous build without reporting the failure. The `probe` command checks
compilation without changing the working application. Other commands manage
development-environment branches, dumps and the technology version.

The tool is available from the command line and CI, over MCP for AI agents, and
as the `elemctl` Python module for scripts.

Development notes and updates (in Russian): the [1C × AI: engineering workshop](https://t.me/ceh_1c_ai) Telegram channel.

![The CLI, the MCP server and the Python library share one engine that talks to the server over Console API v2. The deploy cycle goes sources, build, upload, apply, verify. The server rolls back a failed apply without reporting the rollback. A separate check confirms the result. The probe checks the same archive in a temporary application](https://raw.githubusercontent.com/keyfire/elemctl/main/docs/architecture.svg)

## Features


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

## Installation


```bash
pipx install elemctl            # or: pip install elemctl
pip install "elemctl[mcp]"      # with the MCP server
```

You need Python 3.10 or newer. The core and the CLI have no external dependencies: the standard library is enough.

## Quick start


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

## Nearby

- **[XBSL](https://docs.keyfire.ru/xbsl/)** – everything that happens to the sources before the
  deploy: a linter with autofixes, an LSP server, metadata scaffolding and a VS Code
  extension. Its editor-title button runs `elemctl deploy`.
- **[EDT-Bridge](https://docs.keyfire.ru/edt-bridge/)** – an MCP bridge into 1C:EDT
  for 1C:Enterprise configurations.

## Limitations and status


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
