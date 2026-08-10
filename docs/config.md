---
title: "Configuration"
description: "Connection settings, environment variables and the interface language."
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

Client-Id/Client-Secret are issued in the 1cmycloud control panel (the Console API integrations section). A file template is [.env.example](https://github.com/keyfire/elemctl/blob/main/.env.example).

### Behaviour of the tool

These are set through the environment only – a connection `.env` is not their place:

| Variable | Purpose |
|---|---|
| `ELEMCTL_LANG` | language of the messages and the help (`ru`, `en`); the `--lang` flag wins over it |
| `ELEMCTL_NO_PROXY` | set it to bypass the environment's proxy for every call (loopback and private addresses are bypassed anyway) |
| `ELEMCTL_NO_PLUGINS` | do not look for plugins: a run with the core capabilities only |

### The CI environment

The build declares no variables of its own, but it reads the ones CI sets itself – which is why a pipeline needs neither a version flag nor an edit of the sources:

| Variable | Purpose |
|---|---|
| `CI_PIPELINE_IID` | run number; the build version suffix comes from it when there is neither `--build-version` nor a previous build |
| `GITHUB_RUN_NUMBER` | the same, second in order |
| `BUILD_NUMBER` | the same, third in order (the first NUMERIC value wins) |
| `CI_COMMIT_BRANCH` | the branch name for the manifest when git is in a detached `HEAD` |
| `CI_COMMIT_REF_NAME` | the same, second in order |
| `GITHUB_REF_NAME` | the same, third in order; the value `HEAD` is discarded and the field stays empty |

## Language


Error and progress messages, and the `--help` text, come in Russian and English (the JSON result is language-neutral). The language is picked by `--lang ru|en` > the `ELEMCTL_LANG` env var > the system locale (`LC_ALL`, then `LANG`) > Russian; `--lang` is read before the parser is built, so `elemctl --lang en --help` prints English help.
