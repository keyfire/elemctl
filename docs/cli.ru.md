---
title: "Команды"
description: "Справочник команд и параметров elemctl: общие флаги, приложения, сборки, деплой и всё остальное."
sidebar:
  label: Команды
  order: 3
---

<!-- Собрано из вывода `elemctl --help` скриптом scripts/gen-cli-docs.py. Не редактировать вручную. -->

Справочник собран из самого инструмента – это то же, что показывает `elemctl --help`, только на одной странице и целиком.

Общие флаги ставятся до команды: `elemctl --timeout 120 apps list`. Язык вывода переключается флагом `--lang`, переменной `ELEMCTL_LANG` или берётся из локали системы.

## Общие флаги

Управление приложениями платформы 1С:Предприятие.Элемент (Console API v2)

```bash
usage: elemctl [-h] [--base-url BASE_URL] [--client-id CLIENT_ID] [--client-secret CLIENT_SECRET]
               [--env-file ENV_FILE] [--timeout TIMEOUT] [--lang {ru,en}] [--version]
               команда ...
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--base-url BASE_URL` | базовый URL платформы (ELEMENT_BASE_URL) |
| `--client-id CLIENT_ID` | Client-Id для получения токена (ELEMENT_CLIENT_ID) |
| `--client-secret CLIENT_SECRET` | Client-Secret к этому Client-Id (ELEMENT_CLIENT_SECRET) |
| `--env-file ENV_FILE` | путь к .env-файлу (по умолчанию .env в текущем каталоге) |
| `--timeout TIMEOUT` | таймаут запросов в секундах (по умолчанию 60) |
| `--lang {ru,en}` | язык вывода (по умолчанию: env ELEMCTL_LANG / локаль системы / ru) |
| `--version` | показать версию и выйти |

**Команды**

| Команда | Описание |
|---|---|
| `token` | получить и напечатать токен |
| `apps` | приложения |
| `spaces` | пространства |
| `projects` | проекты |
| `builds` | сборки проекта на платформе |
| `build` | локально собрать архив сборки из исходников |
| `inspect` | разобрать готовый архив сборки (.xasm/.xlib) |
| `deploy` | полный цикл: сборка -&gt; загрузка -&gt; применение -&gt; перезапуск -&gt; проверка применения |
| `branches` | ветки среды разработки |
| `dumps` | дампы приложений |
| `tasks` | задачи приложений |
| `tech` | версия технологии |
| `debug-adapter` | путь к debug-адаптеру платформы из плагина (для расширения VS Code) |
| `plugins` | диагностика плагинов elemctl (точки расширения) |
| `self-update` | обновить elemctl распаковкой колеса (безопасно, когда exe занят MCP-сервером) |
| `mcp` | запустить MCP-сервер (транспорт stdio) |

## `elemctl token`

```bash
usage: elemctl token [-h]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

## `elemctl apps`

```bash
usage: elemctl apps [-h] действие ...
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `list` | список приложений |
| `get` | карточка приложения |
| `find` | найти приложение по имени (точное совпадение без учёта регистра) |
| `create` | создать приложение |
| `ensure` | создать приложение, если его ещё нет (идемпотентно) |
| `delete` | удалить приложение (необратимо, URL меняется при пересоздании) |
| `start` | запустить приложение |
| `stop` | остановить приложение |
| `debug` | данные для сессии отладки (debug-token, debug-address) |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl apps list`

```bash
usage: elemctl apps list [-h] [--name NAME]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--name NAME` | фильтр по имени |

### `elemctl apps get`

```bash
usage: elemctl apps get [-h] [APP_ID]
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `APP_ID` | ид приложения (по умолчанию ELEMENT_APP_ID) |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl apps find`

```bash
usage: elemctl apps find [-h] [--include-deleted] NAME
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `NAME` | имя приложения |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--include-deleted` | искать и среди удалённых приложений (по умолчанию пропускаются) |

### `elemctl apps create`

```bash
usage: elemctl apps create [-h] [--project-id PROJECT_ID] [--version-id VERSION_ID]
                           [--latest-build] [--space-id SPACE_ID] [--tech-version TECH_VERSION]
                           [--no-dev-mode] [--wait]
                           NAME
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `NAME` | имя приложения |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--project-id PROJECT_ID` | проект-источник |
| `--version-id VERSION_ID` | id сборки-источника; нового проекта ещё нет – заведите его 'builds upload &lt;файл&gt;.xasm `--space-id` &lt;id&gt;' без `--project-id` |
| `--latest-build` | источник – последняя сборка проекта |
| `--space-id SPACE_ID` | пространство |
| `--tech-version TECH_VERSION` | версия технологии |
| `--no-dev-mode` | не создавать среду разработки |
| `--wait` | дождаться готовности приложения |

### `elemctl apps ensure`

```bash
usage: elemctl apps ensure [-h] [--project-id PROJECT_ID] [--version-id VERSION_ID]
                           [--latest-build] [--space-id SPACE_ID] [--tech-version TECH_VERSION]
                           [--no-dev-mode] [--wait]
                           NAME
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `NAME` | имя приложения |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--project-id PROJECT_ID` | проект-источник |
| `--version-id VERSION_ID` | id сборки-источника; нового проекта ещё нет – заведите его 'builds upload &lt;файл&gt;.xasm `--space-id` &lt;id&gt;' без `--project-id` |
| `--latest-build` | источник – последняя сборка проекта |
| `--space-id SPACE_ID` | пространство |
| `--tech-version TECH_VERSION` | версия технологии |
| `--no-dev-mode` | не создавать среду разработки |
| `--wait` | дождаться готовности приложения |

### `elemctl apps delete`

```bash
usage: elemctl apps delete [-h] APP_ID
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `APP_ID` | ид приложения |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl apps start`

```bash
usage: elemctl apps start [-h] [APP_ID]
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `APP_ID` | ид приложения (по умолчанию ELEMENT_APP_ID) |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl apps stop`

```bash
usage: elemctl apps stop [-h] [APP_ID]
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `APP_ID` | ид приложения (по умолчанию ELEMENT_APP_ID) |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl apps debug`

```bash
usage: elemctl apps debug [-h] [APP_ID]
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `APP_ID` | ид приложения (по умолчанию ELEMENT_APP_ID) |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

## `elemctl spaces`

```bash
usage: elemctl spaces [-h] действие ...
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `list` | список пространств |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl spaces list`

```bash
usage: elemctl spaces list [-h]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

## `elemctl projects`

```bash
usage: elemctl projects [-h] действие ...
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `list` | список проектов |
| `get` | карточка проекта |
| `delete` | удалить проект |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl projects list`

```bash
usage: elemctl projects list [-h]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl projects get`

```bash
usage: elemctl projects get [-h] [PROJECT_ID]
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `PROJECT_ID` | ид проекта (по умолчанию ELEMENT_PROJECT_ID) |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl projects delete`

```bash
usage: elemctl projects delete [-h] PROJECT_ID
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `PROJECT_ID` | ид проекта |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

## `elemctl builds`

```bash
usage: elemctl builds [-h] действие ...
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `list` | список сборок проекта |
| `get` | карточка сборки по версии либо ид |
| `upload` | загрузить файл сборки (.xasm/.xlib) |
| `delete` | удалить сборку по версии либо ид |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl builds list`

```bash
usage: elemctl builds list [-h] [--project-id PROJECT_ID]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--project-id PROJECT_ID` | ид проекта (по умолчанию ELEMENT_PROJECT_ID) |

### `elemctl builds get`

```bash
usage: elemctl builds get [-h] [--project-id PROJECT_ID] VERSION
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `VERSION` | версия сборки либо её ид |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--project-id PROJECT_ID` | ид проекта (по умолчанию ELEMENT_PROJECT_ID) |

### `elemctl builds upload`

```bash
usage: elemctl builds upload [-h] [--project-id PROJECT_ID] [--new-project] [--space-id SPACE_ID]
                             [--branch BRANCH] [--commit COMMIT] [--commit-message COMMIT_MESSAGE]
                             FILE
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `FILE` | файл сборки .xasm/.xlib |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--project-id PROJECT_ID` | проект; БЕЗ него платформа заводит новый проект – это единственный способ создать проект через Console API |
| `--new-project` | загрузить сборку новым проектом, игнорируя ELEMENT_PROJECT_ID из окружения и .env-файла |
| `--space-id SPACE_ID` | пространство, в котором завести проект – нужно, когда `--project-id` не задан |
| `--branch BRANCH` | имя git-ветки (метаданные) |
| `--commit COMMIT` | хэш коммита (метаданные) |
| `--commit-message COMMIT_MESSAGE` | сообщение коммита (метаданные) |

### `elemctl builds delete`

```bash
usage: elemctl builds delete [-h] [--project-id PROJECT_ID] VERSION
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `VERSION` | версия сборки либо её ид |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--project-id PROJECT_ID` | ид проекта (по умолчанию ELEMENT_PROJECT_ID) |

## `elemctl build`

```bash
usage: elemctl build [-h] [--project-dir PROJECT_DIR] [--output OUTPUT]
                     [--build-version BUILD_VERSION] [--last-build LAST_BUILD] [--commit COMMIT]
                     [--branch BRANCH] [--kind {application,library}]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--project-dir PROJECT_DIR` | каталог проекта (по умолчанию ищется вглубь от текущего) |
| `--output OUTPUT` | каталог для архива (по умолчанию текущий) |
| `--build-version BUILD_VERSION` | явная версия сборки, например 1.0-42 |
| `--last-build LAST_BUILD` | версия последней сборки проекта – для автоинкремента |
| `--commit COMMIT` | хэш коммита в манифест (по умолчанию из git) |
| `--branch BRANCH` | имя ветки в манифест (по умолчанию из git) |
| `--kind {application,library}` | вид проекта (по умолчанию из Проект.yaml) |

## `elemctl inspect`

```bash
usage: elemctl inspect [-h] FILE
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `FILE` | файл архива сборки |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

## `elemctl deploy`

```bash
usage: elemctl deploy [-h] [--app-id APP_ID] [--project-id PROJECT_ID] [--project-dir PROJECT_DIR]
                      [--output OUTPUT] [--build-version BUILD_VERSION] [--branch BRANCH]
                      [--commit COMMIT] [--commit-message COMMIT_MESSAGE] [--dry-run]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--app-id APP_ID` | ид приложения (по умолчанию ELEMENT_APP_ID) |
| `--project-id PROJECT_ID` | ид проекта (по умолчанию ELEMENT_PROJECT_ID) |
| `--project-dir PROJECT_DIR` | каталог проекта (по умолчанию ищется вглубь от текущего) |
| `--output OUTPUT` | каталог для архива (по умолчанию временный) |
| `--build-version BUILD_VERSION` | явная версия сборки |
| `--branch BRANCH` | имя ветки в метаданные (по умолчанию из git) |
| `--commit COMMIT` | хэш коммита в метаданные (по умолчанию из git) |
| `--commit-message COMMIT_MESSAGE` | сообщение коммита (метаданные загрузки) |
| `--dry-run` | только сборка, без загрузки |

## `elemctl branches`

```bash
usage: elemctl branches [-h] действие ...
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `list` | список веток |
| `get` | карточка ветки |
| `create` | создать ветку |
| `update` | изменить ветку (перепривязать к приложению) |
| `delete` | удалить ветку |
| `merge` | принять изменения ветки |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl branches list`

```bash
usage: elemctl branches list [-h] [--project-id PROJECT_ID] [--name NAME]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--project-id PROJECT_ID` | ид проекта (по умолчанию ELEMENT_PROJECT_ID) |
| `--name NAME` | фильтр по имени ветки |

### `elemctl branches get`

```bash
usage: elemctl branches get [-h] ID
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `ID` | ид ветки |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl branches create`

```bash
usage: elemctl branches create [-h] [--project-id PROJECT_ID] [--app-id APP_ID] NAME
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `NAME` | имя ветки |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--project-id PROJECT_ID` | ид проекта (по умолчанию ELEMENT_PROJECT_ID) |
| `--app-id APP_ID` | сразу привязать к приложению |

### `elemctl branches update`

```bash
usage: elemctl branches update [-h] [--app-id APP_ID] ID
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `ID` | ид ветки |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--app-id APP_ID` | ид приложения (по умолчанию ELEMENT_APP_ID) |

### `elemctl branches delete`

```bash
usage: elemctl branches delete [-h] ID
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `ID` | ид ветки |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl branches merge`

```bash
usage: elemctl branches merge [-h] ID
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `ID` | ид ветки |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

## `elemctl dumps`

```bash
usage: elemctl dumps [-h] действие ...
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `create` | создать дамп |
| `get` | статус дампа |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl dumps create`

```bash
usage: elemctl dumps create [-h] [--description DESCRIPTION] [APP_ID]
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `APP_ID` | ид приложения (по умолчанию ELEMENT_APP_ID) |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--description DESCRIPTION` | описание дампа |

### `elemctl dumps get`

```bash
usage: elemctl dumps get [-h] APP_ID DUMP_ID
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `APP_ID` | ид приложения |
| `DUMP_ID` | ид дампа |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

## `elemctl tasks`

```bash
usage: elemctl tasks [-h] действие ...
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `list` | список задач приложений |
| `get-group` | статус групповой задачи |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl tasks list`

```bash
usage: elemctl tasks list [-h] [--app-id APP_ID]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--app-id APP_ID` | фильтр по приложению (на клиенте) |

### `elemctl tasks get-group`

```bash
usage: elemctl tasks get-group [-h] TASK_ID
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `TASK_ID` | ид групповой задачи |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

## `elemctl tech`

```bash
usage: elemctl tech [-h] действие ...
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `get` | версия технологии приложения |
| `set` | обновить версию технологии (групповая задача) |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl tech get`

```bash
usage: elemctl tech get [-h] [APP_ID]
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `APP_ID` | ид приложения (по умолчанию ELEMENT_APP_ID) |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

### `elemctl tech set`

```bash
usage: elemctl tech set [-h] APP_ID VERSION
```

**Аргументы**

| Параметр | Описание |
|---|---|
| `APP_ID` | ид приложения |
| `VERSION` | версия технологии, на которую перевести приложение |

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

## `elemctl debug-adapter`

```bash
usage: elemctl debug-adapter [-h]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

## `elemctl plugins`

```bash
usage: elemctl plugins [-h]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

## `elemctl self-update`

```bash
usage: elemctl self-update [-h] [--version VERSION]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |
| `--version VERSION` | целевая версия (по умолчанию – последняя с PyPI) |

## `elemctl mcp`

```bash
usage: elemctl mcp [-h]
```

**Параметры**

| Параметр | Описание |
|---|---|
| `-h, --help` | показать эту справку и выйти |

