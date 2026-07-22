---
title: "The platform underneath"
description: "Console API v2, the build file format and the platform behaviours worth knowing about."
sidebar:
  label: Platform
  order: 6
---

Everything on this page is about the platform, not about the tool: what the Console API
looks like, what a build file is made of, and how the platform behaves in cases that surprise
you the first time. It is written down because the platform's own documentation does not cover
these corners, and because `elemctl` had to learn them the hard way.

You do not need this page to use the tool. It is here for the times when something behaves
oddly and you want to know what happens underneath – or when you are writing your own client.

## Console API v2 contract

Common prefix: `{base}/console/api/v2`. Request and response bodies are JSON (except for build upload). Field names are in kebab-case.

### Applications

- `GET /applications` – list; optional `name` query (filter).
- `GET /applications/{id}` – card. Significant response fields: `id`, `status`, `uri` (address of the running application), `error` (error text, if any), `technology-version`, `date-updated`, `display-name`, `publication-context`, `source` (an object with source information, containing among other things `project-version` – the version of the applied build).
- `POST /applications` – create. Body:
  - `source` – the object `{"type": "repository"}` plus exactly one of the keys: `project-version-id` (id of the source build) or `image-id` (project id);
  - `display-name`, `publication-context` – publication name and path;
  - `development-mode` – boolean, whether to create a development environment;
  - optional `space-id`, `technology-version`.
- `DELETE /applications/{id}` – delete.
- `PUT /applications/{id}/status/start` – start.
- `PUT /applications/{id}/status/stop` – stop.
- `POST /applications/{id}/actions/debug` – data for a debug session (`ApplicationDebugInfo`: `{"debug-token": ..., "debug-address": ...}`). The request body is empty; requires debugging enabled on the server (`config/debug.yml` `enabled: true`).
- `POST /applications/{id}/project/update` – apply a build to the application. Body: `{"source": {"type": "repository", "image-id": "<build id>"}}` or `{"source": {"type": "repository", "project-id": "<id>", "assembly-version": "<version>"}}` (assembly-version is optional).
- `POST /applications/{id}/dumps` – create a dump. Body: `include-users`, `include-binary-data` (booleans), `description` (string).
- `GET /applications/{id}/dumps/{dumpId}` – dump status.

Application statuses: stable `Running`, `Stopped`, `Error`; transitional `Starting`, `Stopping`, `Initializing`, `Updating`, `Frozen`, `Creating`. During transitions the `status` field may also be empty.

### Technology version

- Reading – from the `technology-version` field of the application card (a dedicated read endpoint is not present in all platform versions – do not use it).
- Update: `POST /tasks/group-tasks/update-applications-technology`, body `{"technology-version": "<version>", "applications": ["<app-id>"]}`. Returns a group task; its status – `GET /tasks/group-tasks/{taskId}`.

### Spaces and projects

- `GET /spaces` – list of spaces.
- `GET /projects` – list of projects; `GET /projects/{id}` – card; `DELETE /projects/{id}` – delete.

### Project builds (assemblies)

- Uploading a build file – a binary POST (Content-Type `application/octet-stream`, body – the file bytes):
  - `POST /projects/{id}/assemblies` – add a build to an existing project;
  - `POST /projects` – create a new project from a build.
  Query parameters (all optional): `SpaceId`, `BranchName`, `CommitId`, `CommitMessage`. Note: the names of these query parameters are in PascalCase. The response contains the id of the created build in one of the fields: `image-id`, `assembly-id`, or `id` (check in this order).
- `GET /projects/{id}/assemblies` – list of builds. Each element contains `assembly-version` (a string like `1.0-42`) and an id (`id` or `image-id`). The response may be either an array or an object with the list in the `items` or `assemblies` field.
- `GET /projects/{id}/assemblies/{assembly-id}` – build card; `DELETE .../{assembly-id}` – delete. The API addresses a build ONLY by UUID: a version gets a 400 "Version is not a valid UUID". The client must also accept a version (that is what the user sees), resolving it to an id via the build list (`assembly-version`/`project-version`); note that the platform renumbers the manifest version on upload. Deleting a build that took part in an apply (even a rolled-back one) is rejected by the platform with a 500.

Comparing build versions: by the numeric suffix after the last hyphen (`1.0-10` is newer than `1.0-9`; lexicographic comparison gives the wrong order).

### Development environment branches

- `GET /branches` – list; optional queries `project-id`, `name`.
- `GET /branches/{id}` – card. Fields: `name`, `kind`, `project`, `application`, `source-branch`, `deletion-mark`, `version-stamp`.
- `POST /branches` – create. Body: `name`, `kind: "development"`, `project: {"id": "<id>"}`, optionally `application: {"id": "<id>"}`.
- `PUT /branches/{id}` – modify. The platform uses optimistic locking: first read the card, then send a body assembled from the current values – `name`, `kind`, `deletion-mark`, `version-stamp` (must be returned as is), `source-branch` and `application` – collapsed to `{"id": ...}` (or `{"name": ...}` if there is no id). To rebind to an application, replace `application` with `{"id": "<new app-id>"}`.
- Accepting branch changes (merge) – the same `PUT /branches/{id}` with an additional body key `write-parameters: {"merge": true}`.
- `DELETE /branches/{id}` – delete the branch.

The tool works ONLY with the documented Console API v2. Internal (undocumented) platform console APIs are not used and not described.

### Application tasks

`GET /tasks/application-tasks` – list of tasks for all applications (there is no server-side filter – filter on the client). Task fields: `id`, `application-id`, `status` (including `Error`, `Failed`), `operation-type`, `error-message`, `start-date` (ISO 8601, may end with `Z`).

## Build file format (.xasm / .xlib)

A build file is a ZIP archive (deflate):

- at the root, `Assembly.yaml` – the manifest, flat key-value pairs:

  ```
  ManifestVersion: 1.0
  ProjectKind: Application | Library
  Vendor: <vendor>
  Name: <project name>
  Version: <version, e.g. 1.0-42>
  Created: <UTC, format YYYY.MM.DD HH:MM:SS>
  BranchName: <git branch name>
  CommitId: <commit hash>
  ```

  For a library (`ProjectKind: Library`), a `Release:` line (empty value) is added at the end; the file extension is `.xlib`, for an application – `.xasm`.

- then the project files at paths `{vendor}/{name}/...` – relative to the repository root. The project directory must follow the scheme `{repo}/{vendor}/{name}/Проект.yaml`. Path separators in the archive are forward slashes (including on Windows).

Build file name: `{Имя} {Version}.xasm` (with a space).

Project metadata – from `Проект.yaml` (YAML; parsing flat top-level `key: value` pairs is sufficient, skip nested indented lines): `Имя`, `Поставщик`, `Версия` (base, e.g. `1.0`), `ВидПроекта` (the value `Библиотека` means a library, otherwise an application).

Build version, if not set explicitly: `{base version}-{N+1}`, where N is the counter from the version of the project's latest build; if there are no builds – `{base version}-1`.

Git metadata (commit hash, branch name) – from the git repository containing the project directory; if git is unavailable, leave them empty.

File selection for the archive:

- only these extensions are included: `.yaml .xbsl .xbql .md .txt .json` (sources), `.png .svg .jpg .jpeg .gif .webp .ico` (images), `.css .html .js .woff .woff2 .ttf .eot` (web resources);
- the directories `.git`, `.claude`, `.github`, `__pycache__`, `node_modules`, `.venv` and all hidden ones (starting with a dot) are excluded;
- the files `.gitignore`, `.env`, `.DS_Store` and `*.xasm`, `*.xlib` files are excluded.

### Parsing a built archive

The reverse of a build: given a `.xasm`/`.xlib` file – the manifest, the project properties from its `Проект.yaml` inside the archive, and the contents. It is needed to attach a library to a project without unpacking its sources.

The layout inside a project (directories are the only source of truth about the contents):

- a first-level directory is a **subsystem**; `Подсистема.yaml` is **optional** (a library subsystem may have none at all), so it cannot be relied upon when looking for subsystems;
- a nested directory of a subsystem is a **package**; a package has no description file, every directory contributes a name segment;
- the qualified name of a type: `{vendor}::{name}::{subsystem}[::{package}]::{TypeName}`. The same name without the last segment is what `Использование` and `импорт` take.

Only types with `ОбластьВидимости: Глобально` are visible outside, in the project that attached the library (the default is `ВПодсистеме`, the global scope is written explicitly).

Compatibility is checked against the `РежимСовместимости` property of `Проект.yaml`. The `ВерсияТехнологии` property **does not exist** in `Проект.yaml` – it belongs to the body of the Console API request that creates an application, not to the project file.

## Platform behavioral specifics (must be accounted for)

1. **Silent rollback of build apply.** If applying a build to the application fails (e.g., a compilation error), the platform silently rolls the application back to the previous build and starts it – the `Running` status does NOT mean success. A reliable check of the deploy result:
   - application tasks (section 4.6) with status `Error`/`Failed` whose `start-date` is not earlier than the moment the deploy started (do not count old errors from history!);
   - comparison of the actually applied version (`source.project-version` of the application card) with the version of the uploaded build;
   - for information – a check GET against the application `uri` (codes 401/403 are normal for closed applications and do not contradict success).
2. **Empty skeleton on creation.** Creating an application with a "project" source (`image-id` = project id) on some platform configurations yields an empty application without project data. A reliable source is a specific build (`project-version-id`), for example the project's latest build.
3. **Deletion with drafts.** If the application's development environment has unpublished edits, `DELETE /applications/{id}` returns 400 with `FAILED_PRECONDITION` in the body. There is no forced deletion in the API – only the control panel; the tool must provide a clear hint.
4. **Readiness of a new application.** After creation, the application is in transitional statuses and without a `uri` for some time – provide for waiting until ready (a `uri` has appeared and the status is stable). An `Error` status while waiting is an immediate error.
5. **Restart after apply.** `project/update` may restart the application itself. After the call, wait until it leaves the transitional statuses; if the result is not `Running` – stop it (if not `Stopped`), wait for `Stopped`, start it, wait for `Running`. Reasonable timeouts: waiting for stop ~3 min, for start/stabilization ~5 min, polling every ~10 s.
6. **Windows.** Temporary files and caches – only via `tempfile`; switch console output to UTF-8 (`reconfigure` for stdout/stderr), otherwise Cyrillic breaks.
