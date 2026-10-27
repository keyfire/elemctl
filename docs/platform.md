---
title: "Console API and builds"
description: "Console API v2, the build file format and 1C:Element server behavior."
sidebar:
  label: Console API and builds
  order: 6
---

This page describes the Console API, the build archive format and 1C:Element server
behavior observed during elemctl development. It is intended for developers of
other clients and for diagnosing server behavior.

## Console API v2 contract

Common prefix: `{base}/console/api/v2`. Request and response bodies are JSON, apart from the build upload. Field names are in kebab-case.

The console reference lists Console API 2.1 as the main version, with prefix
`{base}/console/api/v2.1`. Version 2.0 remains available. elemctl uses 2.0 by
default and calls 2.1 for applied extensions, which are unavailable in 2.0.

An unsupported method returns 401 with the message
`Handler of HTTP request "[<method>] <path>" in application "console" not found.`
Renewing the token does not change the response. elemctl checks the response text
before renewing a token and reports an unsupported method rather than a sign-in error.

### Applications

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
  and the extension shows up in `extension-projects` of `GET /v2.1/applications/{id}/project`, with the version of the build
  in `assembly-version`. `elemctl` verifies such an apply by that list.
- `POST /applications/{id}/project/export` exports the application build. The method is
  documented for 2.0 and 2.1. The request has no body; the response is
  `application/octet-stream` without `Content-Disposition`, containing repacked build files.
  The console obtains the archive from the application server; it excludes applied extensions.
  During an update or after a failed update, the response contains the build uploaded for
  that update. A build uploaded into a project has the server-assigned number in its manifest.
  The 2.1 handler also accepts an undocumented `extension-id` query parameter for exporting
  an extension. `elemctl apps export` saves the archive as `{Name} {Version}.xasm`.
- `POST /applications/{id}/dumps` – create a dump. Body: `include-users`, `include-binary-data` (booleans), `description` (string).
- `GET /applications/{id}/dumps/{dumpId}` – dump status.
- `GET /applications/{id}/users` – the users connected to the application, each `{user-list-id, user-id, presentation, is-admin, token-access-enabled}`. The users of
  the control panel are among them: the server connects them itself and names such a user by
  the login. `token-access-enabled` is the access of the user to the HTTP services of the application
  by a token; without it a call of a service with the user's token is refused with a 500 "Token
  access is denied".
- `PUT /applications/{id}/users/change-token-access` – switch that access. Body: `{"user-list-id", "user-id", "enable-access"}`, all three required; the answer is
  the connection as it became. A user who is not connected to the application gets a 500 "Can't
  change user token access" without an explanation. The method is documented under v2 and v2.1
  alike. `elemctl apps token-access` finds the connection first and reads the flag back after a switch, and
  `elemctl apps users` prints the whole list.
- `GET /me` – the user the credentials belong to: `id`, `login`, `presentation`, `user-list-id`.
- `GET /v2.1/applications/{id}/project` – the projects the application runs: `application-project`, and the extensions
  applied to it in `extension-projects`, each with `id`, `project-id`, `assembly-id`,
  `enabled`, `order`, `vendor-name`, `project-name`, `project-presentation`,
  `project-version` and `assembly-version`. `id` is the id of the extension on the
  application server: the `Ид` of the extension's `Проект.yaml`, the
  `configuration-id` its upload answered with. For an extension, the console fills `assembly-id`
  with its project id, so that field names no build. The same 2.0 path returns only the application project.
- `POST /v2.1/applications/{id}/project/{ExtensionId}/export` exports an applied extension.
  The request has no body; the response is `application/octet-stream` without
  `Content-Disposition`, containing the uploaded build files. The path segment is the extension
  `id`; letter case does not matter. The reference calls it an extension project id, but
  `project-id` returns the same 500 "Unable to export extension ... from application ..." as
  an unknown id. Export works for a stopped application. The method is unavailable in 2.0.
  `elemctl apps export-extension` first finds an extension by any of its names, then saves the
  archive as `{Name} {Version}.xasm`.
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

### Technology version

- Reading – from the `technology-version` field of the application card (a dedicated read endpoint is
  not present in all server versions – do not use it).
- Update: `POST /tasks/group-tasks/update-applications-technology`, body `{"technology-version": "<version>", "applications": ["<app-id>"]}`. Returns a group task; its status –
  `GET /tasks/group-tasks/{taskId}`.

### Spaces and projects

- `GET /spaces` – list of spaces.
- `GET /projects` – list of projects; `GET /projects/{id}` – card; `DELETE /projects/{id}` – delete. The kind
  of a project is in `project-kind`: `Application`, `Library` or `Extension`, and
  `Group` for a project group included in the list alongside its members.

### Project builds (assemblies)

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

### Development environment branches

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

### User lists

A user list holds either the users of an application or the users of the control panel. An
application has a list of its own, named after it, and the application card points at it with
`default-user-list`. The control panel has one list per installation.

- `GET /user-lists` – the list: `id`, `presentation`, `space-id`. There is no
  server-side name filter. `GET /user-lists/{id}` – the full card. `POST /user-lists` creates one and requires the whole card: an incomplete body is answered with a 500 and the misleading text "Failed to
  parse json". `DELETE /user-lists/{id}` removes it.
- `GET|PUT /user-lists/{id}/settings/self-registration` – `{enabled, phone-required, email-required}`, the control panel's "allow users to register themselves".
- `GET|POST /user-lists/{id}/settings/account-services-settings`, `PUT|DELETE .../{account-service-id}` – the account services. An entry is `{account-service-id, account-service-type, local-id, enabled, create-user-on-auth, additional-settings}`. The type
  `Local` authenticates by a password; the rest are external: `OIDC`,
  `Cas`, `ActiveDirectory`, `Esia`. Both write operations require the whole entry.
- `GET|POST|DELETE /applications/{id}/userlists` – the ids of the lists connected to an application. Note the spelling:
  `userlists` here, `user-lists` at the top level. The link has no settings of its own.
- `GET /user-lists/{id}/users` – the users of the list, `id` and `login` among their fields.
  Entries include user access tokens and secrets. Remove confidential fields before recording
  the response in a log.

User-list API limitations:

- the rules for parsing an account service response are accepted under the key `userPropertiesCalculationRules`.
  Those rules are `presentation-rule`, `email-rule`, `phone-rule` and `response-kind`. The
  reference's own schema calls the field `calculation-rules`, and that spelling is answered with a
  400. A GET never returns the rules: the setting is write-only, and an API client cannot
  confirm it applied;
- the composition of an application's authentication forms is not in the API at all, and
  neither is the connection setting "users of the list are connected automatically on sign-in".
  Those stay in the control panel;
- a GET of an account service returns the `client_secret` of an OIDC client in cleartext, so
  such answers do not belong in logs and reports as they are;
- an unknown path of the Console API is answered with a **401** carrying "Handler of HTTP
  request ... not found", not a 404. When probing for the surface, that is the sign that a
  method does not exist.

### Application tasks

`GET /tasks/application-tasks` – list of tasks for all applications. There is no server-side filter, so filter
on the client. Task fields: `id`, `application-id`, `status` (including
`Error`, `Failed`), `operation-type`, `error-message`, `start-date` (ISO 8601, may
end with `Z`).

## Build file format (.xasm / .xlib)

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
  project kind: \"Extension\"". The console writes the same pair for an extension.

- then the project files at paths `{vendor}/{name}/...` relative to the repository root. The project
  directory must follow the scheme `{repo}/{vendor}/{name}/Проект.yaml`. Path separators in the archive are forward
  slashes, on Windows too.

Build file name: `{Имя} {Version}.xasm` (with a space).

Project metadata comes from `Проект.yaml`. It is YAML, and parsing the flat top-level "key:
value" pairs is enough; skip the nested indented lines. 1C:Element supports bilingual sources,
including descriptors with English keys. Read each key in both spellings:
`Имя`/`Name`, `Поставщик`/`Vendor`, `Версия`/`Version`
(base, e.g. `1.0`) and `ВидПроекта`/`ProjectKind`. The value `Библиотека` or
`Library` means a library, `Расширение` or `Extension` an extension; anything else
means an application. When both spellings of a key are present, the Russian value takes
precedence. The service file names are bilingual too: the 1C:Element converter accepts
`Project.yaml` and `Проект.yaml`, `Subsystem.yaml` and `Подсистема.yaml`. An English descriptor
also uses English enumeration values, such as `VisibilityScope: Global`.

When the build version is not set explicitly, it is built as `{base version}-{N+1}`, where N is the
counter from the version of the project's latest build of the same base version. `deploy`
takes N as the higher of the latest build in the list and the highest number recorded in the
local upload registry for that project and base: the server counts on from the highest number
it has ever given, deleted builds included. A project bumped to a new base version starts from
`-1` again, whatever counters the old base reached. With no last build of that base,
the suffix comes from the CI run number in the environment: the first numeric value of
`CI_PIPELINE_IID`, `GITHUB_RUN_NUMBER`, `BUILD_NUMBER`, in that order. Otherwise a clean CI checkout
would produce `-1` every time. With no CI number either, the version is
`{base version}-1`.

Git metadata, meaning the commit hash and the branch name, comes from the git repository that
contains the project directory. When git is unavailable, the fields stay empty.

File selection for the archive:

- only these extensions are included: `.yaml .xbsl .xbql .md .txt .json` (sources), `.png .svg .jpg .jpeg .gif .webp .ico` (images),
  `.css .htm .html .js .woff .woff2 .ttf .eot` (web resources);
- the extension filter does not apply inside a `Ресурсы` directory, at any level and in
  subdirectories too: according to the 1C:Element documentation a resource is an arbitrary
  file, so everything there goes in;
- the description files of a SOAP service client are included wherever they lie: `<Client>.Wsdl.<n>`
  and `<Client>.Xsd`. They are stored next to the project element and read by name;
- the directories `.git`, `.claude`, `.github`, `__pycache__`, `node_modules`, `.venv` and all hidden ones (starting with a dot) are excluded;
- the files `.gitignore`, `.env`, `.DS_Store` and `*.xasm`, `*.xlib` files are excluded.

### Parsing a built archive

The reverse of a build: from a `.xasm` or `.xlib` file you get the manifest, the
project properties from its `Проект.yaml` inside the archive, and the contents. It is needed
to attach a library to a project without unpacking its sources.

The directory structure defines the layout inside a project:

- a first-level directory is a **subsystem**. `Подсистема.yaml` is **optional**, and a library
  subsystem may have none at all, so it cannot be relied upon when looking for subsystems;
- a nested directory of a subsystem is a **package**. A package has no description file, and every directory contributes a name segment;
- the qualified name of a type: `{vendor}::{name}::{subsystem}[::{package}]::{TypeName}`. The same name without the last segment is what
  `Использование` and `импорт` take.

Only types with `ОбластьВидимости: Глобально` are visible outside, in the project that attached the library.
The default is `ВПодсистеме`, and the global scope is written explicitly.

Compatibility is checked against the `РежимСовместимости` property of `Проект.yaml`. The
`ВерсияТехнологии` property **does not exist** in `Проект.yaml`: it belongs to the body of the
Console API request that creates an application, not to the project file.

<a id="platform-behaviour-you-have-to-account-for"></a>

## Server behavior to account for

1. **Rollback without a message.** After an apply failure, such as a compilation
   error, the server restores the previous build and starts the application.
   `Running` does not confirm the apply. To verify it:
   - read [application tasks](#application-tasks) with status `Error` or `Failed`
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
