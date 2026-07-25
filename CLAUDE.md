# Repository conventions

elemctl is a public, international project: a CLI, an MCP server and a Python library for the
1C:Enterprise.Element Console API v2. The contract the tool implements lives in
[docs/SPEC.md](docs/SPEC.md) (with a Russian twin, `docs/SPEC.ru.md`); this file records how the
repository itself is written.

## Language of the code

- **Code is English.** Comments, docstrings, identifiers, test names – all of them, in `src/`,
  `tests/`, `tools/` and `editors/`. The code is read by people who do not speak Russian.
- **Russian stays where it faces the user**: the i18n message catalog (`src/elemctl/i18n.py`),
  argparse help strings, user-facing strings, the MCP tool descriptions and the server
  `INSTRUCTIONS` literal – an agent reads those in Russian.
- **Platform identifiers are quoted as they are**: `Проект.yaml`, `Ресурсы`, `Имя`, `Поставщик`,
  `ВидПроекта`, `ОбластьВидимости` and the like are real keys and file names, not text to
  translate. The same goes for the Russian data of test fixtures.

## Typography

Applies to English text as well:

- dashes – en dash `–` (U+2013) only, never an em dash;
- quotes – straight `"` and `'`, never guillemets or curly quotes;
- ellipsis – three dots `...`, never the `…` character.

## Nothing internal

The repository is public. It must not carry internal project identifiers, stand names,
real application or assembly ids, internal hosts, issue keys or machine paths – not in the
code, not in comments, not in test fixtures. Neutral examples: vendors `acme`, `globex`,
applications `crm-dev`, `demo-app`.

## Documentation pairs

English and Russian pages go together: `README.md` / `README.ru.md`, `docs/SPEC.md` /
`docs/SPEC.ru.md`, `CHANGELOG.md` / `CHANGELOG.ru.md` and the rest of `docs/*.md`. A change
to one side without the other is an unfinished change. Two pages are generated – never edit
them by hand:

- `docs/cli.md` / `docs/cli.ru.md` – `python scripts/gen-cli-docs.py`;
- `docs/changelog.md` / `docs/changelog.ru.md` – `node scripts/sync-docs.mjs`.

## Tests

`python -m pytest -q` – the suite runs without network access, the transport is stubbed.
It also runs in CI on every push to `main` and on pull requests (`.github/workflows/ci.yml`),
and again before publishing on a `v*` tag. Anything depending on the environment (`CI_*`
variables and the like) has to be neutralized by a fixture, otherwise it passes locally and
fails in CI.

## Release

The version lives in `src/elemctl/__init__.py` alone (`pyproject.toml` reads it dynamically).
A release is a version bump, a `CHANGELOG` section for the day and an annotated `v<version>`
tag – publishing to PyPI happens in CI through Trusted Publishing. The VS Code debug companion
in `editors/vscode` is released separately under `vscode-v*` tags.
