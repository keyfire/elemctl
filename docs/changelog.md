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
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The VS Code debug companion in
`editors/vscode` is released separately under the `vscode-v*` tags and is not tracked here.

## 2026-07-26 – 0.15.0

### Added
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
- The documented behaviour of deleting a build was wrong: the platform rejects it with a 500
  only while an application created from that build is still alive – after the application
  has really disappeared the same request succeeds. That is why `probe` deletes the
  application first, waits for it to be gone (the new `wait_app_deleted` of the client), and
  only then deletes the build.

### Documentation
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

## 2026-07-24 – 0.13.1

### Fixed
- Build: files inside resource directories (the literal directory name is `Ресурсы`) are
  now archived regardless of extension (`.pdf`, `.htm`, `.mxl`, `.docx`, `.xsd` etc.) – per
  the platform documentation a resource is an arbitrary file. Previously the general
  extension allowlist applied to them too, such files were silently dropped from the
  assembly, and applying it failed with "Unknown resource" followed by a platform rollback.
  Outside resource directories the allowlist still applies and now also accepts `.htm`
  (previously only `.html`).

## 2026-07-24 – 0.13.0

### Changed
- MCP: `list_projects` returns brief cards by default (id, name, project kind, space,
  application count, deletion flag), like `list_apps` does; pass `brief=false` for full cards.

## 2026-07-24 – 0.12.0

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
