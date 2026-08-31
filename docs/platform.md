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

- `GET /applications` – list. The `name` query parameter exists but the platform IGNORES it and returns the full list (verified against a live instance) – name filtering must be done client-side.
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
  The only query parameter (optional): `SpaceId`; note that its name is in PascalCase. The method has NO `BranchName`/`CommitId`/`CommitMessage` parameters: the Console API reference does not list them, and the server ignores them when sent (a direct POST with a real hash answers `commit-id: null`) - the commit on a build card only comes from the project's link to its repository. The response contains the id of the created build in one of the fields: `image-id`, `assembly-id`, or `id` (check in this order), plus an `artifact` object naming the project the build landed in: `artifact-id` (the project id – it opens as a project card), `configuration-id` (the `Ид` of `Проект.yaml`) and `name` (the project presentation). The console shows a project under the name of the last uploaded build (the manifest `Name`), so a build uploaded into a project under a different name silently renames that project; uploading a build with the project's own name puts the name back. `elemctl` warns about such a mismatch before uploading.
- **A project is identified by the `Vendor` + `Name` pair of the manifest**, not by the `Ид` of `Проект.yaml`. `POST /projects` therefore does not always create a project: when the pair is already known, the build is simply added to the project that owns it, and that project comes back in `artifact-id`. Two ways to hit a 409 `ALREADY_EXISTS`: uploading a version that is already there ("Версия сборки ... уже присутствует в группе проекта") and trying to register the same vendor+name under another project ("Сборка с именем поставщика ... уже зарегистрирована в другом проекте") – the second one is not worked around by generating a fresh `Ид` either. A second, throwaway project for the same sources can therefore only be had by renaming them.
- `GET /projects/{id}/assemblies` – list of builds. Each element contains `assembly-version` (a string like `1.0-42`) and an id (`id` or `image-id`). The response may be either an array or an object with the list in the `items` or `assemblies` field.
- `GET /projects/{id}/assemblies/{assembly-id}` – build card; `DELETE .../{assembly-id}` – delete. The API addresses a build ONLY by UUID: a version gets a 400 "Version is not a valid UUID". The client must also accept a version (that is what the user sees), resolving it to an id via the build list (`assembly-version`/`project-version`); note that the platform renumbers the manifest version on upload. Deleting a build is rejected with a 500 while an application created from it is still alive; once that application has really disappeared, the very same request succeeds (a build that only took part in an apply, even a rolled-back one, deletes without a fuss).

Comparing build versions: by the numeric suffix after the last hyphen (`1.0-10` is newer than `1.0-9`; lexicographic comparison gives the wrong order).

### Development environment branches

- `GET /branches` – list; optional queries `project-id`, `name`.
- `GET /branches/{id}` – card. Fields: `name`, `kind`, `project`, `application`, `source-branch`, `deletion-mark`, `version-stamp`.
- `POST /branches` – create. Body: `name`, `kind: "development"`, `project: {"id": "<id>"}`, optionally `application: {"id": "<id>"}`.
- `PUT /branches/{id}` – modify. The platform uses optimistic locking: first read the card, then send a body assembled from the current values – `name`, `kind`, `deletion-mark`, `version-stamp` (must be returned as is), `source-branch` and `application` – collapsed to `{"id": ...}` (or `{"name": ...}` if there is no id). To rebind to an application, replace `application` with `{"id": "<new app-id>"}`.
- Accepting branch changes (merge) – the same `PUT /branches/{id}` with an additional body key `write-parameters: {"merge": true}`.
- `DELETE /branches/{id}` – delete the branch.

The tool works ONLY with the documented Console API v2. Internal (undocumented) platform console APIs are not used and not described.

### User lists

A user list holds the users of an application (an application has one of its own, named after it – the application card points at it with `default-user-list`) or of the control panel (one per installation).

- `GET /user-lists` – the list: `id`, `presentation`, `space-id`; there is no server-side name filter. `GET /user-lists/{id}` – the full card. `POST /user-lists` creates one, and it wants the WHOLE card: an incomplete body is answered with a 500 and the misleading text "Failed to parse json". `DELETE /user-lists/{id}` removes it.
- `GET|PUT /user-lists/{id}/settings/self-registration` – `{enabled, phone-required, email-required}`, the control panel's "allow users to register themselves".
- `GET|POST /user-lists/{id}/settings/account-services-settings`, `PUT|DELETE .../{account-service-id}` – the account services. An entry is `{account-service-id, account-service-type, local-id, enabled, create-user-on-auth, additional-settings}`; the type `Local` authenticates by a password, the rest (`OIDC`, `Cas`, `ActiveDirectory`, `Esia`) are external. Both writes want the whole entry.
- `GET|POST|DELETE /applications/{id}/userlists` – the ids of the lists connected to an application. Note the spelling: `userlists` here, `user-lists` at the top level. The link carries no settings of its own.

Worth knowing before you build on this:

- the rules for parsing an account service response (`presentation-rule`, `email-rule`, `phone-rule`, `response-kind`) are accepted under the key `userPropertiesCalculationRules`, although the reference's own schema calls the field `calculation-rules` – that spelling is answered with a 400. A GET never returns the rules: the setting is write-only, and an API client cannot confirm it applied;
- the composition of the authentication FORMS of an application and the connection setting "users of the list are connected automatically on sign-in" are not in the API at all – those stay in the control panel;
- a GET of an account service returns the `client_secret` of an OIDC client in cleartext, so such answers do not belong in logs and reports as they are;
- an unknown path of the Console API is answered with a **401** carrying "Handler of HTTP request ... not found", not a 404 – when probing for the surface, that is the sign that a method does not exist.

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

Project metadata – from `Проект.yaml` (YAML; parsing flat top-level `key: value` pairs is sufficient, skip nested indented lines). Bilingual sources are a declared platform capability – a descriptor written with English keys deploys fine – so every key is read in both spellings: `Имя`/`Name`, `Поставщик`/`Vendor`, `Версия`/`Version` (base, e.g. `1.0`), `ВидПроекта`/`ProjectKind` (the value `Библиотека`/`Library` means a library, otherwise an application). The Russian spelling wins when both are present. The service file names are bilingual too: the platform converter accepts `Project.yaml`/`Проект.yaml` and `Subsystem.yaml`/`Подсистема.yaml`, and an English descriptor carries English enumeration VALUES as well (`VisibilityScope: Global`).

Build version, if not set explicitly: `{base version}-{N+1}`, where N is the counter from the version of the project's latest build. Without a last build, the suffix comes from the CI run number in the environment – the first numeric value of `CI_PIPELINE_IID`, `GITHUB_RUN_NUMBER`, `BUILD_NUMBER` (in that order) – so a clean CI checkout does not produce `-1` on every run; with no CI number either, the version is `{base version}-1`.

Git metadata (commit hash, branch name) – from the git repository containing the project directory; if git is unavailable, leave them empty.

File selection for the archive:

- only these extensions are included: `.yaml .xbsl .xbql .md .txt .json` (sources), `.png .svg .jpg .jpeg .gif .webp .ico` (images), `.css .htm .html .js .woff .woff2 .ttf .eot` (web resources);
- the extension filter does NOT apply inside a `Ресурсы` directory (at any level, subdirectories included): by the platform's own documentation a resource is an arbitrary file, so everything there goes in;
- the description files of a SOAP service client are included wherever they lie: `<Client>.Wsdl.<n>` and `<Client>.Xsd` – the platform keeps them next to the project element and reads them by name;
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
6. **Error is terminal.** A stable `Error` (e.g., after a failed apply) is an immediate failure: surface the error messages of the application tasks right away. Do not try to stop/restart such an application and do not keep waiting for another status – from `Error` it does not transition to `Stopped`, and the wait just eats the whole timeout.
7. **Windows.** Temporary files and caches – only via `tempfile`; switch console output to UTF-8 (`reconfigure` for stdout/stderr), otherwise Cyrillic breaks.
8. **The project is identified by vendor and name.** See the build upload above: the identity of a project is the `Vendor` + `Name` pair of the manifest. An upload without a project id is not "create a new project", it is "put it where this pair belongs".
9. **Deletion is asynchronous and ordered.** `DELETE /applications/{id}` returns immediately, and the application lives on for a while with a `DeleteApplication` task. While it exists, deleting the build it was created from is rejected with a 500. The order for cleanup: delete the application, wait until its card answers 404 (or the status becomes `Deleted`), and only then delete the build.
10. **Compilation is the server's, and it happens on apply.** A local build only packs an archive: the syntax, the types and the visibility of the sources are checked by the server compiler when a build is applied or an application is created out of it. There is no separate "compile" endpoint. Together with points 8 and 9 this is what `elemctl probe` is built out of: the sources go to their own project as a build with a one-off version, the compiler is reached through a throwaway application, and both are removed afterwards – so the working application is never at risk.
11. **Signing in to a freshly created application.** A new application gets its OWN, empty user list (the card points at it with `default-user-list`), password sign-in in it is off, and it has no account service. So the accounts used to sign in to other applications do not work here – and connecting another application's user list (`POST /applications/{id}/userlists`) together with enabling the local sign-in does NOT change it. What does work is a CONTROL PANEL account: the platform connects its users to the application itself, and they sign in right away. Worth knowing before raising a stand for a task: the way in does not follow from the card, and trying accounts is a bad idea – a user has a failed-attempt counter.
