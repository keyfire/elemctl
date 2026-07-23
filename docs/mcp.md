---
title: "MCP server and editors"
description: "Driving elemctl from an AI agent over MCP, plus plugins and the VS Code extension."
sidebar:
  label: MCP and editors
  order: 4
---

## MCP server


The server exposes platform operations as MCP tools (stdio transport):

```bash
pip install "elemctl[mcp]"
claude mcp add elemctl -- elemctl mcp
```

The server reads connection credentials from the same `ELEMENT_*` variables / `.env`. Among the tools: `list_apps`, `get_app`, `deploy` (with an `ok` field in the response), `verify_deploy`, `list_builds`, `merge_branch` and others.

A single environment is not a limit: every tool that talks to the platform takes an optional `env_file` - a path to another installation's `.env`. One server thus serves both the cloud and a local installation without a restart with different credentials. `list_apps` returns brief cards by default (id, name, status, uri, applied version): full cards of a whole space are tens of thousands of characters in an agent's response - pass `brief=false` for them. `list_projects` behaves the same way (id, name, project kind, space, application count, deletion flag).

## Plugins


elemctl discovers external packages through `importlib.metadata` entry points: it declares nothing about plugins in its own `pyproject.toml` and reads them on demand. This keeps non-publishable vendor artifacts in a separate package while the elemctl core stays clean and public.

One group is currently supported – **`elemctl.debug_adapter`**: a plugin package declares the directory of the platform debug adapter (proprietary 1C jars, not shipped with elemctl). The entry-point value is a path or a zero-argument callable returning a path; the path points to a directory that contains a `repo/` subdirectory with the adapter jars.

```toml
# a plugin package's pyproject.toml
[project.entry-points."elemctl.debug_adapter"]
name = "my_package:adapter_root"     # () -> Path to the directory containing repo/
```

```bash
# the adapter path from the installed plugin (for the VS Code extension):
# {"path": "...", "found": true} or {"path": null, "found": false}
elemctl debug-adapter

# which plugins are visible – install diagnostics
elemctl plugins
```

The adapter itself (proprietary 1C jars) is extracted from the platform distribution by `tools/extract_adapter.py` – into a directory for a manual `xbslDebug.adapterPath`, or for building the plugin package. The script is not shipped in the package distribution.

Plugin discovery is disabled by `ELEMCTL_NO_PLUGINS=1` (a run with the core capabilities only).

## VS Code


Two companion extensions integrate elemctl into the editor:

- [XBSL](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl) (the
  [xbsl-lint](https://github.com/keyfire/xbsl-lint) project) – highlighting, linting, a form
  preview, and the *XBSL: deploy the project* button that runs `elemctl deploy` as a terminal
  task with the apply verification.
- [XBSL Debug](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl-debug) (lives
  in this repository, [`editors/vscode`](editors/vscode)) – debugging 1C:Element applications
  with the platform's DAP adapter; the debug session data comes from `elemctl apps debug`.

Both are also published to [Open VSX](https://open-vsx.org/namespace/keyfire).
