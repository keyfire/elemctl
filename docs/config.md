---
title: "Configuration"
description: "Connection settings, environment variables and the interface language."
sidebar:
  label: Configuration
  order: 2
---

## Configuration


elemctl takes the connection credentials from environment variables or from a `.env` file in the current directory. Environment variables take precedence over values in the file.

| Variable | Purpose |
|---|---|
| `ELEMENT_BASE_URL` | the server base URL starting with `http://` or `https://`, e.g. `https://1cmycloud.com` |
| `ELEMENT_CLIENT_ID` | Client-Id used to obtain a token |
| `ELEMENT_CLIENT_SECRET` | Client-Secret |
| `ELEMENT_APP_ID` | default application (optional) |
| `ELEMENT_PROJECT_ID` | default project (optional) |
| `ELEMENT_SPACE_ID` | default space (optional) |
| `ELEMENT_CA_FILE` | additional PEM CA bundle for a private cloud (optional) |
| `ELEMENT_TLS_STRICT` | strict RFC 5280 certificate checks; `true` by default |
| `ELEMENT_TLS_VERIFY` | certificate and hostname verification; `true` by default |

Client-Id and Client-Secret are issued in the 1cmycloud control panel, in the Console API integrations section. A file template is [.env.example](https://github.com/keyfire/elemctl/blob/main/.env.example).

### Configuring with `.env`

Copy the template into the directory from which you will run `elemctl`:

```bash
cp .env.example .env
```

Then fill in at least the server address, Client-Id and Client-Secret:

```dotenv
ELEMENT_BASE_URL=https://1cmycloud.com
ELEMENT_CLIENT_ID=client-id
ELEMENT_CLIENT_SECRET=client-secret
```

Without `--env-file`, the tool looks for a file named exactly `.env` in the
**current working directory**. That is not necessarily the project directory,
and not the directory `elemctl` is installed into. The `elemctl` repository
excludes `.env` from Git. If you create one in another repository, add `.env`
to its `.gitignore` to keep credentials out of commits and logs.

If the configuration is stored elsewhere, specify its path. An absolute path is
more reliable for the MCP server, background jobs and CI:

```bash
elemctl --env-file /opt/elemctl/cloud.env apps list
```

The option is also accepted after the command:

```bash
elemctl apps list --env-file /opt/elemctl/cloud.env
```

A relative path is resolved from the current working directory. Separate files
allow connections to several installations without changing process variables:

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
`ELEMENT_TLS_STRICT=false`. Certificate-chain, validity, signature and hostname
verification all stay on. Only OpenSSL's strict RFC 5280 profile is relaxed.
Where you can, fix or reissue the CA certificate instead.

Use `ELEMENT_CA_FILE=/path/to/internal-ca.pem` when the private CA is not in the
system trust store. `ELEMENT_TLS_VERIFY=false` turns off both certificate and
hostname verification. It is a last resort, and only for an isolated test
network. With verification off, every command prints a warning to stderr while
stdout contains only the response, preserving valid JSON for pipeline processing. Boolean
values accept `true`/`false`, `yes`/`no`, `on`/`off`, or `1`/`0`.

`ELEMCTL_NO_PROXY` sends requests without the environment's proxy. Use it when
an internal address is unreachable through the proxy or the proxy replaces the
server certificate. TLS verification remains enabled. If the direct connection
fails with `CERTIFICATE_VERIFY_FAILED`, configure a trusted CA or the `ELEMENT_TLS_*`
options.

`ELEMCTL_NO_PROXY` can also be set in the connection's `.env` file. An
environment variable takes precedence when both are present. This allows one MCP
server to serve several installations through `env_file`. The server handles
one call at a time, and each file's setting applies only to requests for its
installation.

File changes take effect on the next call without restarting the server if the
file's modification time or size changes. The client cache key includes
`env_file` and these two attributes.
When `env_file` is absent, the server uses its own `--env-file` or the `.env` in
the current working directory. Changing access permissions without changing the
file's modification time or size does not refresh the cached client.

This behavior applies to `elemctl mcp`. When an application passes a `Config`
object directly to the server without a file, the configuration remains fixed
for the lifetime of the process.

### Behaviour of the tool

`ELEMCTL_LANG`, `ELEMCTL_NO_PLUGINS`, `ELEMCTL_DATA_DIR` and `ELEMCTL_REGISTRY_LIMIT`
are read only from environment variables. They are not read from a connection's
`.env` file. `ELEMCTL_NO_PROXY` supports both sources, as described above.

| Variable | Purpose |
|---|---|
| `ELEMCTL_LANG` | language of the messages and the help (`ru`, `en`); the `--lang` flag takes precedence |
| `ELEMCTL_NO_PROXY` | set it to bypass the environment's proxy for every call (loopback and private addresses are bypassed anyway); also readable from the stand's `.env` |
| `ELEMCTL_NO_PLUGINS` | do not look for plugins: work with the core capabilities only |
| `ELEMCTL_DATA_DIR` | the directory of the local registry of uploads; by default `%LOCALAPPDATA%\elemctl` on Windows and `$XDG_STATE_HOME/elemctl` (`~/.local/state/elemctl`) elsewhere |
| `ELEMCTL_REGISTRY_LIMIT` | how many uploads the local registry of uploads keeps; 1000 by default, `0` keeps every one |

### The local registry of uploads

The server stores the commit of a build uploaded to an existing project.
elemctl records additional upload details in the local `uploads.jsonl` file.
Each record contains the build and project identifiers, version, branch, commit,
uncommitted-change status, source directory, installation, command and upload
time. The registry is updated by `deploy`, `builds upload` and `probe`.

`builds list --brief` and `apps get` use the registry to fill in a branch or
commit missing from the build card on the server. The source of each value is
reported. The local file does not contain builds uploaded from another machine,
from CI or by a version of elemctl without a registry.

A registry write failure produces a warning and does not cancel the upload.
The file can be deleted; only this machine's upload history is removed. By
default, the registry keeps the last 1000 uploads. `ELEMCTL_REGISTRY_LIMIT`
sets another limit; `0` removes it. When the number of records exceeds the
limit by 10%, the next upload trims the file to the most recent records.

### The CI environment

The build uses standard CI variables. When these are set, a version can be determined without a separate flag or source changes:

| Variable | Purpose |
|---|---|
| `CI_PIPELINE_IID` | run number; the build version suffix comes from it when there is neither `--build-version` nor a previous build |
| `GITHUB_RUN_NUMBER` | the same, second in order |
| `BUILD_NUMBER` | the same, third in order; the first numeric value is used |
| `CI_COMMIT_BRANCH` | the branch name for the manifest when git is in a detached `HEAD` |
| `CI_COMMIT_REF_NAME` | the same, second in order |
| `GITHUB_REF_NAME` | the same, third in order; the value `HEAD` is discarded and the field stays empty |

## Language


Error and progress messages, and the `--help` text, come in Russian and English. The JSON result is language-neutral. The language is picked in this order: `--lang ru|en`, then the `ELEMCTL_LANG` env var, then the system locale (`LC_ALL`, then `LANG`), then Russian. `--lang` is read before the parser is built, so `elemctl --lang en --help` prints English help.
