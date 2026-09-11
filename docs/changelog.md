---
title: "Changelog"
description: "What changed in elemctl from release to release, grouped by day."
sidebar:
  label: Changelog
  order: 7
---

<!-- Assembled from CHANGELOG.md; rebuilt by python scripts/rebuild-docs.py. Do not edit by hand. -->

Notable changes to elemctl, newest first. Entries are grouped by day; the versions released that
day are named in the heading. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every entry ends with a link to the pull request it came from –
`([#12](https://github.com/keyfire/elemctl/pull/12))`. That is why changes come in through pull
requests: an entry without such a link is unfinished, because the reader has no way from the line
to the code and the reasoning behind it. Internal identifiers of the platform have no place in an
entry either – say what the behaviour was, not which id or response field was compared with what.
The link is written by `python scripts/changelog-link.py <number>`, which rebuilds the generated
pages of the site in the same run – writing it by hand is how the mirrors get left behind.

## Unreleased

### Added
- **`get_build` on the MCP surface: the whole card of one build.** The listing was there and the
  card was not, so an agent after the manifest name, the vendor or the comment of a build had to
  fall back to the CLI. The tool is addressed by the build VERSION – an id is accepted as well
  and looked up in the listing, because the id of a card is not an address the platform's method
  understands. ([#14](https://github.com/keyfire/elemctl/pull/14))

### Changed
- **What kind of build listing the reader is looking at is judged by the numbering, not by the
  length.** The line under a listing was chosen by a threshold of thirty – a number measured
  once on one installation, back when we believed the platform capped the store. It does not:
  it deletes the builds nobody uses. The answer now judges itself – the platform hands out the
  numbers of a base version one after another, so a number the listing has not got is a build
  already taken away. Thirty-one builds in a row are no longer called a remnant, and a short
  listing with a hole in it no longer passes for the whole history. Whether there are gaps is
  said, never how many numbers are missing - a live listing showed twenty thousand of them,
  left by an auto-increment that once jumped a base, and a count of "deleted builds" would have
  been a fabrication. `ASSEMBLY_STORE_LIMIT` is gone, `builds_summary` takes the builds
  themselves instead of their count, and the message key `client.builds-summary-capped` is now
  `client.builds-summary-trimmed`. ([#13](https://github.com/keyfire/elemctl/pull/13))

### Documentation
- **A process read as text has to name its encoding, and a check says so.** Every call in the
  repository already did – and then a new script did not, and the failure was the silent kind:
  the output of a generator naming the Russian pages it writes was decoded with the code page of
  the console, the names came back as replacement characters, the text was lost, and the exit
  code went on saying the run had gone well. The convention is written down in `CLAUDE.md` with
  both of its halves – the reader names `encoding="utf-8"`, and a Python script started from
  here is given `PYTHONIOENCODING=utf-8` so that it writes what the reader reads – and
  `tests/test_conventions.py` reads the sources with `ast` and fails on a call without it. It
  found two test helpers still decoding with the code page of the machine; both are fixed.
  ([#17](https://github.com/keyfire/elemctl/pull/17))
- **The claim mechanics moved into the shared guard.** One fact told in several documents at
  once is not an elemctl problem – the engine and the bridge keep their documentation the same
  way and have the same defect waiting – so `Claim`, `claim_texts` and `claim_problems` now come
  from the `docsguard` package, and the table of statements stays here, where the facts are
  known. A place is still written the way a reader writes it, the changelog is still left out of
  the search, and the guard finds exactly what it found before – the same wordings on the same
  data. ([#16](https://github.com/keyfire/elemctl/pull/16))
- **One command rebuilds every generated page.** Two generators write four pages – the command
  reference from `elemctl --help`, the mirrored changelog and the README sections from the root
  editions – and each generator was a thing to remember on its own. The mirrors were the first to
  be forgotten, which turned `main` red on the guard; the fix tied them to the changelog link and
  left the command reference as the last "do not forget" of exactly the same shape.
  `python scripts/rebuild-docs.py` runs both generators, reports each half and answers with an
  exit code – one failing generator no longer hides the other. The changelog link step calls that
  one step, and the guard's finding, the note in the head of a generated page and the repository
  conventions all name it. ([#15](https://github.com/keyfire/elemctl/pull/15))
- **The guard now catches one fact told in two different ways.** A statement about the platform
  lives in the specification, on the Console API page, in the MCP page, in the README and in the
  docstrings at once, and it is corrected in one of them – twice that left the rest telling the
  model it replaced, once inside a single document. The statements that live in many places are
  listed as `CLAIMS` in `scripts/check_docs.py`: every place the claim names has to state it,
  and the superseded wording – in the spelling it really had – may appear nowhere but the
  changelog. The two that drifted are covered: automatic deletion of unused builds and the
  address of a build card. ([#12](https://github.com/keyfire/elemctl/pull/12))
- **The pull request link and the mirror rebuild are one step now.** A link can only be written
  once the pull request exists, so it arrives in a commit of its own – and the mirrored
  `docs/changelog*.md` pages kept being left behind, which turned `main` red on the documentation
  guard. `python scripts/changelog-link.py <number>` does both halves: it appends the link to the
  entries of the topmost section in both editions and rebuilds the mirrors right after, and the
  guard's finding now names the command instead of saying "regenerate the mirrors".
  ([#11](https://github.com/keyfire/elemctl/pull/11))

## 2026-09-11 – 0.39.0

### Added
- **`--verify` for `apps create` and `apps ensure`, and a `verify` parameter of the MCP tools
  `create_app` and `ensure_app`.** The proof that a build really landed lived in `deploy`,
  `apps apply` and `verify-deploy`; raising a stand had to call it separately afterwards. The
  report now comes in the `verify` field of the answer. ([#5](https://github.com/keyfire/elemctl/pull/5))

### Changed
- **A command that only works locally no longer accepts the connection options.** `build` and
  `inspect` took `--env-file`, `--base-url` and the credentials and dropped them without a word –
  a call then LOOKED like a build bound to a stand, and twice it sent the reader looking for
  whether a local build goes to the server. **A behaviour change:** that is a refusal with exit
  code 1 now, and it says outright that a local build never calls the platform and reserves no
  version number there, and which commands do. Only the OPTIONS are refused: the environment
  variables and a `.env` next to the project still change nothing about a build.
  ([#7](https://github.com/keyfire/elemctl/pull/7))
- **The build listing is described as it really works.** We believed the platform capped builds
  per project and pushed old ones out; in fact it deletes the ones nobody uses, and age plays no
  part – the build an application runs, the project's first build and a release build stay, the
  rest goes. The listing's summary and the Console API pages were rewritten. ([#6](https://github.com/keyfire/elemctl/pull/6))
- **Waiting means verifying: `--wait` no longer hands back a card on trust.** A failed apply is
  rolled back to the previous build and the application comes up running all the same, so the
  card said nothing about the build being served. **A behaviour change:** `--wait` ends with the
  check and exits 1 when it does not pass, `--no-verify` brings the plain wait back, and an
  application `ensure` created stops answering `applied: true` unchecked. ([#5](https://github.com/keyfire/elemctl/pull/5))

### Fixed
- **The correction about automatic build deletion reached the rest of the pages.** The Console API
  sections describe the listing as it really works, while the CLI requirements, the MCP server
  pages, the hint of the `list_builds` tool and the comments in the code still told of a store
  limit and of older builds being pushed out – two different models inside one document. There is
  one now: the platform deletes the builds nobody uses, and age plays no part.
  ([#9](https://github.com/keyfire/elemctl/pull/9))
- **`builds get` did not work at all: a build card is addressed by its version.** Our pages
  claimed the method takes a UUID only and answers a version with a 400 – so the command dutifully
  turned a version into an id, and the platform answered 404 "no build with that version". Live
  calls on two installations of different ages say the opposite: the last segment of the address
  is the version, the way the method names it, and the id of a card is not an address. The command
  now takes both forms – the value is looked up in the build list and the version taken from
  there, and a refused address is retried with the id, for an installation that wants that form. A
  refusal on the merits (a 500 on deleting a build a live application was created from, say) is
  never retried with another spelling. The Console API pages were corrected.
  ([#8](https://github.com/keyfire/elemctl/pull/8))

## 2026-09-10 – 0.37.0, 0.38.0

### Added
- **The `verify-deploy` command – the verification apart from the deploy.** The library and the
  MCP tool had the mechanism; the CLI did not, so CI scripts rebuilt the same check by hand out
  of `apps get` and `tasks list`. The command now answers with the report `deploy` gives and
  exits 1 on a failure; it deploys nothing itself.
- **The `--json` flag: the answer alone reaches stdout.** Scripts parsed the output by hunting
  for the first brace, and one stray line ahead of the JSON broke the parse. While a command
  runs, stdout is now swapped for stderr – no line of a plugin, no warning of a library slips
  into the stream. The flag is global and accepted in any position.

### Changed
- **`builds list` says what kind of listing the reader is looking at.** "30 of 30" read as the
  project's whole history, while the platform keeps only so many builds per project. The count
  line now says whether the listing is complete or has hit the store limit. **A behaviour change:**
  the MCP tool `list_builds` answers with `{total, shown, summary, builds}`, not a bare array.
- **A group called straight with a flag gets a hint about the action.** argparse answered
  `elemctl tasks --app-id ...` with "invalid choice", and the reader went looking for the mistake
  in the value while the missing word was `list`. The refusal now prints the form of the call and
  the actions of the group, and `tasks --help` spells both forms out.
- **`--latest-build` picks the newest build by its created stamp**, not by the highest counter:
  after a base version bump the old base keeps the higher numbers, and an application created
  "from the latest build" would have got an old one.

### Fixed
- **The command reference no longer breaks a word wrapped on its hyphen.** argparse wraps a long
  word on the hyphen, and joining the lines with a space broke the very name under discussion:
  the reference read `elemctl tasks get- group TASK_ID`. The joining rule is now shared – it
  covers the parser's description and its epilogue too.
- **The build counter restarts when the project's base version changes.** The auto-increment
  took the highest counter of all the project's builds: one stray `1.0.1-19001` pushed every
  later build to 19xxx, and bumping the project to `1.0.2` would have continued at 19024. The
  counter is now taken among the builds of the project's own base version, so a bumped project
  starts from `1.0.2-1`.

## 2026-09-09 – 0.36.0

### Changed
- **`apps list` hides the deleted applications and says how many it hid.** The platform keeps
  them in the list under the `Deleted` status with their former id: a stand a few months old
  answered with three hundred cards of which a handful were alive, and `--brief` did not drop
  them – the answer had to be filtered by the caller's own code. The deleted ones are now hidden,
  `--include-deleted` brings them back, and `--status deleted` lifts the hiding on its own: a
  filter that would answer with nothing is worse than no filter. A cut nobody is told about is a
  trap, so the command ends with a count line on stderr ("7 live of 324", plus the number shown
  when a filter narrowed the answer further); stdout stays the same JSON array scripts parse.
- **The `list_apps` MCP tool takes `include_deleted` and answers with an object.** The cards
  (`applications`) come with the counters `total`, `live`, `shown` and a ready `summary` line: an
  agent sees only the JSON, and the cards that were cut have to be named, otherwise the listing
  reads as "the stand holds seven applications". The former answer – a bare array – is gone;
  `find_app` and the name-to-id resolution still see the deleted applications and skip them
  themselves.

## 2026-09-06 – 0.35.0

### Added
- **`projects list --name` and `--include-deleted`; the `list_projects` MCP tool takes the same
  filters.** The platform keeps deleted projects in the list under a flag, so a stand a few months
  old answered a check for a project name with over a hundred cards, most of them deleted. The
  deleted ones are now hidden unless asked for, and `name` narrows the list by a case-insensitive
  substring on the client – the way `apps list` already does it.

## 2026-09-05 – 0.34.0

### Fixed
- **The application is addressed both positionally and with `--app-id`.** The `apps get`,
  `apply`, `delete`, `start`, `stop` and `debug` commands took the positional form only, while
  `deploy` and `apps ensure` took the option only, so a call written the other way answered
  with usage instead of doing the work. Two DIFFERENT references in one call are refused:
  silently preferring one would send the command to the wrong application.

## 2026-08-31 – 0.33.0

### Added

- **The schema guard covers the dimensions of a register.** The records are keyed by them, so
  changing a dimension's type – or removing it – makes the platform convert the records, collapse
  the values and fail the apply on their uniqueness, with a silent rollback behind it. A probe
  cannot foresee that: a throwaway application has no records to convert.
- **A SOAP service client's description goes into the build.** `<Client>.Wsdl.<n>` and
  `<Client>.Xsd` lie next to the project element rather than in `Ресурсы`, and their extensions
  are outside the allowlist – the archive used to lose them silently. A client whose description
  is missing is named before the upload.
- **`apps list --status running`** (several statuses separated by commas). A stand a few months
  old holds hundreds of applications of which a handful are alive, and asking what runs here
  should not cost the full listing.
- **The deploy report carries the refusal as lines.** `problems-lines` holds the platform's text
  broken into plain lines: JSON escapes a multi-line refusal into `
` and `	` exactly where it
  has to be read – which object, which keys stopped being unique.

### Fixed

- **An apply waits out a busy application** instead of giving up on it. A deploy right after
  another one used to fail with "the application is busy" AFTER the build had been uploaded;
  the wait is short and only fires on the busy wording, so a missing application still fails at
  once.
- **A probe stops at a refused compatibility mode.** A stand older than the project refuses the
  whole project and then complains about types and properties of that mode in files the change
  never touched – hundreds of lines that read like a verdict on the code. The refusal is now
  named for what it is, and what followed from it is counted rather than parsed.

## 2026-08-30 – 0.32.3

### Changed

- **The package description names the probe.** The PyPI summary and the site descriptions
  listed applications, builds and deploys and said nothing about the compilation check the
  server runs without risking the working application – a reason of its own to pick elemctl.

## 2026-08-27 – 0.32.2

### Added

- **A release leaves a GitHub release card.** After a successful PyPI publication the
  workflow creates a GitHub release whose body is this changelog's section for the
  released versions – repository subscribers now see the actual "what's new" in their
  feeds instead of a bare tag.

## 2026-08-26 – 0.32.1

### Changed

- **The local-cloud example in the documentation points at a placeholder domain** in the
  reserved `.example` zone: a configuration example must not name any real server.
- **The changelog is trimmed to two-four lines per entry**: what changed and why it matters;
  the history of a finding stays in the commits and the documentation.

## 2026-08-24 – 0.32.0

### Added

- **`apps apply [APP_ID] VERSION_ID` – apply an uploaded assembly and verify the result.**
  Applying used to be reachable through the MCP tool alone, while long operations are the ones
  that want a CLI run in the background. On a failure the platform silently rolls the application
  back to the previous build and starts it, so the command checks what actually landed and exits
  with 1 when the assembly did not.
- **`apps ensure` answers about the assembly too.** The creation flags act on creation alone, so
  `--version-id` was not applied to an existing application - silently. The answer now carries
  `applied` and `applied-version-id`, stderr names the command that brings the application to the
  requested assembly, and `--apply` does it in the same run; the MCP tool `ensure_app` grew the
  same field.

### Fixed

- **`builds upload` no longer refuses an assembly of its own project.** Two different things were
  compared: the technical name of the manifest and the presentation the console shows the project
  under - they could only match by accident, and every correct upload looked like a rename. What
  is compared now is the project presentation from the descriptor inside the archive; a foreign
  assembly is refused as before.
- **The refusal explains `--new-project`.** The wording "starts a separate project" scared people
  away from the path that worked: the platform recognizes a project by the vendor and name of the
  manifest, so an assembly of the same project lands in the existing one.

## 2026-08-18 – 0.31.0, 0.31.1

### Added

- **A connection with verification off says so on every run.** `ELEMENT_TLS_VERIFY=false` is
  written into `.env` once, and a call that checks nothing looks exactly like a call that passed
  the check. The warning goes to stderr, so JSON piped out of stdout stays intact.
- **TLS is configurable: a private CA and the strictness of the checks.** The RFC 5280 strict
  profile enabled in Python 3.13 rejected the internal CA of a private cloud. `ELEMENT_CA_FILE`
  adds a PEM file to the trust store, `ELEMENT_TLS_STRICT=false` drops the strict profile alone,
  and `ELEMENT_TLS_VERIFY=false` stays the last resort; a typo in a value is a configuration
  error rather than silently weakened TLS. Contributed by @dvkuchin (pull request #4).

## 2026-08-14 – 0.30.0

### Changed

- **`builds list` answers with ten recent assemblies.** An old project accumulates thousands of
  them, and the question "which commit is the applied build from" was answered by truncating the
  full list. `--limit` sets the slice (`0` for all), stderr says how many of how many are shown,
  and `--brief` leaves the id, the versions, the date, the branch and the commit; the MCP tool
  `list_builds` took the same parameters.

### Fixed

- **A probe assembly can no longer win the choice of "the latest build".** The random token of
  its version comes out all digits about once in forty draws, and such a version reads as a huge
  counter - `--latest-build` would pick the probe instead of the real one. An all-digit token is
  now redrawn; caught live in CI.

## 2026-08-11 – 0.29.0

### Changed

- **A missing `.env` file is named by its absolute path and the current directory.** A relative
  `--env-file` resolves against the current directory rather than `--project-dir`, and in a
  background run the refusal read as an unreachable stand.
- **`probe` states what it needs of the project layout.** The directory has to sit as
  `{repository}/{Vendor}/{Name}/Проект.yaml` - which used to be learned from the error afterwards.

## 2026-08-10 – 0.28.0

### Documentation

- **The list of MCP tools is complete.** Seven of the twenty-four were named nowhere but in the
  sources: the page made do with "and others".
- **The environment variables are described in full** - together with `ELEMCTL_NO_PLUGINS`, the
  CI variables a build takes its run number from, and the system `LC_ALL`/`LANG`.
- **Stale claims corrected:** the common flags are accepted in any position, `.htm` is one of the
  archive extensions, and inside a `Ресурсы` directory there is no extension filter at all.
- **One source per text.** The README sections that repeated the site pages had drifted both
  ways; the page is now the source, and `scripts/sync-docs.mjs` inserts its section into the
  README between markers.
- **An architecture diagram** (`docs/architecture.svg`) - the surfaces, the engine, the deploy
  cycle with its silent rollback, and the probe; the palette follows the reader's theme.
- **The guard `scripts/docsguard.py` and the `docs` job in CI.** It judges what is mechanically
  checkable: a tool with no row in the table, an environment variable the code reads and nobody
  described, a stale changelog mirror. Every class of finding is provoked by a test.

### Added

- **`deploy` takes an application name as well as an id** - the way `apps get`, `apps start`,
  `apps stop` and `apps debug` have long done.

### Changed

- **The VS Code extension left this repository.** Debugging 1C:Element applications is part of
  the [XBSL](https://github.com/keyfire/xbsl) extension as of its 0.57.0, together with the
  deploy button: while they were apart, the path to elemctl and the application id had to be set
  twice. The elemctl side stays here - `apps debug`, `debug-adapter` and the `elemctl.debug_adapter`
  entry point.

## 2026-08-07 – 0.26.0, 0.27.0

### Added

- **Projects with English artifacts build and deploy.** `build`, `deploy` and `probe` find a
  `Project.yaml` descriptor as readily as `Проект.yaml`, the archive reader takes English keys and
  values, and the schema guard knows that the two spellings of a primitive type name are ONE type:
  translating a description does not read as a data-destroying change.

### Changed

- **Uploading an assembly no longer sends the commit and the branch.** The documented method does
  not take them, and the server ignores what is sent: the commit on an assembly card comes only
  from the project's link to its repository. Inside the archive both still travel - the build
  writes them into the manifest.
- **A skipped schema check is named in the report.** The `schema-check` field answers `clean`,
  `allowed` or `skipped:<reason>`: a check that did not run must not read as a check that passed.

## 2026-08-03 – 0.25.0

### Changed

- **An assembly with a foreign name is refused rather than merely warned about.** The console
  shows a project under the name of the last uploaded assembly, and deleting the assembly does not
  bring the former name back. The ways out are named in the message itself: `--force-rename` if
  that was the intent, `--new-project` if the assembly belongs elsewhere.

## 2026-07-31 – 0.23.0, 0.24.0

### Fixed

- **`self-update` right after a release no longer misses it.** The file list came from the PyPI
  JSON metadata, which lags the publication by minutes: inside that window the command answered
  "already current". The list now comes from the simple index (PEP 691), and versions are ranked
  numerically.

### Changed

- **The MCP server works with both majors of the `mcp` package, the pin is gone.** In `mcp 2.0.0`
  the server class moved without leaving an alias, and a fresh install would not start at all.
  The import tries both locations, two helpers hide the difference in reading the answers, and CI
  runs the suite against both majors.
- **`serverInfo` names the version of elemctl itself,** not of the `mcp` package.

## 2026-07-30 – 0.22.0

### Added

- **A build takes in library projects lying next to the application,** transitive dependencies
  included; a declared library with no local project stays an external dependency of the
  platform. Contributed by @dvkuchin (pull request #3).

### Fixed

- **A proxy in the environment no longer passes a live stand off as a dead one.** A proxy that
  cannot reach the stand refuses exactly the way a stand that is down would. A proxy that clearly
  will not help is now bypassed, `ELEMCTL_NO_PROXY=1` bypasses it everywhere, and a failed call
  that did go through a proxy names it.
- **`self-update --stop-holders` no longer kills its own process tree.** The command runs as a
  child of the launcher, indistinguishable from a holder by name, so it offered to kill itself
  and broke the update halfway.

## 2026-07-28 – 0.20.0, 0.21.1

### Added

- **Creating an application ends with the way into it.** `apps create` and `apps ensure` (and
  their MCP twins) gained a `sign-in` field. A new application gets its own empty user list, so
  the accounts used to sign in to other applications do not work here: the way in is a control
  panel account. Guessing is not an option - a user has a failed-attempt counter.

### Changed

- **`self-update` no longer replaces a working installation with nothing.** `pip install
  --upgrade` hit a file held by a live session, removed the package, failed to unpack the new one
  and said nothing. The installed package is now renamed first, holders are named by name and
  pid, and the previous installation is restored unless the new one proves it imports.

## 2026-07-27 – 0.19.0

### Added

- **`user-lists calculation-rules` - reapply the rules a user is assembled from.** Recreating the
  sign-in service resets them, and reading never returns them, so the report says it plainly:
  what was sent, that the request was accepted, and that the value cannot be confirmed through
  the API - only by the console or a live sign-in.

### Fixed

- **A build made on a CI runner recorded the branch as `HEAD`.** A runner checks out a commit
  rather than a branch. The name now comes from the CI environment, and when nobody names the
  branch the field stays EMPTY: an honest blank beats a word that looks like a branch name.

## 2026-07-26 – 0.15.0, 0.16.0, 0.17.0, 0.18.0

### Added

- **`deploy` names its target and where the target came from.** The report gained `app-name`,
  `app-id-source` and `project-id-source`, and the target is announced in the first progress line
  - before the build, while a deploy aimed at the wrong application can still be interrupted.
- **A build names the files that did not make it in** (`skipped-files` plus a warning). A file
  with an extension outside the allowed list enters the archive only from a `Ресурсы` directory;
  anywhere else it is lost silently, and the platform reports it only on apply.
- **A guard against destructive schema changes.** Narrowing an attribute's length or changing its
  type RECREATES the object's data, so `deploy` compares the sources against the commit of the
  applied build and refuses before the build; `--allow-data-loss` skips it. With nothing to
  compare against, the guard says so and does not stand in the way: not being able to compare is
  no proof of danger.
- **`user-lists` - the sign-in settings of a user list,** the ones usually looked up in the
  console: `list`, `get`, `self-registration` and `password-login`. Without a flag both setting
  commands only read the state; on the MCP side, `list_user_lists` and `configure_user_list`.
- **The `elemctl.commands` entry point group** - a plugin package brings commands of its own, and
  one declaration becomes both a CLI subcommand and an MCP tool. That is where a command that
  knows about someone else's environment belongs, since it cannot live in a public core.
- **`elemctl probe` - an isolated compilation check.** Compilation on this platform is
  server-side and happens on apply, so the probe builds an archive, creates a throwaway
  application from it and cleans up after itself. Errors come back parsed: file, line, column,
  environment and text.

### Fixed

- **A common option is accepted after a subcommand too** - `elemctl deploy --env-file .env` no
  longer fails with the argparse "unrecognized arguments".
- **A token the server rejected no longer lives in the cache.** This server rejects a bad token
  with 400 rather than 401, naming the reason in `error_description`; such a refusal now drops
  the cache file and retries once.
- **The assembly is deleted after its application is gone.** The platform refuses the deletion
  while the application created from that assembly is alive, so the probe waits for it to
  disappear first.

### Documentation

- **The Console API contract gained the user lists** (section 4.7) and what the API does not
  carry at all: the composition of the authentication forms and the "connect users automatically"
  setting.
- **A platform project is recognized by the `Vendor` plus `Name` pair of the manifest,** not by
  the `Ид` of `Проект.yaml`: a second project under the same pair is refused with 409
  `ALREADY_EXISTS`.

## 2026-07-25 – 0.14.0

### Added

- **The version suffix comes from the CI run number** (`CI_PIPELINE_IID`, `GITHUB_RUN_NUMBER`,
  `BUILD_NUMBER`) when there is neither an explicit version nor a previous build: a clean CI
  working directory no longer yields `-1` on every run.
- **`build` and `deploy --dry-run` print what was built** - `name`, `vendor`, `version`,
  `version-source`, `kind`, `branch`, `commit` and `dirty` - so CI stops digging the version out
  of a file name.
- **`apps get/delete/start/stop/debug` take an exact application name** as well as an id (in MCP
  too); several matches are an error listing the ids, destructive commands do not guess.
- **`apps list --brief` - brief cards:** the question "is acme-crm-dev alive" costs a few hundred
  bytes instead of tens of kilobytes.
- **Uncommitted changes in the project directory are visible** in the report (`dirty`,
  `dirty-files`), and `--require-clean` stops the work before the build.

### Changed

- **`apps list --name` filters on the client:** the platform ignores the query parameter, so the
  previous pass-through filter filtered nothing.
- **The keys of the `Проект.yaml` descriptor are read in both spellings** - bilingual sources are
  a declared feature of the platform, and such a project used to be refused.
- **Status waits treat `Error` as terminal:** a deploy fails at once with the compilation errors
  instead of waiting out the full timeout.

### Fixed

- **`--lang en` is English everywhere now.** Some forty user-facing lines were hardcoded in
  Russian past the message catalog; a test walks the modules and keeps new ones from appearing.

## 2026-07-24 – 0.12.0, 0.13.0, 0.13.1

### Fixed

- **Files of `Ресурсы` directories enter the archive whatever their extension.** The general
  allow-list used to apply to them as well, files fell out of the build silently, and the apply
  failed with "Неизвестный ресурс". Outside resource directories the list still applies, and it
  gained `.htm`.

### Changed

- **MCP: `list_projects` returns brief cards by default** - like `list_apps`; `brief=false`
  returns the full ones.

### Added

- **`builds upload` reports its target** (`project-id` and `project-id-source`): an assembly used
  to land silently in the project from the environment when a new project was intended.
- **`builds upload --new-project`** uploads the assembly as a new project, ignoring
  `ELEMENT_PROJECT_ID`.
- **`builds upload` warns about a foreign assembly name:** the console shows a project under the
  name of the last uploaded assembly.
- **The command reference and its generator are under tests** (`tests/test_cli_docs.py`): every
  command answers `--help` and has a section of its own, and the two language versions really do
  differ.

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
