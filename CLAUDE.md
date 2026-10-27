# Repository conventions

elemctl is a public, international project: a CLI, an MCP server and a Python library for the
1C:Enterprise.Element Console API v2. The implemented contract is documented in
[docs/SPEC.md](docs/SPEC.md), with a Russian edition in `docs/SPEC.ru.md`. This file records how
the repository itself is written.

## Language of the code

- **Code is English.** Comments, docstrings, identifiers, test names – all of them, in `src/`,
  `tests/`, `tools/` and `editors/`. The code is read by people who do not speak Russian.
- **Russian stays where it faces the user**: the i18n message catalog (`src/elemctl/i18n.py`),
  argparse help strings, user-facing strings, the MCP tool descriptions and the server
  `INSTRUCTIONS` literal. An agent reads those in Russian.
- **1C:Element identifiers are quoted as they are**: `Проект.yaml`, `Ресурсы`, `Имя`, `Поставщик`,
  `ВидПроекта`, `ОбластьВидимости` and the like are real keys and file names, so do not
  translate them. The same goes for the Russian data of test fixtures.

## Typography

Applies to English text as well:

- dashes – en dash `–` (U+2013) only, never an em dash;
- quotes – straight `"` and `'`, never guillemets or curly quotes;
- ellipsis – three dots `...`, never the `…` character.

## Russian without borrowed words

Use the Russian equivalents listed in the `docsguard` dictionary rather than
transliterated terms such as `пин` or `прогон`. The repository declares the
checked documents in `scripts/check_docs.py`: pages under `docs/` are selected
by pattern; the README, changelog and this file are listed explicitly.

Format terms discussed as terms in backticks. The check excludes inline code,
fenced blocks, link targets and file names. Exact command captions should also
use inline-code formatting.

## Nothing internal

The repository is public. It must not carry internal project identifiers, stand names, real
application or assembly ids, internal hosts, issue keys or machine paths. That holds for the
code, for comments and for test fixtures alike. Use neutral examples: vendors `acme` and
`globex`, applications `crm-dev` and `demo-app`.

Describe the problem, resulting behavior and reason for a change. Do not
explain a change by naming who requested it. The description should be useful
to a reader without access to private discussions.

## Documentation pairs

English and Russian pages go together: `README.md` / `README.ru.md`, `docs/SPEC.md` /
`docs/SPEC.ru.md`, `CHANGELOG.md` / `CHANGELOG.ru.md` and the rest of `docs/*.md`. A change
to one side without the other is an unfinished change. Four pages are generated, so never edit
them by hand:

- `docs/cli.md` / `docs/cli.ru.md` – from the output of `elemctl ... --help`;
- `docs/changelog.md` / `docs/changelog.ru.md` – from the root `CHANGELOG` editions.

Run `python scripts/rebuild-docs.py` to rebuild all four generated pages.
Regenerate them whenever their sources change.

Use `python scripts/changelog-link.py <number>` to add the pull request link
to entries in the latest section of both changelog editions. The same command
rebuilds the generated pages. Do not add the links manually and leave the
mirrors unchanged.

## One fact, one wording

Facts about server behavior can appear in the specification, Console API page,
MCP page, README and code docstrings. Update every occurrence when correcting
a fact. Register facts repeated across these sources in `CLAIMS` within
`scripts/check_docs.py`.

Each row lists the required sources, accepted wording and obsolete wording.
Obsolete claims may appear only in changelog entries explaining the correction.
The shared `docsguard` package performs the checks; this repository maintains
the claim table. Add equivalent wording when editing prose, while retaining
checks for missing or obsolete claims.

## The shared guard

Common documentation checks are provided by `docsguard`, installed from git
by the workflows. Pin it to a tag rather than `@main`, so unrelated changes
to that package do not alter checks in this repository.

Update the pinned version in a separate pull request. Merge and tag
`docsguard` as `v<version>` before updating this repository. Every workflow
must use the same tag; `tests/test_workflows.py` checks this requirement,
including consistency between CI and publication.

## Starting a process

When reading process output as text, specify its encoding:
`capture_output=True, text=True, encoding="utf-8"`. Add `errors="replace"`
when output is intended only for display. Without an explicit encoding,
Python uses the console code page, which can corrupt Cyrillic output while
the process still exits successfully. Calls that exchange only bytes do not
need text-decoding arguments.

Also set `PYTHONIOENCODING=utf-8` for child Python scripts so their output uses
the same encoding. The elemctl CLI configures its streams itself; ordinary
scripts do not.

Specify `stdin=subprocess.DEVNULL` for child processes. In an MCP server,
stdin is the client communication pipe. On Windows, an inherited handle can
prevent a child from exiting until the parent timeout, even after its work
finishes. This affected git, interpreters and pip; `tasklist`, `powershell`
and `cmd` closed their handles normally. A build consequently reported git
as unavailable. Calls that supply data through `input=` or their own `stdin=`
keep that explicit input instead.

`tests/test_conventions.py` checks text reads for explicit encoding, including
the `(run or subprocess.run)(...)` runner form. The shared `docsguard` package
implements the checks; this repository declares the directories to scan.
The stdin check covers `src` only. Scripts, helper tools and tests run from
a console and may pass its stdin through.

## Writing a file

Specify `newline=""` when writing text files. Without it, `write_text` and
`open` translate line feeds to the operating system's ending, so a generator
on Windows can change every line of a document. `core.autocrlf=input` may
normalize the result on commit, but contributors without that setting would
still produce unrelated line-ending changes. This affected the changelog-link
script and its generated mirrors.

`tests/test_conventions.py` uses `ast` to check `p.write_text(...)` and `open`
in text-write modes. Byte writes and reads are excluded. The directory list
is narrower than the process-check list: tests write temporary files and may
deliberately create fixtures with other line endings.

The write argument does not remove carriage returns already present in source
text. `scripts/sync-docs.mjs` copies sections between documents, so mixed input
can produce mixed output. The `.gitattributes` rule `* text=auto eol=lf`
keeps stored and checked-out text files in LF format on every machine.
The local `core.autocrlf=input` setting alone does not provide that guarantee.

## Naming a test

Python retains only the last definition with a given name. A duplicate test
therefore prevents the earlier definition from being collected by pytest.

`tests/test_conventions.py` runs `shadowed_test_problems` over `tests` and
reports the duplicate definition's line for renaming. Namespaces are checked
separately; methods in different classes may share a name.

## Tests

`python -m pytest -q` runs the suite without network access, with the transport stubbed. CI runs
it too, on every push to `main` and on pull requests (`.github/workflows/ci.yml`), and again
before publishing on a `v*` tag. Anything that depends on the environment, `CI_*` variables and
the like, has to be neutralized by a fixture, otherwise it passes locally and fails in CI.

## Release

The version is defined only in `src/elemctl/__init__.py`, and `pyproject.toml` reads it dynamically.
A release is a version bump, a `CHANGELOG` section for the day and an annotated `v<version>`
tag. Publishing to PyPI happens in CI through Trusted Publishing.
