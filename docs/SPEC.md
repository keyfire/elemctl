# elemctl Specification

**English** · [Русский](SPEC.ru.md)

This document describes the Console API v2 contract of the 1C:Enterprise.Element platform (1cmycloud.com), the build file format, and the requirements for the elemctl tool. The specification contains only facts about the platform interface and product requirements – the implementation is designed from scratch.

## 1. Purpose and package composition

The `elemctl` Python package consists of three layers on top of a shared core:

1. **Library** – a programmatic client for Console API v2 and high-level operations (build, deploy). Python standard library only.
2. **CLI** – the `elemctl` console command (entry point `elemctl` in `[project.scripts]`).
3. **MCP server** – the same operations exposed as tools for AI agents; stdio transport; the `mcp>=1.2` dependency is included as the optional extra `elemctl[mcp]` (uses FastMCP from the `mcp` package).

Package requirements: name `elemctl`, version 0.1.0, Python >= 3.10, MIT license, author KeyFire, `src/elemctl/` layout, `dev` extra with pytest. The LICENSE, README.md, .env.example, and .gitignore files are provided by the customer and are not modified.

## 2. Connection configuration

Parameters are taken from three sources, in decreasing order of priority:

1. explicit arguments (CLI flags `--base-url`, `--client-id`, `--client-secret`);
2. environment variables;
3. the .env file: path from the `--env-file` flag, or, without it, the `.env` file in the current directory, if it exists.

Environment variables:

| Variable | Meaning | Required |
|---|---|---|
| `ELEMENT_BASE_URL` | platform base URL, e.g. `https://1cmycloud.com` | yes |
| `ELEMENT_CLIENT_ID` | Client-Id for obtaining the token | yes |
| `ELEMENT_CLIENT_SECRET` | Client-Secret | yes |
| `ELEMENT_APP_ID` | default application | no |
| `ELEMENT_PROJECT_ID` | default project | no |
| `ELEMENT_SPACE_ID` | default space | no |

.env format: `KEY=VALUE` lines; empty lines and lines starting with `#` are skipped; a leading `export ` prefix and single/double quotes around the value are allowed; UTF-8 encoding, a BOM is possible (read as `utf-8-sig`). A trailing slash in `ELEMENT_BASE_URL` is trimmed.

## 3. Authentication

Obtaining a token: `POST {base}/console/sys/token`

- header `Authorization: Basic base64(client_id:client_secret)`;
- body `grant_type=client_credentials`, Content-Type `application/x-www-form-urlencoded`.

The response is a JSON object; the token is in the first non-empty of the fields `id_token`, `token`, `value`, `access_token`. Special case: the `access_token` value may be the string `"Not implemented"` – this is not a token, ignore the field.

All other requests use the header `Authorization: Bearer {token}`.

The token lives for about an hour: cache it in a file in the system temporary directory (`tempfile.gettempdir()`, NOT a hardcoded `/tmp` – the tool also runs on Windows) with a TTL of 1 hour; the cache key must distinguish base_url + client_id pairs. On a 401 response, refresh the token forcibly and retry the request once.

## 4. Console API v2 contract

Common prefix: `{base}/console/api/v2`. Request and response bodies are JSON (except for build upload). Field names are in kebab-case.

### 4.1. Applications

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

### 4.2. Technology version

- Reading – from the `technology-version` field of the application card (a dedicated read endpoint is not present in all platform versions – do not use it).
- Update: `POST /tasks/group-tasks/update-applications-technology`, body `{"technology-version": "<version>", "applications": ["<app-id>"]}`. Returns a group task; its status – `GET /tasks/group-tasks/{taskId}`.

### 4.3. Spaces and projects

- `GET /spaces` – list of spaces.
- `GET /projects` – list of projects; `GET /projects/{id}` – card; `DELETE /projects/{id}` – delete.

### 4.4. Project builds (assemblies)

- Uploading a build file – a binary POST (Content-Type `application/octet-stream`, body – the file bytes):
  - `POST /projects/{id}/assemblies` – add a build to an existing project;
  - `POST /projects` – create a new project from a build.
  Query parameters (all optional): `SpaceId`, `BranchName`, `CommitId`, `CommitMessage`. Note: the names of these query parameters are in PascalCase. The response contains the id of the created build in one of the fields: `image-id`, `assembly-id`, or `id` (check in this order). The console shows a project under the name of the last uploaded build (the manifest `Name`), so a build uploaded into a project under a different name silently renames that project – the client warns about such a mismatch before uploading (best effort, never blocks the upload).
- `GET /projects/{id}/assemblies` – list of builds. Each element contains `assembly-version` (a string like `1.0-42`) and an id (`id` or `image-id`). The response may be either an array or an object with the list in the `items` or `assemblies` field.
- `GET /projects/{id}/assemblies/{assembly-id}` – build card; `DELETE .../{assembly-id}` – delete. The API addresses a build ONLY by UUID: a version gets a 400 "Version is not a valid UUID". The client must also accept a version (that is what the user sees), resolving it to an id via the build list (`assembly-version`/`project-version`); note that the platform renumbers the manifest version on upload. Deleting a build that took part in an apply (even a rolled-back one) is rejected by the platform with a 500.

Comparing build versions: by the numeric suffix after the last hyphen (`1.0-10` is newer than `1.0-9`; lexicographic comparison gives the wrong order).

### 4.5. Development environment branches

- `GET /branches` – list; optional queries `project-id`, `name`.
- `GET /branches/{id}` – card. Fields: `name`, `kind`, `project`, `application`, `source-branch`, `deletion-mark`, `version-stamp`.
- `POST /branches` – create. Body: `name`, `kind: "development"`, `project: {"id": "<id>"}`, optionally `application: {"id": "<id>"}`.
- `PUT /branches/{id}` – modify. The platform uses optimistic locking: first read the card, then send a body assembled from the current values – `name`, `kind`, `deletion-mark`, `version-stamp` (must be returned as is), `source-branch` and `application` – collapsed to `{"id": ...}` (or `{"name": ...}` if there is no id). To rebind to an application, replace `application` with `{"id": "<new app-id>"}`.
- Accepting branch changes (merge) – the same `PUT /branches/{id}` with an additional body key `write-parameters: {"merge": true}`.
- `DELETE /branches/{id}` – delete the branch.

The tool works ONLY with the documented Console API v2. Internal (undocumented) platform console APIs are not used and not described.

### 4.6. Application tasks

`GET /tasks/application-tasks` – list of tasks for all applications (there is no server-side filter – filter on the client). Task fields: `id`, `application-id`, `status` (including `Error`, `Failed`), `operation-type`, `error-message`, `start-date` (ISO 8601, may end with `Z`).

## 5. Build file format (.xasm / .xlib)

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

Project metadata – from `Проект.yaml` (YAML; parsing flat top-level `key: value` pairs is sufficient, skip nested indented lines). Bilingual sources are a declared platform capability – a descriptor written with English keys deploys fine – so every key is read in both spellings: `Имя`/`Name`, `Поставщик`/`Vendor`, `Версия`/`Version` (base, e.g. `1.0`), `ВидПроекта`/`ProjectKind` (the value `Библиотека`/`Library` means a library, otherwise an application). The Russian spelling wins when both are present.

Build version, if not set explicitly: `{base version}-{N+1}`, where N is the counter from the version of the project's latest build. Without a last build, the suffix comes from the CI run number in the environment – the first numeric value of `CI_PIPELINE_IID`, `GITHUB_RUN_NUMBER`, `BUILD_NUMBER` (in that order) – so a clean CI checkout does not produce `-1` on every run; with no CI number either, the version is `{base version}-1`.

Git metadata (commit hash, branch name) – from the git repository containing the project directory; if git is unavailable, leave them empty.

File selection for the archive:

- inside resource directories (the literal directory name is `Ресурсы`) – at any level, including their subdirectories – files of ANY extension are included: per the platform documentation a resource is an arbitrary file (`.pdf`, `.htm`, `.mxl`, `.docx`, `.xsd` etc.);
- outside resource directories only these extensions are included: `.yaml .xbsl .xbql .md .txt .json` (sources), `.png .svg .jpg .jpeg .gif .webp .ico` (images), `.css .htm .html .js .woff .woff2 .ttf .eot` (web resources);
- the directories `.git`, `.claude`, `.github`, `__pycache__`, `node_modules`, `.venv` and all hidden ones (starting with a dot) are excluded;
- the files `.gitignore`, `.env`, `.DS_Store` and `*.xasm`, `*.xlib` files are excluded – including inside resource directories.

### 5.1. Parsing a built archive

The reverse of a build: given a `.xasm`/`.xlib` file – the manifest, the project properties from its `Проект.yaml` inside the archive, and the contents. It is needed to attach a library to a project without unpacking its sources.

The layout inside a project (directories are the only source of truth about the contents):

- a first-level directory is a **subsystem**; `Подсистема.yaml` is **optional** (a library subsystem may have none at all), so it cannot be relied upon when looking for subsystems;
- a nested directory of a subsystem is a **package**; a package has no description file, every directory contributes a name segment;
- the qualified name of a type: `{vendor}::{name}::{subsystem}[::{package}]::{TypeName}`. The same name without the last segment is what `Использование` and `импорт` take.

Only types with `ОбластьВидимости: Глобально` are visible outside, in the project that attached the library (the default is `ВПодсистеме`, the global scope is written explicitly).

Compatibility is checked against the `РежимСовместимости` property of `Проект.yaml`. The `ВерсияТехнологии` property **does not exist** in `Проект.yaml` – it belongs to the body of the Console API request that creates an application, not to the project file.

## 6. Platform behavioral specifics (must be accounted for)

1. **Silent rollback of build apply.** If applying a build to the application fails (e.g., a compilation error), the platform silently rolls the application back to the previous build and starts it – the `Running` status does NOT mean success. A reliable check of the deploy result:
   - application tasks (section 4.6) with status `Error`/`Failed` whose `start-date` is not earlier than the moment the deploy started (do not count old errors from history!);
   - comparison of the actually applied version (`source.project-version` of the application card) with the version of the uploaded build;
   - for information – a check GET against the application `uri` (codes 401/403 are normal for closed applications and do not contradict success).
2. **Empty skeleton on creation.** Creating an application with a "project" source (`image-id` = project id) on some platform configurations yields an empty application without project data. A reliable source is a specific build (`project-version-id`), for example the project's latest build.
3. **Deletion with drafts.** If the application's development environment has unpublished edits, `DELETE /applications/{id}` returns 400 with `FAILED_PRECONDITION` in the body. There is no forced deletion in the API – only the control panel; the tool must provide a clear hint.
4. **Readiness of a new application.** After creation, the application is in transitional statuses and without a `uri` for some time – provide for waiting until ready (a `uri` has appeared and the status is stable). An `Error` status while waiting is an immediate error.
5. **Restart after apply.** `project/update` may restart the application itself. After the call, wait until it leaves the transitional statuses; if the result is not `Running` – stop it (if not `Stopped`), wait for `Stopped`, start it, wait for `Running`. Reasonable timeouts: waiting for stop ~3 min, for start/stabilization ~5 min, polling every ~10 s.
6. **Error is terminal.** A stable `Error` (e.g., after a failed apply) is an immediate failure: surface the error messages of the application tasks (section 4.6) right away. Do not try to stop/restart such an application and do not keep waiting for another status – from `Error` it does not transition to `Stopped`, and the wait just eats the whole timeout.
7. **Windows.** Temporary files and caches – only via `tempfile`; switch console output to UTF-8 (`reconfigure` for stdout/stderr), otherwise Cyrillic breaks.

## 7. CLI requirements

Common flags (before the subcommand): `--base-url`, `--client-id`, `--client-secret`, `--env-file`, `--timeout` (seconds, default 60), `--version`.

Output: the result is JSON on stdout (`ensure_ascii=False`, indent 2); progress of long operations – lines on stderr; errors – JSON with an `error` field on stderr and return code 1.

Commands (significant flags in parentheses):

- `token` – obtain and print the token.
- `apps list [--name --brief]`, `apps get [APP_ID]`, `apps find NAME [--include-deleted]`,
  `apps create NAME [--project-id --version-id --latest-build --space-id
  --tech-version --no-dev-mode --wait]`,
  `apps ensure NAME [--project-id --version-id --latest-build --space-id
  --tech-version --no-dev-mode --wait]`, `apps delete APP_ID`,
  `apps start [APP_ID]`, `apps stop [APP_ID]`.
  - `apps list --name` filters by a case-insensitive name substring on the client (section 4.1: the platform ignores the query parameter); `--brief` prints brief cards (id, name, status, uri, applied version) instead of full ones.
  - `APP_ID` of `apps get/delete/start/stop/debug` is the application id (UUID) or its exact name: a non-UUID value is resolved through the list by an exact case-insensitive match (deleted applications do not count). No match is an error; several matches are an error listing the ids – destructive commands must not guess.
  - `apps find` searches by an exact (case-insensitive) name match among the fields `name`, `display-name`, `publication-context`; output `{"id": ..., "found": true|false}`, return code 0 in both cases – the absence of an application is an answer, not an error. A non-zero return code means the request failed and is accompanied by JSON with an `error` field on stderr. In scripts, check the `found` field, not the return code.
  - Deleted applications remain in the platform list with the `Deleted` status and their former `id`. `apps find` SKIPS them: the found id must be usable, otherwise the caller gets an id on which `apps get` and `deploy` return 404. The `--include-deleted` flag restores the former behavior – searching among all applications, including deleted ones.
  - `apps ensure` idempotently brings an application with the given name into existence: it searches by the `apps find` rules (deleted ones do not count) and creates only if absent. Output `{"id": ..., "created": true|false}`; `created: false` means the application already existed and was NOT touched. The creation flags are the same as for `apps create` and take effect only when creation happens. An existing application is never recreated: `delete` + `create` produce a new URL and break external bindings to the former one.
  - `--latest-build` – use the project's latest build as the source (protection against an empty skeleton, section 6.2); `--wait` – wait until ready (section 6.4) and output the final card.
- `spaces list`.
- `projects list`, `projects get [PROJECT_ID]`, `projects delete PROJECT_ID`.
- `builds list [--project-id]`, `builds get VERSION [--project-id]`,
  `builds upload FILE [--project-id --new-project --space-id --branch --commit
  --commit-message]`, `builds delete VERSION [--project-id]`. `builds upload`
  reports the chosen target in the output (`project-id`, `project-id-source`:
  `flag`/`env`/none) and notes on stderr when the target comes from
  `ELEMENT_PROJECT_ID`; `--new-project` ignores the environment binding and
  always creates a new project (mutually exclusive with `--project-id`).
- `build [--project-dir --output --build-version --last-build --commit
  --branch --kind {application,library} --require-clean]` – build the archive locally.
  Output: `file`, `name`, `vendor`, `version`, `version-source`
  (`flag`/`last-build`/the CI variable name/`default`), `kind`, `branch`, `commit`,
  `dirty` (whether the project directory has uncommitted changes; null when git is
  unavailable) – the version is a field of its own so CI does not parse the file name.
  Without `--project-dir`, the project directory is found automatically
  (the first directory with `Проект.yaml` when descending from the current one). `--kind`
  defaults based on `ВидПроекта`. `--require-clean` aborts before building when the
  project directory has uncommitted changes (git unavailable also aborts: there is
  nothing to confirm a clean tree with).
- `deploy [--app-id --project-id --project-dir --output --build-version
  --branch --commit --commit-message --dry-run --require-clean]` –
  the full cycle: build -> upload -> apply -> restart -> verification of the actual apply (section 6.1). Output – a JSON report with fields: `app-id`, `uri`, `status`, `version`, `assembly-id`, `applied-version`, `applied` (true/false/null – null when the actual version could not be determined), `uri-status`, `problems` (list of strings), `ok` (boolean), `dirty`/`dirty-files` (uncommitted changes of the project directory at build time – the build captures the current disk state, so the divergence from HEAD must be visible; a warning also goes to stderr; null when git is unavailable). Return code 0 only when `ok`. `--dry-run` – build only. `--require-clean` – abort before building on a dirty tree.
- `branches list [--project-id --name]`, `branches get ID`,
  `branches create NAME [--project-id --app-id]`,
  `branches update ID [--app-id]`, `branches delete ID`,
  `branches merge ID`.
- `dumps create [APP_ID] [--description]`, `dumps get APP_ID DUMP_ID`.
- `tasks list [--app-id]`, `tasks get-group TASK_ID`.
- `tech get [APP_ID]`, `tech set APP_ID VERSION`.
- `debug-adapter` – the path to the platform debug adapter directory supplied by a plugin (the `elemctl.debug_adapter` entry-point group, section 10). Output `{"path": ..., "found": true, "adapter-class": ...}` when present or `{"path": null, "found": false}`; exit code 0 in both cases. The `path` is a ready value for the VS Code extension's `xbslDebug.adapterPath` (a directory with a `repo/` subdirectory).
- `plugins` – plugin diagnostics: the declared adapter directories and whether each holds jars (`{"debug-adapter": [{"path": ..., "has-jars": true|false}]}`).
- `self-update [--version X]` – update the installed elemctl by unpacking the wheel from PyPI into site-packages, without touching busy exe files (plain pipx/pip breaks the install when `elemctl.exe` is held by a running MCP server; only the package files are updated, and the exe stub calls the new code). Fixes `pipx_metadata.json`. Output `{updated, from, to}`.
- `mcp` – start the MCP server; without the extra installed – a clear error with the hint `pip install "elemctl[mcp]"`.

Positional APP_ID/PROJECT_ID marked as optional above are taken from the configuration (`ELEMENT_APP_ID`/`ELEMENT_PROJECT_ID`) when absent; if those are empty too – an error.

## 8. MCP server requirements

Server name `elemctl`, stdio transport, credentials – from the same environment variables/.env. In the server instructions, warn about the silent rollback of build apply (section 6.1). Tools (docstrings – short, in Russian):

`list_apps(name="")` – `name` filters by a case-insensitive substring on the
client (section 4.1), `get_app(app_id)`, `find_app(name)`,
`create_app(name, project_id="", version_id="", space_id="",
development_mode=True)` – when only project_id is given, the project's latest build is
automatically used as the source (section 6.2);
`start_app(app_id)`, `stop_app(app_id)`, `debug_info(app_id)` – data for a
debug session (requires debugging enabled on the server), `debug_adapter()` –
the path to the platform debug adapter from a plugin (section 10; a local
operation that does not call the platform), `delete_app(app_id)`
(the docstring – a warning about irreversibility and URL change), `list_spaces()`,
`app_id` of `get_app`/`delete_app`/`start_app`/`stop_app`/`debug_info` is the
id (UUID) or the exact application name (resolved like the CLI does),
`list_projects()`, `list_builds(project_id)`,
`build_assembly(project_dir="", output_dir="", version="")`,
`inspect_assembly(file)` – parsing of a built archive (section 5.1; a local operation),
`deploy(app_id, project_id, project_dir="", version="", branch="",
commit_message="")` – returns the deploy report plus a `log` field with progress
lines; `apply_build(app_id, version_id)`, `verify_deploy(app_id,
expected_version="", since_minutes=30)` – verification of the apply per section 6.1;
`list_app_tasks(app_id="")`, `list_branches(project_id="", name="")`,
`merge_branch(branch_id)`.

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
  platform identifiers quoted as they are (`Проект.yaml`, `Ресурсы`, `Имя`, `Поставщик`) and
  the Russian data of test fixtures. Straight quotes `"` in text, dashes –
  en dash `–` (not em dash), ellipsis – three dots `...`.
- The library does not print to stdout/stderr itself – progress is delivered via a
  callback passed by the caller.
- API errors – a dedicated exception with server response details (JSON-serializable).

## 10. Plugins (entry points)

elemctl discovers external packages through `importlib.metadata.entry_points`. The core declares nothing about plugins in its own `pyproject.toml` – it is a consumer that reads the entry points on demand. This keeps non-publishable vendor artifacts (proprietary 1C jars) in a separate package while the public core stays clean.

The **`elemctl.debug_adapter`** group. The entry-point value is a path (Path/str) or a zero-argument callable returning a path (`() -> Path | str`). The path points to the platform debug adapter directory: a directory containing a `repo/` subdirectory with the adapter jars (including `com.e1c.g5rt.debugger.adapter*.jar`). This is a ready value for the VS Code extension's `xbslDebug.adapterPath`.

Declaration in a plugin package:

```toml
[project.entry-points."elemctl.debug_adapter"]
name = "my_package:adapter_root"
```

Discovery behavior:

- entry points are sorted by name; `debug_adapter_path()` returns the first directory that actually holds the adapter jars (a directory without `repo/` or without the adapter jar is skipped), otherwise `None`;
- a failing entry point is an error (`PluginError`, a subclass of `ElemctlError`), not a silent skip: a tool that silently drops a plugin would leave the user without debugging and without an explanation;
- the `ELEMCTL_NO_PLUGINS=1` environment variable disables discovery (a run with the core capabilities only).

Surfaces using the mechanism: the CLI `debug-adapter`/`plugins` (section 7), the MCP tool `debug_adapter` (section 8), and the VS Code extension, which requests the path from `elemctl debug-adapter` when the `adapterPath` setting is empty.

The adapter itself is extracted from the platform distribution by `tools/extract_adapter.py` (clean code, not shipped in the package distribution – `prune`): the `data/ide/theia/plugins/@1c-appengine-plugin/bin/debugger/` directory from the `.car` is copied into `<output>/<version>/`, and `index.json` is updated. The proprietary jars are not included in the public package – a separate plugin package ships them.
