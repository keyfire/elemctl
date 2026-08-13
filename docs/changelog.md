---
title: "Changelog"
description: "What changed in elemctl from release to release, grouped by day."
sidebar:
  label: Changelog
  order: 7
---

<!-- Assembled from CHANGELOG.md by scripts/sync-docs.mjs. Do not edit by hand. -->

Notable changes to elemctl, newest first. Entries are grouped by day; the versions released that
day are named in the heading. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Changed
- **`builds list` answers with the ten newest assemblies by default.** A long-lived project
  holds assemblies by the thousand, and "which commit is the applied build from" meant piping
  the full list through `head` and hoping the right card made the cut. The list is now sorted
  newest first, `--limit N` changes the cut (`--limit 0` – everything), and the cut is never
  silent: stderr names how many of how many are shown. The new `--brief` flag keeps the id,
  the versions, the date, the branch and the commit of each card. The MCP `list_builds` tool
  takes the same `limit` (default 10) and `brief` (on by default).

### Fixed
- **A probe build can no longer win the latest-build pick.** The probe version ends with a
  random token, and eight hex digits come out all-numeric once in ~43 draws – such a version
  parses as a huge numeric counter, and `create_app --latest-build` would pick the probe build
  over the real one. An all-digit token is redrawn now. Caught live by CI.

## 2026-08-11 – 0.29.0

### Changed
- **A missing `.env` file is reported with the absolute path and the current directory.** A
  relative `--env-file` is resolved from the current directory, not from `--project-dir`, and in
  a background run the current directory is not always the one it seems to be – the refusal used
  to read as "the stand is unreachable".
- **`probe` documents its project layout requirement.** The command description and the
  `--project-dir` help now say the directory must follow the
  `{repository}/{Vendor}/{Name}/Project.yaml` layout (the Vendor+Name pair is how the platform
  identifies the project); previously the requirement surfaced only as an error after the fact.

## 2026-08-10 – 0.28.0

### Documentation
- **The MCP tool catalogue is on the page now.** Seven of the twenty-four – `apply_build`,
  `build_assembly`, `find_app`, `inspect_assembly`, `list_app_tasks`, `list_branches`,
  `list_spaces` – were named nowhere outside the sources, the page making do with "and others".
  A table lists every one of them.
- **The environment variables are documented in full.** The settings page was missing
  `ELEMCTL_NO_PLUGINS` and the variables the build reads from CI (`CI_PIPELINE_IID`,
  `GITHUB_RUN_NUMBER`, `BUILD_NUMBER`, `CI_COMMIT_BRANCH`, `CI_COMMIT_REF_NAME`,
  `GITHUB_REF_NAME`), and the `ELEMCTL_NO_PROXY` row had fallen out of the table into a
  paragraph of pipes. The language section now names the system `LC_ALL`/`LANG` as well.
- **Statements that had stopped being true.** The command reference promised common flags before
  the subcommand only, though they are accepted in any position; the platform page left `.htm`
  out of the archive extensions and did not say that inside a `Ресурсы` directory nothing is
  filtered by extension; the Russian README still claimed the documentation was Russian-only.
- **One source per text.** The README sections that repeat a site page had drifted both ways:
  the README knew about `probe` and the user lists and the page did not, the page knew about the
  `elemctl.commands` plugin group and the README did not, and the README still promised two VS
  Code extensions after one of them was gone. The page is the source now, and
  `scripts/sync-docs.mjs` injects its section into the README between markers.
- **A diagram of how the tool is wired.** `docs/architecture.svg` (with a Russian twin) – the
  surfaces, the engine, the deploy cycle with its silent rollback and the probe; on the home page
  and in the README. The palette follows the reader's theme, and the README PNG is rendered by
  `scripts/render-diagrams.py` with the palette forced.
- **The guard `scripts/docsguard.py` and a `docs` job in CI.** It checks what is mechanically
  checkable: a tool without a row, a row without a tool, an environment variable the code reads
  and nobody documented, an archive extension the page omits, a stale README block or changelog
  mirror, a page without a translation, an image without a file. Every class of finding is
  provoked by a test (`tests/test_docs_coverage.py`).

### Added
- **`deploy` accepts an application name, not only its id.** Every other command addressing one
  application - `apps get`, `apps start`, `apps stop`, `apps debug` - has always taken a name and
  resolved it; the deploy took the value as it was and sent the name to the API, where it is not
  an identifier at all. A UUID still passes through without a request.

### Changed
- **The VS Code extension moved out of this repository.** Debugging 1C:Element applications is
  part of the [XBSL](https://github.com/keyfire/xbsl) extension since its 0.57.0, together with
  the deploy button that was already there - the split made a user configure the elemctl path and
  the application id twice. What stays here is the elemctl side: `apps debug`, `debug-adapter`,
  the `elemctl.debug_adapter` entry point group and the adapter extraction script.

## 2026-08-07 – 0.26.0, 0.27.0

### Added
- **Projects with English artifacts build and deploy.** The platform accepts both spellings of
  the service file names - its converter checks the pairs itself - so the toolkit now resolves
  them too: `build`/`deploy`/`probe` find a descriptor named `Project.yaml` next to
  `Проект.yaml`, a local library dependency is found by either name, and the archive inspection
  reads `ElementKind`/`VisibilityScope` (with the English values, e.g. `Global`) and skips
  `Subsystem.yaml` as a descriptor. The schema guard reads the English attribute keys
  (`Attributes`, `Id`, `Name`, `Type`, `Length`, `MaxLength`) as well, and knows the two
  spellings of a primitive type name are the SAME type - translating a description does not read
  as a data-destroying change.

### Changed
- **The upload sends no commit or branch parameters.** `CommitId`/`BranchName`/`CommitMessage`
  went out as query parameters of the assembly upload, looked functional - and did nothing: the
  Console API reference does not list them, and the server ignores them when sent (a direct POST
  with a real hash answered `commit-id: null`). The commit on a build card only comes from the
  project's link to its repository. The parameters are gone from the client, the `--branch`/
  `--commit`/`--commit-message` flags - from `builds upload`, `--commit-message` - from `deploy`
  and its MCP tool. The branch and the commit still travel INSIDE the archive: the build writes
  them into the manifest, and `build`/`deploy` keep their `--branch`/`--commit` for exactly that.
- **A skipped schema check is named in the report, not only in the progress log.** The deploy
  report carries `schema-check`: `clean`, `allowed` (narrowings let through by
  `--allow-data-loss`) or `skipped:<reason>` - a skipped check must not read as a passed one.
  And when the applied build carries no commit, the message now explains the mechanism: a commit
  only comes from the project's repository link, so without the link the check can never run -
  that is by design, not a server version quirk.

## 2026-08-03 – 0.25.0

### Changed
- **A build whose name differs from the target project is refused, not just warned about.** The
  console shows a project under the name of the LAST uploaded build, so a foreign build renames
  the project and its group - and deleting the build does not bring the name back. `builds upload`
  now stops with exit code 1 and names the price; the message spells out both ways on:
  `--force-rename` when that is intended, `--new-project` when the build belongs elsewhere. The
  check stays best effort - when the names cannot be compared the upload proceeds as before.
## 2026-07-31 – 0.23.0, 0.24.0

### Fixed

- **`self-update` right after a release no longer misses it.** The file list came from the JSON
  metadata of PyPI, a cache that catches up minutes after an upload: within that window the
  command answered "already current", and with an explicit version - "no wheel", because the
  files were read from that same lagging document. The list now comes from the SIMPLE index
  (PEP 691), the newest release is ranked numerically (`0.9.0` before `0.23.0`, no pre-releases,
  no yanked files), and the JSON metadata stays as the fallback for an index that does not speak
  PEP 691. Proven on the toolkit engine first, in the live lag window: the JSON still answered
  with the previous version while the index already served the new wheel.

### Changed

- **The MCP server works with both majors of the `mcp` package, and the pin is lifted.**
  `mcp 2.0.0` moved the ergonomic server class – `FastMCP` from `mcp.server.fastmcp` became
  `MCPServer` in `mcp.server.mcpserver`, and the old module is gone rather than kept as an
  alias – so a fresh install of `elemctl[mcp]` picked up the new major and the server did not
  start at all. The answer at the time was the pin `mcp>=1.2,<2`: it kept installations working
  but froze them on 1.x. The import now tries the new home first and falls back to the old one,
  and the extra allows `mcp>=1.2,<3`. Everything the server uses of the class is the same in
  both majors – the `instructions` keyword, `@tool()` / `add_tool()`, `run()` over stdio – so
  the tool set, the schemas and the descriptions come out identical, checked over the wire with
  `initialize`, `tools/list` and `tools/call`. What differs is reading the answers: `inputSchema`
  became `input_schema` and `call_tool` now returns a `CallToolResult` instead of a bare list of
  content blocks. `tool_input_schema()` and `call_result_content()` hide exactly that, and CI
  runs the suite against both majors.
- **`serverInfo` now names the version of elemctl.** mcp 2.x asks the server for its version and
  stamps an empty string when it is not given; mcp 1.x had no such parameter and stamped the
  version of the `mcp` package instead, which was never the version of the tool.

## 2026-07-30 – 0.22.0

### Added

- **An application build now carries the library projects that live next to it.** When the
  application declares libraries whose sources sit under the same repository root, their files
  go into the archive with it, transitive dependencies included; a declared library with no
  local project stays an external dependency of the platform, and unrelated neighbouring
  projects are not swept in. Contributed by @dvkuchin (pull request #3).

### Fixed

- **A proxy in the environment no longer makes a live stand look dead.** With an `HTTPS_PROXY`
  set, every call died as a bare connection reset on `/console/sys/token`: urllib honours the
  proxy, correctly, and a proxy that cannot reach the stand fails exactly like a stand that is
  down - two runs were lost before the proxy was suspected. Now a proxy that cannot possibly help
  is bypassed (loopback, private and link-local addresses, `localhost`, `.local`/`.lan` and the
  like), `ELEMCTL_NO_PROXY=1` bypasses it everywhere, and a failed call that did go through a
  proxy says so and names it. A stand that is reachable only through a corporate proxy keeps
  working as before - the default is unchanged.
- **`self-update --stop-holders` no longer stops its own process tree.** Started via the
  installed shim, the command runs as a python child of an `elemctl.exe` launcher – by name
  that launcher looks exactly like a holder, so the command offered itself for stopping and
  the stop cut the update short (the rollback insurance kept the old installation intact, but
  the update never happened). Holders now exclude the command's own process: its ancestors –
  the shim and whatever started it – and its descendants. Other live `elemctl` processes, the
  actual holders, are still named and stopped.

## 2026-07-28 – 0.20.0, 0.21.1

### Added

- **Creating an application ends with the way into it.** `apps create` and `apps ensure`
  (and their MCP twins) now add a `sign-in` field to the answer – the address, the account
  code `control-panel` and two sentences of explanation – and the CLI prints the same on
  stderr. The reason it is worth saying out loud: a fresh application gets its OWN, empty
  user list, password sign-in in it is off and no account service is attached, so
  the accounts used to sign in to other applications do
  not work here – and connecting another application's user list together with enabling the
  local sign-in does not change it. A CONTROL PANEL account does work: the platform
  connects its users to the application itself. Until now that had to be found by trying,
  which is the one thing not to do – a user has a failed-attempt counter. While the
  application is still starting and has no address, `url` is `null` rather than a guess,
  and the hint says where to take the address from.

### Changed

- **`self-update` no longer trades a working installation for an empty directory.** It happened
  during the previous release, on the machine that publishes the package: `pip install
  --upgrade` hit an `elemctl.exe` held by a live MCP session, removed the package, failed to
  unpack the new one and said nothing - the next `elemctl --version` answered
  `ModuleNotFoundError`. The command now renames the installed package aside FIRST (a rename
  fails while a file inside is open, and nothing has been removed at that point), names the
  holding processes by name and pid (`--stop-holders` ends them), and keeps the previous
  installation until the new one has been PROVEN to import in a separate process - a broken
  archive, a failed extraction or a package that does not import puts the old one back. A
  process counts as a holder by our own executable name or by an interpreter running our
  modules: a client that merely carries `elemctl mcp` in its own command line is never offered
  for stopping. The order is the one proven in the toolkit engine first.

## 2026-07-27 – 0.19.0

### Added

- **`user-lists calculation-rules` – re-apply the rules that build a user from the provider's
  answer.** Recreating the sign-in service resets them, and the only way back is to write them
  again; the platform takes them in the body of the account service under a key that differs
  from the one in the schema of the same catalog (it answers 400 to that one, so the command
  refuses an unknown key by name instead of forwarding it). Reading the service does NOT return
  these rules, and the report says exactly that: what was sent, that the request was accepted,
  and that the value itself cannot be confirmed through the API - the control panel or a live
  sign-in answers that. What IS checked is that the rest of the service card came back
  unchanged: the write carries the whole entry, so a mistake would quietly drop a neighbouring
  field.

### Fixed

- **A build made on a CI runner recorded `HEAD` as its branch.** The runner checks out the
  commit rather than the branch, so `git rev-parse --abbrev-ref HEAD` answers the literal
  `HEAD` – and that word went into `BranchName` of every assembly the pipeline shipped. The
  manifest field exists to answer "where is this build from", and it answered nothing exactly
  where it was needed most. A detached checkout now takes the name from the CI environment
  (`CI_COMMIT_BRANCH`, `CI_COMMIT_REF_NAME`, `GITHUB_REF_NAME`), and when nothing names a
  branch the field is left EMPTY: an honest blank beats a word that looks like a branch name.
  The commit hash was always recorded correctly and is unchanged, and `--require-clean` still
  judges the tree by `git status`.

## 2026-07-26 – 0.15.0, 0.16.0, 0.17.0, 0.18.0

### Added

- **`deploy` names the target and where it came from.** The report carries `app-name`,
  `app-id-source` and `project-id-source` next to the ids, and the target is announced by the
  FIRST progress line – before the build, while a deploy aimed at the wrong application can still
  be interrupted. `--dry-run` shows the same target, softly: it must keep building without any
  configuration, so an unreadable `.env` leaves the fields empty instead of failing.
- **The build names the files it left behind** (`skipped-files` in the report plus a warning).
  A file with an extension outside the allowlist only gets into the archive when it lies in a
  `Ресурсы` directory; kept anywhere else it silently misses the archive and the platform says so
  only on apply, as "Неизвестный ресурс". Deliberately excluded files (`.gitignore`, `.env`,
  prebuilt `.xasm`/`.xlib`) are not counted as a loss.

- **A guard against the schema changes that destroy data.** A narrowed length or a changed type
  makes an apply RECREATE the data of the object – widening keeps it, so the dangerous class is
  narrow. `deploy` compares the sources on disk with their state at the commit the applied build
  was made from and, on a finding, refuses BEFORE the build: nothing is built and nothing uploaded.
  `--allow-data-loss` lets it through. Attributes are matched by `Ид`, the way the platform matches
  them, so a rename under the same `Ид` stays silent. The reading pulls in no dependencies – the
  tool has none at all – it reads the `Реквизиты` block and says nothing about what it does not
  recognize: the guard may fail to judge, but it must never invent a change.
  **What it cannot do:** the Console API does not hand out the contents of an assembly, so an
  archive-to-archive comparison is impossible and the check rests on the `commit-id` of the
  assembly card. With no commit, or no such commit in the local repository, the guard says it
  cannot judge and does NOT stand in the way: being unable to compare is not evidence of danger.
  The platform may IGNORE the `CommitId`/`BranchName` parameters on
  upload – even an explicitly passed value comes back empty, while assemblies uploaded earlier do
  carry a commit. Where that holds, the guard will more often stay silent than judge.

- `elemctl user-lists` – the sign-in settings of a user list, the ones a control panel
  usually holds: `list`, `get`, `self-registration [--enable|--disable]` and
  `password-login [--enable|--disable]`. The list is addressed by id, by its exact
  presentation or by `--app` – the application's own list. Without a flag the two setting
  commands only read the state, so the same command answers "how is it now". Behind
  "signing in with a login and a password" there is the account service of type `Local`:
  the answer says `enabled: null` when the list has no such service at all, and `changed`
  tells whether this very call altered anything – switching to the state that is already
  there sends no request. The MCP side is `list_user_lists` and `configure_user_list`,
  which does both settings in one call.

- The **`elemctl.commands`** entry point group – a plugin package brings commands of its own.
  The value is a `Command`, a list of them or a zero-argument callable returning either; one
  declaration serves both surfaces at once, becoming a CLI subcommand and an MCP tool with a
  proper schema, while the core knows nothing about what the command does. That is where a
  command belongs when it knows about someone's own environment – internal circuits,
  neighbouring systems, private stands – and therefore cannot live in a public core. The
  declaration types are `Argument`, `Command` and `CommandContext` from `elemctl.plugins`; the
  handler gets the configuration, a client built on first use and a progress callback. A
  result that is a dict with `"ok": false` gives exit code 1, the MCP tool additionally takes
  `env_file` and returns the progress in a `log` field. A plugin may not take over a name the
  core already occupies – neither a subcommand nor a tool – and a wrong declaration is
  reported at discovery time rather than when the command is run.
- `plugins` reports the commands the plugins bring (`commands`: the name, the entry point and
  the name of the MCP tool) alongside the adapter directories.

- `elemctl probe` – an isolated compilation check of the sources that does not touch the
  working application. Compilation on this platform is the server's and happens when a build
  is applied, so the probe builds the archive, uploads it, creates a THROWAWAY application out
  of it – that is the compilation – and removes what it created afterwards. The errors come
  back parsed: `file` (relative to the project directory), `line`, `column`, `environment`
  (`Сервер`/`Клиент`) and the text; the platform's own messages are kept verbatim in
  `messages`. `ELEMENT_APP_ID` and `ELEMENT_PROJECT_ID` are deliberately not used – the probe
  must not be able to reach the working application. Exit code 0 only when `ok`; `--keep`
  leaves the application and the build in place for a hands-on look. The same as the `probe`
  MCP tool.

### Fixed

- **A global option is accepted after the subcommand too.** `--env-file`, `--lang`, `--base-url`,
  `--client-id`, `--client-secret` and `--timeout` are declared on the root parser, so
  `elemctl deploy --env-file .env` used to die with argparse's "unrecognized arguments" and the
  order rule had to live in a checklist and in three skills. The options are hoisted to the front
  of argv instead; both spellings work and the tokens after a bare `--` are left alone.
- **A token the server has rejected no longer survives in the cache.** The refresh-and-retry
  watched for a 401, but this server refuses a bad token with **400 `invalid_request`**, naming the
  reason in `error_description` ("JWT strings must contain exactly 2 period characters", "Unable to
  verify RSA signature ..."). Both answers are reproducible by planting a bad
  token into the cache, which is why the cure used to be written down as deleting
  `<TEMP>/elemctl-token-*.json` by hand. Such a refusal now drops the cache FILE and retries once;
  an ordinary bad request, whose description says nothing about a token, is not retried.

- The documented behaviour of deleting a build was wrong: the platform rejects it with a 500
  only while an application created from that build is still alive – after the application
  has really disappeared the same request succeeds. That is why `probe` deletes the
  application first, waits for it to be gone (the new `wait_app_deleted` of the client), and
  only then deletes the build.

### Documentation

- The Console API contract now describes user lists (section 4.7): the settings endpoints,
  the meaning of the `Local` account service, and the fact that the link between an
  application and a list carries no settings of its own. Also written down: the composition
  of the authentication FORMS and the "connect users automatically" setting are not in the
  API at all; the rules for parsing an account service response
  are accepted under `userPropertiesCalculationRules` while the reference's own schema calls
  them `calculation-rules` and the platform answers 400 to that spelling – and a GET never
  returns them, so the setting is write-only; `POST /user-lists` wants the whole card and
  answers a 500 "Failed to parse json" to anything less; an unknown Console API path is
  answered with a 401 "Handler ... not found", not a 404.

- A platform project is identified by the `Vendor` + `Name` pair of the manifest, not by the
  `Ид` of `Проект.yaml`: an upload without a project id lands in the project that already owns
  the pair, and a second project for the same pair is refused with a 409 `ALREADY_EXISTS`
  (a freshly generated `Ид` does not help). The upload response describes that project in its
  `artifact` object: `artifact-id`, `configuration-id`, `name`.

## 2026-07-25 – 0.14.0

### Added

- Build: without an explicit version and a last build, the version suffix comes from the CI
  run number in the environment (`CI_PIPELINE_IID`, `GITHUB_RUN_NUMBER`, `BUILD_NUMBER` – the
  first numeric value in that order), so a clean CI checkout no longer produces `-1` on every
  run and a CI job reduces to a plain `elemctl build`.
- `build` (and `deploy --dry-run`) output the build's `name`, `vendor`, `version`,
  `version-source` (`flag`/`last-build`/the CI variable name/`default`), `kind`, `branch`,
  `commit` and `dirty` alongside `file` – CI no longer parses the version out of the file name.
- `apps get/delete/start/stop/debug` (CLI) and `get_app`/`delete_app`/`start_app`/`stop_app`/
  `debug_info` (MCP) accept the application's exact name as well as its id: a non-UUID value
  is resolved through the list case-insensitively; several matches are an error listing the
  ids, so destructive commands never guess.
- `apps list --brief` – brief cards (id, name, status, uri, applied version), like the MCP
  tool has had; with `--name` it answers "is acme-crm-dev alive" in a couple hundred bytes
  instead of tens of kilobytes.
- The deploy report and `elemctl build` surface uncommitted changes of the project directory
  (`dirty`, `dirty-files` plus a stderr warning): the build captures the current disk state,
  so the divergence from HEAD must be visible. The new `--require-clean` flag of `build` and
  `deploy` aborts before building instead (an unavailable git is also a refusal – there is
  nothing to confirm a clean tree with).

### Changed

- `apps list --name` (CLI) and `list_apps(name=...)` (MCP) filter by a case-insensitive name
  substring on the client. The platform ignores the `name` query parameter and returns the
  full list (verified against a live instance), so the former pass-through filter did not
  filter anything.
- Descriptor keys of `Проект.yaml` are read in both spellings – `Имя`/`Name`,
  `Поставщик`/`Vendor`, `Версия`/`Version`, `ВидПроекта`/`ProjectKind` (values
  `Библиотека`/`Library`), same for `CompatibilityMode`/`Presentation` in `inspect`:
  bilingual sources are a declared platform capability, and a descriptor written with
  English keys deploys fine. Previously such a project was rejected with "Имя and Поставщик
  must be filled in", and a mixed one silently got version `1.0` instead of the declared one.
- Waiting for application statuses treats `Error` as terminal: `deploy` fails right away
  with the tasks' compilation errors instead of polling for `Stopped` through the whole
  180-second timeout (an application in `Error` never reaches `Stopped`).

### Fixed

- `--lang en` is now English everywhere. About forty user-facing strings were built into
  the modules as Russian literals and bypassed the message catalog, so an English-speaking
  user still got Russian out of `deploy` (the problems of the report), `self-update` (all of
  its progress), the configuration errors, the plugin loader and several `apps` errors. They
  are keys of the catalog now, and a test walks the modules to keep new literals from
  creeping back in.

## 2026-07-24 – 0.12.0, 0.13.0, 0.13.1

### Fixed

- Build: files inside resource directories (the literal directory name is `Ресурсы`) are
  now archived regardless of extension (`.pdf`, `.htm`, `.mxl`, `.docx`, `.xsd` etc.) – per
  the platform documentation a resource is an arbitrary file. Previously the general
  extension allowlist applied to them too, such files were silently dropped from the
  assembly, and applying it failed with "Unknown resource" followed by a platform rollback.
  Outside resource directories the allowlist still applies and now also accepts `.htm`
  (previously only `.html`).

### Changed

- MCP: `list_projects` returns brief cards by default (id, name, project kind, space,
  application count, deletion flag), like `list_apps` does; pass `brief=false` for full cards.

### Added

- `builds upload` reports the upload target: the JSON output carries `project-id` and
  `project-id-source` (`flag`/`env`/none), and when the target comes from `ELEMENT_PROJECT_ID`
  a stderr note says so – previously the build could silently land in the project from the
  environment when a new project was intended.
- `builds upload --new-project` uploads the build as a new project, ignoring
  `ELEMENT_PROJECT_ID` from the environment and the `.env` file.
- `builds upload` warns when the assembly name differs from the target project name: the
  console shows a project under the name of the last uploaded build, so a foreign build
  silently renames the project. The check is best effort and never blocks the upload.
- The command reference and its generator are under tests (`tests/test_cli_docs.py`): every
  command answers `--help`, every one is covered by a section of the reference, the pages stay
  fresh, and the two language versions actually differ.

## 2026-07-22 – 0.11.0

### Added

- The documentation site ([docs.keyfire.ru/elemctl](https://docs.keyfire.ru/elemctl/)), a full
  command reference and CLI help – complete in English and Russian.

## 2026-07-21 – 0.10.0

### Changed

- MCP: the environment is passed per call, and `apps list` is brief by default.
- The "no application source" error now tells you how to set a project up.

### Fixed

- CLI help is localized: the language is resolved before the argument parser is built.
- `apps create` surfaces the task's own compilation errors instead of the platform's generic
  "Неизвестная ошибка. Обратитесь к администратору".

## 2026-07-19 – 0.9.1

### Changed

- The command section of the help is named "commands", and the version is read from a single
  source.

## 2026-07-17 – 0.9.0

### Added

- `inspect` – parse a ready-made build archive.
- `builds get` and `builds delete` accept a build version and resolve it to the build id.

## 2026-07-15 – 0.5.0, 0.6.0, 0.7.0, 0.8.0

### Added

- `self-update` – update by unpacking the wheel, safe even when the running executable is locked
  (0.7.0).
- A plugin system: the platform debug adapter is contributed through extension points (0.5.0).

### Changed

- `verify` confirms the deploy by the applied build's id instead of the version string (0.8.0).
- The MCP tool guidance notes that long operations are asynchronous – run the CLI in the
  background (0.5.0).
- PyPI project links (Homepage / Repository / Issues) in the package metadata (0.6.0).

### Fixed

- The MCP server honours the global configuration arguments (`--env-file` and the rest) (0.7.0).

## 2026-07-12 – 0.4.0, 0.4.1

### Added

- Full ru/en bilinguality: runtime i18n (`--lang` / `ELEMCTL_LANG`), with the README and the
  specification in both languages.
- `apps debug` – the data for a platform debug session (`POST /actions/debug`).

### Changed

- Releases publish to PyPI on a `v*` tag through Trusted Publishing, with signed provenance
  attestations; the `vscode-v*` tags are left untouched.

## 2026-07-10 – 0.2.0, 0.2.1, 0.3.0

### Added

- Initial release: a client for the documented Console API v2, `.xasm`/`.xlib` builds from
  source, a one-command deploy with an honest check that the change actually applied, a CLI and an
  MCP server – written clean-room, to the specification in `docs/SPEC.md` (0.2.0).
- `apps ensure` – create the application only when it is absent (0.3.0).

### Changed

- `apps find` skips deleted applications; `--include-deleted` restores the old behaviour (0.3.0).

### Fixed

- `apps find` exits 0 when the application is absent instead of failing (0.2.1).
