# Спецификация elemctl

[English](SPEC.md) · **Русский**

Документ описывает контракт Console API v2 платформы 1С:Предприятие.Элемент
(1cmycloud.com), формат файлов сборки и требования к инструменту elemctl.
Спецификация содержит только факты об интерфейсе платформы и требования к
продукту - реализация проектируется с нуля.

## 1. Назначение и состав пакета

Python-пакет `elemctl` из трёх слоёв поверх общего ядра:

1. **Библиотека** - программный клиент Console API v2 и операции высокого
   уровня (сборка, деплой). Только стандартная библиотека Python.
2. **CLI** - консольная команда `elemctl` (entry point `elemctl` в
   `[project.scripts]`).
3. **MCP-сервер** - те же операции как инструменты для AI-агентов; транспорт
   stdio; зависимость `mcp>=1.2` подключается как optional extra
   `elemctl[mcp]` (используется FastMCP из пакета `mcp`).

Требования пакета: имя `elemctl`, версия 0.1.0, Python >= 3.10, лицензия MIT,
автор KeyFire, layout `src/elemctl/`, extra `dev` с pytest. Файлы LICENSE,
README.md, .env.example и .gitignore предоставлены заказчиком и не меняются.

## 2. Конфигурация подключения

Параметры берутся из трёх источников, по убыванию приоритета:

1. явные аргументы (флаги CLI `--base-url`, `--client-id`, `--client-secret`);
2. переменные окружения;
3. .env-файл: путь из флага `--env-file`, а без него - файл `.env` в текущем
   каталоге, если существует.

Переменные окружения:

| Переменная | Смысл | Обязательна |
|---|---|---|
| `ELEMENT_BASE_URL` | базовый URL платформы, например `https://1cmycloud.com` | да |
| `ELEMENT_CLIENT_ID` | Client-Id для получения токена | да |
| `ELEMENT_CLIENT_SECRET` | Client-Secret | да |
| `ELEMENT_APP_ID` | приложение по умолчанию | нет |
| `ELEMENT_PROJECT_ID` | проект по умолчанию | нет |
| `ELEMENT_SPACE_ID` | пространство по умолчанию | нет |

Формат .env: строки `KEY=VALUE`; пустые строки и строки с `#` в начале
пропускаются; допускается префикс `export ` и одинарные/двойные кавычки
вокруг значения; кодировка UTF-8, возможен BOM (читать как `utf-8-sig`).
Хвостовой слэш у `ELEMENT_BASE_URL` обрезается.

## 3. Аутентификация

Получение токена: `POST {base}/console/sys/token`

- заголовок `Authorization: Basic base64(client_id:client_secret)`;
- тело `grant_type=client_credentials`, Content-Type
  `application/x-www-form-urlencoded`.

Ответ - JSON-объект; токен лежит в первом непустом из полей `id_token`,
`token`, `value`, `access_token`. Особый случай: значение `access_token`
может быть строкой `"Not implemented"` - это не токен, поле игнорировать.

Все прочие запросы - с заголовком `Authorization: Bearer {токен}`.

Токен живёт около часа: кешировать его в файле в системном каталоге временных
файлов (`tempfile.gettempdir()`, НЕ жёсткий `/tmp` - инструмент работает и на
Windows) с TTL 1 час; ключ кеша должен различать пары base_url + client_id.
При ответе 401 обновить токен принудительно и повторить запрос один раз.

## 4. Контракт Console API v2

Общий префикс: `{base}/console/api/v2`. Тела запросов и ответов - JSON
(кроме загрузки сборки). Имена полей - в kebab-case.

### 4.1. Приложения

- `GET /applications` - список; необязательный query `name` (фильтр).
- `GET /applications/{id}` - карточка. Значимые поля ответа: `id`, `status`,
  `uri` (адрес работающего приложения), `error` (текст ошибки, если есть),
  `technology-version`, `date-updated`, `display-name`,
  `publication-context`, `source` (объект с информацией об источнике,
  содержит в т.ч. `project-version` - версию применённой сборки).
- `POST /applications` - создать. Тело:
  - `source` - объект `{"type": "repository"}` плюс ровно один из ключей:
    `project-version-id` (id сборки-источника) либо `image-id` (id проекта);
  - `display-name`, `publication-context` - имя и путь публикации;
  - `development-mode` - булево, создавать ли среду разработки;
  - необязательные `space-id`, `technology-version`.
- `DELETE /applications/{id}` - удалить.
- `PUT /applications/{id}/status/start` - запустить.
- `PUT /applications/{id}/status/stop` - остановить.
- `POST /applications/{id}/actions/debug` - данные для сессии отладки
  (`ApplicationDebugInfo`: `{"debug-token": ..., "debug-address": ...}`).
  Тело запроса пустое; требует включённой отладки на сервере
  (`config/debug.yml` `enabled: true`).
- `POST /applications/{id}/project/update` - применить сборку к приложению.
  Тело: `{"source": {"type": "repository", "image-id": "<id сборки>"}}`
  либо `{"source": {"type": "repository", "project-id": "<id>",
  "assembly-version": "<версия>"}}` (assembly-version необязательна).
- `POST /applications/{id}/dumps` - создать дамп. Тело: `include-users`,
  `include-binary-data` (булевы), `description` (строка).
- `GET /applications/{id}/dumps/{dumpId}` - статус дампа.

Статусы приложения: стабильные `Running`, `Stopped`, `Error`; переходные
`Starting`, `Stopping`, `Initializing`, `Updating`, `Frozen`, `Creating`.
Во время переходов поле `status` может быть и пустым.

### 4.2. Версия технологии

- Чтение - из поля `technology-version` карточки приложения (отдельный
  endpoint чтения есть не во всех версиях платформы - не использовать).
- Обновление: `POST /tasks/group-tasks/update-applications-technology`,
  тело `{"technology-version": "<версия>", "applications": ["<app-id>"]}`.
  Возвращает групповую задачу; её статус - `GET /tasks/group-tasks/{taskId}`.

### 4.3. Пространства и проекты

- `GET /spaces` - список пространств.
- `GET /projects` - список проектов; `GET /projects/{id}` - карточка;
  `DELETE /projects/{id}` - удаление.

### 4.4. Сборки проекта (assemblies)

- Загрузка файла сборки - бинарный POST (Content-Type
  `application/octet-stream`, тело - байты файла):
  - `POST /projects/{id}/assemblies` - добавить сборку в существующий проект;
  - `POST /projects` - создать новый проект из сборки.
  Query-параметры (все необязательные): `SpaceId`, `BranchName`, `CommitId`,
  `CommitMessage`. Внимание: имена этих query-параметров - в PascalCase.
  Ответ содержит id созданной сборки в одном из полей: `image-id`,
  `assembly-id` или `id` (проверять в этом порядке).
- `GET /projects/{id}/assemblies` - список сборок. Элемент содержит
  `assembly-version` (строка вида `1.0-42`) и id (`id` либо `image-id`).
  Ответ может быть как массивом, так и объектом со списком в поле `items`
  или `assemblies`.
- `GET /projects/{id}/assemblies/{version}` - карточка сборки по версии;
  `DELETE .../{version}` - удаление.

Сравнение версий сборок: по числовому суффиксу после последнего дефиса
(`1.0-10` новее `1.0-9`; лексикографическое сравнение даёт неверный порядок).

### 4.5. Ветки среды разработки

- `GET /branches` - список; необязательные query `project-id`, `name`.
- `GET /branches/{id}` - карточка. Поля: `name`, `kind`, `project`,
  `application`, `source-branch`, `deletion-mark`, `version-stamp`.
- `POST /branches` - создать. Тело: `name`, `kind: "development"`,
  `project: {"id": "<id>"}`, необязательно `application: {"id": "<id>"}`.
- `PUT /branches/{id}` - изменить. Платформа использует оптимистическую
  блокировку: сначала прочитать карточку, затем отправить тело, собранное из
  текущих значений - `name`, `kind`, `deletion-mark`, `version-stamp`
  (обязательно вернуть как есть), `source-branch` и `application` - свернуть
  до `{"id": ...}` (или `{"name": ...}`, если id нет). Для перепривязки к
  приложению заменить `application` на `{"id": "<новый app-id>"}`.
- Принятие изменений ветки (merge) - тот же `PUT /branches/{id}` с
  дополнительным ключом тела `write-parameters: {"merge": true}`.
- `DELETE /branches/{id}` - удалить ветку.

Инструмент работает ТОЛЬКО с документированным Console API v2. Внутренние
(недокументированные) API консоли платформы не используются и не описываются.

### 4.6. Задачи приложений

`GET /tasks/application-tasks` - список задач всех приложений (серверного
фильтра нет - фильтровать на клиенте). Поля задачи: `id`, `application-id`,
`status` (в т.ч. `Error`, `Failed`), `operation-type`, `error-message`,
`start-date` (ISO 8601, может оканчиваться на `Z`).

## 5. Формат файла сборки (.xasm / .xlib)

Файл сборки - ZIP-архив (deflate):

- в корне `Assembly.yaml` - манифест, плоские пары ключ-значение:

  ```
  ManifestVersion: 1.0
  ProjectKind: Application | Library
  Vendor: <поставщик>
  Name: <имя проекта>
  Version: <версия, например 1.0-42>
  Created: <UTC, формат YYYY.MM.DD HH:MM:SS>
  BranchName: <имя git-ветки>
  CommitId: <хэш коммита>
  ```

  Для библиотеки (`ProjectKind: Library`) в конце добавляется строка
  `Release:` (пустое значение); расширение файла `.xlib`, для приложения -
  `.xasm`.

- далее файлы проекта путями `{vendor}/{name}/...` - относительно корня
  репозитория. Каталог проекта обязан лежать по схеме
  `{repo}/{vendor}/{name}/Проект.yaml`. Разделители путей в архиве - прямые
  слэши (и на Windows).

Имя файла сборки: `{Имя} {Version}.xasm` (через пробел).

Метаданные проекта - из `Проект.yaml` (YAML, достаточно разбора плоских пар
`ключ: значение` верхнего уровня, вложенные строки с отступом пропускать):
`Имя`, `Поставщик`, `Версия` (базовая, например `1.0`), `ВидПроекта`
(значение `Библиотека` означает библиотеку, иначе приложение).

Версия сборки, если не задана явно: `{базовая версия}-{N+1}`, где N - счётчик
из версии последней сборки проекта; если сборок нет - `{базовая версия}-1`.

Git-метаданные (хэш коммита, имя ветки) - из git-репозитория, содержащего
каталог проекта; при недоступности git оставить пустыми.

Отбор файлов в архив:

- включаются только расширения: `.yaml .xbsl .xbql .md .txt .json`
  (исходники), `.png .svg .jpg .jpeg .gif .webp .ico` (изображения),
  `.css .html .js .woff .woff2 .ttf .eot` (веб-ресурсы);
- исключаются каталоги `.git`, `.claude`, `.github`, `__pycache__`,
  `node_modules`, `.venv` и все скрытые (начинающиеся с точки);
- исключаются файлы `.gitignore`, `.env`, `.DS_Store` и файлы `*.xasm`,
  `*.xlib`.

## 6. Поведенческие особенности платформы (обязательны к учёту)

1. **Тихий откат применения.** Если применение сборки к приложению падает
   (например, ошибка компиляции), платформа молча откатывает приложение на
   предыдущую сборку и запускает его - статус `Running` НЕ означает успех.
   Достоверная проверка результата деплоя:
   - задачи приложения (п. 4.6) со статусом `Error`/`Failed`, у которых
     `start-date` не раньше момента начала деплоя (старые ошибки из истории
     не учитывать!);
   - сверка фактически применённой версии (`source.project-version` карточки
     приложения) с версией загруженной сборки;
   - информационно - контрольный GET по `uri` приложения (коды 401/403
     нормальны для закрытых приложений и успеху не противоречат).
2. **Пустой каркас при создании.** Создание приложения с источником "проект"
   (`image-id` = id проекта) на части конфигураций платформы даёт пустое
   приложение без данных проекта. Надёжный источник - конкретная сборка
   (`project-version-id`), например последняя сборка проекта.
3. **Удаление с черновиками.** Если в среде разработки приложения есть
   неопубликованные правки, `DELETE /applications/{id}` возвращает 400 с
   `FAILED_PRECONDITION` в теле. Принудительного удаления в API нет - только
   панель управления; инструмент обязан дать понятную подсказку.
4. **Готовность нового приложения.** После создания приложение какое-то время
   в переходных статусах и без `uri` - предусмотреть ожидание готовности
   (появился `uri` и стабильный статус). Статус `Error` при ожидании -
   немедленная ошибка.
5. **Перезапуск после применения.** `project/update` может сам перезапустить
   приложение. После вызова дождаться выхода из переходных статусов; если
   итог не `Running` - остановить (если не `Stopped`), дождаться `Stopped`,
   запустить, дождаться `Running`. Разумные таймауты: ожидание остановки
   ~3 мин, запуска/стабилизации ~5 мин, опрос каждые ~10 с.
6. **Windows.** Временные файлы и кеши - только через `tempfile`; вывод
   консоли перевести в UTF-8 (`reconfigure` для stdout/stderr), иначе
   кириллица ломается.

## 7. Требования к CLI

Общие флаги (до подкоманды): `--base-url`, `--client-id`, `--client-secret`,
`--env-file`, `--timeout` (сек, по умолчанию 60), `--version`.

Вывод: результат - JSON в stdout (`ensure_ascii=False`, отступ 2); прогресс
длительных операций - строки в stderr; ошибки - JSON с полем `error` в
stderr и код возврата 1.

Команды (в скобках - существенные флаги):

- `token` - получить и напечатать токен.
- `apps list [--name]`, `apps get [APP_ID]`, `apps find NAME [--include-deleted]`,
  `apps create NAME [--project-id --version-id --latest-build --space-id
  --tech-version --no-dev-mode --wait]`,
  `apps ensure NAME [--project-id --version-id --latest-build --space-id
  --tech-version --no-dev-mode --wait]`, `apps delete APP_ID`,
  `apps start [APP_ID]`, `apps stop [APP_ID]`.
  - `apps find` ищет по точному совпадению (без учёта регистра) имени среди
    полей `name`, `display-name`, `publication-context`; вывод
    `{"id": ..., "found": true|false}`, код возврата 0 в обоих случаях –
    отсутствие приложения это ответ, а не ошибка. Ненулевой код возврата
    означает сбой запроса и сопровождается JSON'ом с полем `error` в stderr.
    В скриптах проверять поле `found`, а не код возврата.
  - Удалённые приложения остаются в списке платформы со статусом `Deleted` и
    прежним `id`. `apps find` их ПРОПУСКАЕТ: найденный id обязан быть пригоден
    для работы, иначе вызывающий получает id, на котором `apps get` и `deploy`
    отвечают 404. Флаг `--include-deleted` возвращает прежнее поведение – поиск
    среди всех приложений, включая удалённые.
  - `apps ensure` идемпотентно приводит приложение с данным именем в
    существование: ищет по правилам `apps find` (удалённые не в счёт) и создаёт
    только при отсутствии. Вывод `{"id": ..., "created": true|false}`;
    `created: false` означает, что приложение уже было и НЕ трогалось. Флаги
    создания те же, что у `apps create`, и действуют, только когда создание
    происходит. Существующее приложение никогда не пересоздаётся: `delete` +
    `create` дают новый URL и рвут внешние привязки к прежнему.
  - `--latest-build` - взять источником последнюю сборку проекта (защита от
    пустого каркаса, п. 6.2); `--wait` - дождаться готовности (п. 6.4) и
    вывести финальную карточку.
- `spaces list`.
- `projects list`, `projects get [PROJECT_ID]`, `projects delete PROJECT_ID`.
- `builds list [--project-id]`, `builds get VERSION [--project-id]`,
  `builds upload FILE [--project-id --space-id --branch --commit
  --commit-message]`, `builds delete VERSION [--project-id]`.
- `build [--project-dir --output --build-version --last-build --commit
  --branch --kind {application,library}]` - локально собрать архив, вывести
  `{"file": путь}`. Без `--project-dir` каталог проекта ищется автоматически
  (первый каталог с `Проект.yaml` вглубь от текущего). `--kind` по умолчанию
  определяется по `ВидПроекта`.
- `deploy [--app-id --project-id --project-dir --output --build-version
  --branch --commit --commit-message --dry-run]` -
  полный цикл: сборка -> загрузка -> применение -> перезапуск -> проверка
  фактического применения (п. 6.1). Вывод - JSON-отчёт с полями: `app-id`,
  `uri`, `status`, `version`, `assembly-id`, `applied-version`, `applied`
  (true/false/null - null когда фактическую версию определить не удалось),
  `uri-status`, `problems` (список строк), `ok` (булево). Код возврата 0
  только при `ok`. `--dry-run` - только сборка.
- `branches list [--project-id --name]`, `branches get ID`,
  `branches create NAME [--project-id --app-id]`,
  `branches update ID [--app-id]`, `branches delete ID`,
  `branches merge ID`.
- `dumps create [APP_ID] [--description]`, `dumps get APP_ID DUMP_ID`.
- `tasks list [--app-id]`, `tasks get-group TASK_ID`.
- `tech get [APP_ID]`, `tech set APP_ID VERSION`.
- `debug-adapter` - путь к каталогу debug-адаптера платформы, принесённому
  плагином (группа точек расширения `elemctl.debug_adapter`, п. 10). Вывод
  `{"path": ..., "found": true, "adapter-class": ...}` при наличии либо
  `{"path": null, "found": false}`; код возврата 0 в обоих случаях. Значение
  `path` - готовое значение настройки `xbslDebug.adapterPath` для расширения
  VS Code (каталог с подкаталогом `repo/`).
- `plugins` - диагностика плагинов: объявленные каталоги адаптера и признак
  наличия jar (`{"debug-adapter": [{"path": ..., "has-jars": true|false}]}`).
- `self-update [--version X]` - обновить установленный elemctl распаковкой колеса с PyPI в
  site-packages, не трогая занятые exe (штатный pipx/pip ломает установку, когда `elemctl.exe`
  держит работающий MCP-сервер; обновляются только файлы пакета, стаб exe вызовет новый код).
  Правит `pipx_metadata.json`. Вывод `{updated, from, to}`.
- `mcp` - запустить MCP-сервер; без установленного extra - понятная ошибка
  с подсказкой `pip install "elemctl[mcp]"`.

Позиционные APP_ID/PROJECT_ID, помеченные выше как необязательные, при
отсутствии берутся из конфигурации (`ELEMENT_APP_ID`/`ELEMENT_PROJECT_ID`);
если и там пусто - ошибка.

## 8. Требования к MCP-серверу

Имя сервера `elemctl`, транспорт stdio, реквизиты - из тех же переменных
окружения/.env. В instructions сервера предупредить о тихом откате применения
(п. 6.1). Инструменты (докстринги - краткие, по-русски):

`list_apps(name="")`, `get_app(app_id)`, `find_app(name)`,
`create_app(name, project_id="", version_id="", space_id="",
development_mode=True)` - при задании только project_id источником
автоматически берётся последняя сборка проекта (п. 6.2);
`start_app(app_id)`, `stop_app(app_id)`, `debug_info(app_id)` - данные для
сессии отладки (требует включённой отладки на сервере), `debug_adapter()` -
путь к debug-адаптеру платформы из плагина (п. 10; локальная операция, к
платформе не обращается), `delete_app(app_id)`
(в докстринге - предупреждение о необратимости и смене URL), `list_spaces()`,
`list_projects()`, `list_builds(project_id)`,
`build_assembly(project_dir="", output_dir="", version="")`,
`deploy(app_id, project_id, project_dir="", version="", branch="",
commit_message="")` - возвращает отчёт деплоя плюс поле `log` со строками
прогресса; `apply_build(app_id, version_id)`, `verify_deploy(app_id,
expected_version="", since_minutes=30)` - проверка применения по п. 6.1;
`list_app_tasks(app_id="")`, `list_branches(project_id="", name="")`,
`merge_branch(branch_id)`.

## 9. Требования к качеству

- Тесты pytest без обращений к сети: разбор .env и приоритеты конфигурации,
  отбор файлов и содержимое архива сборки (включая манифест), автоинкремент
  и числовое сравнение версий, логика итога деплоя (`ok`/`applied`),
  подсказка при `FAILED_PRECONDITION`, поиск приложения по имени, обнаружение
  плагинов через точки расширения и разрешение пути к debug-адаптеру
  (стаб-точки расширения, каталоги во временных папках), извлечение адаптера
  из мини-.car, обновление распаковкой колеса (urllib замокан, колесо и
  site-packages во временных папках).
- Докстринги и комментарии - литературный русский; кавычки в тексте прямые
  `"`, тире - среднее `–` (не длинное), многоточие - три точки `...`.
- Библиотека не печатает в stdout/stderr сама - прогресс отдаётся через
  передаваемый вызывающей стороной callback.
- Ошибки API - собственное исключение с деталями ответа сервера
  (сериализуемыми в JSON).

## 10. Плагины (точки расширения)

elemctl обнаруживает внешние пакеты через `importlib.metadata.entry_points`. Ядро
в собственном `pyproject.toml` о плагинах ничего не объявляет - оно потребитель:
читает точки расширения при обращении. Так непубликуемые вендорские артефакты
(проприетарные jar 1С) остаются в отдельном пакете, а публичное ядро - чистым.

Группа **`elemctl.debug_adapter`**. Значение точки расширения - путь (Path/str)
либо функция без аргументов, возвращающая путь (`() -> Path | str`). Путь
указывает на каталог debug-адаптера платформы: каталог, содержащий подкаталог
`repo/` с jar-файлами адаптера (в т.ч. `com.e1c.g5rt.debugger.adapter*.jar`).
Это готовое значение настройки `xbslDebug.adapterPath` расширения VS Code.

Объявление в пакете-плагине:

```toml
[project.entry-points."elemctl.debug_adapter"]
имя = "мой_пакет:adapter_root"
```

Поведение обнаружения:

- точки сортируются по имени; `debug_adapter_path()` возвращает первый каталог,
  в котором действительно есть jar адаптера (каталог без `repo/` или без jar
  адаптера пропускается), иначе `None`;
- сбой загрузки точки расширения - ошибка (`PluginError`, наследник
  `ElemctlError`), а не тихий пропуск: инструмент, молча потерявший плагин,
  оставил бы пользователя без отладки и без объяснения причины;
- переменная окружения `ELEMCTL_NO_PLUGINS=1` отключает обнаружение (прогон
  только со штатными возможностями ядра).

Поверхности, использующие механизм: CLI `debug-adapter`/`plugins` (п. 7),
MCP-инструмент `debug_adapter` (п. 8), а также расширение VS Code, которое при
пустой настройке `adapterPath` запрашивает путь у `elemctl debug-adapter`.

Сам адаптер извлекается из дистрибутива платформы скриптом `tools/extract_adapter.py`
(чистый код, в дистрибутив пакета не входит – `prune`): каталог
`data/ide/theia/plugins/@1c-appengine-plugin/bin/debugger/` из `.car` копируется в
`<output>/<версия>/`, обновляется `index.json`. Проприетарные jar в публичный пакет не
включаются – их несёт отдельный пакет-плагин.
