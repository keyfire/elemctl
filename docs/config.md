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
| `ELEMENT_CA_FILE` | additional PEM CA bundle for a private cloud (optional) |
| `ELEMENT_TLS_STRICT` | strict RFC 5280 certificate checks; `true` by default |
| `ELEMENT_TLS_VERIFY` | certificate and hostname verification; `true` by default |

Client-Id/Client-Secret are issued in the 1cmycloud control panel (the Console API integrations section). A file template is [.env.example](https://github.com/keyfire/elemctl/blob/main/.env.example).

### Configuring with `.env`

Copy the template into the directory from which you will run `elemctl`:

```bash
cp .env.example .env
```

Then fill in at least the platform address, Client-Id and Client-Secret:

```dotenv
ELEMENT_BASE_URL=https://1cmycloud.com
ELEMENT_CLIENT_ID=client-id
ELEMENT_CLIENT_SECRET=client-secret
```

Without `--env-file`, the tool looks for a file named exactly `.env` in the
**current working directory**. That is not necessarily the project directory or
the directory where `elemctl` is installed. The `elemctl` repository excludes
`.env` from Git; if you create one in another repository, add `.env` to its
`.gitignore`. The file contains a secret and must stay out of commits and logs.

When the configuration lives elsewhere, pass it explicitly. An absolute path is
more reliable for the MCP server, background jobs and CI:

```bash
elemctl --env-file /opt/elemctl/cloud.env apps list
```

The option is also accepted after the command:

```bash
elemctl apps list --env-file /opt/elemctl/cloud.env
```

A relative path is resolved from the current working directory. Separate files
let one installation address multiple stands without changing process variables:

```bash
elemctl --env-file ./env/public-cloud.env apps list
elemctl --env-file ./env/local-cloud.env apps list
```

Example for a local cloud with a trusted but legacy internal CA that Python 3.13
rejects under strict RFC 5280 checks:

```dotenv
ELEMENT_BASE_URL=https://cloud.internal.example
ELEMENT_CLIENT_ID=client-id
ELEMENT_CLIENT_SECRET=client-secret
ELEMENT_TLS_STRICT=false
```

For an internal CA that is trusted but rejected by Python 3.13 with
`Basic Constraints of CA cert not marked critical`, set
`ELEMENT_TLS_STRICT=false`. This keeps certificate-chain, validity, signature,
and hostname verification enabled; it only relaxes OpenSSL's strict RFC 5280
profile. Prefer fixing or reissuing the CA certificate when possible.

Use `ELEMENT_CA_FILE=/path/to/internal-ca.pem` when the private CA is not in the
system trust store. `ELEMENT_TLS_VERIFY=false` disables both certificate and
hostname verification and is intended only as a last resort in an isolated test
network. With verification off every command prints a warning to stderr - stdout
keeps the answer, so a piped JSON output is not spoiled by it. Boolean values
accept `true`/`false`, `yes`/`no`, `on`/`off`, or `1`/`0`.

`ELEMCTL_NO_PROXY` solves a different problem: it routes requests past the
environment's proxy. It can help when the proxy cannot reach an internal address
or replaces its certificate, but it does not disable server-certificate
verification. If the direct connection reaches the server and ends with
`CERTIFICATE_VERIFY_FAILED`, configure the trusted CA or `ELEMENT_TLS_*` options.

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
