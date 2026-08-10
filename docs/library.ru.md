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

Проверка компиляции, не трогающая рабочее приложение, - тот же цикл, что
выполняет команда `probe`:

```python
from elemctl.probe import probe_project

report = probe_project(client, project_dir="acme/crm", log=print)
for error in report.errors:
    print(f"{error['file']}:{error['line']}:{error['column']} {error['message']}")
assert report.ok, report.messages
```

## Формат сборки


`.xasm` (приложение) и `.xlib` (библиотека) - это ZIP-архив:

```
Assembly.yaml            # манифест: ProjectKind, Vendor, Name, Version, ...
{vendor}/{name}/...      # файлы проекта: .yaml, .xbsl, ресурсы
```

Каталог проекта должен лежать по схеме `{repo}/{vendor}/{name}/Проект.yaml` -
пути в архиве строятся относительно корня репозитория. Вид проекта
(приложение/библиотека) определяется по полю `ВидПроекта` в `Проект.yaml`.
Если приложение ссылается на библиотеки, исходные проекты которых находятся
под тем же корнем репозитория, их файлы автоматически включаются в архив
приложения (включая транзитивные локальные зависимости). Библиотека, на которую
есть ссылка, но которой нет локально, остаётся внешней зависимостью платформы.
