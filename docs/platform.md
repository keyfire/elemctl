---
title: "The platform underneath"
description: "Console API v2, the build file format and the platform behaviours worth knowing about."
sidebar:
  label: Platform
  order: 6
---

This page is about the platform rather than the tool: what the Console API looks like, what
a build file is made of, and how the platform behaves in the cases that surprise you the
first time. The platform's own documentation does not cover these corners, and `elemctl` had
to learn them by running into them.

You do not need this page to use the tool. It is here for the times when something behaves
oddly and you want to know what happens underneath. Or when you are writing a client of your
own.

## Console API v2 contract

Common prefix: `{base}/console/api/v2`. Request and response bodies are JSON, apart from the build upload. Field names are in kebab-case.

### Applications

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
  The only query parameter, and an optional one at that, is `SpaceId`; note that its name is in PascalCase. The method has no `BranchName`, `CommitId` or `CommitMessage` parameters: the Console API reference does not list them, and the server ignores them when sent. A direct POST with a real hash answers `commit-id: null`. The commit on a build card only comes from the project's link to its repository. The response carries the id of the created build in one of the fields `image-id`, `assembly-id` or `id`, checked in that order. Next to it sits an `artifact` object naming the project the build landed in: `artifact-id` is the project id and opens as a project card, `configuration-id` is the `Ид` of `Проект.yaml`, and `name` is the project presentation. The console shows a project under the name of the last uploaded build, meaning the manifest `Name`. So a build uploaded into a project under a different name silently renames that project, and uploading a build with the project's own name puts the name back. `elemctl` warns about such a mismatch before uploading.
- **A project is identified by the `Vendor` + `Name` pair of the manifest**, not by the `Ид` of `Проект.yaml`. `POST /projects` therefore does not always create a project: when the pair is already known, the build is simply added to the project that owns it, and that project comes back in `artifact-id`. There are two ways to hit a 409 `ALREADY_EXISTS`. The first is uploading a version that is already there, answered with "Версия сборки ... уже присутствует в группе проекта". The second is registering the same vendor and name under another project, answered with "Сборка с именем поставщика ... уже зарегистрирована в другом проекте"; generating a fresh `Ид` does not get around that one. A second, throwaway project for the same sources can only be had by renaming them.
- `GET /projects/{id}/assemblies` – list of builds. Each element contains `assembly-version`, a string like `1.0-42`, and an id in `id` or `image-id`. The response is either an array or an object with the list in the `items` or `assemblies` field. **The method has no pages and reports no total.** `limit`, `size`, `pageSize`, `count`, `top`, `maxResults`, `page`, `pageNumber`, `offset`, `skip`, `from` and `start` are all ignored: the answers to every one of them match byte for byte, and neither the headers nor the body carry a counter or a cursor. Verified by live calls on two installations. **The platform deletes builds nobody uses,** and age has nothing to do with it: the vendor's help calls this automatic deletion of unused builds. A build an application runs is kept, and so are a library build another project uses, a release build, the project's default build and the build the project's repository was created from. Everything else goes when the collector gets to it. Seen live: seventeen builds of one day's series were made and one survived, the one the application runs, while a build from two months earlier is still listed because it is the project's first. So a listing is not the project's history and not a page of it. It is what survived, and the client must say so.
- `GET /projects/{id}/assemblies/{version}` – build card, `DELETE .../{version}` – delete. The last segment is the version, the way the method names it: `assembly-version` or `project-version`, a string like `1.0-42`. The id of the card does not go there: a UUID is answered with a 404 "Assembly with version <uuid> not found". Checked live on two installations of different ages, both behave this way. An id is still an address a caller holds: the build list prints it, and an upload answers with one. So `elemctl` accepts both forms and looks the value up in the build list to get the version. When the address is refused with a 400 or a 404, it tries the id as the segment as well, for an installation that wants that form. Note that the platform renumbers the manifest version on upload. Deleting a build is rejected with a 500 while an application created from it is still alive. Once that application has really disappeared, the very same request succeeds. A build that only took part in an apply, even a rolled-back one, deletes without a fuss.

Build versions are compared by the numeric suffix after the last hyphen: `1.0-10` is newer than `1.0-9`. Lexicographic comparison gives the wrong order.

### Development environment branches

- `GET /branches` – list; optional queries `project-id`, `name`.
- `GET /branches/{id}` – card. Fields: `name`, `kind`, `project`, `application`, `source-branch`, `deletion-mark`, `version-stamp`.
- `POST /branches` – create. Body: `name`, `kind: "development"`, `project: {"id": "<id>"}`, optionally `application: {"id": "<id>"}`.
- `PUT /branches/{id}` – modify. The platform uses optimistic locking, so read the card first, then send a body assembled from the current values. Those are `name`, `kind`, `deletion-mark` and `version-stamp`, which has to come back exactly as it was. Collapse `source-branch` and `application` to `{"id": ...}`, or to `{"name": ...}` when there is no id. To rebind to an application, replace `application` with `{"id": "<new app-id>"}`.
- Branch changes are accepted by that same `PUT /branches/{id}` with an additional body key `write-parameters: {"merge": true}`.
- `DELETE /branches/{id}` – delete the branch.

The tool works only with the documented Console API v2. It neither uses nor describes the internal, undocumented APIs of the platform console.

### User lists

A user list holds either the users of an application or the users of the control panel. An application has a list of its own, named after it, and the application card points at it with `default-user-list`. The control panel has one list per installation.

- `GET /user-lists` – the list: `id`, `presentation`, `space-id`. There is no server-side name filter. `GET /user-lists/{id}` – the full card. `POST /user-lists` creates one and wants the whole card: an incomplete body is answered with a 500 and the misleading text "Failed to parse json". `DELETE /user-lists/{id}` removes it.
- `GET|PUT /user-lists/{id}/settings/self-registration` – `{enabled, phone-required, email-required}`, the control panel's "allow users to register themselves".
- `GET|POST /user-lists/{id}/settings/account-services-settings`, `PUT|DELETE .../{account-service-id}` – the account services. An entry is `{account-service-id, account-service-type, local-id, enabled, create-user-on-auth, additional-settings}`. The type `Local` authenticates by a password; the rest are external: `OIDC`, `Cas`, `ActiveDirectory`, `Esia`. Both writes want the whole entry.
- `GET|POST|DELETE /applications/{id}/userlists` – the ids of the lists connected to an application. Note the spelling: `userlists` here, `user-lists` at the top level. The link carries no settings of its own.

Worth knowing before you build on this:

- the rules for parsing an account service response are accepted under the key `userPropertiesCalculationRules`. Those rules are `presentation-rule`, `email-rule`, `phone-rule` and `response-kind`. The reference's own schema calls the field `calculation-rules`, and that spelling is answered with a 400. A GET never returns the rules: the setting is write-only, and an API client cannot confirm it applied;
- the composition of an application's authentication forms is not in the API at all, and neither is the connection setting "users of the list are connected automatically on sign-in". Those stay in the control panel;
- a GET of an account service returns the `client_secret` of an OIDC client in cleartext, so such answers do not belong in logs and reports as they are;
- an unknown path of the Console API is answered with a **401** carrying "Handler of HTTP request ... not found", not a 404. When probing for the surface, that is the sign that a method does not exist.

### Application tasks

`GET /tasks/application-tasks` – list of tasks for all applications. There is no server-side filter, so filter on the client. Task fields: `id`, `application-id`, `status` (including `Error`, `Failed`), `operation-type`, `error-message`, `start-date` (ISO 8601, may end with `Z`).

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

- then the project files at paths `{vendor}/{name}/...` relative to the repository root. The project directory must follow the scheme `{repo}/{vendor}/{name}/Проект.yaml`. Path separators in the archive are forward slashes, on Windows too.

Build file name: `{Имя} {Version}.xasm` (with a space).

Project metadata comes from `Проект.yaml`. It is YAML, and parsing the flat top-level "key: value" pairs is enough; skip the nested indented lines. Bilingual sources are a capability the platform declares, and a descriptor written with English keys deploys fine, so every key is read in both spellings: `Имя`/`Name`, `Поставщик`/`Vendor`, `Версия`/`Version` (base, e.g. `1.0`) and `ВидПроекта`/`ProjectKind`. The value `Библиотека` or `Library` means a library; anything else means an application. When both spellings of a key are present, the Russian one wins. The service file names are bilingual too: the platform converter accepts `Project.yaml` and `Проект.yaml`, `Subsystem.yaml` and `Подсистема.yaml`. An English descriptor also carries English enumeration values, such as `VisibilityScope: Global`.

When the build version is not set explicitly, it is built as `{base version}-{N+1}`, where N is the counter from the version of the project's latest build of the same base version. A project bumped to a new base version starts from `-1` again, whatever counters the old base reached. With no last build of that base, the suffix comes from the CI run number in the environment: the first numeric value of `CI_PIPELINE_IID`, `GITHUB_RUN_NUMBER`, `BUILD_NUMBER`, in that order. Otherwise a clean CI checkout would produce `-1` every time. With no CI number either, the version is `{base version}-1`.

Git metadata, meaning the commit hash and the branch name, comes from the git repository that contains the project directory. When git is unavailable, the fields stay empty.

File selection for the archive:

- only these extensions are included: `.yaml .xbsl .xbql .md .txt .json` (sources), `.png .svg .jpg .jpeg .gif .webp .ico` (images), `.css .htm .html .js .woff .woff2 .ttf .eot` (web resources);
- the extension filter does not apply inside a `Ресурсы` directory, at any level and in subdirectories too: by the platform's own documentation a resource is an arbitrary file, so everything there goes in;
- the description files of a SOAP service client are included wherever they lie: `<Client>.Wsdl.<n>` and `<Client>.Xsd`. The platform keeps them next to the project element and reads them by name;
- the directories `.git`, `.claude`, `.github`, `__pycache__`, `node_modules`, `.venv` and all hidden ones (starting with a dot) are excluded;
- the files `.gitignore`, `.env`, `.DS_Store` and `*.xasm`, `*.xlib` files are excluded.

### Parsing a built archive

The reverse of a build: from a `.xasm` or `.xlib` file you get the manifest, the project properties from its `Проект.yaml` inside the archive, and the contents. It is needed to attach a library to a project without unpacking its sources.

The layout inside a project; only the directories tell the truth about the contents:

- a first-level directory is a **subsystem**. `Подсистема.yaml` is **optional**, and a library subsystem may have none at all, so it cannot be relied upon when looking for subsystems;
- a nested directory of a subsystem is a **package**. A package has no description file, and every directory contributes a name segment;
- the qualified name of a type: `{vendor}::{name}::{subsystem}[::{package}]::{TypeName}`. The same name without the last segment is what `Использование` and `импорт` take.

Only types with `ОбластьВидимости: Глобально` are visible outside, in the project that attached the library. The default is `ВПодсистеме`, and the global scope is written explicitly.

Compatibility is checked against the `РежимСовместимости` property of `Проект.yaml`. The `ВерсияТехнологии` property **does not exist** in `Проект.yaml`: it belongs to the body of the Console API request that creates an application, not to the project file.

## Platform behaviour you have to account for

1. **Silent rollback of build apply.** When applying a build to the application fails, a compilation error for instance, the platform silently rolls the application back to the previous build and starts it. The `Running` status does not mean success. A reliable check of the result looks like this:
   - take the application tasks (section 4.6) with status `Error` or `Failed` whose `start-date` is not earlier than the moment the deploy started. Old errors from history do not count;
   - compare the actually applied version, the `source.project-version` of the application card, with the version of the uploaded build;
   - for information, make a check GET against the application `uri`. Codes 401 and 403 are normal for closed applications and do not contradict success.
2. **Empty skeleton on creation.** On some platform configurations an application created with a "project" source, meaning `image-id` set to the project id, comes out empty, with no project data. A reliable source is a specific build in `project-version-id`, for example the project's latest build.
3. **Deletion with drafts.** If the application's development environment has unpublished edits, `DELETE /applications/{id}` returns 400 with `FAILED_PRECONDITION` in the body. There is no forced deletion in the API, only the control panel, and the tool must provide a clear hint.
4. **Readiness of a new application.** After creation, the application sits in transitional statuses and without a `uri` for some time, so provide for waiting until it is ready: a `uri` has appeared and the status is stable. An `Error` status while waiting is an immediate error.
5. **Restart after apply.** `project/update` may restart the application itself. After the call, wait until it leaves the transitional statuses. If the result is not `Running`, stop it unless it is already `Stopped`, wait for `Stopped`, start it and wait for `Running`. Reasonable waits: about 3 minutes for a stop, about 5 minutes for a start and stabilization, polling every 10 seconds or so.
6. **`Error` is a final status.** A stable `Error`, after a failed apply for instance, is an immediate failure: surface the error messages of the application tasks right away. Do not stop or restart such an application, and do not keep waiting for another status: from `Error` it never moves to `Stopped`, and the wait just burns the whole time budget.
7. **Windows.** Temporary files and caches go through `tempfile` only. Switch console output to UTF-8 with `reconfigure` for stdout and stderr, otherwise Cyrillic breaks.
8. **The project is identified by vendor and name.** See the build upload above: a project is identified by the `Vendor` + `Name` pair of the manifest. An upload without a project id is not "create a new project", it is "put it where this pair belongs".
9. **Deletion runs in the background and in order.** `DELETE /applications/{id}` returns immediately, and the application lives on for a while with a `DeleteApplication` task. While it exists, deleting the build it was created from is rejected with a 500. The order for cleanup is: delete the application, wait until its card answers 404 or the status becomes `Deleted`, and only then delete the build.
10. **Compilation is the server's, and it happens on apply.** A local build only packs an archive. The syntax, the types and the visibility of the sources are checked by the server compiler when a build is applied or an application is created out of it. There is no separate "compile" endpoint. That, together with points 8 and 9, is what `elemctl probe` is built out of: the sources go to their own project as a build with a one-off version, the compiler is reached through a throwaway application, and both are removed afterwards. The working application is never at risk.
11. **Signing in to a freshly created application.** A new application gets its own empty user list, and the card points at it with `default-user-list`. Password sign-in is off, and it has no account service. So the accounts used to sign in to other applications do not work here. Connecting another application's user list (`POST /applications/{id}/userlists`) together with enabling the local sign-in does not change that. What does work is a control-panel account: the platform connects its users to the application itself, and they sign in right away. Worth knowing before raising a stand for a task: the way in does not follow from the card, and trying accounts is a bad idea, because a user has a failed-attempt counter.
12. **A server that is still starting.** After a start or an update the server takes minutes to bring its console up: thirteen of them were seen after one update. All that time every console request, the token request included, is answered with a 404 whose text names the console application, `Application "console" not found`. That is the status a missing application or build gets, so only the text tells them apart. `elemctl` recognizes the answer in its client and says what it means: the server is starting, repeat once `/console` answers 302. `deploy` waits it out by itself, for up to `--server-start-timeout` seconds (900 by default, 0 turns the wait off), and goes on once the console answers. A request the console refused was never processed, so asking again is safe.
