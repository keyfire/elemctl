# elemctl Specification

**English** · [Русский](SPEC.ru.md)

This document describes the Console API v2 contract for 1C:Element technology
(1cmycloud.com), the build format and elemctl requirements. It is intended for
developers of clients and extensions to the tool.

## 1. Purpose and package composition

The `elemctl` Python package consists of three layers on top of a shared core:

1. **Library** – a programmatic client for Console API v2 and high-level operations: build and deploy. Python standard library only.
2. **CLI** – the `elemctl` console command, entry point `elemctl` in `[project.scripts]`.
3. **MCP server** – the same operations exposed as tools for AI agents, over the stdio
transport. The `mcp>=1.2,<3` dependency comes as the optional extra `elemctl[mcp]`. It uses
the ergonomic server class of the `mcp` package: `FastMCP` in mcp 1.x,
`MCPServer` in mcp 2.x.

The initial release was specified as version 0.1.0. The current version is `elemctl.__version__`, referenced by `pyproject.toml`. The package is named `elemctl`, requires Python >= 3.10, uses
the MIT license, credits KeyFire as author and follows the `src/elemctl/` layout.
The `dev` extra includes pytest. The initial specification retained LICENSE,
README.md, .env.example and .gitignore without modification.

## 2. Connection configuration

Parameters are taken from three sources, in decreasing order of priority:

1. explicit arguments (CLI flags `--base-url`, `--client-id`, `--client-secret`);
2. environment variables;
3. the .env file: path from the `--env-file` flag, or, without it, the `.env` file in the current directory, if it exists.

Environment variables:

| Variable | Meaning | Required |
|---|---|---|
| `ELEMENT_BASE_URL` | server base URL starting with `http://` or `https://`, e.g. `https://1cmycloud.com` | yes |
| `ELEMENT_CLIENT_ID` | Client-Id for obtaining the token | yes |
| `ELEMENT_CLIENT_SECRET` | Client-Secret | yes |
| `ELEMENT_APP_ID` | default application | no |
| `ELEMENT_PROJECT_ID` | default project | no |
| `ELEMENT_SPACE_ID` | default space | no |
| `ELEMENT_CA_FILE` | additional PEM CA bundle for a private cloud | no |
| `ELEMENT_TLS_STRICT` | strict RFC 5280 certificate checks; `true` by default | no |
| `ELEMENT_TLS_VERIFY` | certificate and hostname verification; `true` by default | no |

.env format: `KEY=VALUE` lines. Empty lines and lines starting with `#` are
skipped. A leading `export ` prefix is allowed, and the value may be wrapped in single or
double quotes. The encoding is UTF-8 and a BOM is possible, so read the file as `utf-8-sig`.
A trailing slash in `ELEMENT_BASE_URL` is trimmed. A nonempty base URL must start with
`http://` or `https://`.

## 3. Authentication

Obtaining a token: `POST {base}/console/sys/token`

- header `Authorization: Basic base64(client_id:client_secret)`;
- body `grant_type=client_credentials`, Content-Type `application/x-www-form-urlencoded`.

The response is a JSON object, and the token sits in the first non-empty of the fields
`id_token`, `token`, `value`, `access_token`. Special case: the
`access_token` value can be the string `"Not implemented"`. That is not a token, so skip the field.

All other requests use the header `Authorization: Bearer {token}`.

The token is valid for about an hour. Cache it in a file in the system temporary directory that
`tempfile.gettempdir()` reports, not in a hardcoded `/tmp`, because the tool also runs on
Windows. The cache expires after one hour, and its key must distinguish base_url and client_id
pairs. On a 401 response, refresh the token forcibly and retry the request once.

## 4. Console API v2 contract

Common prefix: `{base}/console/api/v2`. Request and response bodies are JSON, apart from the build upload. Field names are in kebab-case.

The console reference lists Console API 2.1 as the main version, with prefix
`{base}/console/api/v2.1`. Version 2.0 remains available. elemctl uses 2.0 by
default and calls 2.1 for applied extensions, which are unavailable in 2.0.

An unsupported method returns 401 with the message
`Handler of HTTP request "[<method>] <path>" in application "console" not found.`
Renewing the token does not change the response. elemctl checks the response text
before renewing a token and reports an unsupported method rather than a sign-in error.

Other 401 responses trigger one token refresh and one retry.

### 4.1. Applications

- `GET /applications` – list. The Console API ignores the `name` query parameter and returns
  the full list, as verified against a live instance. Clients must filter by name.
- `GET /applications/{id}` – card. Significant response fields: `id`, `status`,
  `uri` (address of the running application), `error` (error text, if any),
  `technology-version`, `date-updated`, `display-name`, `publication-context`, `source` (an object
  with source information, containing among other things `project-version` – the version of the
  applied build).
- `POST /applications` – create. Body:
  - `source` – the object `{"type": "repository"}` plus exactly one of the keys: `project-version-id` (id
    of the source build) or `image-id` (project id);
  - `display-name`, `publication-context` – publication name and path;
  - `development-mode` – boolean, whether to create a development environment;
  - optional `space-id`, `technology-version`.
- `DELETE /applications/{id}` – delete.
- `PUT /applications/{id}/status/start` – start.
- `PUT /applications/{id}/status/stop` – stop.
- `POST /applications/{id}/actions/debug` – data for a debug session (`ApplicationDebugInfo`: `{"debug-token": ..., "debug-address": ...}`). The request body
  is empty; requires debugging enabled on the server (`config/debug.yml` `enabled: true`).
- `POST /applications/{id}/project/update` – apply a build to the application. Body: `{"source": {"type": "repository", "image-id": "<build id>"}}` or `{"source": {"type": "repository", "project-id": "<id>", "assembly-version": "<version>"}}`
  (assembly-version is optional). The same method applies an extension build alongside the
  application build: `source.project-version-id` in the card continues to identify the application build,
  and the extension shows up in `extension-projects` of the 2.1 method below, with the version of the
  build in `assembly-version`. Checked live, on an apply that went through and on two followed by a
  server rollback.
- `POST /applications/{id}/project/export` exports the application build. The reference
  documents the method for 2.0 and 2.1; a live check returned the same archive from both.
  The request has no body. The response is `application/octet-stream` without
  `Content-Disposition`: a repacked archive with directory entries and build files, including
  `Assembly.yaml`. The console obtains it from the application server. Applied extensions
  are excluded and have their own export methods in 2.1.

  Console source shows that during an update or after a failed update, export returns the
  build uploaded for that update; a live check during an update confirmed this. For a build
  uploaded into a project, the manifest contains the server-assigned number (section 4.4)
  and upload time in `Created`. A build that created its project retains the archive manifest.
  The 2.1 handler also accepts an undocumented `extension-id` query parameter and exports the
  extension, as does `/v2.1/applications/{id}/project/{ExtensionId}/export`; 2.0 ignores it.
  Any authenticated user can call the controller, which reads the application using that
  user's rights.
- `POST /applications/{id}/dumps` – create a dump. Body: `include-users`, `include-binary-data` (booleans), `description` (string).
- `GET /applications/{id}/dumps/{dumpId}` – dump status.
- `GET /applications/{id}/users` – the users connected to the application, each `{user-list-id, user-id, presentation, is-admin, token-access-enabled}`. The users of
  the control panel are among them: the server connects them automatically, and it names such a
  user by the login. `token-access-enabled` is the access of the user to the HTTP services of the
  application by a token. Without it a call of a service with the user's token is refused with
  a 500 "Token access is denied", whatever the rights of the user.
- `PUT /applications/{id}/users/change-token-access` – switch that access. Body: `{"user-list-id", "user-id", "enable-access"}`, all three required; the answer is
  the connection as it became. A user who is not connected to the application is refused with a
  500 "Can't change user token access" and no word about the cause, so the client finds the
  connection first and names the user when there is none. The reference documents the method
  under v2 and v2.1 with the same body, and a live check got the same answer from both; the
  client takes the v2 prefix, like every other request.
- `GET /me` – the user the credentials belong to: `id`, `login`, `presentation`, `user-list-id`.
- `GET /v2.1/applications/{id}/project` – the projects the application runs: `application-project`, and the extensions
  applied to it in `extension-projects`. Each extension has `id`, `project-id`,
  `assembly-id`, `enabled`, `order`, `vendor-name`, `project-name`,
  `project-presentation`, `project-version` and `assembly-version`. `id` is the id of the
  extension on the application server: the `Ид` of the extension's `Проект.yaml`,
  the `configuration-id` its upload answered with (section 4.4). For an extension, the console
  fills `assembly-id` with its project id, which a live check and the sources of the console
  agree on, so that field names no build. The same 2.0 path returns only the application project.
- `POST /v2.1/applications/{id}/project/{ExtensionId}/export` exports an applied extension.
  The request has no body; the response is `application/octet-stream` without
  `Content-Disposition`, containing the repacked build files including `Assembly.yaml`.
  The path segment is the extension `id` from the previous method; letter case does not matter.
  Although the reference describes an extension project id, `project-id` produces the same
  500 "Unable to export extension ... from application ..." as an unknown id, with "Contact
  administrator for details" in `details`. Export also works for a stopped application; the
  listing returns 404 for a deleted application. The method is absent from 2.0: `/v2/...`
  returns the 401 for a missing handler. The controller admits any authenticated user
  (`PermitAuthenticated`) and reads the application using that user's rights.
Application statuses are grouped as follows:

- stable: `Running`, `Stopped`, `Error`;
- transitional: `Starting`, `Stopping`, `Initializing`, `Updating`, `Frozen`,
  `Creating`, `Deleting`.

During a transition, `status` may be empty. The reference defines it as a string
without listing values; this list was established through checks on running
installations. `Deleting` persists during the `DeleteApplication` task. After
completion, the entry remains in the list with status `Deleted`.

`UNKNOWN` was observed for an application with missing database files. It could
not be started or deleted, because deletion begins with a data export. The
console uses `UNKNOWN` when an application server state has no mapped status
name. It does not confirm a final state. The client treats it as neither stable
nor transitional: if it persists for one minute, waiting stops with a message
identifying the status.

### 4.2. Technology version

- Reading – from the `technology-version` field of the application card (a dedicated read endpoint is
  not present in all server versions – do not use it).
- Update: `POST /tasks/group-tasks/update-applications-technology`, body `{"technology-version": "<version>", "applications": ["<app-id>"]}`. Returns a group task; its status –
  `GET /tasks/group-tasks/{taskId}`.

### 4.3. Spaces and projects

- `GET /spaces` – list of spaces.
- `GET /projects` – list of projects; `GET /projects/{id}` – card; `DELETE /projects/{id}` – delete. The list
  is answered in full whatever the query, and deleted projects stay in it under the
  `deleted` flag with their former id. Filtering by name and hiding the deleted ones is
  the client's work, as with applications (section 4.1). A project card has no status field;
  `deleted` is the only indication of its state. The `project-kind` field is
  `Application`, `Library`, `Extension`, or `Group` for a project group listed
  alongside its members.

### 4.4. Project builds (assemblies)

- Uploading a build file – a binary POST (Content-Type `application/octet-stream`, body – the file bytes):
  - `POST /projects/{id}/assemblies` – add a build to an existing project;
  - `POST /projects` – create a new project from a build, or add the build to the project matching `Ид` in its `Проект.yaml`;
  - `POST /spaces/{space-id}/projects` – the same, with a new project created in that space.
#### Upload parameters

For uploads into an existing project, the optional `space-id` query parameter
selects the space. Live checks returned 400 for a non-UUID value and 404 for an
unknown space. The PascalCase parameter `SpaceId` is ignored.

`POST /projects` neither documents nor processes either spelling of the space
parameter: a request with `space-id=not-a-uuid` created a project. To create a
project in a specific space, use `POST /spaces/{space-id}/projects`. An unknown
space returns 404. If a project already has the build's `Ид`, the build is added
to that project, as with `POST /projects`.

For `POST /projects/{id}/assemblies`, `commit-id` records the commit in the build
card. The schema check of the next deployment compares sources against that
commit. The documented `branch-name`, `commit-message` and `modified` parameters
are accepted but not returned in the card. `branch-name` refers to a group-development
branch, not a git branch. `modified=1` returns 500. PascalCase `CommitId`,
`BranchName` and `CommitMessage` are ignored. `POST /projects` documents no commit
parameter; a build that creates its project has no commit in its card.

elemctl sends only the commit. The branch, uncommitted-change status and source
directory are recorded in the local upload registry.

#### Build numbering

`POST /projects/{id}/assemblies` ignores the archive version. It reads the base
version from `Версия` in the project descriptor and assigns the highest number
ever issued for that base plus one. Live checks produced these results:

| Archive version | Version after upload |
|---|---|
| `1.0.0-i1` | `1.0.0-1` |
| `1.0.0-10001` | `1.0.0-2` |
| `1.0.0-2`, already present in the project | `1.0.0-3` |
| `1.0.1-7`, with `1.0.0` in the project descriptor | `1.0.0-502` |

Deleting a build does not reduce the counter. After deleting `1.0.0-4` from the
end of the list, the next upload became `1.0.0-5`. After deleting `1.0.0-50` and
`1.0.0-51`, the next upload became `1.0.0-52`, although the list ended at `1.0.0-8`.
Deleting a build from the middle also leaves the counter unchanged. The counter
is not exposed by the API: it is absent from the project card, deleted builds
are not listed, and their card requests return 404. The assigned number is
returned in `assembly-version` after upload.

An upload without a project id, `POST /projects`, preserves the archive version,
including nonnumeric suffixes. An existing version returns 409. A deleted version
can be reused without resetting the project counter: after re-uploading
`1.0.0-2`, the next upload into the project became `1.0.0-8`, not `1.0.0-3`.
A CI-run suffix is therefore preserved only by an upload without a project id.

Before building, `elemctl deploy` warns if the server will change the supplied
version. After upload, it reports the assigned version. Without an explicit
version, it uses the higher number from the build list and local upload registry.
The registry retains numbers uploaded from this machine, including builds later
deleted. A build uploaded elsewhere and then deleted may be absent from both
sources. The post-upload message then identifies the number as server-assigned.

#### Project details in the upload response

The created build id is read from `image-id`, `assembly-id` or `id`, in that order.
The `artifact` object describes the project:

- `artifact-id` – the id used to request the project card;
- `configuration-id` – `Ид` from `Проект.yaml`;
- `name` – the project presentation.

The console displays the project using `Представление` from the most recently
uploaded build, rather than the manifest's `Name`. Uploads with the same `Ид`
and different `Name` and presentation values confirmed this behavior. A build
with a different name renames the project without a separate server message;
uploading the former name restores it. Renaming affects the project and its group; deleting the build does not restore
the previous name. If the mismatch is known before uploading, `builds upload`
rejects the operation unless `--force-rename` is supplied. This is a best-effort
check: if the manifest is unreadable or the project card unavailable, uploading
continues without comparing names.

An upload without a project id can also rename an existing project. The server
selects it by `Ид`, and there is no separate lookup method for that field.
`builds upload` therefore reads the project list before uploading and compares
it with the returned `artifact`. It reports the selected project, whether it
was created and whether the upload renamed it.

- **A project is identified by the `Ид` of `Проект.yaml`**, returned in
  `configuration-id`. `POST /projects` first searches for an active project with
  that `Ид` in the upload space, then in other spaces. If found, the build is
  added to it regardless of the manifest vendor and name. The selected project
  id is returned in `artifact-id`.

  The `Vendor` + `Name` pair must be unique among projects in a space. During
  checks, builds of `acme/crm`, `acme/crm-next` and `globex/crm` with one `Ид`
  were assigned to one project and renamed it. An `acme/crm` build with a new
  `Ид` returned 409.

  A 409 `ALREADY_EXISTS` response has two possible causes:

  - the version is already uploaded: "Версия сборки ... уже присутствует в группе проекта";
  - a new `Ид` uses an existing vendor-and-name pair:
    "Сборка с именем поставщика ... уже зарегистрирована в другом проекте".
    The project creation started for that `Ид` is cancelled.

  The console source performs this lookup with `FindProjectById`. Checks also
  confirmed assignment to an existing project through `POST /spaces/{space-id}/projects`.
  A separate temporary project for the same sources requires both a new `Ид`
  and a new vendor-and-name pair.

- `GET /projects/{id}/assemblies` lists builds. Each entry has `assembly-version`,
  such as `1.0-42`, and an id in `id` or `image-id`. The response is an array
  or an object with an `items` or `assemblies` list.

  **The method has no pagination and reports no total.** Parameters `limit`,
  `size`, `pageSize`, `count`, `top`, `maxResults`, `page`, `pageNumber`, `offset`,
  `skip`, `from` and `start` are ignored. Checks on two installations returned
  byte-identical responses, with no count or cursor in the headers or body.

  **The console automatically deletes builds nobody uses, regardless of age.**
  This occurs when an application finishes applying a build. A background job
  checks builds in that application's project with the same base version as the
  applied build. No more than ten builds are deleted per apply. It retains:

  - release and protected builds;
  - the project's default build;
  - builds used by a running application or uploaded into an application;
  - the highest-numbered build of the base version.

  A build uploaded without a project id (`POST /projects`) is protected from
  creation, as is the build used to create the project repository. Uploading into
  a project by id (`POST /projects/{id}/assemblies`) does not protect a build.
  A library build with no remaining dependent builds is deleted with its group.

  Extension-project builds are not subject to automatic deletion. Applying an
  extension starts the same update process, but the following cleanup checks
  the application's project and base version, not the extension project.
  Extension builds remain until manually deleted or removed with their project.

  A check confirmed this distinction: the application used `1.0.0-1`; its project
  also had `1.0.0-2` and `1.0.0-3` uploaded by project id. The extension project
  contained `1.0.0-1` through `1.0.0-4`. Applying extension `1.0.0-2` deleted
  `1.0.0-2` from the application project and no extension builds. Applying
  `1.0.0-4` afterwards retained extension builds `1.0.0-2` and `1.0.0-3`.

  A project without build applies retains all builds. A build uploaded for later
  use remains protected by its number only while it is the highest. A separate
  check of nine builds matched the console source in the server distribution:

  - creating an application deleted no builds during two minutes of observation;
  - applying `1.0.0-3` deleted `1.0.0-2`, `1.0.0-4` and `1.0.0-11` before the
    apply returned; it retained `1.0.0-1` and `1.0.0-10`, uploaded without a
    project id, the applied `1.0.0-3`, highest-numbered `1.0.0-12` and both `2.0.0` builds;
  - applying `1.0.0-12` deleted `1.0.0-3`;
  - applying `2.0.0-1` deleted no builds, including `1.0.0-12`, because cleanup
    was limited to base version `2.0.0`.

  An earlier observation also found only the applied build remaining from a
  seventeen-build daily series, while the project's first build from two months
  earlier remained: it had been uploaded without a project id. Clients must
  describe the result as the remaining builds, rather than a project history or
  a page of that history.

- `GET /projects/{id}/assemblies/{version}` returns a build card;
  `DELETE .../{version}` deletes the build. The final segment is a version such
  as `1.0-42`, named `assembly-version` or `project-version` in the reference.
  Passing a card UUID returns 404 "Assembly with version <uuid> not found".
  This was checked on two installations of different ages.

  elemctl accepts both versions and ids because ids are returned by uploads and
  build lists. It first resolves the value through the build list. If no card matches, it
  reports a missing build instead of returning an unresolved server 404. If the request
  returns 400 or 404, it also tries the id as the path segment for installations
  using that form. For builds uploaded into a project, the actual version is the
  server-assigned number, not the archive version.

  Deletion returns 500 while an application created from the build still exists.
  After the application is deleted, the same request succeeds. A build used only
  in an apply, including one subsequently rolled back, can be deleted. A 500 is returned to
  the caller without retrying an alternative address format.

Build versions are compared by the numeric suffix after the last hyphen: `1.0-10` is
newer than `1.0-9`. Lexicographic comparison gives the wrong order.

### 4.5. Development environment branches

- `GET /branches` – list; optional queries `project-id`, `name`.
- `GET /branches/{id}` – card. Fields: `name`, `kind`, `project`, `application`, `source-branch`, `deletion-mark`, `version-stamp`.
- `POST /branches` – create. Body: `name`, `kind: "development"`, `project: {"id": "<id>"}`, optionally `application: {"id": "<id>"}`.
- `PUT /branches/{id}` – modify. The server uses optimistic locking, so read the card first, then
  send a body assembled from the current values. Those are `name`, `kind`,
  `deletion-mark` and `version-stamp`, which has to come back exactly as it was. Collapse
  `source-branch` and `application` to `{"id": ...}`, or to `{"name": ...}` when there is no
  id. To rebind to an application, replace `application` with `{"id": "<new app-id>"}`.
- Branch changes are accepted by that same `PUT /branches/{id}` with an additional body key `write-parameters: {"merge": true}`.
- `DELETE /branches/{id}` – delete the branch.

The tool works only with the documented Console API v2. It neither uses nor describes the internal, undocumented APIs of the management console.

### 4.6. Application tasks

`GET /tasks/application-tasks` – list of tasks for all applications. There is no server-side filter, so filter
on the client. Task fields: `id`, `application-id`, `status` (including
`Error`, `Failed`), `operation-type`, `error-message`, `start-date` (ISO 8601, may
end with `Z`).

### 4.7. User lists

A user list holds either the users of an application, which has a list of its own named after
it, or the users of the control panel, which has one list per installation. What the panel
calls the sign-in settings is stored here.

- `GET /user-lists` – the list of user lists: `id`, `presentation`, `space-id`. There is no server-side name filter, so filter on the client.
- `GET /user-lists/{id}` – the full card: `self-registration`, `password-policy`, `password-policy-enabled`,
  `account-services-settings`, `confirmations`, the gateways, `include-personal-data-in-messages`.
- `GET|PUT /user-lists/{id}/settings/self-registration` – `{enabled, phone-required, email-required}`. This is the panel's "allow users to register themselves".
  The PUT requires the whole object.
- `GET|POST /user-lists/{id}/settings/account-services-settings`, `PUT|DELETE .../{account-service-id}` – the account services of the list. An entry is
  `{account-service-id, account-service-type, local-id, enabled, create-user-on-auth, additional-settings}`. The type `Local` authenticates by a password, so the panel's "allow
  signing in with a login and a password" is that entry being `enabled`. The other types
  are external services: `OIDC`, `Cas`, `ActiveDirectory`, `Esia`. The
  PUT requires the whole entry.
- `GET /applications/{id}/userlists` – the ids of the lists connected to the application; `POST` connects,
  `DELETE` disconnects. Note the spelling: no dash here. There are no per-connection
  settings: the link is a set of ids and nothing more.
- `GET /user-lists/{id}/users` – the users of the list, `id` and `login` among their fields.
  An entry contains the access tokens of the user as well, secrets included, so the client
  takes nothing but the ids out of it.
- The application card names the application's own list in `default-user-list`. That is the list of
  its users, and the panel list connected to it is a separate one.

Two things the panel can do and the API cannot, so both stay manual:

- the composition of an application's authentication forms is not in the API at all;
- the connection setting "users of the list are connected to the application automatically on
  sign-in" is not represented either. It is in neither `userlists`, which is a set of ids,
  nor the application's `account-services-settings`; on a stand where the setting is on, nothing appears
  there.

The rules for parsing the response of an account service are accepted in the body of an account
service under the key `userPropertiesCalculationRules`. Those rules are `presentation-rule`, `email-rule`,
`phone-rule` and `response-kind`, all of them JsonPath or XPath. There are two traps. The
schema of the reference calls the same thing `calculation-rules`, and the server returns 400 for
that spelling. And a GET never returns the rules: the setting is write-only, so an API client
cannot confirm it applied.

## 5. Build file format (.xasm / .xlib)

A build file is a ZIP archive (deflate):

- at the root, `Assembly.yaml` – the manifest, flat key-value pairs:

  ```
  ManifestVersion: 1.0 | 1.1
  ProjectKind: Application | Library | Extension
  Vendor: <vendor>
  Name: <project name>
  Version: <version, e.g. 1.0-42>
  Created: <UTC, format YYYY.MM.DD HH:MM:SS>
  BranchName: <git branch name>
  CommitId: <commit hash>
  ```

  For a library (`ProjectKind: Library`), append an empty `Release:` line. Libraries use the `.xlib` extension; applications and extensions use `.xasm`.

  An extension (`ProjectKind: Extension`) uses `ManifestVersion: 1.1`; other kinds use `1.0`. The server
  picks the reader of the manifest by its version, and the 1.0 reader supports only
  `Application` and `Library`: an extension under 1.0 is refused on apply with "Unknown
  project kind: \"Extension\"". The console writes the same pair for an extension it creates.
  An extension built this way was applied live through `project/update` and exported back file
  for file (section 4.1).

- then the project files at paths `{vendor}/{name}/...` relative to the repository root. The project
  directory must follow the scheme `{repo}/{vendor}/{name}/Проект.yaml`. For an application and an extension, locally
  available libraries declared in `Библиотеки`/`Libraries` are included recursively; the
  console gives an extension its libraries the way it gives them to an application. The
  projects an extension extends, listed under `РасширяемыеПроекты`/`ExtendedProjects`, are not libraries
  and stay out of the archive. A declared library without a project under the same repository
  root stays an external dependency of the 1C:Element application. Unreferenced sibling
  projects are not included. Path separators in the archive are forward slashes, on Windows
  too.

Build file name: `{Имя} {Version}.xasm` (with a space).

Project metadata comes from `Проект.yaml`. It is YAML, and parsing the flat top-level "key:
value" pairs is enough; skip the nested indented lines. 1C:Element supports bilingual sources,
including descriptors with English keys. Read each key in both spellings:
`Имя`/`Name`, `Поставщик`/`Vendor`, `Версия`/`Version`
(base, e.g. `1.0`) and `ВидПроекта`/`ProjectKind`. The value `Библиотека` or
`Library` means a library, `Расширение` or `Extension` an extension; anything else
means an application. When both spellings of a key are present, the Russian value takes
precedence. The service file names are bilingual too: the 1C:Element converter accepts
`Project.yaml` and `Проект.yaml`, `Subsystem.yaml` and `Подсистема.yaml`. Both descriptor names
are used for project discovery, local library dependencies, archive inspection and the schema
guard's availability probe.

When the build version is not set explicitly, it is built as `{base version}-{N+1}`, where N is the
counter from the version of the project's latest build of the same base version. `deploy`
takes N as the higher of the latest build in the list and the highest number recorded in the
local upload registry for that project and base: the server counts on from the highest number
it has ever given, deleted builds included (section 4.4). A project bumped to a new base
version starts from `-1` again, whatever counters the old base reached. With no last
build of that base, the suffix comes from the CI run number in the environment: the first
numeric value of `CI_PIPELINE_IID`, `GITHUB_RUN_NUMBER`, `BUILD_NUMBER`, in that order. Otherwise a
clean CI checkout would produce `-1` every time. With no CI number either, the
version is `{base version}-1`.

Git metadata, meaning the commit hash and the branch name, comes from the git repository that
contains the project directory. When git is unavailable, the fields stay empty.

File selection for the archive:

- inside resource directories, whose literal name is `Ресурсы`, files of any extension are
  included, at any level and in their subdirectories too: according to the 1C:Element
  documentation a resource is an arbitrary file, such as `.pdf`, `.htm`,
  `.mxl`, `.docx` or `.xsd`;
- outside resource directories only these extensions are included: `.yaml .xbsl .xbql .md .txt .json` (sources),
  `.png .svg .jpg .jpeg .gif .webp .ico` (images), `.css .htm .html .js .woff .woff2 .ttf .eot` (web resources);
- the description files of a SOAP service client are included wherever they lie: `<Client>.Wsdl.<n>`
  and `<Client>.Xsd`. These files are located next to the project element outside the resource
  directory. Renaming is unsupported, so they are matched by name, not by extension;
- the directories `.git`, `.claude`, `.github`, `__pycache__`, `node_modules`, `.venv` and all hidden ones (starting with a dot) are excluded;
- the files `.gitignore`, `.env`, `.DS_Store` and any `*.xasm` or `*.xlib` are excluded, inside resource directories too.

### 5.1. Parsing a built archive

The reverse of a build: from a `.xasm` or `.xlib` file you get the manifest, the
project properties from its `Проект.yaml` inside the archive, and the contents. It is needed
to attach a library to a project without unpacking its sources.

The directory structure defines the layout inside a project:

- a first-level directory is a **subsystem**. `Подсистема.yaml` or `Subsystem.yaml` is **optional**,
  and a library subsystem may have none at all, so it cannot be relied upon when looking for
  subsystems;
- a nested directory of a subsystem is a **package**. A package has no description file, and every directory contributes a name segment;
- the qualified name of a type: `{vendor}::{name}::{subsystem}[::{package}]::{TypeName}`. The same name without the last segment is what
  `Использование` and `импорт` take.

Only types with `ОбластьВидимости: Глобально`, in English `VisibilityScope: Global`, are visible outside, in the project
that attached the library. The default is `ВПодсистеме`, or `InSubsystem`, and the global
scope is written explicitly. An English descriptor uses English enumeration values as well, so
those values are read in both spellings.

Compatibility is checked against the `РежимСовместимости` property of `Проект.yaml`. The
`ВерсияТехнологии` property **does not exist** in `Проект.yaml`: it belongs to the body of the
Console API request that creates an application, not to the project file.

<a id="6-platform-behaviour-you-have-to-account-for"></a>

## 6. Server behavior

1. **Rollback without a message.** After an apply failure, such as a compilation
   error, the server restores the previous build and starts the application.
   `Running` does not confirm the apply. To verify it:
   - read application tasks from section 4.6 with status `Error` or `Failed`
     and `start-date` at or after deployment began;
   - compare the application's `source.project-version` with the uploaded build;
   - for an extension, check its version and `enabled` in `extension-projects`
     from `GET /v2.1/applications/{id}/project`. The application card identifies
     only the application build. Without Console API 2.1, an extension apply
     remains unverified; that does not establish a rollback;
   - optionally send GET to `uri`. Responses 401 and 403 are valid for
     applications requiring authentication.
2. **Creation without project data.** With some server configurations, a
   "project" source, meaning `image-id` set to a project id, creates an empty
   application. Specify a build in `project-version-id`, such as the latest
   project build, to include the project data.
3. **Deletion with unpublished changes.** Such changes in the development
   environment cause `DELETE /applications/{id}` to return 400
   `FAILED_PRECONDITION`. The API has no forced deletion; use the control panel.
   A client should report this limitation.
4. **New application readiness.** After creation, an application may remain in
   transitional states without `uri`. Wait for a stable status and a `uri`.
   `Error` ends the wait as a failure.
5. **Restart after apply.** `project/update` can restart the application. Wait
   for transitions to finish. If the result is not `Running`, stop the application
   unless already `Stopped`, wait for `Stopped`, start it and wait for `Running`.
   Suggested limits are 3 minutes for stopping, 5 minutes for starting and
   stabilization, with checks every 10 seconds.
6. **Final `Error` status.** Return a failure and the application-task messages
   for a stable `Error`. Do not restart or wait for a different status: an
   application in `Error` does not transition to `Stopped`, so that wait can
   only reach its timeout.
7. **Windows.** Use `tempfile` for temporary files and caches. Configure stdout
   and stderr as UTF-8 with `reconfigure` to preserve Cyrillic text.
8. **Project identity.** A project is identified by the `Ид` of `Проект.yaml`.
   Its `Vendor` + `Name` pair must be unique in the space. An upload without a
   project id may add a build to an existing project with that `Ид`; it does
   not guarantee creation of a new project.
9. **Background deletion.** `DELETE /applications/{id}` returns before the
   `DeleteApplication` task completes. While the application exists, deleting
   its source build returns 500. Delete the application, wait for its card to
   return 404 or its status to become `Deleted`, then delete the build.
10. **Server compilation.** A local build packages an archive. The server
    compiler checks syntax, types and visibility when applying a build or
    creating an application. There is no separate compile endpoint.
    `elemctl probe` uploads sources into their own project with a one-off
    version, creates a temporary application for compilation and removes both
    objects afterwards. The working application is unchanged.
11. **Signing in to a new application.** Its own empty user list is identified
    by `default-user-list`. Password sign-in is disabled and no account service
    is configured. Connecting another application's list through
    `POST /applications/{id}/userlists` and enabling local sign-in does not
    enable those accounts. Use a control-panel account, whose users are
    connected automatically by the server. The card does not describe the
    sign-in method; avoid trying accounts because failed attempts are counted.
12. **Server startup.** The console can remain unavailable for several minutes
    after startup or an update; one observed update required thirteen minutes.
    All requests, including token requests, return 404 with
    `Application "console" not found`. The response text distinguishes this
    from a missing application or build. elemctl reports server startup; retry
    after `/console` returns 302. `deploy` waits for up to
    `--server-start-timeout` seconds, 900 by default; 0 disables waiting.
    Execution continues when the console is available. Retrying a rejected
    request is safe because the console did not process it.
13. **Data deletion after source changes.** Removing a tabular part from the
    sources deletes its rows on apply without warning. A check on a catalog
    with one row in that part completed successfully and left the application
    running. Tabular-part and object attributes are removed with their values;
    removing a catalog descriptor removes its table, checked on an empty catalog.
    Recreating a descriptor under the same path and name with a new `Ид` also
    removes data: a catalog with two rows was empty after a successful apply.

    Narrowing a length or changing a type recreates object data. `elemctl deploy`
    rejects these changes without explicit permission, as it does removal of an
    entire catalog, document or register. For removed attributes or tabular parts,
    it lists the affected data before building and continues.

## 7. CLI requirements

Common flags are accepted in any position, after the subcommand too: `--base-url`,
`--client-id`, `--client-secret`, `--env-file`, `--timeout` (seconds, default 60),
`--lang`, `--json`, `--quiet`. `--version` is the exception and stands
before the subcommand.

An option that takes one value may be repeated with the same value, but different values
produce an argparse error before the command runs: exit code 2, with the key and both values.
Both `--key=value` and `--key value` identify the same key. Values are compared after parsing,
so `--limit 5` and `--limit 05` match. Previously `--output a --output b` silently selected `b`.
The rule covers common flags in any position, command options and plugin options (section 10).
Repeatable options collect all values: `apps list --status`, `apps token-access --user`,
`probe --cleanup` and a plugin's `multiple` argument. Repeating a flag has the same effect
as specifying it once.
Connection flags are used for server requests. `build` and `inspect` are local
operations and reject these flags, including `--env-file`, before execution.
The error lists commands for server operations: `deploy` and `builds upload`.
This restriction applies only to flags. `ELEMENT_*` variables and a `.env` file
next to the project must not affect a local build.

Output works like this: the result is JSON on stdout (`ensure_ascii=False`, indent 2), progress of
long operations comes as lines on stderr, and an error is JSON with an `error` field on
stderr plus return code 1.

`--json` makes that a guarantee rather than just a convention: for the duration of the
call stdout is redirected to stderr, and the answer alone is written to the real stdout. A
caller then parses stdout whole. Without the flag, anything a handler or a plugin prints stays
in the stream ahead of the answer. A failure keeps to stderr and leaves stdout empty in this
mode too.

`--quiet` silences the progress stream for the duration of the call: the progress lines,
the summaries and the warnings that go to stderr, a plugin command's `context.log` among them.
The answer on stdout and a failure on stderr with its exit code stay, and the form of the
answer does not change: `--brief` and `--json` are the keys for that. A plugin
command written with `--quiet` after it used to be refused as an unrecognized argument
before it did any work.

`apps list` and `builds list` print their count and truncation lines after the answer,
never before it. Other stderr output can still come first even for these two commands – a
warning such as the one `ELEMENT_TLS_VERIFY=false` prints, or another command's own progress lines – so
only stdout read on its own is safe to parse as a whole.

Commands, with the significant flags in parentheses:

- `token` – obtain and print the token.
- `apps list [--name --status --include-deleted --brief]`, `apps get [APP_ID]`, `apps find NAME [--include-deleted]`,
  `apps create NAME [--project-id --version-id --latest-build --space-id
  --tech-version --no-dev-mode --wait --verify --no-verify]`,
  `apps ensure NAME [--project-id --version-id --latest-build --space-id
  --tech-version --no-dev-mode --wait --verify --no-verify --apply]`,
  `apps apply [APP_ID] VERSION_ID`,
  `apps delete APP_ID`, `apps start [APP_ID]`, `apps stop [APP_ID]`,
  `apps users [APP_ID]`, `apps token-access APP_ID [--user --enable --disable]`,
  `apps export [APP_ID] [--output]`, `apps export-extension [APP_ID] EXTENSION [--output]`.
  - `apps list --name` filters by a case-insensitive name substring, and it does so on the client
    because the platform ignores the query parameter (section 4.1). `--status` selects by
    the whole status word, several of them separated by commas or given by repeating the key.
    `--brief` prints brief cards instead of full ones: id, name, status, uri, applied
    version.
  - `apps list` hides records with status `Deleted`. Include them with
    `--include-deleted` or `--status deleted`. A summary on stderr reports
    the active and total counts, such as "7 live of 324", plus the number
    shown when another filter is applied. stdout remains a JSON array.

  - `apps get` adds `applied-build` to the card: the brief card of the build the application
    runs, with its branch and commit from the build card or from the local registry of uploads,
    in the shape `builds list --brief` prints. It is null when the card names no applied build.
  - `APP_ID` of `apps get`, `delete`, `start`, `stop`,
    `debug` and `users` is the application id (UUID) or its exact name. A value
    that is not a UUID is resolved through the list by an exact case-insensitive match, and
    deleted applications do not count. No match is an error, and several matches are an error
    listing the ids: destructive commands must not guess.
  - `apps find` searches for an exact, case-insensitive name match among the fields
    `name`, `display-name` and `publication-context`. Output is `{"id": ..., "found": true|false}` with return
    code 0 in both cases: the absence of an application is an answer, not an error. A non-zero
    return code means the request failed and comes with JSON carrying an `error` field
    on stderr. In scripts, check the `found` field, not the return code.
  - Deleted applications remain in the server list with the `Deleted` status and their
    former `id`. `apps find` skips them: the found id must be usable, otherwise
    the caller gets an id on which `apps get` and `deploy` return 404. The
    `--include-deleted` flag restores the former behaviour, searching among all applications
    including deleted ones.
  - `apps ensure` creates an application with the given name only if it does not
  already exist. Lookup follows `apps find` rules and excludes deleted entries.
  The output is `{"id": ..., "created": true|false, "sign-in": ...}`.
  `created: false` means an existing application was found; without `--apply`, it is retained unchanged. Creation flags
  match `apps create` and apply only when creating. An existing application is
  never recreated: deleting and creating changes its URL and breaks external bindings.

  With `--version-id`, an existing application's response also contains `applied`
  and `applied-version-id`: whether the requested build is running and which build
  is actually running. An assembly not identified by the application card is
  checked among extension-project builds and against application extensions,
  as in `apps apply` and `verify-deploy` (section 6.1). The application card
  identifies only the application build.

  For an extension, `applied-version-id` identifies its running build;
  `extension-project-id` and `extension` contain its project and `extension-projects`
  entry. Without Console API 2.1, `applied` is `null` because it cannot be verified.
  `--apply` applies the requested assembly to the existing application in the same call; `apps apply` is the separate command. After `--apply`, build details are in `verify`, not at the top level. `--verify` performs the complete check even if the
  requested build is already running. A created application receives a verified
  result whenever the check runs, rather than assuming success from creation.

- `apps apply [APP_ID] VERSION_ID` applies an already uploaded assembly to an application and verifies the result
  (section 6.6). An apply is not a fact until it is verified: on a failure the server rolls the
  application back without reporting the rollback to the previous build and starts it. The
  output is the verification report, and the exit code is 1 when the assembly did not land.
  Until this command, applying was reachable through the MCP tool alone, while long operations
  are the ones that want a CLI run in the background. The assembly of an extension is applied
  the same way and verified by the extensions of the application (section 6.1): the card goes
  on naming the build of the application, and comparing with it called every extension apply a
  rollback, the successful ones included.
  - `apps create` and `apps ensure` return sign-in details (section 6.11) in
  `sign-in`, shaped `{"url", "account": "control-panel", "hint", "note"}`,
  and print the same information to stderr. `url` is the application address
  from its card. It is `null` until an address is available, including creation
  without `--wait`; the hint describes how to obtain it. `account` is a code
  identifying the control-panel account. The note explains why accounts from
  other applications cannot be used.

- `--latest-build` uses the project's latest build as the source and protects against an empty
  skeleton (section 6.2). `--wait` waits until ready (section 6.4), verifies the result
  (section 6.6) and outputs the final card.
  - Before creation, `--version-id` is looked up in the build list of
  `--project-id`, or `ELEMENT_PROJECT_ID` when the flag is absent. The server
  deletes builds nobody uses, so creating from a deleted build returns 400
  "Can't create application". The command checks availability before sending creation.

  If that project has no matching build, other projects are searched. An upload
  without a project id may have been assigned elsewhere. There is no lookup by
  build id alone: the search reads build lists, starting with the project recorded
  for that build in the local upload registry, then other projects newest first.
  A project from `ELEMENT_PROJECT_ID` is a default and can be replaced with the
  build's project; stderr records the change. An explicit `--project-id` is not
  replaced: the error names the build's project and the flag to pass.

  If no project lists the build, the error reports the cause and suggests the
  build used by a running application of the project, or `--latest-build` when
  none is running. If other projects could not be read, the error identifies
  `ELEMENT_PROJECT_ID` as the project source because the build may belong elsewhere.
  Without any project, the lookup is unavailable and creation proceeds without it.

- `--wait` checks the applied build after waiting. A rollback can leave an
  application `Running`, so the returned card alone does not confirm the requested
  build. The check matches `apps apply` and `verify-deploy`: applied build id,
  tasks failed since creation began and uri availability. The report is returned
  in `verify`; a failed check produces exit code 1. `--verify` requests the check
  separately and also waits for creation to finish. `--no-verify` selects waiting
  without verification. Without these flags, no waiting or verification occurs.
- An interrupted wait or check does not delete the created application. The
  output retains its id: the card for `apps create`, or `id` and `applied: null`
  for `apps ensure` when no verification completed. `wait-error` contains the
  error; stderr gives a `verify-deploy` command for a later check. The exit code is 1.

- `apps users [APP_ID]` prints the users connected to the application the way `GET /applications/{id}/users` gives
  them (section 4.1): `user-list-id`, `user-id`, `presentation`, `is-admin`,
  `token-access-enabled`. There is no login among them: the server returns the login for a
  control-panel user in `presentation` and any other user by its presentation. The command only
  reads, so the application defaults to `ELEMENT_APP_ID`, and it ends with a count line on
  stderr: how many users are connected, how many of them administer the application and how
  many reach its HTTP services by a token. Until the command the list was seen only in a
  refusal of `apps token-access`.
  - `apps token-access APP_ID` shows or switches the access of a user to the HTTP services of the
    application by a token (section 4.1). The application is named explicitly, by the argument
    or by `--app-id`: `ELEMENT_APP_ID` names the working application, and a switch that opens
    its services must not land there by default. `--user` is a login, a presentation or a
    user id, and without it the command uses the account elemctl itself signs in with
    (`GET /me`). Without `--enable` or `--disable` it only reads; both at once is
    an error. A switch reads the connection back, so `token-access-enabled` in the output is what the
    server stores after the change, and a flag that did not move is an error with exit code 1.
    The output is `{"app-id", "user", "user-id", "user-list-id", "token-access-enabled", "changed"}`, where `changed` indicates whether the current call made
    a change: the state that is already there sends no request. A user who is not connected to
    the application is named as such, with the users that are, before anything is sent.
    `--user` may be repeated, and then every user is read or switched in turn. The
    output becomes `{"ok", "app-id", "users"}` with an entry per user in the order given: the report above
    with `"ok": true`, or `{"ok": false, "user", "error"}` for a user that could not be found or switched.
    Such a user does not stop the others, and the return code is 1 when any entry failed. The
    same user given twice counts once, and a single user keeps the output above.
  - `apps export [APP_ID]` saves the build the application runs to a file (section 4.1). `--output`
    is the file to write or a directory for it. Without it the file lands in the current
    directory under the name `{Name} {Version}.xasm` taken from the manifest of the archive, the name a
    build of elemctl gets; for a build uploaded into a project that is the number the server
    gave it. The extensions applied to the application are not in the archive, `apps export-extension`
    saves them. The command only reads the server, so the application defaults to
    `ELEMENT_APP_ID` the way `apps get` does. The output is `{app-id, file, size, manifest}`, where
    `file` is the full path and `manifest` is the `Assembly.yaml` of the archive. An
    answer that is not a build archive is refused, and no file is written. A server without the
    method is refused with the reason and the answer its console gave (status 401, section 4).
  - `apps export-extension [APP_ID] EXTENSION` saves the build of an extension applied to the application to a file
    (section 4.1, Console API 2.1). `EXTENSION` is the id of the extension, the id of its
    project, the name or the presentation of the project, compared exactly and without regard
    to case. The value is looked up among the extensions of the application first, because the
    export answers a miss with a 500 that names no cause: no match is an error naming the
    extensions the application has, and several matches are an error listing them.
    `--output` is the file to write or a directory for it. Without it the file lands in the
    current directory under the name `{Name} {Version}.xasm` taken from the manifest of the archive, the
    name a build of elemctl gets. The command only reads the server, so the application
    defaults to `ELEMENT_APP_ID` the way `apps get` does. The output is `{app-id, extension-id, project-id, vendor-name, project-name, assembly-version, enabled, file, size, manifest}`, where
    `file` is the full path and `manifest` is the `Assembly.yaml` of the archive. An
    answer that is not a build archive is refused, and no file is written. A server without the
    method is refused with the reason and the answer its console gave (status 401, section 4),
    rather than with what reads as a failed sign-in.
- `spaces list`.
- `user-lists list [--name]`, `user-lists get [LIST] [--app]`,
  `user-lists self-registration [LIST] [--app --enable --disable]`,
  `user-lists password-login [LIST] [--app --enable --disable]` – user lists and their
  sign-in settings (section 4.7). The target is the `LIST` argument, an id or the exact
  presentation, resolved like an application name: no match is an error, several matches
  are an error listing the ids. The other way to give a target is `--app`, the
  application's own list out of its `default-user-list`; giving both is an error. Without
  `--enable` or `--disable` the two setting commands only read the current state, so the
  same command answers "how is it now". Both flags at once is an error. `password-login`
  works on the account service of type `Local`. The output is
  `{"list-id", "enabled", "changed"}`, where `enabled: null` means the list has no such
  service at all and nothing signs in by password, and `changed` indicates whether the
  current call made a change: switching to the state that is already there sends no request.
- `projects list [--name --include-deleted]`, `projects get [PROJECT_ID]`, `projects delete PROJECT_ID`.
  - `projects list --name` filters by a case-insensitive name substring, and it does so on the client
    because the Console API returns the full list (section 4.3). Projects marked deleted are
    hidden unless `--include-deleted` is given: this keeps searches concise on environments with many deleted project records.
- `builds list [--project-id --limit --brief]`, `builds get VERSION [--project-id]`,
  `builds upload FILE [--project-id --new-project --force-rename --space-id]`,
  `builds delete VERSION [--project-id]`.
  `builds upload` sends the commit the manifest of the archive names as `commit-id`
  (section 4.4), names on stderr a build the server numbered otherwise than its archive
  (section 4.4) and reports the target in the output through `project-id` and
  `project-id-source`: `flag` or `env` for the project the call named, `server` for the
  project the server chose, and a note on stderr identifies a target taken from
  `ELEMENT_PROJECT_ID`. `--new-project` ignores the environment binding and uploads
  without a project id: the server puts the build into the existing project identified by its
  `Ид`, or creates one when there is none (section 6.8); it is mutually exclusive with
  `--project-id`. Such an upload names that project in the `project` field,
  `{id, name, configuration-id, created, renamed-from, found-by}`, and in a line on stderr.
  The project comes from the `artifact` of the answer (section 4.4), and an answer without
  one sends the client through the build lists (`found-by` is `response` or
  `build-list`). `created` and `renamed-from` are judged against the project list read
  before the upload: an id the list did not have is a project the upload created, and an
  id it had under another name is a project the upload renamed. The rename is a warning on
  stderr, since deleting the build does not bring the name back. The answer used to print
  `project-id: null`, and a project the server had created for the build was then looked
  up by hand. A list that cannot be read leaves `created` null and does not stop the
  upload. `--force-rename`
  allows uploading an assembly whose name differs, which renames the target project.
  `builds list` shows the ten newest builds; `--limit 0` removes that limit. The count on
  stderr distinguishes the command's `--limit` from automatic server cleanup (section 4.4),
  which removes unused builds regardless of age. Gaps in consecutive server numbering may
  indicate cleanup, but an upload without a project id can also introduce a jump by retaining
  its archive number. In a live check `1.0.0-3` was followed by `1.0.0-500` and
  `1.0.0-501`; the intervening versions had never existed. Creation timestamps cannot reliably
  distinguish these cases: the server assigned four numbers in a third of a second.

  The local upload registry identifies jumps caused by uploads without a project id on this
  machine. A gap below such a build is reported as a jump, not evidence of cleanup, if the
  registry has no upload within the gap. An upload from elsewhere is not in the registry,
  so its jump can be reported as a deletion. A gap can contain both a jump and deletions. For
  example, the list went from `1.0.0-8` to `1.0.0-52` after deletion of `1.0.0-50`, uploaded
  without a project id, and `1.0.0-51`; it was reported only as a deletion. A jump to
  `1.0.0-10` over `1.0.0-4`, removed by cleanup, was reported only as a jump.

  A gap with a locally recorded upload inside it is reported as both a jump and a deletion,
  whether the jumped build is above or inside the gap. The report names the build that
  introduced the archive number, the first three locally recorded uploads absent from the
  list, and the number of additional uploads. It counts as a deletion. An empty list reports
  that the project has no builds; a list without numbered builds reports that numbering cannot
  be assessed. Extension projects are excluded from automatic cleanup (section 4.4); gaps
  indicate manual deletion, and unused builds remain until `builds delete`. The project kind
  comes from its card. If the card is unavailable, the ordinary count line is used.
  `--brief` prints the id, the versions, the date, the branch and the commit of a build.
  The branch and the commit come from the card when the server returned them, otherwise
  from the local registry of uploads, and `branch-name-source` and `commit-id-source`
  identify the source: `platform`, `registry`, or null when data is absent. The registry
  alone contains `dirty`, whether the tree had uncommitted changes, and `project-dir`,
  the
  directory the build was made from.
- The local registry of uploads. Every upload elemctl makes – `deploy`, `builds upload`,
  `probe` – appends a JSON line to `uploads.jsonl` in the data directory of the user:
  `ELEMCTL_DATA_DIR` when it is set, otherwise `%LOCALAPPDATA%\elemctl` on Windows and
  `$XDG_STATE_HOME/elemctl` (`~/.local/state/elemctl`) elsewhere. A line holds the build
  id, the project id, the version, the branch, the commit, the `dirty` flag, the directory
  of the sources, the archive, the stand, the command, the application the upload was made
  for (the target of a deploy, the throwaway application of a probe), the route of the
  upload (`project` into a project by its id, `no-project-id` without one; the lines
  written before the route got that name carry `vendor-name` and are read the same way)
  and the time. The server stores only the commit, and with several sessions deploying
  from one machine a build on an application could not be traced to the working tree it
  came from. The registry is local:
  a build uploaded from another machine, from CI or by an elemctl that had no registry yet
  is not in it. A registry that cannot be written is a warning on stderr, never a failure
  – the build is on the server by then – and one that cannot be read reads as empty. The
  schema guard of `deploy` takes the commit of an applied build from here when the card of
  the build card has no commit. `deploy` counts the number of the next build from here as well:
  the version a build of the project got stays in the registry after the build is deleted
  (section 5). The registry keeps the newest 1000 uploads,
  `ELEMCTL_REGISTRY_LIMIT` sets another number and `0` keeps every one: once the file has
  grown past the limit by a tenth, the next upload cuts it back to the newest lines. The
  file is rewritten beside itself and swapped in by a rename, and a line another process
  appended meanwhile is carried over; a swap the system refuses leaves the file as it was
  until the next upload.
- `build [--project-dir --output --build-version --last-build --commit
  --branch --kind {application,library,extension} --require-clean]` – build the archive locally.
  Output: `file`, `name`, `vendor`, `version`, `version-source`
  (`flag`, `last-build`, the CI variable name or `default`), `kind`, `branch`, `commit`
  and `dirty`, which indicates whether the project directory has uncommitted changes and is
  null when git is unavailable. The version is a field of its own so CI does not parse
  the file name. Without `--project-dir`, the project directory is found automatically:
  the first directory with `Проект.yaml` when descending from the current one. `--kind`
  defaults based on `ВидПроекта`. `--require-clean` aborts before building when the
  project directory has uncommitted changes; git being unavailable also aborts, because
  there is nothing to confirm a clean tree with.
- `inspect FILE` – parse a prebuilt archive (section 5.1). Local as well: the server is not
  contacted, and the connection flags are refused the same way.
- `deploy [--app-id --project-id --project-dir --output --build-version
  --branch --commit --dry-run --require-clean --allow-data-loss
  --server-start-timeout --expected-app-name --expected-app-uri]` –
  Build, upload, apply, restart and verify the applied build (section 6.1). The JSON report
  contains:

  - `app-id`, `uri`, `status`, `version` and `assembly-id`;
  - `assembly-version`, assigned by the server, and `renumbered`, which is true if the
    assigned version differs from the archive and null if the upload did not report it;
  - `applied-version`, `applied` (true, false or null if the actual version could not be
    determined), `uri-status` and `ok`;
  - `problems`, the original server messages, and `problems-lines`, the same messages split
    into plain lines. JSON escapes newlines and tabs as `\n` and `\t`;
  - `dirty` and `dirty-files`, the uncommitted changes in the project directory at build
    time. The build uses the current disk state; a warning is also printed to stderr. A null
    value means git was unavailable;
  - `extension-project-id` and `extension` for an extension build, described below.

  `hint` points to the server log when a task fails without a compilation error in its message.
  The server may return only "Contact administrator for details". The last `Caused by` line
  in the log describes the cause, and `SrcPath:` beside it identifies the affected file. An
  apply ending in `Error` fails with the same hint.

  For an upload to a project, the server assigns a build number (section 4.4). Before building,
  stderr warns if an explicit `--build-version` will not be retained: a nonnumeric suffix,
  a missing suffix or a base different from the project's `Версия`. After upload it reports
  a version that differs from the archive. Without `--build-version`, deploy uses the higher
  number from the build list and local upload registry (section 5). The server does not reuse
  deleted numbers, and the registry retains numbers uploaded from this machine. A build uploaded
  elsewhere and then deleted may be absent from both sources; the post-upload message then
  identifies the version as server-assigned without a warning.

  An extension build (`ProjectKind: Extension`) is verified against the application's extensions
  (section 6.1). `extension-project-id` identifies the project, and `extension` contains the
  `extension-projects` entry used for verification, or null if the extension is absent.
  `applied-version` and `applied-version-id` identify the extension build rather than the
  application build in the card. The exit code is 0 only when `ok` is true. `--dry-run` stops
  after building, `--require-clean` stops before building on a dirty tree, and
  `--server-start-timeout` sets the wait for server startup in seconds (section 6.12).

  Before building, the schema guard compares sources with the commit used for the applied
  build: `commit-id` in its card (section 4.4), or the local upload registry if the card has
  no commit. A build that created its project has no commit in its card. The registry has one
  if this machine uploaded it; stderr reports that source and whether the build had uncommitted
  changes, which the commit comparison cannot inspect. `schema-commit` identifies the commit;
  `schema-commit-source` is `platform` or `registry`. Project discovery follows the build rules.

  The deploy refuses the following changes unless `--allow-data-loss` is set:

  - narrowing a length or changing the type of an attribute, dimension or resource, including
    a tabular-part attribute, or removing a dimension, because data may be recreated or broken;
  - removing the description of a data-bearing element: catalog, document, information or
    accumulation register, constants set, exchange plan or settings storage. Its table and
    all rows would be removed.

  The guard lists files from the applied commit through git and matches elements by `Ид`.
  A moved or renamed description with the same id is compared with its old text. A removed or moved description without `Ид` cannot be matched to its former element and is left alone. A description
  at the old path with a different `Ид` is a different element; its fields are not compared
  with the former element. The guard treats the former element as removed and reports its old
  `Ид`, which can be restored if it is meant to be the same element. In a live check, applying
  a catalog recreated under the same path and name emptied it without confirmation.

  A removed attribute, resource, tabular part or tabular-part attribute is applied by the
  server without confirmation (section 6.13). Deploy lists each in stderr and
  `schema-warnings` and continues. Fields are matched by `Ид`, so renaming retains data;
  without an id, field removals across a translated description cannot be detected.

  `schema-check` is `clean`, `warned` (removals only), `allowed`, or `skipped:<reason>`.
  Skip reasons are `no-project-dir`, `read-failed`, `no-applied-build`, `no-applied-extension`,
  `applied-build-not-listed`, `no-commit-id` and `commit-unavailable`; each has an explanation.
  Extension sources are compared with their applied extension build. For the first apply,
  when the application has no such extension, the reason is `no-applied-extension`. A skipped
  check is also reported after the verdict, so successful verification is not mistaken for a
  completed schema check.
- `verify-deploy [APP_ID] [--app-id --version-id --expected-version --since-minutes]` –
  the verification of section 6.1 on its own, deploying nothing. It looks at the
  application tasks in an error status raised over the last `--since-minutes` minutes,
  whose `error-message` contains the file and position of a compilation error. Then it
  compares the applied build with the expected one: `--version-id` is the id of the
  uploaded build and the reliable comparison, `--expected-version` is the version string
  and the backup. It finishes with a control GET on the address. The report is the same
  as `deploy` gives, and the return code is 0 only when `ok`. It is what a CI script needs
  after `apps create`: a build that failed to apply is rolled back silently, and a status
  of `Running` proves nothing. A `--version-id` the card does not name is looked up among
  the builds of the extension projects of the stand (`project-kind`, section 4.3): a build
  found there is an extension build and is verified by the extensions of the application,
  the way `deploy` verifies one, and any other build keeps the verdict of the card. The
  lookup costs the listing of the projects and one build listing per extension project,
  and it runs only when the card names another build. `--expected-version` alone leads to
  no project, so an extension is verified by its id.
- `probe [--project-dir --output --build-version --name --space-id --keep
  --require-clean]`, `probe --cleanup APP_ID` – compile in a temporary application
  and then clean up. The process builds and uploads the archive, creates an application
  for compilation (section 6.10), reports errors with file and position, and removes
  temporary objects.

  Before building, the project descriptor is checked for:

  - `Представление` (`Presentation`): without it upload fails with an unexplained 500;
  - `ЯзыкРазработки` (`DevelopmentLanguage`): without it application creation fails;
  - `ЯзыкиЛокализации` (`LocalizationLanguages`) when `ЯзыкПоУмолчанию`
    (`DefaultLanguage`) is set: omitting it also produces an unexplained refusal.

  Missing keys and lines to add are reported in the descriptor's language before building
  or uploading. `ELEMENT_APP_ID` and `ELEMENT_PROJECT_ID` are not used for creation;
  the working application is unchanged and the server selects the project by the
  descriptor's `Ид` (section 6.8). The default version `{base}-probe-{token}` is unique
  to avoid a 409, and its nonnumeric suffix excludes the build from latest numeric version
  comparisons.

  Cleanup runs after successful or failed compilation in the order of section 6.9:
  application, build, then the project if the probe created it. The report contains:

  - `ok`, `project-dir`, `vendor`, `name`, `file`, `version`;
  - `project-id`, `project-created`, `project-renamed-from`. The last field is the former
    name if the uploaded build renamed an existing project with the same `Ид`, or null
    otherwise. The rename is reported on stderr and cleanup does not reverse it;
  - `assembly-id`, `app-id`, `app-name`, `status`;
  - `errors`: `{file, entry, line, column, environment, message}` records, with `file`
    relative to the project directory; `messages`: the original server messages, including
    failures that are not compilation errors;
  - `cleanup`: `kept`, `app-deleted`, `assembly-deleted`, `project-deleted`, `problems`,
    `command`, `steps`;
  - `hint`: a server-log recommendation, as in `deploy`, when the server refuses without
    naming a file. It remains empty when waiting times out.

  A server that does not support the project's compatibility mode can also report derived
  type and property errors in unchanged files. Parsing stops after the compatibility refusal;
  `compatibility-refused` identifies the mode and `messages-dropped` counts the omitted
  follow-on messages. Exit code 0 requires `ok`. Cleanup failures appear in the report and
  stderr without changing the compilation verdict. `--keep` retains the application and
  build. Even after deletion, the server retains the application entry with status `Deleted`
  and its former id; the API cannot remove that entry.

  With `--keep` or failed cleanup, `cleanup` and stderr provide `command` and manual `steps`
  in the order of section 6.9. The command is `probe --cleanup APP_ID` when the application
  id is available; otherwise `command` is null. Cleanup addresses the build in the probe's
  own project: a bare `builds delete` uses `ELEMENT_PROJECT_ID`, which may not contain it.
  Deleting the build before the application has disappeared returns 500. The cleanup commands
  include the original `--env-file`.

  **Repeated cleanup.** `probe --cleanup APP_ID` accepts an application id or name and reads
  its project and build from the card. At least one of these identifies a probe:

  - name prefix `elemctl-probe-`;
  - `-probe-` in the build version, including with a custom `--name`;
  - a local upload-registry record of probe creation. This also covers a custom `--name`
    and `--build-version`, and an application subsequently deployed to.

  Applications without these signs and the application named by `ELEMENT_APP_ID` are refused
  with an explanation. Cleanup deletes the application, waits until it disappears, then
  deletes the probe build and builds recorded for it in the local registry. The probe build is
  identified by its version token or registry record. The client checks whether builds are in
  use by another live application only when `remembered_builds` is nonempty. Without local
  records, a probe identified by name or version does not get that check. When the check finds
  another user, the build is retained and its `builds` entry identifies that application in
  `kept`.

  The project is removed last only if it has no builds or live applications, and never when
  it is `ELEMENT_PROJECT_ID`. Builds uploaded to the probe from another machine and absent
  from the local registry remain for automatic server cleanup. A repeat completes unfinished
  steps; an already deleted application entry or project is not deleted twice. No new build is
  made, and probe-run flags are rejected with `--cleanup`.

  The result is `ok`, `app-id`, `app-name`, `project-id`, `app-deleted`, `builds` (entries
  `{id, version, deleted}`), `project-deleted`, `project-kept` with the reason, and `problems`.
  Exit code 0 requires `ok`. Repeating `--cleanup` processes probes sequentially so their
  shared project can be removed after the last build. Output is `{"ok", "cleanups"}` with
  one report per application in input order, or `{"ok": false, "app-id", "error"}` for a
  refused item (not a probe, working application, or not found), preserving its input `app-id`.
  A refusal does not stop the rest; overall `ok` and exit code 0 require all cleanups to
  succeed. Duplicate applications are processed once; a single application keeps the report
  shape described above.
- `branches list [--project-id --name]`, `branches get ID`,
  `branches create NAME [--project-id --app-id]`,
  `branches update ID [--app-id]`, `branches delete ID`,
  `branches merge ID`.
- `dumps create [APP_ID] [--description]`, `dumps get APP_ID DUMP_ID`.
- `tasks list [--app-id]`, `tasks get-group TASK_ID`.
- `tech get [APP_ID]`, `tech set APP_ID VERSION`.
- `debug-adapter` – the path to the 1C:Element debug adapter directory supplied by a plugin (the
  `elemctl.debug_adapter` entry-point group, section 10). Output `{"path": ..., "found": true, "adapter-class": ...}` when present or
  `{"path": null, "found": false}`; exit code 0 in both cases. The `path` is a ready value for the VS
  Code extension's `xbsl.debug.adapterPath` (a directory with a `repo/` subdirectory).
- `plugins` – diagnostics: what the plugins bring. `debug-adapter` holds the declared
  adapter directories and whether each of them holds jars. `commands` holds the commands of
  the plugins with the entry point they arrived through and the name of their MCP tool, which
  is `null` when the command stays out of MCP. `failures` holds what was left out:
  a plugin that did not load, or a command that would have taken over a name of the core, each
  with the entry point and the reason. The answer looks like `{"debug-adapter": [{"path": ..., "has-jars": true|false}], "commands": [{"name": ..., "source": ..., "mcp": ...}], "failures": [{"source": ..., "error": ...}]}`.
- The subcommands the plugins bring (section 10, the `elemctl.commands` group) stand alongside the
  commands of the core and are listed by `--help`. They may not take over a name of the
  core; the command reference describes the core alone. A plugin that fails to load is left out
  and does not take the CLI down (section 10): every command names it on stderr, and a call to
  a command that is missing while plugins failed is refused with JSON on stderr, the failures
  in its `plugin-failures` field.
- `self-update [--version X] [--stop-holders[=all]]` updates elemctl by unpacking
  a PyPI wheel into site-packages. Busy exe files are not replaced: the launcher
  uses the updated package code. This permits updates while a running MCP server
  uses `elemctl.exe`, unlike pipx or pip in that situation. `pipx_metadata.json`
  is also updated. The result is `{updated, from, to}`.

  Without `--version`, the simple index and JSON summary of PyPI are checked.
  Different cache nodes may list the previous version for several minutes.
  The newer response is used, then pages for the next three version numbers
  are checked: `0.44.1`, `0.45.0` and `1.0.0` after `0.44.0`. A release page
  is available immediately after publication. If sources disagree, stderr
  reports both versions. An installed version newer than every response is
  retained. An explicit `--version` missing from the index is checked against
  its own page; only a 404 establishes that the release is absent.

  If package files are busy, their holder pids and command lines are reported,
  and updating stops without changing the installation. `--stop-holders` stops
  MCP servers because applying new code requires their restart. The running
  commands of other sessions are listed and left alone. If they hold package
  files, the error suggests waiting for completion and retrying.
  `--stop-holders=all` also stops those commands, which then return no result.

- `mcp` – start the MCP server; without the extra installed – a clear error with the hint `pip install "elemctl[mcp]"`.

Positional APP_ID and PROJECT_ID marked as optional above are taken from the configuration when
absent, from `ELEMENT_APP_ID` and `ELEMENT_PROJECT_ID`. If those are empty too, the command errors out.

The optional `--expected-app-name` / `--expected-app-uri` arguments (`expected_app_name` / `expected_app_uri` in the
library and MCP) compare exact values from the live application card before schema review,
build or upload. A mismatch or a missing expected field refuses the deploy. Without either
argument there is no additional card request. Offline `--dry-run` does not check the live
target.

## 8. MCP server requirements

Server name `elemctl`, stdio transport, credentials from the same environment variables
and `.env`. In the server instructions, warn about the silent rollback of build apply
(section 6.1). The tools, whose docstrings are short and in Russian:

- `list_apps(name="", status="", include_deleted=False, brief=True)` – application list. The name
  filter is a case-insensitive substring applied on the client (section 4.1); status is
  matched as a whole word. Deleted applications are excluded unless requested. The result
  contains `total`, `live`, `shown`, `summary` and `applications`. `brief=True` returns
  abbreviated application cards; `brief=False` returns full cards.
- `get_app(app_id)` – the card with `applied-build`, as in `apps get` (section 7).
  `find_app(name)` searches by name.
- `create_app(name, project_id="", version_id="", space_id="", development_mode=True,
  verify=False)` – create an application. If only project_id is specified, its latest build
  is used (section 6.2). `verify=True` waits and checks the requested build; the report is
  returned in `verify`.
- `ensure_app(name, project_id="", version_id="", space_id="", development_mode=True,
  verify=False)` – find or create an application. `verify=True` checks a newly created
  application. For an existing one, the full check runs only when `version_id` is specified
  and the initial result is `applied: true`; a known mismatch is not rechecked. Extension
  builds are checked against the application's extensions, as in `apps ensure` (section 7).

Before creation, `version_id` is checked against project builds, starting with `project_id`
or the stand's `ELEMENT_PROJECT_ID` (section 7). If the build belongs to another project,
the environment default is replaced; an explicit `project_id` causes an error naming the
build's project. A build absent from all project lists is treated as deleted and creation
is refused.

If waiting is interrupted, the response retains the created application's id and the
reason in `wait-error`; `ensure_app` returns `applied: null`. Both tools return `sign-in`
with the same sign-in information as the CLI (section 6.11), included in the JSON response.

- `start_app(app_id)` and `stop_app(app_id)` start and stop an application.
  `debug_info(app_id)` returns session data; debugging must be enabled on the server.

- `debug_adapter()` –
  the path to the 1C:Element debug adapter from a plugin (section 10; a local
  operation that does not contact the server).

- `delete_app(app_id)` deletes an application; its docstring warns that this is irreversible
  and changes its URL. `list_spaces()` lists spaces. In `get_app`/`delete_app`/`start_app`/
  `stop_app`/`debug_info`, `app_id` is a UUID or an exact application name, resolved as in CLI.

- `list_projects(name="", include_deleted=False)` – the filters of `projects list` (section 7).

- `list_builds(project_id, limit=10, brief=True)` – an object `{total, shown, summary, builds}`:
  the summary must indicate list completeness based on gaps in build numbering (section 4.4) and naming a jump the local registry explains (section 7), the
  summary of an extension project indicates that automatic cleanup does not remove its builds, and a
  brief card names the source of its branch and commit, the
  card or the local registry of uploads, the way `builds list --brief` does (section 7).

- `get_build(project_id, version)` – the whole card of one build, addressed by the build
  version (section 4.4; an id is accepted and resolved through the listing).

- `build_assembly(project_dir="", output_dir="", version="")` builds an archive locally.

- `inspect_assembly(file)` – parsing of a built archive (section 5.1; a local operation).

- `deploy(app_id, project_id, project_dir="", version="", branch="", allow_data_loss=False,
  server_start_timeout=900, expected_app_name="", expected_app_uri="")` – returns the deploy report plus a `log` field with progress
  lines, and waits out a server that is still starting (section 6.12); `allow_data_loss=True`
  lets through what the schema guard refuses, the way `--allow-data-loss` does in the CLI
  (section 7), and without it the refusal comes back as an error before anything is built.
  `expected_app_name` and `expected_app_uri` check the live target before building or upload
  (section 7).

- `probe(project_dir="", space_id="", keep=False)` – an isolated
  compilation check that does not touch the working application (section 7),
  the report plus a `log` field.

- `probe_cleanup(app_id)` – `probe --cleanup` (section 7),
  the removal of a probe left on the stand, the report plus a `log` field; `app_id` may be
  a list, answered the way a repeated `--cleanup` is, `{ok, cleanups}` plus `log`.

- `apply_build(app_id, version_id)` applies an uploaded build.

- `verify_deploy(app_id,
  expected_version="", expected_assembly_id="", since_minutes=30)` – verification of the apply per section 6.1, an
  extension build included (section 7, `verify-deploy`).

- `list_app_tasks(app_id="")`, `list_branches(project_id="", name="")`,
  `merge_branch(branch_id)`, `list_user_lists(name="")` and
  `configure_user_list(list_id="", app_id="", self_registration=None, password_login=None)` –
  the sign-in settings of a user list (section 4.7) in one call: the list is given by id, by
  presentation or by the application whose own list it is; both flags are optional, and
  without them the tool only reports the state (`self-registration-enabled`,
  `password-login-enabled`, `changed`).

- `list_app_users(app_id)` – the users connected to
  the application as `apps users` shows them (section 7), in an object
  `{app-id, total, summary, users}`.

- `token_access(app_id, user="", enabled=None)` – the
  access of a user to the HTTP services of the application by a token, as `apps token-access`
  shows and switches it (section 7): `app_id` is required, an empty `user` means the account
  elemctl signs in with, and without `enabled` the tool only reads; `user` may be a list,
  answered the way a repeated `--user` is, `{ok, app-id, users}` with an entry per user.

- `export_app(app_id, output="")` – the build the application runs saved to a file, as
  `apps export` does it (section 7); an empty `output` is the current directory of the server
  process.

- `export_extension(app_id, extension, output="")` – the build of an extension applied to the
  application saved to a file, as `apps export-extension` does it (section 7); an empty
  `output` is the current directory of the server process.

Plugin tools (section 10, the `elemctl.commands` group) are registered alongside these. Their schema uses the declared arguments, their description uses the command `help`, and the core adds an `env_file` parameter. A name already
taken by a tool of the core is not taken over: that command is left out, and so is a plugin
that fails to load. The server names them on stderr, which a client keeps as its log, and
starts with the rest.

## 9. Quality requirements

- pytest tests without network access: .env parsing and configuration priorities,
  file selection and build archive contents (including the manifest), auto-increment
  and numeric comparison of versions, deploy outcome logic (`ok`/`applied`),
  the hint on `FAILED_PRECONDITION`, application search by name, plugin discovery
  through entry points and debug-adapter path resolution (stubbed entry points,
  directories in temp folders), adapter extraction from a tiny .car, self-update
  by unpacking a wheel (urllib mocked, wheel and site-packages in temp folders).
- Docstrings, comments and identifiers – English, tests and tools included: the project is
  public and international. Russian stays where it faces the user: the i18n message catalog,
  argparse help, user-facing strings, MCP tool descriptions and the server instructions, plus
  1C:Element identifiers quoted exactly (`Проект.yaml`, `Ресурсы`, `Имя`, `Поставщик`) and
  the Russian data of test fixtures. Straight quotes `"` in text, dashes –
  en dash `–` (not em dash), ellipsis – three dots `...`.
- The library never prints to stdout or stderr itself: it delivers progress through a
  callback the caller passes in.
- API errors are raised as a dedicated exception carrying JSON-serializable details of
  the server response.

## 10. Plugins (entry points)

elemctl discovers external packages through `importlib.metadata.entry_points`. The core declares nothing about
plugins in its own `pyproject.toml`: it is a consumer that reads the entry points on demand.
Proprietary vendor artifacts, such as the 1C jars, can therefore be distributed in a separate package without including them in the public core.

The **`elemctl.debug_adapter`** group. The entry-point value is a path, as a `Path` or a
`str`, or a zero-argument callable returning one (`() -> Path | str`). The path points to
the 1C:Element debug adapter directory, meaning a directory with a `repo/` subdirectory
holding the adapter jars, `com.e1c.g5rt.debugger.adapter*.jar` among them. This is a ready value for the VS Code
extension's `xbsl.debug.adapterPath`.

Declaration in a plugin package:

```toml
[project.entry-points."elemctl.debug_adapter"]
name = "my_package:adapter_root"
```

The **`elemctl.commands`** group accepts a `Command`, a list of commands or a
zero-argument callable returning either. Each declaration produces a CLI
subcommand and an MCP tool. The implementation remains in the plugin. This
supports commands for internal systems, private installations and other
environments outside the public core.

```toml
[project.entry-points."elemctl.commands"]
name = "my_package.commands:commands"
```

The declaration types are exported from `elemctl.plugins`:

- `Argument(name, help="", type=str, default=None, required=False, choices=(), cli_alias="", multiple=False)`
  declares a CLI and MCP argument:

  - `name` is `"--stand"` for an option or `"stand"` for a positional argument. `dest` removes
    leading dashes and replaces internal dashes with underscores, as in argparse.
  - Types are `str`, `int`, `float` and `bool`. A `bool` is a flag: `store_true` in CLI and
    a boolean defaulting to `false` in MCP. It cannot be positional or multiple.
  - `required` applies to both kinds. A positional argument is optional unless `required=True`.
  - `cli_alias` adds a CLI-only option for a positional argument. For example,
    `Argument("page", cli_alias="--page")` accepts `wiki-get 123` or `wiki-get --page 123`;
    MCP retains one `page` parameter. The CLI forms share one `dest` and are mutually exclusive:
    supplying both, or neither for a required argument, is a parser error. An option cannot
    declare `cli_alias`.
  - `multiple=True` accepts several values. The handler receives them in command-line order,
    or the declared default as a list, or `[]` when no default is given. MCP receives an array
    of the declared type. A multiple default may be `None`, a list or a tuple.
  - A multiple option uses `action="append"` and may be repeated. A multiple positional uses
    `nargs="+"` when required and `nargs="*"` otherwise; its alias uses `action="append"`.
    Thus `wiki-get 123 456` and `wiki-get --page 123 --page 456` produce the same list, but
    the two forms remain mutually exclusive. The CLI keeps the default outside the parser, so
    command-line values replace rather than extend it.
  - Without `multiple`, an option takes one value. A repeated option with a different value is
    refused; repeating the same value is allowed (section 7).
  - For older cores, check `hasattr(Argument, "multiple")` before declaring a multiple option:
    older dataclasses reject the keyword and exclude the plugin. Multiple positionals also
    require `POSITIONAL_MULTIPLE` from `elemctl.plugins`, checked as
    `getattr(plugins, "POSITIONAL_MULTIPLE", False)`. A core supporting multiple options only
    raises `PluginError` for a multiple positional; the `hasattr` check is still required.
- `Command(name, help, handler, arguments=[], mcp=True, mcp_name="")` – `name` is the CLI subcommand. The MCP tool is named `mcp_name`,
  or the same name with dashes turned into underscores. `mcp=False` leaves the command in
  the CLI only. `source` is filled in by discovery with the name of the entry point.
- `CommandContext` provides the handler with:

  - `config`, the assembled connection configuration;
  - `client`, a Console API client created on first use and cached. A command that does not
    contact the server does not require credentials;
  - `log(message)`, for progress lines. The CLI writes them to stderr; MCP collects them in
    the response `log` field;
  - `surface`, identifying the caller: `"cli"` (`SURFACE_CLI`) or `"mcp"` (`SURFACE_MCP`).
    A context created outside the core, for example by a test or library caller, has `None`.
    Older cores lack the attribute, so compatible plugins use `getattr(context, "surface", None)`.
    Previously plugins distinguished callers by the shape of `log`, an implementation detail.

The handler is called as `handler(context, **values)`, the values keyed by `dest`. Its result must be
JSON-serializable: the CLI prints it, the MCP tool returns it. The CLI exit code is taken from
the result:

- a dict result whose `exit-code` field holds an integer from 0 to 255 ends with that code.
  A `bool` does not count as an integer here, and the range is what a process returns
  portably: POSIX keeps only the low eight bits of an exit status, so 256 would arrive as 0;
- otherwise a dict result with `"ok": false` ends with 1, the same convention the
  `deploy` and `probe` reports follow, and every other result ends with 0;
- a valid `exit-code` takes precedence over `ok`, so `{"ok": false, "exit-code": 0}` ends with 0. A
  value of another type or out of the range is ignored, and `ok` is used.

The name of the field is exported as `elemctl.plugins.EXIT_CODE_FIELD`; a plugin that also runs on an older core
can tell by its absence that the process code there follows `ok` alone. The MCP tool
returns the `exit-code` field untouched, with the rest of the result. The handler does not
end the process itself: the same function serves the MCP server, where a `SystemExit` leaves
the call unanswered and stops the server. To the MCP tool the core adds an `env_file`
parameter, as every core tool has, and, for a dict result, a `log` field with the
progress lines.

Discovery behavior:

- Entry points are sorted by name. `debug_adapter_path()` returns the first
  directory containing adapter jars. A directory without `repo/` or the required
  jars is skipped; if none matches, the result is `None`.
- Entry-point loading or invocation errors are reported as `PluginError`, a
  subclass of `ElemctlError`. A plugin requiring a newer core field can raise
  `TypeError`; the error includes the installed core version.
- Declarations are validated during discovery. An empty name, noncallable handler,
  unsupported type, positional `bool`, duplicate value names, `cli_alias` on an
  option, an alias without an initial dash or with a conflicting key, a repeatable
  flag or an invalid default produces `PluginError`.
- Common CLI flags from section 7 cannot be used as plugin options, positional
  value names or `cli_alias` values. They are moved before the subcommand and
  parsed by the root parser. A conflict can replace a core value or make the
  plugin value unavailable. A custom `env_file` would also duplicate the MCP
  parameter. Reserved flags are read from the CLI parser, automatically covering
  newly added common flags.
- Reserved value names also include `command`, `handler`, `plugin_command`,
  `plugin_commands`, `plugin_failures`, and options `-h`, `--help`. A conflicting
  `handler` replaces the callable with a string and causes `TypeError`; a custom
  `--help` causes `argparse.ArgumentError` while building the CLI. Both sets are
  read from the parser; conflicts are reported as `PluginError`.
- `discover_commands()` returns available commands and a `PluginFailure` for
  each failed entry point. `to_dict()` returns `{source, error}`. One invalid
  command excludes its entire entry point. The strict `plugin_commands()` raises
  the first error. CLI and MCP use `discover_commands()`, so a failed plugin
  does not stop the core or other plugins.
- Core command names are reserved in CLI and MCP. A conflicting plugin command
  is skipped and included in plugin diagnostics.
- `ELEMCTL_NO_PLUGINS=1` disables plugin discovery, leaving core capabilities
  available. The reference generator sets it to document the core.

Surfaces using the mechanism: the CLI `debug-adapter`/`plugins` (section 7) and the
subcommands of the plugins, the MCP tool `debug_adapter` (section 8) and the tools of the
plugins, and the VS Code extension, which requests the path from `elemctl debug-adapter` when the
`adapterPath` setting is empty.

The adapter itself is extracted from the 1C:Element distribution by `tools/extract_adapter.py`, which is
clean code and is not shipped in the package distribution (`prune`). It copies the
`data/ide/theia/plugins/@1c-appengine-plugin/bin/debugger/` directory from the `.car` into `<output>/<version>/` and updates
`index.json`. The proprietary jars stay out of the public package; a separate plugin package
ships them.
