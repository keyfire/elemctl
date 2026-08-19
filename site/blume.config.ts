// Configuration of the documentation site (Blume, an engine on top of Astro + Vite).
// Published to GitHub Pages from .github/workflows/docs.yml. The content lies in docs/
// as Name.md + Name.ru.md pairs (the suffix i18n mode, parser: "dot"). Local build
// check: npx blume build.
import { defineConfig } from "blume";

export default defineConfig({
  title: "Elemctl",
  description:
    "A CLI, MCP server and library for the 1C:Element Console API: applications, " +
    "builds from source and one-command deploys with an honest check that the " +
    "change actually landed.",

  // The whole content of the site is in docs/. The changelog*.md pages mirror the CHANGELOG
  // from the repository root, they are assembled by scripts/sync-docs.mjs (npm run sync:docs).
  // The content is shared with the repository: the pages lie in ../docs next to the sources,
  // so that an edit of the docs and an edit of the code live in one place.
  content: {
    root: "../docs",
    // BACKLOG is a working note about the gaps found, kept for internal use. SPEC is a
    // development assignment ("product requirements", "the implementation is designed
    // from scratch") rather than a guide: to a reader of the site it explains not the
    // tool but the way it was ordered. The useful part of the specification – the one
    // about the platform itself – has been moved to platform*.md. Both files stay in
    // the repository.
    exclude: ["**/_*", "**/.*", "BACKLOG*.md", "SPEC*.md"],
  },

  // The site is served from the /elemctl/ subpath of the common documentation domain: base
  // moves the whole site there and rewrites internal links and assets; site is the origin
  // for sitemap/canonical/OG. The domain is held by the keyfire.github.io repository.
  deployment: {
    base: "/elemctl",
    site: "https://docs.keyfire.ru",
  },

  // The repository: the "Edit on GitHub" links under the pages and the icon in the header.
  github: {
    owner: "keyfire",
    repo: "elemctl",
  },

  // Search: FlexSearch rather than the default Orama. Both are keyless and share the same
  // static /blume-search.json index, but Orama tokenizes with its English splitter
  // (/[^A-Za-zàèéìòóù0-9_'-]+/), which treats every Cyrillic letter as a separator: the whole
  // Russian half of the site collapses to zero tokens, so every Russian query answered
  // "nothing found". Orama's tokenizer is fixed inside Blume and takes no language from this
  // config, whereas FlexSearch's default encoder is Unicode-aware and indexes Cyrillic as
  // words. Its "forward" tokenization also prefix-matches, which stands in for the stemming
  // an inflected language would otherwise need.
  search: {
    provider: "flexsearch",
  },

  // The "last modified" date taken from the git history (CI needs fetch-depth: 0).
  lastModified: true,

  // Bilingual: English by default (the Name.md files), Russian – the .ru suffix
  // (the Name.ru.md files). The Russian UI pack is built into Blume, only the content
  // is translated.
  i18n: {
    defaultLocale: "en",
    locales: [
      { code: "en", label: "English" },
      { code: "ru", label: "Русский" },
    ],
    parser: "dot",
  },

  // The contributor guides live on GitHub rather than as pages of the site – they are
  // pinned as links above the sidebar.
  navigation: {
    featured: [
    // Neighbouring tools: the link is visible from any page, not only from the home page.
    // They lead to the Russian versions – the language switch sits in the header of the
    // receiving site.
      {
        label: "XBSL",
        href: "https://docs.keyfire.ru/xbsl/ru/",
        icon: "spell-check",
      },
      {
        label: "EDT-Bridge",
        href: "https://docs.keyfire.ru/edt-bridge/ru/",
        icon: "plug",
      },
      {
        label: "GitHub",
        href: "https://github.com/keyfire/elemctl",
        icon: "github",
      },
    ],
  },

  // A violet accent – so that the sites of the projects differ at first glance.
  theme: {
    accent: "violet",
    // Code is set in Geist Mono: at the small size of the table chips its Cyrillic reads
    // more evenly than the default IBM Plex Mono. Astro downloads its Latin subset only –
    // the Cyrillic one comes from theme.css, which names the family variable of every
    // role of this block, so a font changed here has to be renamed there too.
    fonts: { mono: "geist-mono" },
  },
});
