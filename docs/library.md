---
title: "Use as a library"
description: "Calling elemctl from Python code, and the build format it produces."
sidebar:
  label: As a library
  order: 5
---

## Use as a library


```python
from elemctl import Config, ElementClient
from elemctl.deploy import deploy_from_sources

client = ElementClient(Config.from_env())
apps = client.list_apps()

report = deploy_from_sources(
    client,
    app_id="...",
    project_id="...",
    project_dir="acme/crm",
    log=print,
)
assert report.ok, report.problems
```

`list_apps()` answers with the live applications. Deleted ones stay in the
platform list under the `Deleted` status, and a stand a few months old carries
hundreds of them; pass `include_deleted=True` for the full list.
`list_apps_counted()` returns the same list under `items` and adds the counters
the CLI and the MCP tool report: `total`, `live` and `shown`.

To check compilation without touching the working application, run the same
cycle the `probe` command does:

```python
from elemctl.probe import probe_project

report = probe_project(client, project_dir="acme/crm", log=print)
for error in report.errors:
    print(f"{error['file']}:{error['line']}:{error['column']} {error['message']}")
assert report.ok, report.messages
```

## Build format


`.xasm` for an application and `.xlib` for a library are both ZIP archives:

```
Assembly.yaml            # manifest: ProjectKind, Vendor, Name, Version, ...
{vendor}/{name}/...      # project files: .yaml, .xbsl, resources
```

The project directory must follow the `{repo}/{vendor}/{name}/Проект.yaml` layout, because paths inside the archive are built relative to the repository root. The `ВидПроекта` field in `Проект.yaml` says whether the project is an application or a library. When an application references libraries whose source projects sit under the same repository root, their files go into the application archive on their own, transitive local dependencies included. A referenced library that is not present locally remains an external platform dependency.
