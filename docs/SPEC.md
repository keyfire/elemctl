# elemctl Specification

**English** · [Русский](SPEC.ru.md)

This document describes the Console API v2 contract of the 1C:Enterprise.Element platform (1cmycloud.com), the build file format, and the requirements for the elemctl tool. It holds only facts about the platform interface and requirements for the product: the implementation is designed from scratch.

## 1. Purpose and package composition

The `elemctl` Python package consists of three layers on top of a shared core:

1. **Library** – a programmatic client for Console API v2 and high-level operations: build and deploy. Python standard library only.
2. **CLI** – the `elemctl` console command, entry point `elemctl` in `[project.scripts]`.
3. **MCP server** – the same operations exposed as tools for AI agents, over the stdio transport. The `mcp>=1.2,<3` dependency comes as the optional extra `elemctl[mcp]`. It uses the ergonomic server class of the `mcp` package: `FastMCP` in mcp 1.x, `MCPServer` in mcp 2.x.

Package requirements: name `elemctl`, version 0.1.0, Python >= 3.10, MIT license, author KeyFire, `src/elemctl/` layout, `dev` extra with pytest. The LICENSE, README.md, .env.example, and .gitignore files are given and are not modified.

## 2. Connection configuration

Parameters are taken from three sources, in decreasing order of priority:

1. explicit arguments (CLI flags `--base-url`, `--client-id`, `--client-secret`);
2. environment variables;
3. the .env file: path from the `--env-file` flag, or, without it, the `.env` file in the current directory, if it exists.

Environment variables:

| Variable | Meaning | Required |
|---|---|---|
| `ELEMENT_BASE_URL` | platform base URL starting with `http://` or `https://`, e.g. `https://1cmycloud.com` | yes |
| `ELEMENT_CLIENT_ID` | Client-Id for obtaining the token | yes |
| `ELEMENT_CLIENT_SECRET` | Client-Secret | yes |
| `ELEMENT_APP_ID` | default application | no |
| `ELEMENT_PROJECT_ID` | default project | no |
| `ELEMENT_SPACE_ID` | default space | no |
| `ELEMENT_CA_FILE` | additional PEM CA bundle for a private cloud | no |
| `ELEMENT_TLS_STRICT` | strict RFC 5280 certificate checks; `true` by default | no |
| `ELEMENT_TLS_VERIFY` | certificate and hostname verification; `true` by default | no |

.env format: `KEY=VALUE` lines. Empty lines and lines starting with `#` are skipped. A leading `export ` prefix is allowed, and the value may be wrapped in single or double quotes. The encoding is UTF-8 and a BOM is possible, so read the file as `utf-8-sig`. A trailing slash in `ELEMENT_BASE_URL` is trimmed. A nonempty base URL must start with `http://` or `https://`.

## 3. Authentication

Obtaining a token: `POST {base}/console/sys/token`

- header `Authorization: Basic base64(client_id:client_secret)`;
- body `grant_type=client_credentials`, Content-Type `application/x-www-form-urlencoded`.

The response is a JSON object, and the token sits in the first non-empty of the fields `id_token`, `token`, `value`, `access_token`. Special case: the `access_token` value can be the string `"Not implemented"`. That is not a token, so skip the field.

All other requests use the header `Authorization: Bearer {token}`.

The token lives for about an hour. Cache it in a file in the system temporary directory that `tempfile.gettempdir()` reports, not in a hardcoded `/tmp`, because the tool also runs on Windows. The cache lives an hour, and its key must distinguish base_url and client_id pairs. On a 401 response, refresh the token forcibly and retry the request once.

## 4. Console API v2 contract

Common prefix: `{base}/console/api/v2`. Request and response bodies are JSON, apart from the build upload. Field names are in kebab-case.

### 4.1. Applications

- `GET /applications` – list. The `name` query parameter exists, but the platform ignores it and returns the full list. That was verified against a live instance, so filtering by name has to happen on the client.
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
- `GET /projects` – list of projects; `GET /projects/{id}` – card; `DELETE /projects/{id}` – delete. The list is answered in full whatever the query, and deleted projects stay in it under the `deleted` flag with their former id. Filtering by name and hiding the deleted ones is the client's work, as with applications (section 4.1).

### 4.4. Project builds (assemblies)

- Uploading a build file – a binary POST (Content-Type `application/octet-stream`, body – the file bytes):
  - `POST /projects/{id}/assemblies` – add a build to an existing project;
  - `POST /projects` – create a new project from a build.
  The only query parameter, and an optional one at that, is `SpaceId`; note that its name is in PascalCase. The method has no `BranchName`, `CommitId` or `CommitMessage` parameters: the Console API reference does not list them, and the server ignores them when sent. A direct POST with a real hash answers `commit-id: null`. The commit on a build card only comes from the project's link to its repository, and the client does not send those parameters. The response carries the id of the created build in one of the fields `image-id`, `assembly-id` or `id`, checked in that order. Next to it sits an `artifact` object describing the project the build landed in: `artifact-id` is the project id and opens as a project card, `configuration-id` is the `Ид` of `Проект.yaml`, and `name` is the project presentation. The console shows a project under the name of the last uploaded build, meaning the manifest `Name`. So a build uploaded into a project under a different name renames that project and its group, and deleting the build does not undo it. The client refuses such an upload and names the price; uploading a foreign build on purpose takes `--force-rename`. The check is best effort: when the names cannot be compared, because the manifest is unreadable or the project card is unreachable, the upload proceeds as before. Not being able to compare is no proof of danger.
- **A project is identified by the pair `Vendor` + `Name` of the manifest** (section 6.8). `POST /projects` therefore does not always create a project: when a project with that pair already exists, the build is added to it and its `artifact-id` comes back in the response. There are two ways to hit a 409 `ALREADY_EXISTS`. The first is uploading a version that is already there, answered with "Версия сборки ... уже присутствует в группе проекта". The second is registering the same vendor and name under another project, answered with "Сборка с именем поставщика ... уже зарегистрирована в другом проекте"; that one happens even with a freshly generated `Ид` in `Проект.yaml`.
- `GET /projects/{id}/assemblies` – list of builds. Each element contains `assembly-version`, a string like `1.0-42`, and an id in `id` or `image-id`. The response is either an array or an object with the list in the `items` or `assemblies` field. **The method has no pages and reports no total.** `limit`, `size`, `pageSize`, `count`, `top`, `maxResults`, `page`, `pageNumber`, `offset`, `skip`, `from` and `start` are all ignored: the answers to every one of them match byte for byte, and neither the headers nor the body carry a counter or a cursor. Verified by live calls on two installations. **The platform deletes builds nobody uses,** and age has nothing to do with it: the vendor's help calls this automatic deletion of unused builds. A build an application runs is kept, and so are a library build another project uses, a release build, the project's default build and the build the project's repository was created from. Everything else goes when the collector gets to it. Seen live: seventeen builds of one day's series were made and one survived, the one the application runs, while a build from two months earlier is still listed because it is the project's first. So a listing is not the project's history and not a page of it. It is what survived, and the client must say so.
- `GET /projects/{id}/assemblies/{version}` – build card, `DELETE .../{version}` – delete. The last segment is what the method calls it: the version, which is `assembly-version` or `project-version`, a string like `1.0-42`. It is not the id of the card: a UUID there is answered with a 404 "Assembly with version <uuid> not found". Checked live on two installations of different ages, both behave this way. The pages used to claim the opposite, that only a UUID works and a version gets a 400 "Version is not a valid UUID"; anyone following that claim was left with an unreachable card whichever form they gave. An id is still an address a caller holds: the build list prints it, and an upload answers with one. So the client accepts both forms and looks the value up in the build list to get the version the method takes. A value in no card is named as missing instead of becoming a 404 out of the depths of the platform. When the address is refused with a 400 or a 404, the client tries the id as the segment too: no reachable installation wants it, but the 400 the pages described had to come from somewhere, and the second spelling costs one request. Note that the platform renumbers the manifest version on upload. Deleting a build is rejected with a 500 while an application created from it still exists (section 6.9); once that application is really gone, the same request succeeds. A 500 is an answer, not a misunderstood address: it is raised as it is and never retried with another spelling.

Build versions are compared by the numeric suffix after the last hyphen: `1.0-10` is newer than `1.0-9`. Lexicographic comparison gives the wrong order.

### 4.5. Development environment branches

- `GET /branches` – list; optional queries `project-id`, `name`.
- `GET /branches/{id}` – card. Fields: `name`, `kind`, `project`, `application`, `source-branch`, `deletion-mark`, `version-stamp`.
- `POST /branches` – create. Body: `name`, `kind: "development"`, `project: {"id": "<id>"}`, optionally `application: {"id": "<id>"}`.
- `PUT /branches/{id}` – modify. The platform uses optimistic locking, so read the card first, then send a body assembled from the current values. Those are `name`, `kind`, `deletion-mark` and `version-stamp`, which has to come back exactly as it was. Collapse `source-branch` and `application` to `{"id": ...}`, or to `{"name": ...}` when there is no id. To rebind to an application, replace `application` with `{"id": "<new app-id>"}`.
- Branch changes are accepted by that same `PUT /branches/{id}` with an additional body key `write-parameters: {"merge": true}`.
- `DELETE /branches/{id}` – delete the branch.

The tool works only with the documented Console API v2. It neither uses nor describes the internal, undocumented APIs of the platform console.

### 4.6. Application tasks

`GET /tasks/application-tasks` – list of tasks for all applications. There is no server-side filter, so filter on the client. Task fields: `id`, `application-id`, `status` (including `Error`, `Failed`), `operation-type`, `error-message`, `start-date` (ISO 8601, may end with `Z`).

### 4.7. User lists

A user list holds either the users of an application, which has a list of its own named after it, or the users of the control panel, which has one list per installation. What the panel calls the sign-in settings lives here.

- `GET /user-lists` – the list of user lists: `id`, `presentation`, `space-id`. There is no server-side name filter, so filter on the client.
- `GET /user-lists/{id}` – the full card: `self-registration`, `password-policy`, `password-policy-enabled`, `account-services-settings`, `confirmations`, the gateways, `include-personal-data-in-messages`.
- `GET|PUT /user-lists/{id}/settings/self-registration` – `{enabled, phone-required, email-required}`. This is the panel's "allow users to register themselves". The PUT wants the whole object.
- `GET|POST /user-lists/{id}/settings/account-services-settings`, `PUT|DELETE .../{account-service-id}` – the account services of the list. An entry is `{account-service-id, account-service-type, local-id, enabled, create-user-on-auth, additional-settings}`. The type `Local` authenticates by a password, so the panel's "allow signing in with a login and a password" is that entry being `enabled`. The other types are external services: `OIDC`, `Cas`, `ActiveDirectory`, `Esia`. The PUT wants the whole entry back.
- `GET /applications/{id}/userlists` – the ids of the lists connected to the application; `POST` connects, `DELETE` disconnects. Note the spelling: no dash here. There are no per-connection settings: the link is a set of ids and nothing more.
- The application card names the application's own list in `default-user-list`. That is the list of its users, and the panel list connected to it is a separate one.

Two things the panel can do and the API cannot, so both stay manual:

- the composition of an application's authentication forms is not in the API at all;
- the connection setting "users of the list are connected to the application automatically on sign-in" is not represented either. It is in neither `userlists`, which is a set of ids, nor the application's `account-services-settings`; on a stand where the setting is on, nothing appears there.

The rules for parsing the response of an account service are accepted in the body of an account service under the key `userPropertiesCalculationRules`. Those rules are `presentation-rule`, `email-rule`, `phone-rule` and `response-kind`, all of them JsonPath or XPath. There are two traps. The schema of the reference calls the same thing `calculation-rules`, and the platform answers 400 to that spelling. And a GET never returns the rules: the setting is write-only, so an API client cannot confirm it applied.

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

- then the project files at paths `{vendor}/{name}/...` relative to the repository root. The project directory must follow the scheme `{repo}/{vendor}/{name}/Проект.yaml`. For an application, locally available libraries declared in `Библиотеки`/`Libraries` are included recursively. A declared library without a project under the same repository root stays an external platform dependency. Unreferenced sibling projects are not included. Path separators in the archive are forward slashes, on Windows too.

Build file name: `{Имя} {Version}.xasm` (with a space).

Project metadata comes from `Проект.yaml`. It is YAML, and parsing the flat top-level "key: value" pairs is enough; skip the nested indented lines. Bilingual sources are a capability the platform declares, and a descriptor written with English keys deploys fine, so every key is read in both spellings: `Имя`/`Name`, `Поставщик`/`Vendor`, `Версия`/`Version` (base, e.g. `1.0`) and `ВидПроекта`/`ProjectKind`. The value `Библиотека` or `Library` means a library; anything else means an application. When both spellings of a key are present, the Russian one wins. The service file names are bilingual too: the platform converter accepts `Project.yaml` and `Проект.yaml`, `Subsystem.yaml` and `Подсистема.yaml`. So the descriptor is looked up by both names everywhere: project discovery, local library dependencies, archive inspection, the schema guard's availability probe.

When the build version is not set explicitly, it is built as `{base version}-{N+1}`, where N is the counter from the version of the project's latest build of the same base version. A project bumped to a new base version starts from `-1` again, whatever counters the old base reached. With no last build of that base, the suffix comes from the CI run number in the environment: the first numeric value of `CI_PIPELINE_IID`, `GITHUB_RUN_NUMBER`, `BUILD_NUMBER`, in that order. Otherwise a clean CI checkout would produce `-1` every time. With no CI number either, the version is `{base version}-1`.

Git metadata, meaning the commit hash and the branch name, comes from the git repository that contains the project directory. When git is unavailable, the fields stay empty.

File selection for the archive:

- inside resource directories, whose literal name is `Ресурсы`, files of any extension are included, at any level and in their subdirectories too: per the platform documentation a resource is an arbitrary file, such as `.pdf`, `.htm`, `.mxl`, `.docx` or `.xsd`;
- outside resource directories only these extensions are included: `.yaml .xbsl .xbql .md .txt .json` (sources), `.png .svg .jpg .jpeg .gif .webp .ico` (images), `.css .htm .html .js .woff .woff2 .ttf .eot` (web resources);
- the description files of a SOAP service client are included wherever they lie: `<Client>.Wsdl.<n>` and `<Client>.Xsd`. The platform puts them next to the project element rather than into a resource directory and forbids renaming them, so they are matched by name, not by extension;
- the directories `.git`, `.claude`, `.github`, `__pycache__`, `node_modules`, `.venv` and all hidden ones (starting with a dot) are excluded;
- the files `.gitignore`, `.env`, `.DS_Store` and any `*.xasm` or `*.xlib` are excluded, inside resource directories too.

### 5.1. Parsing a built archive

The reverse of a build: from a `.xasm` or `.xlib` file you get the manifest, the project properties from its `Проект.yaml` inside the archive, and the contents. It is needed to attach a library to a project without unpacking its sources.

The layout inside a project; only the directories tell the truth about the contents:

- a first-level directory is a **subsystem**. `Подсистема.yaml` or `Subsystem.yaml` is **optional**, and a library subsystem may have none at all, so it cannot be relied upon when looking for subsystems;
- a nested directory of a subsystem is a **package**. A package has no description file, and every directory contributes a name segment;
- the qualified name of a type: `{vendor}::{name}::{subsystem}[::{package}]::{TypeName}`. The same name without the last segment is what `Использование` and `импорт` take.

Only types with `ОбластьВидимости: Глобально`, in English `VisibilityScope: Global`, are visible outside, in the project that attached the library. The default is `ВПодсистеме`, or `InSubsystem`, and the global scope is written explicitly. An English descriptor carries English enumeration values as well, so those values are read in both spellings.

Compatibility is checked against the `РежимСовместимости` property of `Проект.yaml`. The `ВерсияТехнологии` property **does not exist** in `Проект.yaml`: it belongs to the body of the Console API request that creates an application, not to the project file.

## 6. Platform behaviour you have to account for

1. **Silent rollback of build apply.** When applying a build to the application fails, a compilation error for instance, the platform silently rolls the application back to the previous build and starts it. The `Running` status does not mean success. A reliable check of the result looks like this:
   - take the application tasks (section 4.6) with status `Error` or `Failed` whose `start-date` is not earlier than the moment the deploy started. Old errors from history do not count;
   - compare the actually applied version, the `source.project-version` of the application card, with the version of the uploaded build;
   - for information, make a check GET against the application `uri`. Codes 401 and 403 are normal for closed applications and do not contradict success.
2. **Empty skeleton on creation.** On some platform configurations an application created with a "project" source, meaning `image-id` set to the project id, comes out empty, with no project data. A reliable source is a specific build in `project-version-id`, for example the project's latest build.
3. **Deletion with drafts.** If the application's development environment has unpublished edits, `DELETE /applications/{id}` returns 400 with `FAILED_PRECONDITION` in the body. There is no forced deletion in the API, only the control panel, and the tool must provide a clear hint.
4. **Readiness of a new application.** After creation, the application sits in transitional statuses and without a `uri` for some time, so provide for waiting until it is ready: a `uri` has appeared and the status is stable. An `Error` status while waiting is an immediate error. A read of the card that breaks off on the network is a missed poll, not the end of the wait, since the application is being created all the same. The task list of section 4.6 carries the tasks of every application at once and is the read that breaks off most, so a broken read of it is made again, three times in all.
5. **Restart after apply.** `project/update` may restart the application itself. After the call, wait until it leaves the transitional statuses. If the result is not `Running`, stop it unless it is already `Stopped`, wait for `Stopped`, start it and wait for `Running`. Reasonable waits: about 3 minutes for a stop, about 5 minutes for a start and stabilization, polling every 10 seconds or so. A read of the card that breaks off is a missed poll in these waits too, as in section 6.4.
6. **`Error` is a final status.** A stable `Error`, after a failed apply for instance, is an immediate failure: surface the error messages of the application tasks (section 4.6) right away. Do not stop or restart such an application, and do not keep waiting for another status: from `Error` it never moves to `Stopped`, and the wait just burns the whole time budget.
7. **Windows.** Temporary files and caches go through `tempfile` only. Switch console output to UTF-8 with `reconfigure` for stdout and stderr, otherwise Cyrillic breaks.
8. **The project is identified by vendor and name.** A platform project is identified by the `Vendor` + `Name` pair of the manifest, not by the `Ид` of `Проект.yaml`. An upload without a project id lands in the project that already owns that pair, and creating a second project for the same pair is refused with a 409 (section 4.4). A truly separate project can only be had by renaming the sources, which is why an isolated compilation check is built around a throwaway application rather than a throwaway project.
9. **Deletion runs in the background and in order.** `DELETE /applications/{id}` returns immediately, and the application lives on for a while with a `DeleteApplication` task. While it exists, deleting the build it was created from is rejected with a 500. The order for cleanup is: delete the application, wait until its card answers 404 or its status becomes `Deleted`, and only then delete the build. A read of the card that breaks off during this wait is a missed poll as well, as in section 6.4.
10. **Compilation is the server's, and it happens on apply.** A local build only packs an archive. The syntax, the types and the visibility of the sources are checked by the server compiler when a build is applied or an application is created out of it. There is no separate "compile" endpoint, so the only way to check the sources without risking the working application is a throwaway application created from the same build (section 7, `probe`).
11. **Signing in to a freshly created application.** A new application gets its own empty user list (`default-user-list`, section 4.7), password sign-in in it is off, and it has no account service. The accounts used to sign in to other applications therefore do not work here, and connecting another application's user list (`POST /applications/{id}/userlists`) together with enabling the local sign-in does not change that; this was verified. What works is a control-panel account: the platform connects its users to the application itself, and the sign-in works right away. The tool has to say so out loud when it creates an application (section 7, `apps create` and `apps ensure`): the way in does not follow from the card, and it cannot be found by trying, because a user has a failed-attempt counter.
12. **A server that is still starting.** After a start or an update the server takes minutes to bring its console up; thirteen of them were seen after one update. All that time every console request, the token request included, is answered with a 404 whose text names the console application: `Application "console" not found`. That is the status a missing application or build gets, so only the text tells them apart. The client recognizes the answer in one place, for every request it makes, and raises an error that says what it means: the server is starting, repeat once `/console` answers 302. `deploy` waits it out by itself at any step of its cycle, for up to `--server-start-timeout` seconds (900 by default, 0 turns the wait off), and announces the start and the end of the wait. A request the console refused was never processed, so asking again is safe whatever its method. The other commands do not wait: they name the cause and stop.
13. **A removal is applied without a question.** A build whose sources no longer have a tabular part is applied as it is: the part goes, and its rows go with it. There is no refusal and no warning, the task ends well and the application keeps running; that was seen on a catalog with a row in the part. An attribute of a tabular part and an attribute of the object go the same way, with their values. A narrowed length or a changed type recreates the data of the object instead. What the deploy does about either is in section 7.

## 7. CLI requirements

Common flags are accepted in any position, after the subcommand too: `--base-url`, `--client-id`, `--client-secret`, `--env-file`, `--timeout` (seconds, default 60), `--json`, `--version`.

The connection flags are about talking to the platform. `build` and `inspect` never do that, so they refuse those flags instead of dropping them quietly. A call carrying `--env-file` reads as a build bound to a stand, and twice that left a reader asking whether a local build goes to the server after all; silence of that kind is what misleads. Nothing that worked stops working, because the flags changed nothing, and the refusal names the commands that do reach the platform: `deploy` and `builds upload`. It covers the flags only. `ELEMENT_*` variables and a `.env` next to the project are always around, and whether a build runs must not depend on them.

Output works like this: the result is JSON on stdout (`ensure_ascii=False`, indent 2), progress of long operations comes as lines on stderr, and an error is JSON with an `error` field on stderr plus return code 1.

`--json` makes that a guarantee rather than just a convention: for the duration of the call stdout is redirected to stderr, and the answer alone is written to the real stdout. A caller then parses stdout whole. Without the flag, anything a handler or a plugin prints stays in the stream ahead of the answer. A failure keeps to stderr and leaves stdout empty in this mode too.

`apps list` and `builds list` print their count and truncation lines after the answer, never before it. Other stderr output can still come first even for these two commands – a warning such as the one `ELEMENT_TLS_VERIFY=false` prints, or another command's own progress lines – so only stdout read on its own is safe to parse as a whole.

Commands, with the significant flags in parentheses:

- `token` – obtain and print the token.
- `apps list [--name --status --include-deleted --brief]`, `apps get [APP_ID]`, `apps find NAME [--include-deleted]`,
  `apps create NAME [--project-id --version-id --latest-build --space-id
  --tech-version --no-dev-mode --wait --verify --no-verify]`,
  `apps ensure NAME [--project-id --version-id --latest-build --space-id
  --tech-version --no-dev-mode --wait --verify --no-verify --apply]`,
  `apps apply [APP_ID] VERSION_ID`,
  `apps delete APP_ID`, `apps start [APP_ID]`, `apps stop [APP_ID]`.
  - `apps list --name` filters by a case-insensitive name substring, and it does so on the client because the platform ignores the query parameter (section 4.1). `--status` selects by the whole status word, several of them separated by commas. `--brief` prints brief cards instead of full ones: id, name, status, uri, applied version.
  - `apps list` hides the deleted applications. They stay in the platform list under the `Deleted` status, and a stand a few months old answers with hundreds of cards of which a handful are alive. `--include-deleted` brings them back, and so does `--status deleted`: a filter that would answer with nothing is worse than no filter. A cut nobody is told about is a trap of its own, so the command ends with a count line on stderr, "7 live of 324", plus the number shown when a filter narrowed the answer further. Whatever is cut, stdout stays the same JSON array.
  - `APP_ID` of `apps get`, `delete`, `start`, `stop` and `debug` is the application id (UUID) or its exact name. A value that is not a UUID is resolved through the list by an exact case-insensitive match, and deleted applications do not count. No match is an error, and several matches are an error listing the ids: destructive commands must not guess.
  - `apps find` searches for an exact, case-insensitive name match among the fields `name`, `display-name` and `publication-context`. Output is `{"id": ..., "found": true|false}` with return code 0 in both cases: the absence of an application is an answer, not an error. A non-zero return code means the request failed and comes with JSON carrying an `error` field on stderr. In scripts, check the `found` field, not the return code.
  - Deleted applications remain in the platform list with the `Deleted` status and their former `id`. `apps find` skips them: the found id must be usable, otherwise the caller gets an id on which `apps get` and `deploy` return 404. The `--include-deleted` flag restores the former behaviour, searching among all applications including deleted ones.
  - `apps ensure` idempotently brings an application with the given name into existence: it searches by the `apps find` rules, where deleted ones do not count, and creates only if absent. Output is `{"id": ..., "created": true|false, "sign-in": ...}`, and `created: false` means the application already existed and was left alone. The creation flags are the same as for `apps create` and take effect only when creation happens. An existing application is never recreated: `delete` and `create` produce a new URL and break external bindings to the former one. Because the creation flags include `--version-id`, an existing application gets two more fields in the answer: `applied`, whether it runs the requested assembly, and `applied-version-id`, the one it does run. Staying silent about that cost a stand that went to work on the previous build. `--apply` brings it to the assembly in the same call, and `apps apply` does it separately. `--verify` upgrades the verdict about an application that already runs the requested assembly from the card comparison to the full check. An application `ensure` had created used to answer `applied: true` on trust, since it was created from that assembly, and now answers with the checked verdict whenever a check ran.
  - `apps apply [APP_ID] VERSION_ID` applies an already uploaded assembly to an application and verifies the result (section 6.6). An apply is not a fact until it is verified: on a failure the platform silently rolls the application back to the previous build and starts it. The output is the verification report, and the exit code is 1 when the assembly did not land. Until this command, applying was reachable through the MCP tool alone, while long operations are the ones that want a CLI run in the background.
  - `apps create` and `apps ensure` end by saying how to sign in to the application (section 6.11). That is the `sign-in` field of the output, shaped `{"url", "account": "control-panel", "hint", "note"}`, plus the same two sentences on stderr. `url` is the application address out of the card, and it is `null` while the application has none yet, which is the case without `--wait`; the hint then says where to take it from. `account` is a code, not a text: the way in is a control-panel account, and the note says why the accounts used to sign in to other applications do not work here.
  - `--latest-build` uses the project's latest build as the source and protects against an empty skeleton (section 6.2). `--wait` waits until ready (section 6.4), verifies the result (section 6.6) and outputs the final card.
  - A source given by `--version-id` is looked up in the build list of the project before anything is created. The project is `--project-id`, or `ELEMENT_PROJECT_ID` when the flag is absent. The platform deletes the builds nobody uses and cannot create an application from a deleted one: it answers with a bare 400 "Can't create application", which reads like a limit on the number of applications. So the command refuses by itself. The refusal names the cause and offers the build that a running application of the project runs, or `--latest-build` when no application runs one. A project taken from `ELEMENT_PROJECT_ID` is named in the refusal, because the build may belong to another project. Without a project there is no list to look in, and the create goes as before.
  - Waiting means verifying. A failed apply is rolled back by the platform to the previous build, and the application comes up `Running` all the same, so a card handed back after a wait is not evidence that the build asked for is the one running. `--wait` therefore ends with the same check `apps apply` and `verify-deploy` do: the applied build id against the requested one, the application tasks that failed since the creation started, the uri. It puts the report into the `verify` field of the output and answers with exit code 1 when the check does not pass. `--verify` asks for the check on its own, and waits too, because there is nothing to check on an application still being created. `--no-verify` brings back the plain wait. Without either flag nothing is waited for and nothing is checked, as before.
  - The application exists once the create has answered, so a wait or a check that breaks off does not lose it. The output still carries the id: the card of `apps create`, the `id` of `apps ensure` with `applied: null`, since nothing was checked. The `wait-error` field holds the error that ended the wait, stderr names the `verify-deploy` call that checks the build later, and the exit code is 1. The answer used to be a bare network error without the id, and the id of an application that came up minutes later had to be looked up by name.
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
  service at all and nothing signs in by password, and `changed` says whether this very
  call altered anything: switching to the state that is already there sends no request.
- `projects list [--name --include-deleted]`, `projects get [PROJECT_ID]`, `projects delete PROJECT_ID`.
  - `projects list --name` filters by a case-insensitive name substring, and it does so on the client because the platform answers the full list (section 4.3). Projects marked deleted are hidden unless `--include-deleted` is given: a stand a few months old keeps hundreds of them in the list against a handful of live ones, and a check for a project name must not cost the full listing.
- `builds list [--project-id --limit --brief]`, `builds get VERSION [--project-id]`,
  `builds upload FILE [--project-id --new-project --force-rename --space-id
  --branch --commit --commit-message]`, `builds delete VERSION [--project-id]`.
  `builds upload` reports the chosen target in the output through `project-id` and
  `project-id-source` (`flag`, `env` or none) and notes on stderr when the target comes
  from `ELEMENT_PROJECT_ID`. `--new-project` ignores the environment binding and always
  creates a new project; it is mutually exclusive with `--project-id`. `--force-rename`
  allows uploading an assembly whose name differs, which renames the target project.
  `builds list` shows the ten newest builds, and `--limit 0` lifts the cut. It ends with a
  count line on stderr saying which of the two cuts the reader is looking at: the tool's
  `--limit`, or the platform's housekeeping (section 4.4: it deletes the builds nobody
  uses, whatever their age). "30 of 30" without that line was read as the project's whole
  history. The housekeeping is judged by the facts of the answer, not by the length of the
  listing: the platform hands out the numbers of a base version one after another, so a
  number the listing has not got is a build already taken away, and the line says how many
  are missing.
- `build [--project-dir --output --build-version --last-build --commit
  --branch --kind {application,library} --require-clean]` – build the archive locally.
  Output: `file`, `name`, `vendor`, `version`, `version-source`
  (`flag`, `last-build`, the CI variable name or `default`), `kind`, `branch`, `commit`
  and `dirty`, which says whether the project directory has uncommitted changes and is
  null when git is unavailable. The version is a field of its own so CI does not parse
  the file name. Without `--project-dir`, the project directory is found automatically:
  the first directory with `Проект.yaml` when descending from the current one. `--kind`
  defaults based on `ВидПроекта`. `--require-clean` aborts before building when the
  project directory has uncommitted changes; git being unavailable also aborts, because
  there is nothing to confirm a clean tree with.
- `inspect FILE` – parse a prebuilt archive (section 5.1). Local as well: the platform is
  not called, and the connection flags are refused the same way.
- `deploy [--app-id --project-id --project-dir --output --build-version
  --branch --commit --dry-run --require-clean --allow-data-loss
  --server-start-timeout]` –
  the full cycle: build -> upload -> apply -> restart -> verification of the actual apply (section 6.1). Output – a JSON report with fields: `app-id`, `uri`, `status`, `version`, `assembly-id`, `applied-version`, `applied` (true, false or null, where null means the actual version could not be determined), `uri-status`, `problems` (list of strings, the platform's texts as they came), `problems-lines` (the same broken into plain lines: JSON escapes a multi-line refusal into `
` and `	` exactly where it has to be read), `ok` (boolean), `dirty` and `dirty-files` (uncommitted changes of the project directory at build time). The build captures the current disk state, so the divergence from HEAD must be visible; a warning also goes to stderr, and null means git was unavailable. `hint` points at the log of the server when a task was refused without a compilation error in its text. The platform may answer with "Contact administrator for details" alone, and the cause then sits in the server log: the last `Caused by` line, with `SrcPath:` beside it naming the file the apply stopped at. An apply that leaves the application in `Error` ends the deploy with an error, and that error carries the same hint. Return code 0 only when `ok`. `--dry-run` builds and stops there, and `--require-clean` aborts before building on a dirty tree. `--server-start-timeout` is how many seconds a server that is still starting is waited out (section 6.12).
  Before anything is built, the schema guard reads the sources against the commit the applied build was made from, the `commit-id` of its card (section 4.4). The project directory is found the way the build finds it. A narrowed length or a changed type of an attribute, a dimension or a resource, the attributes of a tabular part included, and a removed dimension recreate or break the data, so the deploy refuses them unless `--allow-data-loss` is given. A removed attribute, resource, tabular part or attribute of a tabular part is a deliberate edit the server applies without asking (section 6.13): the deploy names each one on stderr and in the `schema-warnings` field and goes on. Fields are matched by `Ид`, so a rename keeps its data, and across a translation of the description only an `Ид` can tell that an element is gone. `schema-check` says what the guard did: `clean`, `warned` (removals only), `allowed`, or `skipped:<reason>` when there was nothing to compare against: `no-project-dir`, `read-failed`, `no-applied-build`, `applied-build-not-listed`, `no-commit-id` or `commit-unavailable`, each explained in words of its own. A skipped check is said once more after the verdict: a passed verification alone read as if the schema had been checked too.
- `verify-deploy [APP_ID] [--app-id --version-id --expected-version --since-minutes]` –
  the verification of section 6.1 on its own, deploying nothing. It looks at the
  application tasks in an error status raised over the last `--since-minutes` minutes,
  whose `error-message` carries the file and the position of a compilation error. Then it
  compares the applied build with the expected one: `--version-id` is the id of the
  uploaded build and the reliable comparison, `--expected-version` is the version string
  and the backup. It finishes with a control GET on the address. The report is the same
  as `deploy` gives, and the return code is 0 only when `ok`. It is what a CI script needs
  after `apps create`: a build that failed to apply is rolled back silently, and a status
  of `Running` proves nothing.
- `probe [--project-dir --output --build-version --name --space-id --keep
  --require-clean]` – an isolated compilation check of the sources: build ->
  upload -> a throwaway application (that is the compilation, section 6.10) ->
  errors with file and position -> cleanup. Before the build the manifest is
  checked for what the server needs to take a probe: `Представление`
  (`Presentation`), without which the console refuses the upload with a bare 500;
  `ЯзыкРазработки` (`DevelopmentLanguage`), a required property without which no
  application is created; and `ЯзыкиЛокализации` (`LocalizationLanguages`)
  whenever `ЯзыкПоУмолчанию` (`DefaultLanguage`) is set, since the server refuses
  that pair without naming the cause. A missing key stops the probe before
  anything is built or uploaded, and the error names every such key with the
  line to add, in the spelling the manifest uses. `ELEMENT_APP_ID` and
  `ELEMENT_PROJECT_ID` are deliberately left unused: the probe must not be able to
  reach the working application, and the target project is chosen by the platform
  out of the vendor and the name of the manifest (section 6.8). The default build
  version is `{base}-probe-{token}`. It has to be a new one every time, because a
  repeat is a 409, and it must not look like the project's latest build: the
  counter is numeric, and a non-numeric suffix keeps a probe build out of that
  comparison. Cleanup runs whether the compilation passed or failed, in the order
  of section 6.9: the application, then the build, then the project, and the
  project only if the probe itself created it. Output: `ok`, `project-dir`,
  `vendor`, `name`, `file`, `version`, `project-id`, `assembly-id`, `app-id`,
  `app-name`, `status`, `errors` (a list of `{file, entry, line, column,
  environment, message}`, where `file` is the path relative to the project
  directory), `messages` (the platform texts verbatim, so nothing is lost when the
  failure is not a compilation one), `cleanup` (`kept`, `app-deleted`,
  `assembly-deleted`, `project-deleted`, `problems`) and `hint`, the pointer to the
  server log that the `deploy` report carries too. `hint` is filled when the server
  refused and named no file; a wait that ran out of time leaves it empty. A stand that does not know
  the compatibility mode of the project refuses the whole project and then
  complains about types and properties of that mode in files the change never
  touched. That refusal is recognized, the parsing stops there,
  `compatibility-refused` names the mode and `messages-dropped` counts what
  followed from it, so a verdict about the stand cannot read as a verdict about
  the code. Return code 0 only when `ok`. A failed cleanup is a problem in the
  report and on stderr; it does not change the compilation verdict. `--keep`
  leaves the application and the build in place for a hands-on look. What a probe
  does leave behind is a tombstone: the platform keeps deleted applications in
  the list with the `Deleted` status and their former id, and there is no API to
  remove them.
- `branches list [--project-id --name]`, `branches get ID`,
  `branches create NAME [--project-id --app-id]`,
  `branches update ID [--app-id]`, `branches delete ID`,
  `branches merge ID`.
- `dumps create [APP_ID] [--description]`, `dumps get APP_ID DUMP_ID`.
- `tasks list [--app-id]`, `tasks get-group TASK_ID`.
- `tech get [APP_ID]`, `tech set APP_ID VERSION`.
- `debug-adapter` – the path to the platform debug adapter directory supplied by a plugin (the `elemctl.debug_adapter` entry-point group, section 10). Output `{"path": ..., "found": true, "adapter-class": ...}` when present or `{"path": null, "found": false}`; exit code 0 in both cases. The `path` is a ready value for the VS Code extension's `xbsl.debug.adapterPath` (a directory with a `repo/` subdirectory).
- `plugins` – diagnostics: what the plugins bring. `debug-adapter` holds the declared adapter directories and whether each of them holds jars. `commands` holds the commands of the plugins with the entry point they arrived through and the name of their MCP tool, which is `null` when the command stays out of MCP. `failures` holds what was left out: a plugin that did not load, or a command that would have taken over a name of the core, each with the entry point and the reason. The answer looks like `{"debug-adapter": [{"path": ..., "has-jars": true|false}], "commands": [{"name": ..., "source": ..., "mcp": ...}], "failures": [{"source": ..., "error": ...}]}`.
- The subcommands the plugins bring (section 10, the `elemctl.commands` group) stand alongside the commands of the core and are listed by `--help`. They may not take over a name of the core; the command reference describes the core alone. A plugin that fails to load is left out and does not take the CLI down (section 10): every command names it on stderr, and a call to a command that is missing while plugins failed is refused with JSON on stderr, the failures in its `plugin-failures` field.
- `self-update [--version X]` – update the installed elemctl by unpacking the wheel from PyPI into site-packages, without touching busy exe files. Plain pipx or pip breaks the install when `elemctl.exe` is held by a running MCP server. Here only the package files are updated, and the exe stub calls the new code. The command also fixes `pipx_metadata.json`. Output is `{updated, from, to}`.
- `mcp` – start the MCP server; without the extra installed – a clear error with the hint `pip install "elemctl[mcp]"`.

Positional APP_ID and PROJECT_ID marked as optional above are taken from the configuration when absent, from `ELEMENT_APP_ID` and `ELEMENT_PROJECT_ID`. If those are empty too, the command errors out.

## 8. MCP server requirements

Server name `elemctl`, stdio transport, credentials from the same environment variables and `.env`. In the server instructions, warn about the silent rollback of build apply (section 6.1). The tools, whose docstrings are short and in Russian:

`list_apps(name="", status="", include_deleted=False)` – the filters of `apps list`
(section 7): `name` by a case-insensitive substring on the client (section 4.1), `status`
by the whole status word, and the deleted applications hidden unless asked for. The answer
is an object with `total`, `live`, `shown`, a `summary` line and `applications`, so that
what was hidden is stated rather than guessed at; `get_app(app_id)`, `find_app(name)`,
`create_app(name, project_id="", version_id="", space_id="",
development_mode=True, verify=False)` – when only project_id is given, the project's latest
build is automatically used as the source (section 6.2); `verify=True` waits for the
application and checks that the build asked for is the one it runs, putting the report into
the `verify` field of the answer (the same check `ensure_app(verify=True)` makes, for a
created application as well as for one that was found); a wait that breaks off keeps the id
of the created application in the answer, beside a `wait-error` field with the reason, and
`ensure_app` then answers `applied: null`; a `version_id` the project no longer
lists is refused before the create, as in the CLI (section 7), with the project taken from
`project_id` or from the stand's `ELEMENT_PROJECT_ID`; `create_app` and `ensure_app` add a
`sign-in` field to their answer – the way into the application (section 6.11) in the
same shape the CLI prints: an agent sees only the JSON, so the hint has to live there;
`start_app(app_id)`, `stop_app(app_id)`, `debug_info(app_id)` – data for a
debug session (requires debugging enabled on the server), `debug_adapter()` –
the path to the platform debug adapter from a plugin (section 10; a local
operation that does not call the platform), `delete_app(app_id)`
(the docstring – a warning about irreversibility and URL change), `list_spaces()`,
`app_id` of `get_app`/`delete_app`/`start_app`/`stop_app`/`debug_info` is the
id (UUID) or the exact application name (resolved like the CLI does),
`list_projects(name="", include_deleted=False)` – the filters of `projects list` (section 7),
`list_builds(project_id, limit=10, brief=True)` – an object `{total, shown, summary, builds}`:
the listing has to say whether it is the whole store, judged by the gaps in the build
numbering (section 4.4),
`get_build(project_id, version)` – the whole card of one build, addressed by the build
version (section 4.4; an id is accepted and resolved through the listing),
`build_assembly(project_dir="", output_dir="", version="")`,
`inspect_assembly(file)` – parsing of a built archive (section 5.1; a local operation),
`deploy(app_id, project_id, project_dir="", version="", branch="",
server_start_timeout=900)` – returns the deploy report plus a `log` field with progress
lines, and waits out a server that is still starting (section 6.12); `probe(project_dir="", space_id="", keep=False)` – an isolated
compilation check that does not touch the working application (section 7),
the report plus a `log` field; `apply_build(app_id, version_id)`, `verify_deploy(app_id,
expected_version="", since_minutes=30)` – verification of the apply per section 6.1;
`list_app_tasks(app_id="")`, `list_branches(project_id="", name="")`,
`merge_branch(branch_id)`, `list_user_lists(name="")` and
`configure_user_list(list_id="", app_id="", self_registration=None, password_login=None)` –
the sign-in settings of a user list (section 4.7) in one call: the list is given by id, by
presentation or by the application whose own list it is; both flags are optional, and
without them the tool only reports the state (`self-registration-enabled`,
`password-login-enabled`, `changed`).

The tools the plugins bring (section 10, the `elemctl.commands` group) are registered
alongside these: the schema is built out of the declared arguments, the description is the
`help` of the command, and the core adds an `env_file` parameter of its own. A name already
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
  platform identifiers quoted as they are (`Проект.yaml`, `Ресурсы`, `Имя`, `Поставщик`) and
  the Russian data of test fixtures. Straight quotes `"` in text, dashes –
  en dash `–` (not em dash), ellipsis – three dots `...`.
- The library never prints to stdout or stderr itself: it delivers progress through a
  callback the caller passes in.
- API errors are raised as a dedicated exception carrying JSON-serializable details of
  the server response.

## 10. Plugins (entry points)

elemctl discovers external packages through `importlib.metadata.entry_points`. The core declares nothing about plugins in its own `pyproject.toml`: it is a consumer that reads the entry points on demand. Non-publishable vendor artifacts, the proprietary 1C jars, then live in a separate package while the public core stays clean.

The **`elemctl.debug_adapter`** group. The entry-point value is a path, as a `Path` or a `str`, or a zero-argument callable returning one (`() -> Path | str`). The path points to the platform debug adapter directory, meaning a directory with a `repo/` subdirectory holding the adapter jars, `com.e1c.g5rt.debugger.adapter*.jar` among them. This is a ready value for the VS Code extension's `xbsl.debug.adapterPath`.

Declaration in a plugin package:

```toml
[project.entry-points."elemctl.debug_adapter"]
name = "my_package:adapter_root"
```

The **`elemctl.commands`** group. The entry-point value is a `Command`, a list of them, or a zero-argument callable returning either. One declaration serves both surfaces: the core builds a CLI subcommand and an MCP tool out of it and knows nothing about what the command does. This is where a command belongs when it knows about someone's own environment: internal circuits, neighbouring systems, private stands. A public core is no place for it.

```toml
[project.entry-points."elemctl.commands"]
name = "my_package.commands:commands"
```

The declaration types are exported from `elemctl.plugins`:

- `Argument(name, help="", type=str, default=None, required=False, choices=(), cli_alias="")` – `name` is `"--stand"` for an option or `"stand"` for a positional argument. The value name, `dest`, is the name without the leading dashes and with the inner ones replaced by underscores, exactly as argparse does it. The types are `str`, `int`, `float` and `bool`. A `bool` means a flag, `store_true` in the CLI and a boolean defaulting to `false` in MCP, so it cannot be positional. `required` works for an option; a positional argument is required unless `required=False` makes it optional. `cli_alias` gives a positional argument a CLI-only key synonym: `Argument("page", cli_alias="--page")` accepts both `wiki-get 123` and `wiki-get --page 123`. The MCP tool schema keeps the one `page` parameter it always had – the alias is a parser convenience, not a second declared argument. The CLI builds the two forms as a mutually exclusive pair sharing one `dest`: both at once, or neither of a required argument, is a parser refusal. An option cannot declare `cli_alias` – it already has a name to call it by.
- `Command(name, help, handler, arguments=[], mcp=True, mcp_name="")` – `name` is the CLI subcommand. The MCP tool is named `mcp_name`, or the same name with dashes turned into underscores. `mcp=False` leaves the command in the CLI only. `source` is filled in by discovery with the name of the entry point.
- `CommandContext` – what the handler gets. `config` is the assembled connection configuration. `client` is a platform client built on first use and cached, so a command that never reaches the platform does not demand credentials. `log(message)` takes progress lines.

The handler is called as `handler(context, **values)`, the values keyed by `dest`. Its result must be JSON-serializable: the CLI prints it, the MCP tool returns it. The CLI exit code is taken from the result:

- a dict result whose `exit-code` field holds an integer from 0 to 255 ends with that code. A `bool` does not count as an integer here, and the range is what a process returns portably: POSIX keeps only the low eight bits of an exit status, so 256 would arrive as 0;
- otherwise a dict result with `"ok": false` ends with 1, the same convention the `deploy` and `probe` reports follow, and every other result ends with 0;
- a valid `exit-code` wins over `ok`, so `{"ok": false, "exit-code": 0}` ends with 0. A value of another type or out of the range is ignored, and `ok` decides.

The name of the field is exported as `elemctl.plugins.EXIT_CODE_FIELD`; a plugin that also runs on an older core can tell by its absence that the process code there follows `ok` alone. The MCP tool returns the `exit-code` field untouched, with the rest of the result. The handler does not end the process itself: the same function serves the MCP server, where a `SystemExit` leaves the call unanswered and stops the server. To the MCP tool the core adds an `env_file` parameter, as every core tool has, and, for a dict result, a `log` field with the progress lines.

Discovery behavior:

- entry points are sorted by name; `debug_adapter_path()` returns the first directory that actually holds the adapter jars (a directory without `repo/` or without the adapter jar is skipped), otherwise `None`;
- a failing entry point is an error, `PluginError`, a subclass of `ElemctlError`, rather than a silent skip: a tool that silently drops a plugin would leave the user without debugging and without an explanation. Both loading an entry point and calling the function it names are guarded. A plugin written for a newer core fails in that call, with a `TypeError` about a field the installed core does not know, and the error names the installed version;
- a command declaration is validated at discovery time, not when the command is run: an empty name, a handler that is not callable, an unsupported argument type, a boolean positional argument, duplicate value names, a `cli_alias` on an option, one that does not start with a dash and one that collides with another argument's own flag are all `PluginError`;
- a failure stays with its plugin. `discover_commands()` returns the commands that loaded and a `PluginFailure` for each entry point that did not, `{source, error}` in its `to_dict()`; one bad command leaves its whole entry point out. `plugin_commands()` is the strict form and raises the first failure. The CLI and the MCP server are built from `discover_commands()`: the plugin that failed is left out, and the core and the other plugins keep working. One broken plugin used to stop the parser from being built, so no command worked, the core ones included, and the answer was a Python traceback;
- a plugin may not take over a name the core already occupies – neither a CLI subcommand nor an MCP tool. The clashing command is left out and reported like a plugin that did not load, while the core keeps its own;
- the `ELEMCTL_NO_PLUGINS=1` environment variable disables discovery, leaving the core capabilities alone. The command reference generator sets it, so the reference describes the core alone.

Surfaces using the mechanism: the CLI `debug-adapter`/`plugins` (section 7) and the subcommands of the plugins, the MCP tool `debug_adapter` (section 8) and the tools of the plugins, and the VS Code extension, which requests the path from `elemctl debug-adapter` when the `adapterPath` setting is empty.

The adapter itself is extracted from the platform distribution by `tools/extract_adapter.py`, which is clean code and is not shipped in the package distribution (`prune`). It copies the `data/ide/theia/plugins/@1c-appengine-plugin/bin/debugger/` directory from the `.car` into `<output>/<version>/` and updates `index.json`. The proprietary jars stay out of the public package; a separate plugin package ships them.
