# Agent instructions

Read [CLAUDE.md](CLAUDE.md) for repository conventions, including documentation
generation and validation. The documentation policy below also applies.

## Documentation

**Required skill: `tooling-docs-writing`.** Before creating, editing or proofreading
documentation, load and apply this skill automatically, without waiting for the task
to name it. Use it together with `humanizer` when that skill is available.

This applies to both English and Russian documentation: website pages under `docs/`,
README and contributor guides, changelogs, reference pages, frontmatter and package
annotations, and user-facing CLI/MCP help and descriptions in source files. For
generated pages, edit the source and regenerate the output. Keep RU/EN editions
consistent and run the existing checks relevant to the changed documentation.

Resolve `tooling-docs-writing` from the runtime's installed skills. If it is not
listed, check `~/.codex/skills/tooling-docs-writing/SKILL.md` and
`~/.agents/skills/tooling-docs-writing/SKILL.md`. If it cannot be found, report that
it is missing; do not silently skip it or claim that it was applied.

The skill is the source of the editorial rules; do not maintain a separate copy here.
