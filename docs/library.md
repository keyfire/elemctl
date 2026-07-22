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

## Build format


`.xasm` (application) and `.xlib` (library) are a ZIP archive:

```
Assembly.yaml            # manifest: ProjectKind, Vendor, Name, Version, ...
{vendor}/{name}/...      # project files: .yaml, .xbsl, resources
```

The project directory must follow the `{repo}/{vendor}/{name}/Проект.yaml` layout – paths inside the archive are built relative to the repository root. The project kind (application/library) is determined by the `ВидПроекта` field in `Проект.yaml`.
