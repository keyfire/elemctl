// Конфигурация сайта документации (Blume, движок на Astro + Vite). Публикация на
// GitHub Pages из .github/workflows/docs.yml. Контент лежит в docs/ парами
// Имя.md + Имя.ru.md (суффиксный режим i18n parser: "dot"). Локальная проверка
// сборки: npx blume build.
import { defineConfig } from "blume";

export default defineConfig({
  title: "Elemctl",
  description:
    "A CLI, MCP server and library for the 1C:Element Console API: applications, " +
    "builds from source and one-command deploys with an honest check that the " +
    "change actually landed.",

  // Весь контент сайта – в docs/. Страницы changelog*.md зеркалят CHANGELOG из корня
  // репозитория, их собирает scripts/sync-docs.mjs (npm run sync:docs).
  // Контент – общий с репозиторием: страницы лежат в ../docs рядом с исходниками,
  // чтобы правка доки и правка кода жили в одном месте.
  content: {
    root: "../docs",
    // BACKLOG – рабочая записка о найденных пробелах, ведётся для себя. SPEC – это
    // задание на разработку ("требования к продукту", "реализация проектируется с
    // нуля"), а не руководство: читателю сайта оно объясняет не инструмент, а то,
    // каким его заказывали. Полезная часть спецификации – про саму платформу –
    // вынесена в platform*.md. Оба файла остаются в репозитории.
    exclude: ["**/_*", "**/.*", "BACKLOG*.md", "SPEC*.md"],
  },

  // Сайт отдаётся с подпути /edt-bridge/ общего домена документации: base переносит
  // туда весь сайт и переписывает внутренние ссылки и ассеты; site – origin для
  // sitemap/canonical/OG. Домен держит репозиторий keyfire.github.io.
  deployment: {
    base: "/elemctl",
    site: "https://docs.keyfire.ru",
  },

  // Репозиторий: ссылки "Изменить на GitHub" под страницами и иконка в шапке.
  github: {
    owner: "keyfire",
    repo: "elemctl",
  },

  // Дата "последнее изменение" из истории git (в CI нужен fetch-depth: 0).
  lastModified: true,

  // Двуязычие: английский по умолчанию (файлы Имя.md), русский – суффикс .ru
  // (файлы Имя.ru.md). Русский UI-пакет встроен в Blume, переводим только контент.
  i18n: {
    defaultLocale: "en",
    locales: [
      { code: "en", label: "English" },
      { code: "ru", label: "Русский" },
    ],
    parser: "dot",
  },

  // Гайды для контрибьюторов живут на GitHub, а не страницами сайта – закрепляем
  // ссылками над сайдбаром.
  navigation: {
    featured: [
    // Соседние инструменты: ссылка видна с любой страницы, а не только с главной.
    // Ведут на русские версии – переключатель языка стоит в шапке принимающего сайта.
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

  // Фиолетовый акцент – чтобы сайты проектов различались с первого взгляда.
  theme: {
    accent: "violet",
  },
});
