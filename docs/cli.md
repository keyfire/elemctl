---
title: "Commands"
description: "Reference of elemctl commands and options: common flags, applications, builds, deploy and the rest."
sidebar:
  label: Commands
  order: 3
---

<!-- Собрано из вывода `elemctl --help` скриптом scripts/gen-cli-docs.py. Не редактировать вручную. -->

This reference is generated from the tool itself – the same text `elemctl --help` prints, gathered on one page.

Common flags go before the command: `elemctl --timeout 120 apps list`. The output language follows `--lang`, the `ELEMCTL_LANG` variable, or the system locale.

## Common flags

Manage 1C:Enterprise.Element platform applications (Console API v2)

```bash
usage: elemctl [-h] [--base-url BASE_URL] [--client-id CLIENT_ID] [--client-secret CLIENT_SECRET]
               [--env-file ENV_FILE] [--timeout TIMEOUT] [--lang {ru,en}] [--version]
               command ...
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--base-url BASE_URL` | platform base URL (ELEMENT_BASE_URL) |
| `--client-id CLIENT_ID` | Client-Id for obtaining a token (ELEMENT_CLIENT_ID) |
| `--client-secret CLIENT_SECRET` | the Client-Secret for that Client-Id (ELEMENT_CLIENT_SECRET) |
| `--env-file ENV_FILE` | path to the .env file (default: .env in the current directory) |
| `--timeout TIMEOUT` | request timeout in seconds (default 60) |
| `--lang {ru,en}` | output language (default: env ELEMCTL_LANG / system locale / ru) |
| `--version` | show the version and exit |

**Commands**

| Command | Description |
|---|---|
| `token` | obtain and print a token |
| `apps` | applications |
| `spaces` | spaces |
| `projects` | projects |
| `builds` | project assemblies on the platform |
| `build` | build an assembly archive locally from sources |
| `inspect` | inspect a prebuilt assembly archive (.xasm/.xlib) |
| `deploy` | full cycle: build -&gt; upload -&gt; apply -&gt; restart -&gt; verify the apply |
| `user-lists` | user lists and their sign-in settings |
| `probe` | isolated compilation check: build -&gt; throwaway application -&gt; errors with file and position -&gt; cleanup |
| `branches` | development-environment branches |
| `dumps` | application dumps |
| `tasks` | application tasks |
| `tech` | technology version |
| `debug-adapter` | path to the platform debug adapter from the plugin (for the VS Code extension) |
| `plugins` | elemctl plugin diagnostics (extension points) |
| `self-update` | update elemctl by unpacking the wheel (safe when the exe is held by the MCP server) |
| `mcp` | start the MCP server (stdio transport) |

## `elemctl token`

```bash
usage: elemctl token [-h]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

## `elemctl apps`

```bash
usage: elemctl apps [-h] action ...
```

**Arguments**

| Option | Description |
|---|---|
| `list` | list applications |
| `get` | application details |
| `find` | find an application by name (exact, case-insensitive match) |
| `create` | create an application |
| `ensure` | create the application if it does not exist yet (idempotent) |
| `delete` | delete an application (irreversible; the URL changes on re-creation) |
| `start` | start an application |
| `stop` | stop an application |
| `debug` | data for a debug session (debug-token, debug-address) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl apps list`

```bash
usage: elemctl apps list [-h] [--name NAME] [--brief]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--name NAME` | case-insensitive name substring filter (applied client-side) |
| `--brief` | brief cards: id, name, status, uri, applied version |

### `elemctl apps get`

```bash
usage: elemctl apps get [-h] [APP_ID]
```

**Arguments**

| Option | Description |
|---|---|
| `APP_ID` | the application id (UUID) or its exact name (default: ELEMENT_APP_ID) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl apps find`

```bash
usage: elemctl apps find [-h] [--include-deleted] NAME
```

**Arguments**

| Option | Description |
|---|---|
| `NAME` | the application name |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--include-deleted` | search deleted applications too (skipped by default) |

### `elemctl apps create`

```bash
usage: elemctl apps create [-h] [--project-id PROJECT_ID] [--version-id VERSION_ID]
                           [--latest-build] [--space-id SPACE_ID] [--tech-version TECH_VERSION]
                           [--no-dev-mode] [--wait]
                           NAME
```

**Arguments**

| Option | Description |
|---|---|
| `NAME` | the application name |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--project-id PROJECT_ID` | source project |
| `--version-id VERSION_ID` | id of the source assembly; if the project does not exist yet, create it with 'builds upload &lt;file&gt;.xasm `--space-id` &lt;id&gt;' without `--project-id` |
| `--latest-build` | source: the project's latest assembly |
| `--space-id SPACE_ID` | space |
| `--tech-version TECH_VERSION` | technology version |
| `--no-dev-mode` | do not create a development environment |
| `--wait` | wait until the application is ready |

### `elemctl apps ensure`

```bash
usage: elemctl apps ensure [-h] [--project-id PROJECT_ID] [--version-id VERSION_ID]
                           [--latest-build] [--space-id SPACE_ID] [--tech-version TECH_VERSION]
                           [--no-dev-mode] [--wait]
                           NAME
```

**Arguments**

| Option | Description |
|---|---|
| `NAME` | the application name |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--project-id PROJECT_ID` | source project |
| `--version-id VERSION_ID` | id of the source assembly; if the project does not exist yet, create it with 'builds upload &lt;file&gt;.xasm `--space-id` &lt;id&gt;' without `--project-id` |
| `--latest-build` | source: the project's latest assembly |
| `--space-id SPACE_ID` | space |
| `--tech-version TECH_VERSION` | technology version |
| `--no-dev-mode` | do not create a development environment |
| `--wait` | wait until the application is ready |

### `elemctl apps delete`

```bash
usage: elemctl apps delete [-h] APP_ID
```

**Arguments**

| Option | Description |
|---|---|
| `APP_ID` | the application id (UUID) or its exact name |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl apps start`

```bash
usage: elemctl apps start [-h] [APP_ID]
```

**Arguments**

| Option | Description |
|---|---|
| `APP_ID` | the application id (UUID) or its exact name (default: ELEMENT_APP_ID) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl apps stop`

```bash
usage: elemctl apps stop [-h] [APP_ID]
```

**Arguments**

| Option | Description |
|---|---|
| `APP_ID` | the application id (UUID) or its exact name (default: ELEMENT_APP_ID) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl apps debug`

```bash
usage: elemctl apps debug [-h] [APP_ID]
```

**Arguments**

| Option | Description |
|---|---|
| `APP_ID` | the application id (UUID) or its exact name (default: ELEMENT_APP_ID) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

## `elemctl spaces`

```bash
usage: elemctl spaces [-h] action ...
```

**Arguments**

| Option | Description |
|---|---|
| `list` | list spaces |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl spaces list`

```bash
usage: elemctl spaces list [-h]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

## `elemctl projects`

```bash
usage: elemctl projects [-h] action ...
```

**Arguments**

| Option | Description |
|---|---|
| `list` | list projects |
| `get` | project details |
| `delete` | delete a project |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl projects list`

```bash
usage: elemctl projects list [-h]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl projects get`

```bash
usage: elemctl projects get [-h] [PROJECT_ID]
```

**Arguments**

| Option | Description |
|---|---|
| `PROJECT_ID` | the project id (default: ELEMENT_PROJECT_ID) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl projects delete`

```bash
usage: elemctl projects delete [-h] PROJECT_ID
```

**Arguments**

| Option | Description |
|---|---|
| `PROJECT_ID` | the project id |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

## `elemctl builds`

```bash
usage: elemctl builds [-h] action ...
```

**Arguments**

| Option | Description |
|---|---|
| `list` | list project assemblies |
| `get` | assembly details by version or id |
| `upload` | upload an assembly file (.xasm/.xlib) |
| `delete` | delete an assembly by version or id |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl builds list`

```bash
usage: elemctl builds list [-h] [--project-id PROJECT_ID]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--project-id PROJECT_ID` | the project id (default: ELEMENT_PROJECT_ID) |

### `elemctl builds get`

```bash
usage: elemctl builds get [-h] [--project-id PROJECT_ID] VERSION
```

**Arguments**

| Option | Description |
|---|---|
| `VERSION` | the assembly version or its id |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--project-id PROJECT_ID` | the project id (default: ELEMENT_PROJECT_ID) |

### `elemctl builds upload`

```bash
usage: elemctl builds upload [-h] [--project-id PROJECT_ID] [--new-project] [--space-id SPACE_ID]
                             [--branch BRANCH] [--commit COMMIT] [--commit-message COMMIT_MESSAGE]
                             FILE
```

**Arguments**

| Option | Description |
|---|---|
| `FILE` | the .xasm/.xlib assembly file |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--project-id PROJECT_ID` | project; WITHOUT it the platform creates a new project – the only way to create a project through the Console API |
| `--new-project` | upload the build as a new project, ignoring ELEMENT_PROJECT_ID from the environment and the .env file |
| `--space-id SPACE_ID` | the space to create the project in – needed when `--project-id` is omitted |
| `--branch BRANCH` | git branch name (metadata) |
| `--commit COMMIT` | commit hash (metadata) |
| `--commit-message COMMIT_MESSAGE` | commit message (metadata) |

### `elemctl builds delete`

```bash
usage: elemctl builds delete [-h] [--project-id PROJECT_ID] VERSION
```

**Arguments**

| Option | Description |
|---|---|
| `VERSION` | the assembly version or its id |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--project-id PROJECT_ID` | the project id (default: ELEMENT_PROJECT_ID) |

## `elemctl build`

```bash
usage: elemctl build [-h] [--project-dir PROJECT_DIR] [--output OUTPUT]
                     [--build-version BUILD_VERSION] [--last-build LAST_BUILD] [--commit COMMIT]
                     [--branch BRANCH] [--kind {application,library}] [--require-clean]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--project-dir PROJECT_DIR` | project directory (by default searched downward from the current one) |
| `--output OUTPUT` | directory for the archive (default: current) |
| `--build-version BUILD_VERSION` | explicit assembly version, e.g. 1.0-42 |
| `--last-build LAST_BUILD` | the project's last assembly version – for auto-increment |
| `--commit COMMIT` | commit hash for the manifest (default: from git) |
| `--branch BRANCH` | branch name for the manifest (default: from git) |
| `--kind {application,library}` | project kind (default: from Проект.yaml) |
| `--require-clean` | abort the build if the project directory has uncommitted changes |

## `elemctl inspect`

```bash
usage: elemctl inspect [-h] FILE
```

**Arguments**

| Option | Description |
|---|---|
| `FILE` | assembly archive file |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

## `elemctl deploy`

```bash
usage: elemctl deploy [-h] [--app-id APP_ID] [--project-id PROJECT_ID] [--project-dir PROJECT_DIR]
                      [--output OUTPUT] [--build-version BUILD_VERSION] [--branch BRANCH]
                      [--commit COMMIT] [--commit-message COMMIT_MESSAGE] [--dry-run]
                      [--require-clean]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--app-id APP_ID` | the application id (default: ELEMENT_APP_ID) |
| `--project-id PROJECT_ID` | the project id (default: ELEMENT_PROJECT_ID) |
| `--project-dir PROJECT_DIR` | the project directory (by default searched downward from the current one) |
| `--output OUTPUT` | directory for the archive (default: a temporary one) |
| `--build-version BUILD_VERSION` | explicit assembly version |
| `--branch BRANCH` | branch name for the metadata (default: from git) |
| `--commit COMMIT` | commit hash for the metadata (default: from git) |
| `--commit-message COMMIT_MESSAGE` | commit message (upload metadata) |
| `--dry-run` | build only, no upload |
| `--require-clean` | abort the deploy if the project directory has uncommitted changes |

## `elemctl user-lists`

```bash
usage: elemctl user-lists [-h] action ...
```

**Arguments**

| Option | Description |
|---|---|
| `list` | list the user lists |
| `get` | the list card: registration, password policy, account services |
| `self-registration` | self-registration of users: show or switch |
| `password-login` | signing in with a login and a password (the Local account service): show or switch |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl user-lists list`

```bash
usage: elemctl user-lists list [-h] [--name NAME]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--name NAME` | filter by a presentation substring |

### `elemctl user-lists get`

```bash
usage: elemctl user-lists get [-h] [--app APP] [LIST]
```

**Arguments**

| Option | Description |
|---|---|
| `LIST` | the user list id or its exact presentation |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--app APP` | take the application's own list (its id or exact name) |

### `elemctl user-lists self-registration`

```bash
usage: elemctl user-lists self-registration [-h] [--app APP] [--enable] [--disable] [LIST]
```

**Arguments**

| Option | Description |
|---|---|
| `LIST` | the user list id or its exact presentation |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--app APP` | take the application's own list (its id or exact name) |
| `--enable` | turn on |
| `--disable` | turn off |

### `elemctl user-lists password-login`

```bash
usage: elemctl user-lists password-login [-h] [--app APP] [--enable] [--disable] [LIST]
```

**Arguments**

| Option | Description |
|---|---|
| `LIST` | the user list id or its exact presentation |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--app APP` | take the application's own list (its id or exact name) |
| `--enable` | turn on |
| `--disable` | turn off |

## `elemctl probe`

```bash
usage: elemctl probe [-h] [--project-dir PROJECT_DIR] [--output OUTPUT]
                     [--build-version BUILD_VERSION] [--name NAME] [--space-id SPACE_ID] [--keep]
                     [--require-clean]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--project-dir PROJECT_DIR` | the project directory (by default searched downward from the current one) |
| `--output OUTPUT` | directory for the archive (default: a temporary one) |
| `--build-version BUILD_VERSION` | explicit build version (default {base}`-probe-`{token} – it has to be a new one) |
| `--name NAME` | name of the throwaway application (default elemctl-probe-{token}) |
| `--space-id SPACE_ID` | the space for the project and the application (ELEMENT_SPACE_ID) |
| `--keep` | skip the cleanup: leave the application and the build for a hands-on look |
| `--require-clean` | abort the check if the project directory has uncommitted changes |

## `elemctl branches`

```bash
usage: elemctl branches [-h] action ...
```

**Arguments**

| Option | Description |
|---|---|
| `list` | list branches |
| `get` | branch details |
| `create` | create a branch |
| `update` | update a branch (rebind to an application) |
| `delete` | delete a branch |
| `merge` | accept the branch's changes |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl branches list`

```bash
usage: elemctl branches list [-h] [--project-id PROJECT_ID] [--name NAME]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--project-id PROJECT_ID` | the project id (default: ELEMENT_PROJECT_ID) |
| `--name NAME` | filter by branch name |

### `elemctl branches get`

```bash
usage: elemctl branches get [-h] ID
```

**Arguments**

| Option | Description |
|---|---|
| `ID` | the branch id |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl branches create`

```bash
usage: elemctl branches create [-h] [--project-id PROJECT_ID] [--app-id APP_ID] NAME
```

**Arguments**

| Option | Description |
|---|---|
| `NAME` | the branch name |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--project-id PROJECT_ID` | the project id (default: ELEMENT_PROJECT_ID) |
| `--app-id APP_ID` | bind to an application right away |

### `elemctl branches update`

```bash
usage: elemctl branches update [-h] [--app-id APP_ID] ID
```

**Arguments**

| Option | Description |
|---|---|
| `ID` | the branch id |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--app-id APP_ID` | the application id (default: ELEMENT_APP_ID) |

### `elemctl branches delete`

```bash
usage: elemctl branches delete [-h] ID
```

**Arguments**

| Option | Description |
|---|---|
| `ID` | the branch id |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl branches merge`

```bash
usage: elemctl branches merge [-h] ID
```

**Arguments**

| Option | Description |
|---|---|
| `ID` | the branch id |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

## `elemctl dumps`

```bash
usage: elemctl dumps [-h] action ...
```

**Arguments**

| Option | Description |
|---|---|
| `create` | create a dump |
| `get` | dump status |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl dumps create`

```bash
usage: elemctl dumps create [-h] [--description DESCRIPTION] [APP_ID]
```

**Arguments**

| Option | Description |
|---|---|
| `APP_ID` | the application id (default: ELEMENT_APP_ID) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--description DESCRIPTION` | dump description |

### `elemctl dumps get`

```bash
usage: elemctl dumps get [-h] APP_ID DUMP_ID
```

**Arguments**

| Option | Description |
|---|---|
| `APP_ID` | the application id |
| `DUMP_ID` | the dump id |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

## `elemctl tasks`

```bash
usage: elemctl tasks [-h] action ...
```

**Arguments**

| Option | Description |
|---|---|
| `list` | list application tasks |
| `get-group` | group task status |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl tasks list`

```bash
usage: elemctl tasks list [-h] [--app-id APP_ID]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--app-id APP_ID` | filter by application (client-side) |

### `elemctl tasks get-group`

```bash
usage: elemctl tasks get-group [-h] TASK_ID
```

**Arguments**

| Option | Description |
|---|---|
| `TASK_ID` | the group task id |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

## `elemctl tech`

```bash
usage: elemctl tech [-h] action ...
```

**Arguments**

| Option | Description |
|---|---|
| `get` | the application's technology version |
| `set` | update the technology version (group task) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl tech get`

```bash
usage: elemctl tech get [-h] [APP_ID]
```

**Arguments**

| Option | Description |
|---|---|
| `APP_ID` | the application id (default: ELEMENT_APP_ID) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `elemctl tech set`

```bash
usage: elemctl tech set [-h] APP_ID VERSION
```

**Arguments**

| Option | Description |
|---|---|
| `APP_ID` | the application id |
| `VERSION` | the technology version to move the application to |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

## `elemctl debug-adapter`

```bash
usage: elemctl debug-adapter [-h]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

## `elemctl plugins`

```bash
usage: elemctl plugins [-h]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

## `elemctl self-update`

```bash
usage: elemctl self-update [-h] [--version VERSION]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--version VERSION` | target version (default: the latest from PyPI) |

## `elemctl mcp`

```bash
usage: elemctl mcp [-h]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

