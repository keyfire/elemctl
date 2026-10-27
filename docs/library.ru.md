---
title: "Использование как библиотеки"
description: "Вызов elemctl из кода на Python и формат сборки, который он собирает."
sidebar:
  label: Как библиотека
  order: 5
---

## Использование как библиотеки


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

`list_apps()` возвращает приложения, не помеченные как удаленные. Удаленные
приложения остаются в списке сервера со статусом `Deleted`; на длительно
используемом стенде таких записей может быть несколько сотен. Для полного списка
указать `include_deleted=True`. Метод `list_apps_counted()` возвращает тот же
список в поле `items` и счетчики `total`, `live` и `shown`, используемые CLI
и инструментом MCP.

Проверить компиляцию, не трогая рабочее приложение, можно тем же циклом, что
выполняет команда `probe`:

```python
from elemctl.probe import probe_project

report = probe_project(client, project_dir="acme/crm", log=print)
for error in report.errors:
    print(f"{error['file']}:{error['line']}:{error['column']} {error['message']}")
assert report.ok, report.messages
```

## Формат сборки


`.xasm` для приложения и `.xlib` для библиотеки – это ZIP-архив:

```
Assembly.yaml            # манифест: ProjectKind, Vendor, Name, Version, ...
{vendor}/{name}/...      # файлы проекта: .yaml, .xbsl, ресурсы
```

Каталог проекта должен лежать по схеме `{repo}/{vendor}/{name}/Проект.yaml`,
потому что пути в архиве строятся от корня репозитория. Приложение это или
библиотека, определяется по полю `ВидПроекта` в `Проект.yaml`. Если приложение ссылается
на библиотеки, исходные проекты которых лежат под тем же корнем репозитория, их
файлы включаются в архив приложения вместе с транзитивными локальными
зависимостями. Библиотека, исходники которой отсутствуют локально, остается
внешней зависимостью приложения 1С:Элемента.
