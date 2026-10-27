# Changelog

**English** · [Русский](CHANGELOG.ru.md)

Notable changes to elemctl, newest first. Entries are grouped by day; the versions released that
day are named in the heading. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

New entries must link to their pull request, for example
`([#12](https://github.com/keyfire/elemctl/pull/12))`, so readers can inspect the
code and reason for a change. Describe user-visible behavior; exclude real
application or project identifiers and internal infrastructure.

Run `python scripts/changelog-link.py <number>` to add the link and rebuild
the generated site pages. This updates both language editions and their mirrors
together.

## 2026-10-08 – 0.52.0

### Added

- **Verify the target application before deployment.** The optional `--expected-app-name` and `--expected-app-uri` specify the expected application name and URL. If either differs from the server's application card, `deploy` stops before building or uploading. The library and MCP support the same check. ([#58](https://github.com/keyfire/elemctl/pull/58))

## 2026-09-30 – 0.50.0, 0.51.0

### Added

- **Repeatable plugin options: `Argument(..., multiple=True)`.** Commands receive a list of values in CLI order, and the corresponding MCP tool accepts an array. Previously, repeating an option kept only its last value: a command given seven files uploaded one. ([#54](https://github.com/keyfire/elemctl/pull/54))

- **Multiple values for positional plugin arguments: `multiple=True`.** Supply consecutive values or repeat the `cli_alias` option. Previously, repeating the option kept only its last value. The MCP tool accepts an array. Check for `plugins.POSITIONAL_MULTIPLE` when supporting older cores, which reject this argument definition. ([#56](https://github.com/keyfire/elemctl/pull/56))

### Changed

- **Reject conflicting values for a single-value option.** Previously, `--output a --output b` wrote to `b` and ignored `a` without a warning. The CLI now exits with code 2 and reports the option and both values, including for plugin commands. Identical values, repeatable options and flags remain valid. ([#57](https://github.com/keyfire/elemctl/pull/57))

### Fixed

- **Filter by multiple statuses with `apps list --status running --status stopped`.** Previously, the second option replaced the first despite the help documenting multiple statuses. Both are now included. Comma-separated values remain supported. ([#54](https://github.com/keyfire/elemctl/pull/54))

- **Repeatable `apps token-access --user` and `probe --cleanup` options.** Previously, the second value replaced the first without a warning. Each user or temporary application now has a separate result, and a failure does not interrupt the remaining items. The MCP tools also accept a list. ([#55](https://github.com/keyfire/elemctl/pull/55))

## 2026-09-29 – 0.47.0, 0.48.0, 0.49.0

### Added

- **Project details in the result of `builds upload` without a project ID.** Previously, the command printed `project-id: null` even when the server returned an ID. The result now includes `project-id` and the `project` card. A message on stderr reports whether the project was created or selected by the `Ид` in `Проект.yaml`. ([#52](https://github.com/keyfire/elemctl/pull/52))

- **Plugin command invocation source in `CommandContext.surface`.** The value is `SURFACE_CLI` for a CLI subcommand, `SURFACE_MCP` for an MCP tool and `None` for a manually constructed context. Previously, plugins had to infer the source from `context.log`. ([#47](https://github.com/keyfire/elemctl/pull/47))

- **`--quiet` at any position in a command.** Previously, placing the flag after a plugin command caused an "unrecognized arguments" error. It suppresses progress and warning messages on stderr, including plugin output through `context.log`. Results, errors and exit codes are unchanged. ([#47](https://github.com/keyfire/elemctl/pull/47))

- **`apps export-extension` saves the build of an extension applied to an application.** The MCP
  tool `export_extension` does the same. If the application has no such extension, the error lists
  the ones it has. It needs Console API 2.1. ([#48](https://github.com/keyfire/elemctl/pull/48))
- **Export the application's current build with `apps export`.** The same operation is available through MCP as `export_app`. A build uploaded to a project is exported with its server-assigned number. Use `apps export-extension` for applied extensions. ([#49](https://github.com/keyfire/elemctl/pull/49))

### Changed

- **Find a build's project in `apps create --version-id`.** If the project from `ELEMENT_PROJECT_ID` does not contain the build, the command searches other projects. An incorrect explicit `--project-id` causes an error that identifies the required project. The MCP tools `create_app` and `ensure_app` behave the same way. ([#52](https://github.com/keyfire/elemctl/pull/52))

- **Report the absence of automatic cleanup in `builds list` for an extension project.** These builds remain until manually deleted, so a numbering gap indicates manual deletion. ([#52](https://github.com/keyfire/elemctl/pull/52))

- **Stop waiting after one minute of `UNKNOWN` status.** Previously, polling continued until the full timeout: five minutes for `deploy` and ten for a new application. Because `UNKNOWN` can also occur during transitions, polling continues for one minute before reporting an explanatory error. ([#47](https://github.com/keyfire/elemctl/pull/47), [#49](https://github.com/keyfire/elemctl/pull/49))

### Fixed

- **Preserve running commands with `self-update --stop-holders`.** Previously, updating could interrupt a pipeline-wait command with exit code 1 and no result. The flag now stops only MCP servers. Other commands are listed by PID and command line; if they hold package files, the update is refused until they finish. Use `--stop-holders=all` to stop all holders. ([#53](https://github.com/keyfire/elemctl/pull/53))

- **Warn about project renaming when uploading without a project ID.** If the server selects a project with the same `Ид` and a different name, `builds upload` and `probe` display a warning and return the previous name. The new name comes from the presentation in `Проект.yaml`; the documentation previously named the manifest's `Name` field incorrectly. ([#52](https://github.com/keyfire/elemctl/pull/52))

- **`ROUTE_NAME` is back in `elemctl.registry`.** The previous release renamed it to
  `ROUTE_NO_PROJECT_ID`, and code importing the old name broke. The old name is an alias now. ([#52](https://github.com/keyfire/elemctl/pull/52))
- **Check plugin arguments for conflicts with core names.** A plugin's `--timeout` did not receive its value, `--env-file` prevented MCP startup, and `handler`, `--help` or `-h` caused command or CLI failures. Conflicting plugins are now excluded and identified in an error message. ([#48](https://github.com/keyfire/elemctl/pull/48), [#49](https://github.com/keyfire/elemctl/pull/49))

- **Account for a deleted latest build when numbering in `deploy`.** The server counts deleted builds that are absent from the build list. The next-number calculation now also uses the local upload registry. If a deleted build was uploaded from another machine, its details may be unavailable; the command then reports the server-assigned number. ([#48](https://github.com/keyfire/elemctl/pull/48))

- **`build` packs an extension project as an extension.** Its manifest now has
  `ProjectKind: Extension` and `ManifestVersion: 1.1`, as the console writes it, and `build --kind`
  takes `extension`. Before, the server refused even a hand-corrected archive with
  "Unknown project kind". ([#49](https://github.com/keyfire/elemctl/pull/49))
- **Handle an unsupported endpoint on an older server without signing in again.** Previously, the 401 response "Handler of HTTP request ... not found" was treated as a rejected token and triggered another sign-in. The client now checks the response text first and reports the unknown method. ([#49](https://github.com/keyfire/elemctl/pull/49))

- **More precise numbering information in `builds list`.** An empty list produces a no-builds message; builds without numbers produce an insufficient-data message. If a gap involves both a numbering jump and a deletion, both causes are reported. ([#49](https://github.com/keyfire/elemctl/pull/49))

- **The warning about a disabled certificate check no longer names a setting nobody set.** It named
  `ELEMENT_TLS_VERIFY=false` even when the check was turned off in code. `UrllibTransport` now takes
  the reason in `tls_off_reason`. ([#49](https://github.com/keyfire/elemctl/pull/49))
- **Verify an applied extension without a false rollback report.** The application card contains the application's own build number, so `apps apply`, `deploy` and `verify-deploy` previously reported extension applications as rollbacks. Verification now uses the application's extension list. Servers without Console API 2.1 return "cannot verify". ([#50](https://github.com/keyfire/elemctl/pull/50))

- **Detect an extension build that is already applied in `apps ensure`.** Previously, comparing against the application card returned `applied: false`. The command now uses the application's extension list, as `apps apply` and `verify-deploy` do. The fix also applies to `ensure_app`. ([#51](https://github.com/keyfire/elemctl/pull/51))

### Documentation

- **The specification lists the right flags accepted after a subcommand.** It had `--version`, which
  is not accepted there, and lacked `--lang`, which is.
  ([#48](https://github.com/keyfire/elemctl/pull/48))
- **Document automatic cleanup of unused builds.** The server runs cleanup after a build is applied in a project application. It checks up to ten builds of that base and retains builds in use, the highest-numbered build, release builds and protected builds. Uploads by vendor and name are protected immediately. ([#49](https://github.com/keyfire/elemctl/pull/49))

- **Select projects by the `Ид` in their description.** Vendor and name do not establish project identity. An upload with the same `Ид` and a different name adds a build to the existing project and renames it. A new `Ид` with an existing vendor-and-name pair produces a 409 response. ([#50](https://github.com/keyfire/elemctl/pull/50))

- **Exclude extension builds from automatic cleanup.** Cleanup applies to application builds. All builds in an extension project remain until manually deleted. ([#51](https://github.com/keyfire/elemctl/pull/51))

- **Name the upload route without a project ID.** The server selects the project by `Ид`, rather than vendor and name. New registry entries use `no-project-id`; older entries with `vendor-name` remain readable. ([#51](https://github.com/keyfire/elemctl/pull/51))

## 2026-09-27 – 0.46.0

### Added
- **Check for removed metadata objects before `deploy`.** Previously, schema checks covered only existing files. Removing a catalog, document or register from the sources could therefore drop its entire table without a warning. The check now also uses the applied commit's file list and rejects these removals, like type narrowing, unless `--allow-data-loss` is set. ([#45](https://github.com/keyfire/elemctl/pull/45))

- **The `allow_data_loss` parameter for the MCP `deploy` tool.** Previously, overriding a schema-check refusal for type narrowing was possible only through the CLI. MCP clients can now provide the same permission. The refusal message identifies both the MCP parameter and the CLI flag. ([#45](https://github.com/keyfire/elemctl/pull/45))

- **Report server-assigned build numbers in `deploy`.** Uploading to a project assigns the next number for the project's base, regardless of the archive version. Previously, the report returned `ok`, with renumbering visible only as a difference between `version` and `applied-version`. A warning now appears before building, followed by the actual number after uploading. The report also includes `assembly-version` and `renumbered`. ([#45](https://github.com/keyfire/elemctl/pull/45))

- **List application users with `apps users`.** Previously, this list appeared only in `apps token-access` errors. The command and MCP tool `list_app_users` return the server's user data and counts of administrators and users with token access. ([#46](https://github.com/keyfire/elemctl/pull/46))

- **Check catalog `Ид` changes before `deploy`.** Replacing the identifier in an existing file creates a new metadata object. A server test confirmed loss of catalog data, while the previous check covered only fields. The change is now rejected as an object removal, with the original `Ид` included in the error for restoration. ([#46](https://github.com/keyfire/elemctl/pull/46))

### Changed
- **Use the upload registry's commit for `deploy` schema checks.** The card of a build that created its project has no commit. Previously, this caused the check to be skipped even when the commit was stored locally. The check now uses the upload registry and reports the commit's source. ([#45](https://github.com/keyfire/elemctl/pull/45))

- **Limit the upload registry to its latest thousand entries.** Previously, the file grew with every upload without a retention limit. Once the entry count exceeds the limit by 10%, the next upload removes older entries. Set a different limit with `ELEMCTL_REGISTRY_LIMIT`, or use `0` to disable it. ([#45](https://github.com/keyfire/elemctl/pull/45))

- **Document `Deleting` and `UNKNOWN` statuses.** The API reference defines application status as a string. The specification now includes two observed values: `Deleting` during application deletion and `UNKNOWN` when its database is missing. Polling for a stable state does not accept `UNKNOWN` as a result. ([#46](https://github.com/keyfire/elemctl/pull/46))

### Fixed
- **Clean up a probe with a custom name and version using `probe --cleanup`.** Previously, cleanup refused probes without the standard identifying markers, requiring manual removal of the application, builds and project. Created applications are now recorded in the upload registry, allowing cleanup to remove them and their uploaded builds. ([#46](https://github.com/keyfire/elemctl/pull/46))

- **Upload to the specified space.** Previously, the client sent `SpaceId`, which the server ignored. The new project's space was not set, and an invalid value produced no error. Uploads to an existing project now send `space-id`; new projects are created within a space through `POST /spaces/{space-id}/projects`. ([#46](https://github.com/keyfire/elemctl/pull/46))

- **Distinguish numbering jumps from automatic deletion in `builds list`.** Uploading by vendor and name retains the archive's number, from which project numbering continues. Previously, a gap before that number was incorrectly attributed to deleted builds. The registry now records the upload route so the gap can be identified as a numbering jump. ([#46](https://github.com/keyfire/elemctl/pull/46))

## 2026-09-25 – 0.45.0

### Added
- **Trace builds to their source code.** Uploading to a project sends the commit using the documented parameter name, and the server stores it on the build card. The branch, working-tree state and source directory are stored only in the local upload registry. `builds list --brief` and `apps get` identify the source of each value. ([#42](https://github.com/keyfire/elemctl/pull/42))

- **Manage token access with `apps token-access`.** Previously, HTTP service calls using a user's token returned 500 "Token access is denied" until access was enabled in the control panel. The command and MCP tool `token_access` can inspect and change the setting, then read it back. An error identifies users who are not connected to the application. ([#43](https://github.com/keyfire/elemctl/pull/43))

- **Remove a retained probe with `probe --cleanup`.** During manual cleanup, `builds delete` without a project searched the environment's project rather than the probe's. The new command removes the application, its build and the empty project in the order required by the server. It refuses applications not created by a probe. The `probe --keep` result includes the cleanup command and manual removal steps. ([#43](https://github.com/keyfire/elemctl/pull/43))

### Fixed
- **Explain server startup and wait for the console.** Previously, commands returned an unexplained 404 while the console was starting, and `deploy` failed while listing builds. The error now explains the cause and recommends retrying after `/console` returns 302. `deploy` waits for the console for up to `--server-start-timeout` seconds. ([#42](https://github.com/keyfire/elemctl/pull/42))

- **Check tabular parts before `deploy`.** Previously, removing a tabular part could delete its rows without a warning. In this release, removal of a tabular part, attribute or resource produces a warning before building without stopping deployment. Type narrowing within a tabular part is rejected as elsewhere. A skipped check reports its actual cause instead of always reporting a missing commit. ([#42](https://github.com/keyfire/elemctl/pull/42))

- **Detect recently published releases in `self-update`.** Both PyPI indexes can show the previous version for a while after publication, causing the command to report no updates. It now checks both indexes and pages for subsequent versions, reports discrepancies, and never replaces the installed package with an older release. ([#43](https://github.com/keyfire/elemctl/pull/43))

## 2026-09-24 – 0.44.0

### Added
- **Validate the manifest before building in `probe`.** Without `Представление`, the server rejected the project with an unexplained 500 response; without `ЯзыкРазработки`, application creation failed. Setting `ЯзыкПоУмолчанию` without `ЯзыкиЛокализации` also caused an unexplained rejection. Validation now stops before building and lists the missing keys with lines to add. ([#41](https://github.com/keyfire/elemctl/pull/41))

## 2026-09-23 – 0.43.2

### Changed
- Python comments and docstrings consistently use hyphens. Ordinary string literals remain unchanged.
  ([#40](https://github.com/keyfire/elemctl/pull/40))

## 2026-09-22 – 0.43.1

### Fixed
- **`self-update` reports an incomplete PyPI response without touching the installed package.**
  The simple index, metadata and wheel downloads missed HTTP parser failures, so an interrupted
  response could end in a traceback. ([#38](https://github.com/keyfire/elemctl/pull/38))
- **Validate the base URL scheme during connection setup.** Previously, an address without `http://` or `https://` reached `urllib` and caused an unhandled `ValueError`. It is now rejected during configuration validation. ([#38](https://github.com/keyfire/elemctl/pull/38))

## 2026-09-19 – 0.43.0

### Added
- **Server log guidance in `probe` and `deploy` results.** A failed creation or apply can return only "Contact administrator for details", without a compilation error. The new `hint` field recommends finding the last `Caused by` line in `server.log`. A nearby `SrcPath:` line contains the file path. ([#36](https://github.com/keyfire/elemctl/pull/36))

### Fixed
- **Retry application-card polling after a connection loss.** Previously, only the wait for a new application tolerated a missed poll. One connection loss could interrupt `deploy`, `apps apply` or `probe` cleanup and leave a build on the server. All three now continue polling within their configured timeout. ([#37](https://github.com/keyfire/elemctl/pull/37))

- **Handle incomplete HTTP responses without a traceback.** The transport previously caught only `OSError`, while truncated responses and malformed status lines raise separate `http.client` exceptions. These are now handled as network errors with the usual JSON result. Reads eligible for retry after a connection loss are also retried for these errors. ([#37](https://github.com/keyfire/elemctl/pull/37))

- **Check build availability before `apps create` and `apps ensure`.** A `--version-id` absent from the project's build list is rejected before application creation. A build removed by server cleanup previously caused 400 "Can't create application", which could be mistaken for an application-count limit. The error now explains the cause and identifies the build used by a running application in the project. The MCP tools `create_app` and `ensure_app` provide the same check. ([#36](https://github.com/keyfire/elemctl/pull/36))

- **Retain the created application's ID when waiting fails.** In `apps create --wait` and `apps ensure --wait`, a connection loss while reading tasks previously returned only a network error. If the application started later, its ID had to be found by name. The result now retains the ID alongside `wait-error` and exits with code 1. Interrupted task-list reads are retried. ([#36](https://github.com/keyfire/elemctl/pull/36))

- **Isolate plugin-loading failures.** A factory error in a plugin requiring a newer core previously caused a Python traceback for every command, including core commands. The failed plugin is now excluded and identified on stderr and in `elemctl plugins`. Calling its unavailable command returns a normal JSON error, while the MCP server starts with the remaining plugins. ([#36](https://github.com/keyfire/elemctl/pull/36))

## 2026-09-18 – 0.42.0

### Added
- **Use `cli_alias` for a positional plugin argument.** Previously, `wiki-get --page 123` failed with "unrecognized arguments" even though `wiki-publish` supported that option. Adding a second `Argument("--page")` would have duplicated the MCP `page` parameter. The alias now applies only to the CLI; the MCP schema retains one parameter. Positional syntax remains supported. Supplying both forms, or omitting a required argument, causes a parsing error. Plugins without `cli_alias` are unchanged. ([#34](https://github.com/keyfire/elemctl/pull/34))

### Fixed
- **Read `ELEMCTL_NO_PROXY` from an environment's `.env` file.** MCP tools accept `env_file`, but previously could not disable the proxy for one environment among several served by the same process. This prevented access to local servers through an unreachable proxy; the CLI workaround `ELEMCTL_NO_PROXY=1` could not be applied to one MCP call. The setting is now read from the environment's file. An explicit process variable takes precedence, and one file's setting does not affect other environments. ([#32](https://github.com/keyfire/elemctl/pull/32))

- **Print count and truncation notes after the `builds list` result.** Output order now matches `apps list`. When streams were merged with `2>&1` or `stderr=STDOUT`, notes previously appeared before the JSON result. The corrected order still does not guarantee that merged output is a valid JSON document. Parse stdout separately. ([#32](https://github.com/keyfire/elemctl/pull/32))

- **Refresh MCP clients after `.env` changes.** Previously, the cache keyed clients only by `env_file` for the process lifetime. File edits such as adding `ELEMCTL_NO_PROXY=1` required a restart, including for the default file without `env_file`. The cache now checks modification time and size; a change refreshes the client on the next call for that environment. A missing cached `env_file` or startup `--env-file` produces an error instead of reusing the previous client. An explicit `--env-file` is still checked at `elemctl mcp` startup: if missing, the server does not start and exits with code 1. Other default-environment configuration errors are returned when a tool is called. ([#33](https://github.com/keyfire/elemctl/pull/33))

- **Explicit override for `Config.from_env(no_proxy=...)`.** Previously, `no_proxy` was not removed from `**overrides`, causing `TypeError` during unknown-parameter validation. It now takes precedence over `ELEMCTL_NO_PROXY` in the process environment and file, as other explicit arguments do. There were no callers passing this parameter at the time of the fix. ([#35](https://github.com/keyfire/elemctl/pull/35))

- **MCP client-cache consistency and limitations.** `create_app` and `ensure_app` previously resolved `client(env_file)` repeatedly – up to four times inside `_create_app`, in addition to the tool's own lookup. A file change during a call could switch some steps to another client. Each tool now resolves its client once and passes it through.

  The replacement client is cached before the previous one is closed, so a `close()` failure no longer leaves the old entry in place. A lock protects the cache dictionary. Calls were sequential at the time of this change; the lock also supports a possible future threaded or asynchronous dispatcher.

  Modification time and size do not detect a file becoming unreadable without either changing. Reading the file on every lookup would remove this limitation at an additional I/O cost. A POSIX permission check would not cover the equivalent case on Windows. This limitation is documented beside the fingerprint calculation. ([#35](https://github.com/keyfire/elemctl/pull/35))

## 2026-09-13 – 0.41.0

### Added
- **Plugin command exit status through `exit-code`.** If the result contains an integer from 0 to 255, the CLI exits with that code. A pipeline can therefore distinguish detected differences from execution failures. Without `exit-code`, `"ok": false` still maps to code 1. ([#31](https://github.com/keyfire/elemctl/pull/31))

- **Check for attribution used instead of an explanation.** Documentation should describe a change and its reason rather than identify who requested it. The check covers both language editions and comments and docstrings in `src`, `scripts`, `tests` and `tools`. ([#30](https://github.com/keyfire/elemctl/pull/30))

- **Require explicit stdin for child processes in `src`.** The conventions check applies only to the shipped package. Scripts, helper tools and tests run from a console and may pass its stdin to a child process. ([#29](https://github.com/keyfire/elemctl/pull/29))

- **Detect duplicate test names in `tests/test_conventions.py`.** When two definitions share a name, Python uses the last one and the earlier test is not executed. The check reports the line of the duplicate definition to rename. ([#28](https://github.com/keyfire/elemctl/pull/28))

### Fixed
- **Isolate child-process stdin from the MCP server.** On Windows, inheriting the client's pipe prevented a child process from completing: `git status --porcelain` reached its 15-second timeout and git was reported unavailable. Process launches in `src` now use `stdin=subprocess.DEVNULL`. The tested tool call decreased from 47 seconds to 0.8 seconds. ([#29](https://github.com/keyfire/elemctl/pull/29))

- **Consistent line endings through `.gitattributes`.** The rule `* text=auto eol=lf` sets LF endings for text files on every machine. READMEs generated by `scripts/sync-docs.mjs` previously contained mixed line endings. ([#28](https://github.com/keyfire/elemctl/pull/28))

### Documentation
- **Update the shared checks to `docsguard@v0.7.1`.** This release adds a dictionary of borrowed Russian terms: `пин`, `прогон`, `билд`, `дефолт` and eleven others. The pinned version was updated separately before the new checks were enabled. ([#26](https://github.com/keyfire/elemctl/pull/26))

- **Check Russian prose against the dictionary.** The check discovers `docs/*.ru.md` automatically. Root documents are listed in `scripts/check_docs.py`: `README.ru.md`, `CHANGELOG.ru.md` and `CLAUDE.md`. Inline code and fenced code blocks are excluded. ([#26](https://github.com/keyfire/elemctl/pull/26))

- **Format quoted terms as inline code.** The 12 September entry lists words removed from the documentation that previously triggered the check. They are now enclosed in backticks. The exact command caption in the Russian edition is formatted the same way. ([#26](https://github.com/keyfire/elemctl/pull/26))

- **The shared guard is pinned to `docsguard@v0.8.0`.** The dictionary of borrowed words grew
  by six: `дашборд`, `бэкенд`, `лаунчер`, `мейнтейнер`, `топ-объект`, `легаси`.
  ([#27](https://github.com/keyfire/elemctl/pull/27))
- **Check Russian source-code messages against the dictionary.** Coverage now includes CLI help, error messages and tool descriptions shown by MCP clients, in addition to website pages. The checked files are the message catalog `src/elemctl/i18n.py` and tool descriptions in `src/elemctl/mcp_server.py`. ([#27](https://github.com/keyfire/elemctl/pull/27))

- **Replace `лаунчер` in the `self-update --stop-holders` entry.** The Russian text now uses the term for the program that starts the command as its child process. The same wording was corrected in `tests/test_selfupdate.py`. ([#27](https://github.com/keyfire/elemctl/pull/27))

- **Update the shared checks to `docsguard@v0.9.0`.** This release handles byte-order marks added by some Windows editors. Previously, parsing with `ast` raised `SyntaxError` and prevented findings from other files from being returned. The release also adds the duplicate-test-name check. ([#28](https://github.com/keyfire/elemctl/pull/28))

## 2026-09-12 – 0.40.1

### Added
- **Check explicit `newline` in `tests/test_conventions.py`.** The check parses `src/`, `scripts/` and `tools/` with `ast` and examines `write_text` and `open` in text-write mode. It is provided by the shared `docsguard` package. ([#22](https://github.com/keyfire/elemctl/pull/22))

### Changed
- **Edit the `--help` text.** Capitalized emphasis was removed from `verify-deploy`, `--project-id`, `--force-rename` and the `tasks` epilogue. The Russian text also replaced two borrowed terms, "таймаут" and "деплой", with their Russian equivalents. The command reference was rebuilt from the updated strings. ([#25](https://github.com/keyfire/elemctl/pull/25))

- **Share the implementation of three documentation-coverage checks.** Tools, environment variables and archive file extensions were previously checked by three copies of the same set operation. A defect in one copy could go undetected. All three checks now use `coverage_problems` from `docsguard`. ([#20](https://github.com/keyfire/elemctl/pull/20))

### Fixed
- **Preserve line endings in `scripts/changelog-link.py`.** Previously, adding one link replaced every line ending in four files with the operating system's default. The same issue was fixed in `render-diagrams.py`, the token cache, pipx metadata and the adapter index. ([#22](https://github.com/keyfire/elemctl/pull/22))

### Documentation
- **Edit the documentation.** Long sentences were shortened, and stock phrases, parenthetical asides and capitalized emphasis were removed. The English text was edited for natural technical usage. The Russian changelog also replaced borrowed terms listed in the dictionary. ([#24](https://github.com/keyfire/elemctl/pull/24))

- **Update the shared checks to `docsguard@v0.5.0`.** The release adds an explicit-`newline` check: without it, text writes use the operating system's line endings. The pinned version was updated separately before enabling the check. ([#21](https://github.com/keyfire/elemctl/pull/21))

## 2026-09-11 – 0.39.0, 0.40.0

### Added
- **Retrieve one build card over MCP with `get_build`.** Previously, MCP provided only the list, so obtaining a manifest name, vendor or comment required a CLI call. The new tool accepts a build version or ID. ([#14](https://github.com/keyfire/elemctl/pull/14))

- **Verify application creation in `apps create` and `apps ensure`.** Enable verification through `--verify` in the CLI or `verify` in MCP. Previously, only `deploy`, `apps apply` and `verify-deploy` offered the check, requiring a separate call after creating an environment. The report is returned in the `verify` field. ([#5](https://github.com/keyfire/elemctl/pull/5))

### Changed
- **Analyze numbering gaps in build-list summaries.** In this release, the summary identifies removed builds from gaps in the sequential numbering of one base version, replacing the threshold of thirty builds. `ASSEMBLY_STORE_LIMIT` was removed with the threshold. ([#13](https://github.com/keyfire/elemctl/pull/13))

- **Reject connection options in `build` and `inspect`.** Previously, `--env-file`, `--base-url` and credentials were ignored without a warning, although the call could appear to build for a specified environment. These options now cause an error with exit code 1. ([#7](https://github.com/keyfire/elemctl/pull/7))

- **Correct the description of build retention.** The earlier assumption of a per-project build limit that evicted older builds was incorrect. The server deletes unused builds. The build-list summary and Console API pages were updated. ([#6](https://github.com/keyfire/elemctl/pull/6))

- **Verify the actual build after `--wait`.** After a failed apply, the server can restore the previous build and start the application. A running status alone does not confirm success. Failed verification now exits with code 1. Use `--no-verify` to wait for status only. ([#5](https://github.com/keyfire/elemctl/pull/5))

### Fixed
- **Align descriptions of automatic build deletion.** The outdated retention limit was removed from CLI requirements, MCP-server pages, the `list_builds` description and code comments. They now describe deletion of unused builds consistently. ([#9](https://github.com/keyfire/elemctl/pull/9))

- **Accept build versions in `builds get`.** The documentation previously specified UUIDs only, so the command converted versions to IDs and received 404 responses. Tests on two installations confirmed version support. Both forms are now accepted. ([#8](https://github.com/keyfire/elemctl/pull/8))

### Documentation
- **Move the process encoding check to the shared `docsguard` package.** The check was originally part of elemctl, although the engine and bridge also start processes and can encounter decoding errors. The repository retains its directory list, and the pinned package version is updated to `v0.4.0`. ([#19](https://github.com/keyfire/elemctl/pull/19))

- **Install the shared guard by tag.** Previously, changes to `docsguard` on `@main` immediately affected checks and could cause failures without changes in this repository. Version updates are now separate changes; `tests/test_workflows.py` checks that workflows use the same tag. ([#18](https://github.com/keyfire/elemctl/pull/18))

- **Test that processes read as text specify an encoding.** A new script omitted the encoding and returned Russian page names with replacement characters while its exit code indicated success. The convention is documented in `CLAUDE.md`. ([#17](https://github.com/keyfire/elemctl/pull/17))

- **Move claim checks to the shared package.** The same facts can appear in multiple documents for elemctl, the engine and the bridge. `Claim`, `claim_texts` and `claim_problems` are now provided by `docsguard`. ([#16](https://github.com/keyfire/elemctl/pull/16))

- **`python scripts/rebuild-docs.py` rebuilds all generated pages.** The two generators for four pages previously had to run separately, and mirrors could be missed. The command returns an exit code and reports each generator's failure. ([#15](https://github.com/keyfire/elemctl/pull/15))

- **Detect inconsistent documentation claims.** A fact about the technology may appear in the specification, Console API and MCP pages, README and code comments. The checked facts are listed in `CLAIMS` in `scripts/check_docs.py`. ([#12](https://github.com/keyfire/elemctl/pull/12))

- **Add the pull request link and rebuild mirrors in one step.** The link is added in a separate commit after the pull request exists. `python scripts/changelog-link.py <number>` adds the link and updates the mirrors. ([#11](https://github.com/keyfire/elemctl/pull/11))

## 2026-09-10 – 0.37.0, 0.38.0

### Added
- **`verify-deploy` checks application of a build without deploying.** The library and MCP tool already offered this check, but the CLI did not, so CI scripts used `apps get` and `tasks list`. The command returns the same report as `deploy` and exits with code 1 on failure.

- **`--json` reserves stdout for the response.** Extra lines before JSON previously broke parsing. During command execution, stdout is redirected to stderr so plugin output and library warnings do not enter the result. The global flag is accepted in any position.

### Changed
- **Build-list completeness summary in `builds list`.** This release supplemented "30 of 30" with a retention-limit summary, based on the assumption of a fixed per-project build limit. Later releases corrected the description to account for automatic deletion of unused builds. **Behavior change:** MCP `list_builds` returns `{total, shown, summary, builds}` instead of an array.

- **Show a hint when a command group is called without an action.** `elemctl tasks --app-id ...` previously returned argparse's "invalid choice" error when the missing argument was `list`. The error now shows the call format and group actions; `tasks --help` describes both forms.

- **`--latest-build` selects the newest build by creation time.** Selecting the highest counter could previously return an older build after a project's base version changed.

### Fixed
- **Preserve hyphenated words across line wraps in the command reference.** argparse wrapped a long word at its hyphen, and joining the lines with a space produced `elemctl tasks get- group TASK_ID`. One joining rule now handles both the parser description and its epilogue.

- **Restart the build counter when the project's base version changes.** Auto-increment previously used the highest counter across all builds: `1.0.1-19001` led to subsequent 19xxx numbers, and switching to `1.0.2` would have continued at 19024. Only builds of the same base version are now considered, so the counter starts at `1.0.2-1`.

## 2026-09-09 – 0.36.0

### Changed
- **`apps list` hides deleted applications and reports their count.** The server retains them with status `Deleted` and their former ID; `--brief` previously did not exclude them. `--include-deleted` includes deleted records, and `--status deleted` includes them automatically. stderr reports a summary such as "7 live of 324" and the number shown when a further filter is used. stdout remains a JSON array.

- **The `list_apps` MCP tool accepts `include_deleted` and returns an object.** Alongside `applications`, the response contains the `total`, `live` and `shown` counts and a `summary` string. Previously it returned an array. `find_app` and name-to-ID resolution still receive deleted applications and filter them independently.

## 2026-09-06 – 0.35.0

### Added
- **`projects list --name` and `--include-deleted` are also available in MCP `list_projects`.** Deleted projects are excluded by default; `name` filters by a case-insensitive substring on the client, as in `apps list`. Previously, results included many deleted projects.

## 2026-09-05 – 0.34.0

### Fixed
- **Specify an application positionally or with `--app-id`.** Previously, `apps get`, `apply`, `delete`, `start`, `stop` and `debug` accepted only a positional argument, while `deploy` and `apps ensure` accepted only the option. Two different references in one call are rejected.

## 2026-08-31 – 0.33.0

### Added

- **The schema guard checks register dimensions.** Dimensions form the record key. Changing a dimension type or removing it converts records; values can collapse and cause a uniqueness error during apply, followed by rollback. A probe cannot predict this because its temporary application has no records.

- **Include SOAP client descriptions in the build.** `<Client>.Wsdl.<n>` and `<Client>.Xsd` are stored beside the project element, outside `Ресурсы`; their extensions were previously absent from the allowlist. A client with a missing description is reported before upload.

- **`apps list --status running` filters applications by status.** Multiple statuses can be separated by commas. This reduces the response size on environments with many applications.

- **Line-by-line errors in the deployment report.** `problems-lines` contains server messages split into lines, making object names and non-unique key values easier to read than in one JSON string with escaped `\n` and `\t`.

### Fixed

- **Wait for a busy application before applying.** A deployment immediately after another previously failed with "the application is busy" after uploading the build. The short wait applies only to that message; a missing application still fails immediately.

- **Stop the probe when the compatibility mode is unsupported.** An environment older than the project rejects it and reports many subsequent type and property errors, including in unchanged files. The cause is now reported separately and the subsequent errors are counted without parsing.

## 2026-08-30 – 0.32.3

### Changed

- **Include the probe in the package description.** The PyPI summary and site descriptions now mention server-side compilation checks without changing the working application, alongside application, build and deployment management.

## 2026-08-27 – 0.32.2

### Added

- **Create a GitHub release after publication.** After successful publication to PyPI, the workflow creates a GitHub release with the relevant changelog section as its body.

## 2026-08-26 – 0.32.1

### Changed

- **The local-cloud example in the documentation points at a placeholder domain** in the
  reserved `.example` zone: a configuration example must not name any real server.
- **The changelog is trimmed to two-four lines per entry**: what changed and why it matters;
  the history of a finding stays in the commits and the documentation.

## 2026-08-24 – 0.32.0

### Added

- **`apps apply [APP_ID] VERSION_ID` applies an uploaded build and verifies the result.** Previously the operation was available only through MCP. On failure, the server restores and starts the previous build, so the command checks the applied build and exits with code 1 if the new one was not applied. The CLI can run in the background for long operations.

- **`apps ensure` reports the applied build.** Previously, `--version-id` did not apply to an existing application because creation flags act only during creation. The response includes `applied` and `applied-version-id`, stderr identifies the apply command, and `--apply` performs it immediately. The MCP tool `ensure_app` also received the field.

### Fixed

- **`builds upload` accepts builds belonging to the target project.** Previously, the technical manifest name was compared with the project presentation in the console, so a valid upload could appear to be a rename. The comparison now uses the project presentation from the archive descriptor. Builds from another project are still rejected.

- **Explain `--new-project` in upload errors.** The earlier wording, "starts a separate project", did not account for uploads into an existing project. This release described selection by the manifest's vendor and name; that assumption was later corrected: the server identifies a project by its descriptor ID.

## 2026-08-18 – 0.31.0, 0.31.1

### Added

- **Warn on every run when TLS verification is disabled.** `ELEMENT_TLS_VERIFY=false` can remain unnoticed in `.env`. The warning goes to stderr, leaving JSON on stdout intact.

- **Configure TLS with a private CA and strict verification.** The RFC 5280 strict profile enabled in Python 3.13 rejected a private cloud's internal CA. `ELEMENT_CA_FILE` adds a PEM file to the trust store, `ELEMENT_TLS_STRICT=false` disables only the strict profile, and `ELEMENT_TLS_VERIFY=false` disables verification. An invalid value causes a configuration error. Contributed by @dvkuchin (pull request #4).

## 2026-08-14 – 0.30.0

### Changed

- **`builds list` returns ten recent builds by default.** `--limit` sets the count (`0` means all); stderr reports the shown and total counts, and `--brief` retains the ID, versions, date, branch and commit. MCP `list_builds` accepts the same options. This allows callers to find the applied build's commit without fetching the full list.

### Fixed

- **Prevent a probe build from being selected as the latest by counter.** About one random version token in forty contained only digits and was interpreted as a large counter, so `--latest-build` could select a probe build. An all-digit token is now regenerated. The case was observed in CI.

## 2026-08-11 – 0.29.0

### Changed

- **A missing `.env` file is named by its absolute path and the current directory.** A relative
  `--env-file` resolves against the current directory rather than `--project-dir`, and in a
  background run the refusal read as an unreachable stand.
- **`probe` states what it needs of the project layout.** The directory has to sit as
  `{repository}/{Vendor}/{Name}/Проект.yaml` - which used to be learned from the error afterwards.

## 2026-08-10 – 0.28.0

### Documentation

- **Complete the MCP tool list.** Seven of the twenty-four tools were named only in source code; the page previously used "and others" instead of describing them.

- **Document environment variables**, including `ELEMCTL_NO_PLUGINS`, CI variables used for the run number, and system variables `LC_ALL`/`LANG`.

- **Correct outdated information.** Common flags are accepted in any position, `.htm` is an allowed archive extension, and files inside `Ресурсы` are not filtered by extension.

- **Generate repeated README sections from site pages.** Their contents had previously diverged. `scripts/sync-docs.mjs` inserts the page section between README markers.

- **Architecture diagram `docs/architecture.svg`.** It shows the interfaces, engine, deployment cycle with rollback and probe. Its palette matches the site theme.

- **Documentation guard `scripts/docsguard.py` and CI `docs` job.** The guard reports tools missing from the table, environment variables used in code but not documented, and stale changelog mirrors. Tests cover each finding type.

### Added

- **`deploy` takes an application name as well as an id** - the way `apps get`, `apps start`,
  `apps stop` and `apps debug` have long done.

### Changed

- **Move the VS Code extension to [XBSL](https://github.com/keyfire/xbsl).** Starting with version 0.57.0, it includes 1C:Element application debugging and the deployment button. Previously, the split required entering the elemctl path and application ID twice. elemctl retains `apps debug`, `debug-adapter` and the `elemctl.debug_adapter` entry point.

## 2026-08-07 – 0.26.0, 0.27.0

### Added

- **Build and deploy projects with English artifacts.** `build`, `deploy` and `probe` find both `Project.yaml` and `Проект.yaml`; the archive parser accepts English keys and values; and the schema guard recognizes Russian and English names of the same primitive type. Translating a description is not treated as a destructive change.

### Changed

- **Do not send commit and branch separately when uploading a build.** The documented method does not accept them and the server ignores supplied values. The commit on the build card comes from the project's repository link. Branch and commit remain in the archive manifest.

- **Report a skipped schema check.** The `schema-check` field contains `clean`, `allowed` or `skipped:<reason>` so a skipped check can be distinguished from a passed one.

## 2026-08-03 – 0.25.0

### Changed

- **Reject a build with a different name.** The console displays a project under the name of the last uploaded build; deleting that build does not restore the previous name. The error suggests `--force-rename` for an intentional rename or `--new-project` for a build from another project.

## 2026-07-31 – 0.23.0, 0.24.0

### Fixed

- **`self-update` detects a release immediately after publication.** PyPI JSON metadata can lag by minutes, causing the command to report "already current". The file list now comes from the simple index (PEP 691), and versions are ordered numerically.

### Changed

- **The MCP server supports both major versions of `mcp`.** In `mcp 2.0.0`, the server class moved without an alias and a fresh installation failed to start. The import checks both locations, two helpers handle response differences, and CI tests both versions. The version pin was removed.

- **`serverInfo` names the version of elemctl itself,** not of the `mcp` package.

## 2026-07-30 – 0.22.0

### Added

- **Include adjacent library projects in builds**, including transitive dependencies. A declared library without a local project remains an external dependency of the 1C:Element application. Contributed by @dvkuchin (pull request #3).

### Fixed

- **Identify proxy-related connection failures.** A proxy unable to reach the environment can fail similarly to an unavailable environment. A clearly unsuitable proxy is bypassed automatically; `ELEMCTL_NO_PROXY=1` bypasses it for all calls; and a failed proxied call identifies the proxy.

- **`self-update --stop-holders` excludes its own process tree.** Previously, it could offer to terminate its parent launcher because its name matched a process holding a file, interrupting the update.

## 2026-07-28 – 0.20.0, 0.21.1

### Added

- **Application creation reports how to sign in.** `apps create`, `apps ensure` and their MCP equivalents include a `sign-in` field. A new application has its own empty user list, so sign in with a control-panel account. Failed sign-in attempts are counted per user.

### Changed

- **`self-update` restores the installation after a failed update.** Previously, `pip install --upgrade` could remove the package but fail to unpack the replacement because a file was in use. The installed package is now renamed first, holding processes are reported by name and pid, and the previous installation is restored if the new package cannot be imported.

## 2026-07-27 – 0.19.0

### Added

- **`user-lists calculation-rules` reapplies rules for constructing a user from the provider response.** Recreating the sign-in service resets the rules, and the read API does not return them. The report identifies the submitted data and acceptance of the request, and states that the API cannot confirm the value. Check it in the console or through a live sign-in.

### Fixed

- **Record the correct branch name in CI builds.** The runner checks out a commit rather than a branch, so the build previously recorded `HEAD`. The name now comes from the CI environment; if unavailable, the field remains empty.

## 2026-07-26 – 0.15.0, 0.16.0, 0.17.0, 0.18.0

### Added

- **`deploy` reports its target and how it was selected.** The report includes `app-name`, `app-id-source` and `project-id-source`. The target appears in the first progress line before the build, allowing an incorrect deployment to be interrupted.

- **Report files excluded from the build** through `skipped-files` and a warning. Files with extensions outside the allowlist are included only from a `Ресурсы` directory. Previously, exclusion from another directory was detected only during apply.

- **Check for destructive schema changes before deployment.** Narrowing an attribute's length or changing its type recreates the object's data. `deploy` compares sources with the commit of the applied build and stops before building if it finds such changes; `--allow-data-loss` skips the check. If comparison is unavailable, the report states this and deployment continues.

- **`user-lists` manages sign-in settings for user lists.** The commands are `list`, `get`, `self-registration` and `password-login`. Without a flag, both configuration commands only read state. MCP provides `list_user_lists` and `configure_user_list`.

- **The `elemctl.commands` entry point group.** A plugin can declare a command once for use as both a CLI subcommand and an MCP tool. This supports environment-specific commands outside the public core.

- **`elemctl probe` checks compilation in an isolated application.** Compilation runs on the server when a build is applied. The command builds an archive, creates a temporary application and cleans up the created resources. Errors include file, line, column, environment and text.

### Fixed

- **A common option is accepted after a subcommand too** - `elemctl deploy --env-file .env` no
  longer fails with the argparse "unrecognized arguments".
- **Remove a rejected token from the cache.** The server returns 400 rather than 401 and gives the reason in `error_description`. For this response, the cache file is removed and the request is retried once.

- **Delete a probe build after its application is removed.** The server rejects build deletion while an application created from it exists. The probe first waits for application removal.

### Documentation

- **The Console API contract gained the user lists** (section 4.7) and what the API does not
  carry at all: the composition of the authentication forms and the "connect users automatically"
  setting.
- **Project selection by `Vendor` and `Name` as described in this release.** The initial assumption was that the `Ид` in `Проект.yaml` was unused and a duplicate pair returned 409 `ALREADY_EXISTS`. Later checks clarified the contract: projects are identified by `Ид`, while vendor and name must be unique within a space.

## 2026-07-25 – 0.14.0

### Added

- **The version suffix comes from the CI run number** (`CI_PIPELINE_IID`, `GITHUB_RUN_NUMBER`,
  `BUILD_NUMBER`) when there is neither an explicit version nor a previous build: a clean CI
  working directory no longer yields `-1` on every run.
- **`build` and `deploy --dry-run` report build details:** `name`, `vendor`, `version`, `version-source`, `kind`, `branch`, `commit` and `dirty`. CI can obtain the version from the report instead of parsing the file name.

- **`apps get/delete/start/stop/debug` accept an exact application name or ID**, including through MCP. Multiple matches produce an error listing the IDs.

- **`apps list --brief` returns brief cards.** Checking "acme-crm-dev" requires a response of hundreds of bytes instead of tens of kilobytes.

- **Uncommitted changes in the project directory are visible** in the report (`dirty`,
  `dirty-files`), and `--require-clean` stops the work before the build.

### Changed

- **`apps list --name` filters on the client.** The server ignores the query parameter, so the previous server-side filter did not restrict results.

- **The `Проект.yaml` descriptor accepts keys in both languages.** A project with English keys was previously rejected even though the technology supports bilingual sources.

- **Status waits treat `Error` as terminal.** Deployment reports compilation errors immediately instead of waiting for the timeout.

### Fixed

- **Apply `--lang en` to all user-facing messages.** Around forty Russian strings were hard-coded outside the message catalog; a test checks modules for new occurrences.

## 2026-07-24 – 0.12.0, 0.13.0, 0.13.1

### Fixed

- **Include files in `Ресурсы` directories regardless of extension.** The general allowlist previously applied there too, and a missing file caused apply to fail with "Неизвестный ресурс". The allowlist still applies outside resource directories and now includes `.htm`.

### Changed

- **MCP: `list_projects` returns brief cards by default** - like `list_apps`; `brief=false`
  returns the full ones.

### Added

- **`builds upload` reports its target** in `project-id` and `project-id-source`. Previously, a build could be uploaded to the project from the environment when a new project was intended.

- **`builds upload --new-project`** uploads the assembly as a new project, ignoring
  `ELEMENT_PROJECT_ID`.
- **`builds upload` warns when a build has a different name.** The console displays a project under the name of the last uploaded build.

- **Test the command reference and generator** (`tests/test_cli_docs.py`). Every command supports `--help` and has a reference section; the tests also check that the language editions differ.

## 2026-07-22 – 0.11.0

### Added

- The documentation site ([docs.keyfire.ru/elemctl](https://docs.keyfire.ru/elemctl/)), a full
  command reference and CLI help – complete in English and Russian.

## 2026-07-21 – 0.10.0

### Changed

- MCP: the environment is passed per call, and `apps list` is brief by default.
- The "no application source" error includes instructions for setting up a project.

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

- `inspect` parses an existing build archive.

- `builds get` and `builds delete` accept a build version and resolve it to the build ID.

## 2026-07-15 – 0.5.0, 0.6.0, 0.7.0, 0.8.0

### Added

- `self-update` updates the package by unpacking a wheel, including when the running executable is locked (0.7.0).

- Plugin system: the 1C:Element debug adapter is connected through entry points (0.5.0).

### Changed

- `verify` confirms the deploy by the applied build's id instead of the version string (0.8.0).
- The MCP tool guidance notes that long operations are asynchronous – run the CLI in the
  background (0.5.0).
- PyPI project links (Homepage / Repository / Issues) in the package metadata (0.6.0).

### Fixed

- The MCP server uses global configuration arguments, including `--env-file` (0.7.0).

## 2026-07-12 – 0.4.0, 0.4.1

### Added

- Russian and English support: runtime messages (`--lang` / `ELEMCTL_LANG`), README and specification in both languages.

- `apps debug` returns data for a 1C:Element application debug session (`POST /actions/debug`).

### Changed

- Releases publish to PyPI on a `v*` tag through Trusted Publishing, with signed provenance
  attestations; the `vscode-v*` tags are left untouched.

## 2026-07-10 – 0.2.0, 0.2.1, 0.3.0

### Added

- Initial release: a client for documented Console API v2, `.xasm`/`.xlib` builds from source, one-command deployment with apply verification, a CLI and an MCP server. The implementation was written clean-room to `docs/SPEC.md` (0.2.0).

- `apps ensure` – create the application only when it is absent (0.3.0).

### Changed

- `apps find` skips deleted applications; `--include-deleted` restores the old behaviour (0.3.0).

### Fixed

- `apps find` exits 0 when the application is absent instead of failing (0.2.1).
