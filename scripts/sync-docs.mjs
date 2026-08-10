// Keeps the two documentation surfaces from drifting apart. The mirroring goes both ways.
//
// Down: the root CHANGELOG (CHANGELOG.md + CHANGELOG.ru.md) is the single source of truth,
// and the mirrored docs/changelog*.md pages are assembled from it before the site build
// (npm run sync:docs, called from prebuild). Never edit the mirrored pages by hand.
//
// Up: the sections a README shares with a site page used to be kept by hand on both sides
// and they drifted – the README knew about `probe` and the user lists while the home page
// did not, the page knew about the `elemctl.commands` plugins while the README did not, and
// the README still promised two VS Code extensions after one of them was gone. Now the page
// is the source and the README section is filled from it between the marker comments.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const PAGES = [
  {
    from: 'CHANGELOG.md',
    to: 'docs/changelog.md',
    note: (from) => `Assembled from ${from} by scripts/sync-docs.mjs. Do not edit by hand.`,
    front: {
      title: 'Changelog',
      description: 'What changed in elemctl from release to release, grouped by day.',
      label: 'Changelog',
      order: 7,
    },
  },
  {
    from: 'CHANGELOG.ru.md',
    to: 'docs/changelog.ru.md',
    note: (from) => `Собрано из ${from} скриптом scripts/sync-docs.mjs. Не редактировать вручную.`,
    front: {
      title: 'История изменений',
      description: 'Что менялось в elemctl от версии к версии, с разбивкой по дням.',
      label: 'История изменений',
      order: 7,
    },
  },
];

// Sections injected from a site page into a README, the other direction. The marker comments
// stay in the target file, so the text around them is edited by hand as usual; the heading
// belongs to the README, only the body of the section travels.
const INJECTIONS = [
  { from: 'docs/index.md', section: 'Features', into: 'README.md', marker: 'features' },
  { from: 'docs/index.md', section: 'Installation', into: 'README.md', marker: 'installation' },
  { from: 'docs/index.md', section: 'Quick start', into: 'README.md', marker: 'quickstart' },
  { from: 'docs/index.md', section: 'Limitations and status', into: 'README.md', marker: 'limitations' },
  { from: 'docs/config.md', section: 'Configuration', into: 'README.md', marker: 'configuration' },
  { from: 'docs/config.md', section: 'Language', into: 'README.md', marker: 'language' },
  { from: 'docs/mcp.md', section: 'MCP server', into: 'README.md', marker: 'mcp' },
  { from: 'docs/mcp.md', section: 'Plugins', into: 'README.md', marker: 'plugins' },
  { from: 'docs/mcp.md', section: 'VS Code', into: 'README.md', marker: 'vscode' },
  { from: 'docs/library.md', section: 'Use as a library', into: 'README.md', marker: 'library' },
  { from: 'docs/library.md', section: 'Build format', into: 'README.md', marker: 'buildformat' },

  { from: 'docs/index.ru.md', section: 'Возможности', into: 'README.ru.md', marker: 'features' },
  { from: 'docs/index.ru.md', section: 'Установка', into: 'README.ru.md', marker: 'installation' },
  { from: 'docs/index.ru.md', section: 'Быстрый старт', into: 'README.ru.md', marker: 'quickstart' },
  { from: 'docs/index.ru.md', section: 'Ограничения и статус', into: 'README.ru.md', marker: 'limitations' },
  { from: 'docs/config.ru.md', section: 'Настройка', into: 'README.ru.md', marker: 'configuration' },
  { from: 'docs/config.ru.md', section: 'Язык', into: 'README.ru.md', marker: 'language' },
  { from: 'docs/mcp.ru.md', section: 'MCP-сервер', into: 'README.ru.md', marker: 'mcp' },
  { from: 'docs/mcp.ru.md', section: 'Плагины', into: 'README.ru.md', marker: 'plugins' },
  { from: 'docs/mcp.ru.md', section: 'VS Code', into: 'README.ru.md', marker: 'vscode' },
  { from: 'docs/library.ru.md', section: 'Использование как библиотеки', into: 'README.ru.md', marker: 'library' },
  { from: 'docs/library.ru.md', section: 'Формат сборки', into: 'README.ru.md', marker: 'buildformat' },
];

// The leading heading and the language-switcher line are dropped: the site sets the heading
// from the frontmatter and switches the language with its own button.
const isSwitcherLine = (l) =>
  l.startsWith('**English**') || l.startsWith('**Английская') || l.startsWith('[English]');

const strip = (text) => {
  const lines = text.split('\n').filter((l) => !isSwitcherLine(l));
  // The heading is dropped wherever it stands among the leading lines, not only on line 0:
  // in the Russian changelog the switcher comes first, so an index check would leave the H1
  // in place and the page would show its title twice.
  const first = lines.findIndex((l) => l.trim() !== '');
  if (first !== -1 && lines[first].startsWith('# ')) lines.splice(first, 1);
  return lines.join('\n').trim();
};

const rewriteLinks = (text, links = {}) =>
  Object.entries(links).reduce((t, [from, to]) => t.split(`](${from})`).join(`](${to})`), text);

// The body of one `## Section` of a page: everything up to the next heading of the same level,
// subsections included. The heading itself stays with the README.
export const sectionBody = (text, title) => {
  const lines = text.split('\n');
  const start = lines.findIndex((l) => l.trim() === `## ${title}`);
  if (start === -1) return null;
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((l) => l.startsWith('## '));
  return (end === -1 ? rest : rest.slice(0, end)).join('\n').trim();
};

for (const p of PAGES) {
  const src = fs.readFileSync(path.join(root, p.from), 'utf8');
  const head =
    `---\ntitle: "${p.front.title}"\ndescription: "${p.front.description}"\n` +
    `sidebar:\n  label: ${p.front.label}\n  order: ${p.front.order}\n---\n\n` +
    `<!-- ${p.note(p.from)} -->\n\n`;
  fs.writeFileSync(path.join(root, p.to), head + rewriteLinks(strip(src), p.links) + '\n');
  console.log(`${p.from} -> ${p.to}`);
}

for (const inj of INJECTIONS) {
  const target = path.join(root, inj.into);
  const text = fs.readFileSync(target, 'utf8');
  const open = `<!-- ${inj.marker}:start -->`;
  const close = `<!-- ${inj.marker}:end -->`;
  const from = text.indexOf(open);
  const to = text.indexOf(close);
  if (from === -1 || to === -1) {
    throw new Error(`${inj.into}: markers ${open} ... ${close} not found`);
  }
  const body = sectionBody(fs.readFileSync(path.join(root, inj.from), 'utf8'), inj.section);
  if (body === null) {
    throw new Error(`${inj.from}: section "## ${inj.section}" not found`);
  }
  const next = `${text.slice(0, from + open.length)}\n\n${body}\n\n${text.slice(to)}`;
  fs.writeFileSync(target, next);
  console.log(`${inj.from} [${inj.section}] -> ${inj.into} (${inj.marker})`);
}
