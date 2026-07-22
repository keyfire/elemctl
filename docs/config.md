---
title: "Configuration"
description: "Connection settings, profiles and the interface language."
sidebar:
  label: Configuration
  order: 2
---

## Configuration


Connection credentials are taken from environment variables or from a `.env` file in the current directory (environment variables take priority):

| Variable | Purpose |
|---|---|
| `ELEMENT_BASE_URL` | the platform base URL, e.g. `https://1cmycloud.com` |
| `ELEMENT_CLIENT_ID` | Client-Id used to obtain a token |
| `ELEMENT_CLIENT_SECRET` | Client-Secret |
| `ELEMENT_APP_ID` | default application (optional) |
| `ELEMENT_PROJECT_ID` | default project (optional) |
| `ELEMENT_SPACE_ID` | default space (optional) |

Client-Id/Client-Secret are issued in the 1cmycloud control panel (the Console API integrations section). A file template is [.env.example](.env.example).

## Language


Error and progress messages, and the `--help` text, come in Russian and English (the JSON result is language-neutral). The language is picked by `--lang ru|en` > the `ELEMCTL_LANG` env var > the system locale > Russian; `--lang` is read before the parser is built, so `elemctl --lang en --help` prints English help.
