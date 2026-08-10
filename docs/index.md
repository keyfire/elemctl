---
title: "Elemctl"
description: "A CLI, MCP server and library for the 1C:Element Console API: applications, builds from source and one-command deploys with an honest check that the change actually landed."
sidebar:
  label: Home
  order: 1
---

A command-line tool, MCP server and Python library for managing applications on the **1C:Enterprise.Element** cloud platform (1cmycloud.com) through Console API v2.

elemctl covers an application's lifecycle on the platform without the web console: create an application, build a `.xasm`/`.xlib` build archive from project sources, upload the build, apply it to the application and make sure the apply actually happened (the platform can silently roll back), and manage development-environment branches, dumps and the technology version. The same engine is available in three ways: the `elemctl` command for the terminal and CI, an MCP server for AI agents (Claude Code and other MCP clients), and the `elemctl` Python module for your own scripts.

Development notes and updates (in Russian): the [1C × AI: engineering workshop](https://t.me/ceh_1c_ai) Telegram channel.

![The CLI, the MCP server and the Python library share one engine, which talks to the platform over Console API v2; the deploy cycle goes sources, build, upload, apply, verify, and a failed apply is silently rolled back by the platform, so only the verification tells the truth; the probe runs the same archive through a throwaway application](https://raw.githubusercontent.com/keyfire/elemctl/main/docs/architecture.svg)

## Features


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

## Installation


```bash
pipx install elemctl            # or: pip install elemctl
pip install "elemctl[mcp]"      # with the MCP server
```

Python 3.10+ is required. The core and CLI have no external dependencies (standard library only).

## Quick start


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

## Nearby

- **[XBSL](https://docs.keyfire.ru/xbsl/)** – what happens to the sources before the deploy: a linter with
  autofixes, an LSP server, metadata scaffolding and a VS Code extension whose editor-title
  button runs `elemctl deploy`.
- **[EDT-Bridge](https://docs.keyfire.ru/edt-bridge/)** – the neighbouring platform: an MCP bridge into 1C:EDT
  for 1C:Enterprise configurations.

## Limitations and status


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
