---
title: "Elemctl"
description: "A CLI, MCP server and library for the 1C:Element Console API: applications, builds from source, one-command deploys that verify the change actually landed, and a probe that compiles sources on the server without touching the working application."
sidebar:
  label: Home
  order: 1
---

A command-line tool, MCP server and Python library for managing applications on the **1C:Enterprise.Element** cloud platform (1cmycloud.com) through Console API v2.

elemctl runs an application's whole life on the platform, and you never have to open the web console. It creates the application, builds a `.xasm`/`.xlib` archive from project sources, uploads that build and applies it. Then it checks that the apply really happened, because the platform can roll back without saying so. A probe checks compilation and leaves the working application alone. Other commands handle development-environment branches, dumps and the technology version.

One engine, three ways to reach it. The `elemctl` command works in a terminal and in CI. The MCP server serves AI agents: Claude Code and other MCP clients. The `elemctl` Python module goes into scripts of your own.

Development notes and updates (in Russian): the [1C × AI: engineering workshop](https://t.me/ceh_1c_ai) Telegram channel.

![The CLI, the MCP server and the Python library share one engine that talks to the platform over Console API v2. The deploy cycle goes sources, build, upload, apply, verify. The platform rolls a failed apply back without saying so, so only the verification step shows what happened. The probe puts the same archive through a throwaway application](https://raw.githubusercontent.com/keyfire/elemctl/main/docs/architecture.svg)

## Features


- **Applications**: list, details, create, start, stop, delete, technology version, debug-session data (`apps debug`). The list filters by name on the client side and prints short cards with `--brief`. Commands that address one application take its id or its exact name.
- **Projects and builds**: upload `.xasm`/`.xlib`, list builds, delete.
- **Build from sources**: elemctl packs a project directory into a build archive with a manifest and git metadata. That directory holds `Проект.yaml` and the modules. The version comes from the flag, from the last build's counter or from the CI run number in the environment: `CI_PIPELINE_IID`, `GITHUB_RUN_NUMBER`, `BUILD_NUMBER`. The output carries it as a field. Descriptors written with English key spellings `Name`/`Vendor`/`Version` are read as well as Russian ones.
- **One-command deploy**: build -> upload -> apply -> restart -> **verification that the apply actually took effect**. Uncommitted changes in the project directory show up in the report as `dirty`. Pass `--require-clean` to stop on a dirty tree.
- **Compilation check without risking the application** (`elemctl probe`): the server compiles the sources, and it does so inside a throwaway application. Errors come back with file, line and column, and the probe deletes what it created. The working application stays out of reach on purpose: the probe never reads `ELEMENT_APP_ID` or `ELEMENT_PROJECT_ID`.
- **User lists** (`elemctl user-lists`): the sign-in settings you would normally open the control panel for, namely self-registration and signing in with a login and a password. Address a list by id, by presentation or by the application that owns it.
- **Development-environment branches**: list, create, bind to an application, merge.
- **Dumps**: create and check readiness.
- **MCP server**: the same operations, exposed as tools for AI agents – Claude Code and other MCP clients.
- **Plugins**: `importlib.metadata` entry points. An external package supplies the platform debug adapter (`elemctl debug-adapter`) and commands of its own, and the core stays small. One `Command` declaration becomes both a CLI subcommand and an MCP tool, so a command that knows your own environment lives in your package instead of a public core.
- **Self-update**: `elemctl self-update` updates the package by unpacking the wheel. It works even while a running MCP server holds `elemctl.exe`, which is exactly where plain pipx or pip breaks the install.
- **In VS Code**: deploy and debugging live in the [XBSL](https://github.com/keyfire/xbsl) extension, which calls elemctl. The deploy button runs `elemctl deploy`, and the debug-session coordinates come from `elemctl apps debug`.

### Checking that the build was applied

A platform quirk: when a project apply fails, the platform **silently rolls back** the application to the previous build. The `Running` status then says nothing about whether the deploy worked. So `elemctl deploy` does not trust the status, and once the work is done it checks three things:

1. Application tasks with an `Error` or `Failed` status that started after the deploy began. Older errors from the history are ignored.
2. The application's actual project version, the `source.project-version` field. It has to match the build that was just uploaded.
3. Whether the application uri answers a health-check HTTP request. The result lands in the report's `uri-status` field and changes nothing: 401 and 403 are normal for closed applications.

The `deploy` exit code is zero only when the build really was applied.

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

The `--json` flag turns that convention into a guarantee a script can lean on, and it is accepted in any position. While the command runs, stdout is swapped for stderr, so the real stdout receives nothing but the JSON answer. No stray line from a plugin or a library can slip in. Parse the stream whole with `json.load` instead of hunting for the first brace. With `--json` a failure also goes to stderr and stdout stays empty, because a pipeline would read anything in the machine channel as the answer.

For the full list of commands run `elemctl --help`, and for one group `elemctl apps --help`, `elemctl deploy --help` and so on.

## Nearby

- **[XBSL](https://docs.keyfire.ru/xbsl/)** – everything that happens to the sources before the
  deploy: a linter with autofixes, an LSP server, metadata scaffolding and a VS Code
  extension. Its editor-title button runs `elemctl deploy`.
- **[EDT-Bridge](https://docs.keyfire.ru/edt-bridge/)** – the neighbouring platform: an MCP bridge into 1C:EDT
  for 1C:Enterprise configurations.

## Limitations and status


- The tool is **unofficial** and not affiliated with 1C Company. The Console API may change without notice.
- elemctl uses only the documented Console API v2. It neither calls nor describes the platform console's internal APIs.
- On some platform configurations an application created from `--project-id` alone comes out as an empty skeleton with no project data. Create it from a build instead: `elemctl apps create <name> --project-id <id> --latest-build`. The `create_app` MCP tool substitutes the latest build for you. Run `elemctl deploy` once the application exists.
- The platform describes an application created with an `Error` status only as "Неизвестная ошибка. Обратитесь к администратору". The details live in the application's task: the files, lines and columns of the compilation errors. `apps create --wait` and `apps ensure` print them after the generic text, the way `deploy` and `verify` have long done, so you do not have to dig through the server log. Not every failure ends in `Error`, though. A failed apply is rolled back to the previous build and the application comes up `Running`, so `--wait` also verifies which build the application really runs and answers with exit code 1 when it is not the one you asked for. Use `--no-verify` for the plain wait.
- You cannot compile the sources without creating something on the platform: compilation belongs to the server and happens when a build is applied. That is what `probe` is for, and it takes the hit on a throwaway application instead of the working one. One probe costs as much time as creating an application does, so minutes. Its place is before a deploy or in CI, not in a per-keystroke loop.
- A platform project is identified by the `Vendor` + `Name` pair in the manifest, not by the `Ид` in `Проект.yaml`. A build uploaded without a project id lands in the project that already owns the pair, and a second project for the same pair is refused with a 409.
- You sign in to a freshly created application with a control-panel account. The application gets its own empty user list, password sign-in is off and no account service is attached, so the accounts that work in other applications do not work here. Connecting another application's user list does not change that, and neither does enabling the local sign-in. `apps create` and `apps ensure` say so themselves: the `sign-in` field of the answer, and the same text on stderr.
- Deleted applications stay in the platform's list with a `Deleted` status and their former `id`. On that id `apps get` and `deploy` return 404. `apps find` and `apps ensure` skip them; `apps find --include-deleted` brings the previous search behaviour back.
- The platform refuses to delete an application that has unpublished changes in the development environment and answers HTTP 400 `FAILED_PRECONDITION`. The Console API has no forced deletion, so the control panel is the only way out. elemctl points this out in the error message.
- Recreating an application, meaning delete and then create, changes its URL. External settings tied to that address, an OIDC redirect for instance, will need updating. The Console API has no "soft" wipe of application data; that is done in the management console.
