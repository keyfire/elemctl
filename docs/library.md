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

A compilation check that does not touch the working application – the same cycle
the `probe` command runs:

```python
from elemctl.probe import probe_project

report = probe_project(client, project_dir="acme/crm", log=print)
for error in report.errors:
    print(f"{error['file']}:{error['line']}:{error['column']} {error['message']}")
assert report.ok, report.messages
```

## Build format


`.xasm` (application) and `.xlib` (library) are a ZIP archive:

```
Assembly.yaml            # manifest: ProjectKind, Vendor, Name, Version, ...
{vendor}/{name}/...      # project files: .yaml, .xbsl, resources
```

The project directory must follow the `{repo}/{vendor}/{name}/Проект.yaml` layout – paths inside the archive are built relative to the repository root. The project kind (application/library) is determined by the `ВидПроекта` field in `Проект.yaml`. When an application references libraries whose source projects are present under the same repository root, their files are included in the application archive automatically (including transitive local dependencies). A referenced library that is not present locally remains an external platform dependency.
