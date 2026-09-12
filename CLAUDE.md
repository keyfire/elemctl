# Repository conventions

elemctl is a public, international project: a CLI, an MCP server and a Python library for the
1C:Enterprise.Element Console API v2. The contract the tool implements lives in
[docs/SPEC.md](docs/SPEC.md), with a Russian twin in `docs/SPEC.ru.md`. This file records how
the repository itself is written.

## Language of the code

- **Code is English.** Comments, docstrings, identifiers, test names – all of them, in `src/`,
  `tests/`, `tools/` and `editors/`. The code is read by people who do not speak Russian.
- **Russian stays where it faces the user**: the i18n message catalog (`src/elemctl/i18n.py`),
  argparse help strings, user-facing strings, the MCP tool descriptions and the server
  `INSTRUCTIONS` literal. An agent reads those in Russian.
- **Platform identifiers are quoted as they are**: `Проект.yaml`, `Ресурсы`, `Имя`, `Поставщик`,
  `ВидПроекта`, `ОбластьВидимости` and the like are real keys and file names, so do not
  translate them. The same goes for the Russian data of test fixtures.

## Typography

Applies to English text as well:

- dashes – en dash `–` (U+2013) only, never an em dash;
- quotes – straight `"` and `'`, never guillemets or curly quotes;
- ellipsis – three dots `...`, never the `…` character.

## Nothing internal

The repository is public. It must not carry internal project identifiers, stand names, real
application or assembly ids, internal hosts, issue keys or machine paths. That holds for the
code, for comments and for test fixtures alike. Use neutral examples: vendors `acme` and
`globex`, applications `crm-dev` and `demo-app`.

## Documentation pairs

English and Russian pages go together: `README.md` / `README.ru.md`, `docs/SPEC.md` /
`docs/SPEC.ru.md`, `CHANGELOG.md` / `CHANGELOG.ru.md` and the rest of `docs/*.md`. A change
to one side without the other is an unfinished change. Four pages are generated, so never edit
them by hand:

- `docs/cli.md` / `docs/cli.ru.md` – from the output of `elemctl ... --help`;
- `docs/changelog.md` / `docs/changelog.ru.md` – from the root `CHANGELOG` editions.

One command rebuilds all of them: `python scripts/rebuild-docs.py`. It is the only one to
remember. Every generator used to carry a command of its own, and each of those turned into
something else to remember. The mirrors were the first to be left behind, and `main` went red
on the guard for it.

The pull request link that every changelog entry ends with is written by
`python scripts/changelog-link.py <number>` rather than by hand. It appends the link to every
entry of the topmost section in both editions and rebuilds the generated pages in the same run.
The link and the rebuild are two halves of one step, and doing the first by hand is how the
second gets forgotten.

## One fact, one wording

A statement about the platform is told in several places at once: the specification, the
Console API page, the MCP page, the README, the docstrings of the code. Then it gets corrected
in one of them. Twice that left the rest telling the model it replaced, and one document ended
up carrying both at the same time. Such statements are listed as `CLAIMS` in
`scripts/check_docs.py`. A row names the places that must state the fact, the spellings that
count as stating it, and the spellings of the model it replaced. Those old spellings may appear
nowhere but the changelog, where an entry about a correction quotes what it corrected.
Correcting such a fact means correcting every place the claim names, and the guard says which
one was missed. A fact that starts living in more than one place gets a row of its own. The
judging itself comes from the shared `docsguard` package, because the neighbouring repositories
keep their documentation the same way and have the same defect waiting. What lives here is the
table.

## The shared guard

The parts of the documentation guard that three repositories were keeping in triplicate live in
the `docsguard` package, which the workflows install from git. It is fixed to a tag, never to
`@main`. From the main branch, any change made there would reach a run here in the middle of
unrelated work, and a red run caused by no commit of ours is a red run nobody reads. The order
of merging, the shared package first and this repository second, was also left to memory rather
than written down.

So raising the version is a change of its own, with its own pull request: `docsguard` tags
`v<version>` right after its own merge, and the tag goes up here. Every workflow names the same
tag, and `tests/test_workflows.py` fails when they drift apart. A suite passing against one
version of the guard while the publication runs against another is exactly the difference
nobody looks for.

## Starting a process

A process started from here is read as text, and the text is decoded explicitly:
`capture_output=True, text=True, encoding="utf-8"`, plus `errors="replace"` wherever the output
only goes to a human. Without `encoding`, Python decodes with the code page of the console, and
the failure is silent in the worst way. A generator named the Russian pages it writes, the names
came back as replacement characters, the output was lost, and the exit code went on saying that
everything had gone well. A call that asks for no text at all, bytes in and bytes out, decodes
nothing and needs neither argument.

The other half of the agreement belongs to the child process. A plain Python script encodes its
own stream with that same code page, so a script started from here is given
`PYTHONIOENCODING=utf-8`. The elemctl CLI reconfigures its streams itself; a script does not.

`tests/test_conventions.py` fails on a process read as text without an encoding. It catches the
`(run or subprocess.run)(...)` shape of a runner seam too, which is the shape the offending call
had and which a search for the text of a call looks straight past. The reading itself comes from
the shared `docsguard` package, because the neighbouring repositories start processes the same
way and have the same silent failure waiting. What stays here is the list of folders: which of
them hold code that starts processes is a fact about this repository.

## Writing a file

A text file written from here names `newline=""`. Without it, `write_text` and `open` in text
mode translate the line feed into the platform's ending, so a generator that rewrites a page on
Windows hands back a file with every line changed. `core.autocrlf=input` normalizes that away on
commit and hides it, which is exactly the trouble: on a machine without the setting, the whole
file goes to this public repository as a line-ending change nobody asked for. The script that
appends a pull request link to both changelog editions was doing just that, and the mirrors it
rebuilds in the same run took the change with them, while the two generators beside it were
already spelling the keyword out.

The same `tests/test_conventions.py` fails on a text write that does not name it, and it reads
the sources with `ast` again: a write is `p.write_text(...)` or an `open` in a text write mode,
while bytes and reads are left alone. The list of folders is shorter here than the process
convention takes. A test writes into a temporary directory that is gone when the run ends, and a
fixture carrying the other line ending on purpose is a test in its own right.

## Tests

`python -m pytest -q` runs the suite without network access, with the transport stubbed. CI runs
it too, on every push to `main` and on pull requests (`.github/workflows/ci.yml`), and again
before publishing on a `v*` tag. Anything that depends on the environment, `CI_*` variables and
the like, has to be neutralized by a fixture, otherwise it passes locally and fails in CI.

## Release

The version lives in `src/elemctl/__init__.py` alone, and `pyproject.toml` reads it dynamically.
A release is a version bump, a `CHANGELOG` section for the day and an annotated `v<version>`
tag. Publishing to PyPI happens in CI through Trusted Publishing.
