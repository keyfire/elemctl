---
title: "Elemctl"
description: "A CLI, MCP server and library for the 1C:Element Console API: applications, builds from source and one-command deploys with an honest check that the change actually landed."
sidebar:
  label: Home
  order: 1
---

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
- A freshly created application is signed in to with a CONTROL PANEL account: it gets its OWN, empty user list, password sign-in is off and no account service is attached, so the accounts used to sign in to other applications do not work here – and neither connecting another application's user list nor enabling the local sign-in changes it. `apps create` and `apps ensure` say so themselves: the `sign-in` field of the answer plus the same on stderr.
- Deleted applications remain in the platform's list with a `Deleted` status and their former `id`, on which `apps get` and `deploy` return 404. `apps find` and `apps ensure` skip them; to restore the previous search behavior, use `apps find --include-deleted`.
- The platform will not let you delete an application that has unpublished changes in the development environment (HTTP 400 `FAILED_PRECONDITION`), and there is no forced deletion in the Console API – only through the control panel; elemctl points this out in the error message.
- Recreating an application (delete + create) changes its URL – external settings tied to the address (OIDC redirect, etc.) will need to be updated. There is no "soft" wipe of application data in the Console API; it is done in the management console.
