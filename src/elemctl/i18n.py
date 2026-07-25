"""Language of elemctl runtime output: message catalog and lookup.

elemctl is small and has no rule modules, so every user-facing runtime string – error
texts and progress lines – lives right here in MESSAGES and is registered on import:

    MESSAGES = {
        "deploy.verify-failed": {
            "ru": "проверка НЕ пройдена",
            "en": "verification FAILED",
        },
    }
    register(MESSAGES)

A key is `<module>.<name>`. Placeholders are `str.format` fields and must be the same in
every language – `tests/test_i18n.py` enforces that. A brace that is part of the text –
`() [] {{}}` – has to be doubled, because every template is formatted.

The language is chosen by: set_lang() (CLI --lang) > env ELEMCTL_LANG > system locale > ru.
An unknown key is returned as is, so a caller that passes a literal string rather than a key
keeps working.

Scope: runtime output AND the argparse --help text are translated. Help strings are routed
through t() as well, so the parser has to be built after the language is resolved – cli.main
reads --lang out of argv with lang_from_argv() before build_parser(), because argparse itself
learns --lang only when it parses, which is too late to pick the help language. Docstrings and
code comments are source text rather than runtime output and stay outside this scope.
"""

from __future__ import annotations

import argparse as _argparse
import locale as _locale
import os

LANGS = ("ru", "en")
DEFAULT_LANG = "ru"
ENV_LANG = "ELEMCTL_LANG"

_catalog: dict[str, dict[str, str]] = {}
_selected: str | None = None

# Every user-facing runtime string of elemctl. Keys are grouped by the module that emits them.
MESSAGES = {
    # -- build.py -----------------------------------------------------------------
    "build.project-dir-not-found": {
        "ru": "каталог проекта не найден: нет {file} внутри {base}",
        "en": "project directory not found: no {file} in {base}",
    },
    "build.not-found": {
        "ru": "не найден {file}",
        "en": "not found: {file}",
    },
    "build.unknown-kind": {
        "ru": "неизвестный вид проекта: {kind} (ожидалось application или library)",
        "en": "unknown project kind: {kind} (expected application or library)",
    },
    "build.not-archive": {
        "ru": "файл не является архивом сборки: {file}",
        "en": "the file is not a build archive: {file}",
    },
    "build.no-manifest": {
        "ru": "в архиве {file} нет манифеста {manifest}",
        "en": "archive {file} has no manifest {manifest}",
    },
    "build.no-project-file": {
        "ru": "в архиве {file} нет файла проекта {entry}",
        "en": "archive {file} has no project file {entry}",
    },
    "build.name-vendor-required": {
        "ru": 'в {file} должны быть заполнены поля "Имя"/"Name" и "Поставщик"/"Vendor"',
        "en": '{file} must have the "Имя"/"Name" and "Поставщик"/"Vendor" fields filled in',
    },
    "build.layout-mismatch": {
        "ru": "каталог проекта обязан лежать по схеме {{репозиторий}}/{{поставщик}}/{{имя}}/"
              "{file}: ожидался путь .../{vendor}/{name}, фактический – {actual}",
        "en": "the project directory must follow the {{repo}}/{{vendor}}/{{name}}/{file} "
              "layout: expected .../{vendor}/{name}, actual – {actual}",
    },
    # -- cli.py -------------------------------------------------------------------
    "cli.not-set": {
        "ru": "не задан {what}",
        "en": "{what} is not set",
    },
    "cli.require.app-id-arg": {
        "ru": "app-id (аргумент APP_ID или ELEMENT_APP_ID)",
        "en": "app-id (APP_ID argument or ELEMENT_APP_ID)",
    },
    "cli.require.app-id-flag": {
        "ru": "--app-id (или ELEMENT_APP_ID)",
        "en": "--app-id (or ELEMENT_APP_ID)",
    },
    "cli.require.project-id-arg": {
        "ru": "project-id (аргумент PROJECT_ID или ELEMENT_PROJECT_ID)",
        "en": "project-id (PROJECT_ID argument or ELEMENT_PROJECT_ID)",
    },
    "cli.require.project-id-flag": {
        "ru": "--project-id (или ELEMENT_PROJECT_ID)",
        "en": "--project-id (or ELEMENT_PROJECT_ID)",
    },
    "cli.user-list-source-conflict": {
        "ru": "список задан дважды: аргументом LIST и флагом --app – оставьте что-то одно",
        "en": "the list is given twice: as the LIST argument and as --app – keep one of them",
    },
    "cli.user-list-required": {
        "ru": "не задан список пользователей: аргумент LIST либо флаг --app",
        "en": "no user list given: the LIST argument or the --app flag",
    },
    "cli.enable-disable-conflict": {
        "ru": "флаги --enable и --disable несовместимы",
        "en": "--enable and --disable are mutually exclusive",
    },
    "cli.latest-build-needs-project": {
        "ru": "для --latest-build нужен --project-id (или ELEMENT_PROJECT_ID)",
        "en": "--latest-build requires --project-id (or ELEMENT_PROJECT_ID)",
    },
    "cli.upload-new-project-conflict": {
        "ru": "флаги --new-project и --project-id несовместимы: либо новый проект, "
              "либо конкретный",
        "en": "--new-project and --project-id are mutually exclusive: either a new "
              "project or a specific one",
    },
    "cli.upload-target-from-env": {
        "ru": "цель загрузки – проект {project_id} из ELEMENT_PROJECT_ID (окружение "
              "или .env-файл); загрузить новым проектом – флаг --new-project",
        "en": "upload target is project {project_id} from ELEMENT_PROJECT_ID (the "
              "environment or the .env file); pass --new-project to upload as a new project",
    },
    "cli.upload-name-mismatch": {
        "ru": "внимание: имя сборки '{assembly}' не совпадает с именем проекта-цели "
              "'{project}' ({project_id}) – после загрузки панель покажет проект "
              "под именем сборки",
        "en": "warning: the assembly name '{assembly}' differs from the target project "
              "name '{project}' ({project_id}) – after the upload the console shows "
              "the project under the assembly name",
    },
    "cli.app-source-required": {
        "ru": "нужен источник приложения: --version-id либо --project-id [--latest-build]. "
              "Приложение всегда создаётся из сборки: пустого приложения в Console API нет. "
              "Если проекта ещё нет, заведите его загрузкой сборки БЕЗ --project-id "
              "(builds upload <файл>.xasm --space-id <id>) - в ответе придёт assembly-id, "
              "его и передайте в --version-id",
        "en": "an application source is required: --version-id or --project-id [--latest-build]. "
              "An application is always created from an assembly: Console API has no empty one. "
              "If the project does not exist yet, create it by uploading an assembly WITHOUT "
              "--project-id (builds upload <file>.xasm --space-id <id>) - the response carries "
              "the assembly-id to pass as --version-id",
    },
    "cli.build-file-not-found": {
        "ru": "файл сборки не найден: {path}",
        "en": "build file not found: {path}",
    },
    "cli.project-has-no-builds": {
        "ru": "у проекта {project_id} нет сборок – загрузите сборку (builds upload) "
              "или укажите --version-id",
        "en": "project {project_id} has no builds – upload one (builds upload) or "
              "pass --version-id",
    },
    "cli.whole-project-source-warning": {
        "ru": "внимание: источник – проект целиком; на части конфигураций платформы "
              "это даёт пустой каркас (надёжнее --latest-build)",
        "en": "warning: the source is the whole project; on some platform configurations "
              "this yields an empty skeleton (--latest-build is safer)",
    },
    "cli.mcp-extra-required": {
        "ru": 'MCP-зависимость не установлена – выполните: pip install "elemctl[mcp]"',
        "en": 'the MCP dependency is not installed – run: pip install "elemctl[mcp]"',
    },
    "cli.require-clean-no-git": {
        "ru": "--require-clean: git недоступен или {dir} не в репозитории – "
              "подтвердить чистоту дерева нечем",
        "en": "--require-clean: git is unavailable or {dir} is not inside a repository – "
              "there is nothing to confirm a clean tree with",
    },
    "cli.require-clean-dirty": {
        "ru": "--require-clean: в {dir} есть незакоммиченные изменения ({count}) – "
              "операция отменена",
        "en": "--require-clean: {dir} has uncommitted changes ({count}) – "
              "the operation is cancelled",
    },
    # -- client.py ----------------------------------------------------------------
    "client.assembly-not-found": {
        "ru": "сборка '{version}' не найдена в проекте {project} (ни по версии, ни по ид)",
        "en": "assembly '{version}' not found in project {project} (neither by version nor by id)",
    },
    "client.app-source-exclusive": {
        "ru": "источник приложения – ровно один из параметров: project_version_id "
              "либо image_id",
        "en": "the application source is exactly one of the parameters: "
              "project_version_id or image_id",
    },
    "client.app-not-found": {
        "ru": "приложение '{name}' не найдено (ни по ид, ни по точному имени)",
        "en": "application '{name}' not found (neither by id nor by exact name)",
    },
    "client.app-name-ambiguous": {
        "ru": "имя приложения '{name}' неоднозначно, совпадений несколько: {ids} – "
              "укажите ид (UUID)",
        "en": "the application name '{name}' is ambiguous, there are several matches: "
              "{ids} – pass the id (UUID)",
    },
    "client.app-error-status": {
        "ru": "приложение {app} в статусе Error: {error}",
        "en": "application {app} is in status Error: {error}",
    },
    "client.wait-status-timeout": {
        "ru": "не дождались статуса {expected} приложения {app} за {timeout} с "
              "(текущий: {status})",
        "en": "did not reach status {expected} of application {app} within {timeout} s "
              "(current: {status})",
    },
    "client.wait-ready-timeout": {
        "ru": "приложение {app} не стало готовым за {timeout} с (статус: {status}, uri: {uri})",
        "en": "application {app} did not become ready within {timeout} s "
              "(status: {status}, uri: {uri})",
    },
    "client.transitional-status": {
        "ru": "переходный",
        "en": "transitional",
    },
    "client.no-uri": {
        "ru": "нет",
        "en": "none",
    },
    "client.apply-source-required": {
        "ru": "нужен источник применения: image_id либо project_id",
        "en": "an apply source is required: image_id or project_id",
    },
    "client.api-error": {
        "ru": "Console API ответил {status} на {method} {url}",
        "en": "Console API responded {status} to {method} {url}",
    },
    "client.delete-failed-precondition": {
        "ru": "в среде разработки приложения есть неопубликованные правки – "
              "платформа не удаляет такие приложения через API; опубликуйте "
              "или отмените правки, либо удалите приложение через панель управления",
        "en": "the application's development environment has unpublished changes – "
              "the platform does not delete such applications via the API; publish "
              "or discard the changes, or delete the application through the control panel",
    },
    "client.app-created-with-error": {
        "ru": "приложение {app} создано со статусом Error: {error}",
        "en": "application {app} was created with status Error: {error}",
    },
    "client.no-error-text": {
        "ru": "без текста ошибки",
        "en": "no error text",
    },
    "client.waiting-status": {
        "ru": "статус приложения: {status} – ждём...",
        "en": "application status: {status} – waiting...",
    },
    "client.transitional": {
        "ru": "(переходный)",
        "en": "(transitional)",
    },
    "client.waiting-ready": {
        "ru": "ждём готовности приложения: статус {status}...",
        "en": "waiting for the application to be ready: status {status}...",
    },
    "client.user-list-not-found": {
        "ru": "список пользователей '{name}' не найден",
        "en": "the user list '{name}' was not found",
    },
    "client.user-list-ambiguous": {
        "ru": "под представление '{name}' подходит несколько списков пользователей: {ids} – "
              "укажите ид",
        "en": "several user lists match the presentation '{name}': {ids} – give the id",
    },
    "client.app-has-no-user-list": {
        "ru": "у приложения {app} нет собственного списка пользователей (default-user-list пуст)",
        "en": "the application {app} has no user list of its own (default-user-list is empty)",
    },
    "client.account-service-id-required": {
        "ru": "у сервиса учётных записей не задан account-service-id",
        "en": "the account service has no account-service-id",
    },
    "client.waiting-deleted": {
        "ru": "ждём удаления приложения: статус {status}...",
        "en": "waiting for the application to be deleted: status {status}...",
    },
    "client.stopping": {
        "ru": "статус {status} – останавливаем приложение...",
        "en": "status {status} – stopping the application...",
    },
    "client.starting": {
        "ru": "запускаем приложение...",
        "en": "starting the application...",
    },
    # -- config.py ----------------------------------------------------------------
    "config.unknown-params": {
        "ru": "неизвестные параметры конфигурации: {unknown}",
        "en": "unknown configuration parameters: {unknown}",
    },
    "config.env-file-not-found": {
        "ru": ".env-файл не найден: {path}",
        "en": ".env file not found: {path}",
    },
    "config.connection-not-set": {
        "ru": "не заданы параметры подключения: {missing} (переменные окружения, "
              ".env-файл или флаги CLI)",
        "en": "connection parameters are not set: {missing} (environment variables, "
              "the .env file or CLI flags)",
    },
    # -- mcp_server.py ------------------------------------------------------------
    "mcp.project-or-version-required": {
        "ru": "нужен project_id или version_id",
        "en": "project_id or version_id is required",
    },
    "mcp.project-has-no-builds": {
        "ru": "у проекта {project_id} нет сборок – загрузите сборку или укажите version_id",
        "en": "project {project_id} has no builds – upload one or pass version_id",
    },
    "mcp.extra-required": {
        "ru": 'для MCP-сервера нужен extra: pip install "elemctl[mcp]"',
        "en": 'the MCP server needs the extra: pip install "elemctl[mcp]"',
    },
    # -- plugins.py ---------------------------------------------------------------
    "plugins.entry-point-failed": {
        "ru": "точка расширения '{name}' группы {group} не загрузилась ({value}): {error}",
        "en": "the entry point '{name}' of the group {group} failed to load ({value}): {error}",
    },
    "plugins.not-commands": {
        "ru": "точка расширения '{name}' обязана дать Command, их список или функцию без "
              "аргументов, возвращающую одно из этого; получено: {value}",
        "en": "the entry point '{name}' must give a Command, a list of them or a function "
              "without arguments returning either; got: {value}",
    },
    "plugins.command-name-required": {
        "ru": "у команды плагина '{where}' пустое имя",
        "en": "a command of the plugin '{where}' has an empty name",
    },
    "plugins.command-handler-required": {
        "ru": "у команды '{name}' плагина '{where}' обработчик не вызываемый",
        "en": "the handler of the command '{name}' of the plugin '{where}' is not callable",
    },
    "plugins.not-an-argument": {
        "ru": "у команды '{name}' плагина '{where}' аргумент объявлен не типом Argument: {value}",
        "en": "the command '{name}' of the plugin '{where}' declares an argument that is not "
              "an Argument: {value}",
    },
    "plugins.argument-type-unsupported": {
        "ru": "аргумент {argument} команды '{name}' плагина '{where}' объявлен типом {type}; "
              "поддерживаются: {supported}",
        "en": "the argument {argument} of the command '{name}' of the plugin '{where}' is "
              "declared as {type}; supported are: {supported}",
    },
    "plugins.flag-must-be-option": {
        "ru": "аргумент {argument} команды '{name}' плагина '{where}' булев, а такой аргумент "
              "может быть только опцией (имя с дефисами впереди)",
        "en": "the argument {argument} of the command '{name}' of the plugin '{where}' is "
              "boolean, and such an argument can only be an option (a name starting with dashes)",
    },
    "plugins.argument-duplicate": {
        "ru": "у команды '{name}' плагина '{where}' два аргумента дают одно имя значения: {argument}",
        "en": "two arguments of the command '{name}' of the plugin '{where}' give the same "
              "value name: {argument}",
    },
    "plugins.command-name-taken": {
        "ru": "плагин '{where}' приносит команду '{name}', но такая команда у elemctl уже есть – "
              "плагин обязан выбрать другое имя",
        "en": "the plugin '{where}' brings the command '{name}', but elemctl already has one – "
              "the plugin has to pick another name",
    },
    "plugins.tool-name-taken": {
        "ru": "плагин '{where}' приносит инструмент MCP '{name}', но такой у elemctl уже есть – "
              "поможет mcp_name у команды",
        "en": "the plugin '{where}' brings the MCP tool '{name}', but elemctl already has one – "
              "the mcp_name of the command helps here",
    },
    "plugins.no-client": {
        "ru": "команде плагина не с чем обратиться к платформе: клиент не передан",
        "en": "a command of a plugin has nothing to reach the platform with: no client was given",
    },
    # -- selfupdate.py ------------------------------------------------------------
    "selfupdate.version-not-found": {
        "ru": "версия не найдена на PyPI",
        "en": "the version was not found on PyPI",
    },
    "selfupdate.pypi-http-error": {
        "ru": "PyPI ответил {status}",
        "en": "PyPI responded {status}",
    },
    "selfupdate.pypi-unreachable": {
        "ru": "не удалось обратиться к PyPI: {error}",
        "en": "could not reach PyPI: {error}",
    },
    "selfupdate.no-wheel": {
        "ru": "на PyPI нет wheel для elemctl {version}",
        "en": "PyPI has no wheel for elemctl {version}",
    },
    "selfupdate.already-current": {
        "ru": "уже актуально: elemctl {version}",
        "en": "already current: elemctl {version}",
    },
    "selfupdate.downloading": {
        "ru": "скачиваю elemctl {version} с PyPI...",
        "en": "downloading elemctl {version} from PyPI...",
    },
    "selfupdate.download-failed": {
        "ru": "не удалось скачать колесо: {error}",
        "en": "could not download the wheel: {error}",
    },
    "selfupdate.download-failed": {
        "ru": "не удалось скачать колесо: {error}",
        "en": "could not download the wheel: {error}",
    },
    "selfupdate.unpacking": {
        "ru": "распаковываю в {path}...",
        "en": "unpacking into {path}...",
    },
    "selfupdate.done": {
        "ru": "готово: elemctl {before} -> {after}. Перезапустите MCP-сессии (elemctl mcp).",
        "en": "done: elemctl {before} -> {after}. Restart the MCP sessions (elemctl mcp).",
    },
    "selfupdate.metadata-updated": {
        "ru": "обновлён pipx_metadata.json",
        "en": "pipx_metadata.json updated",
    },
    # -- transport.py -------------------------------------------------------------
    "transport.network-error": {
        "ru": "сетевая ошибка {method} {url}: {error}",
        "en": "network error {method} {url}: {error}",
    },
    # -- auth.py ------------------------------------------------------------------
    "auth.token-http-error": {
        "ru": "не удалось получить токен: HTTP {status}",
        "en": "failed to obtain a token: HTTP {status}",
    },
    "auth.token-not-found": {
        "ru": "токен не найден в ответе сервера (ожидались поля id_token, token, "
              "value или access_token)",
        "en": "no token in the server response (the id_token, token, value or "
              "access_token fields were expected)",
    },
    # -- deploy.py ----------------------------------------------------------------
    "deploy.built": {
        "ru": "собран архив {file} (версия {version})",
        "en": "built archive {file} (version {version})",
    },
    "deploy.dirty-tree": {
        "ru": "внимание: в каталоге проекта незакоммиченные изменения ({count}): {files} – "
              "в архив снято текущее состояние диска, а не HEAD",
        "en": "warning: the project directory has uncommitted changes ({count}): {files} – "
              "the archive captured the current disk state, not HEAD",
    },
    "deploy.and-more": {
        "ru": " и ещё {count}",
        "en": " and {count} more",
    },
    "deploy.uploaded": {
        "ru": "сборка загружена (id: {id})",
        "en": "build uploaded (id: {id})",
    },
    "deploy.unknown": {
        "ru": "не определён",
        "en": "unknown",
    },
    "deploy.apply-started": {
        "ru": "применение запущено, ждём стабилизации приложения...",
        "en": "apply started, waiting for the application to stabilize...",
    },
    "deploy.running-verifying": {
        "ru": "приложение в статусе Running, проверяем фактическое применение...",
        "en": "application is Running, verifying the actual apply...",
    },
    "deploy.no-error-text": {
        "ru": "без текста ошибки",
        "en": "no error text",
    },
    "deploy.task": {
        "ru": "задача",
        "en": "task",
    },
    "deploy.task-failed": {
        "ru": "задача {label} завершилась со статусом {status}: {message}",
        "en": "task {label} finished with status {status}: {message}",
    },
    "deploy.assembly-mismatch": {
        "ru": "применённая сборка {applied} не совпадает с загруженной {expected} – "
              "похоже, платформа откатила применение",
        "en": "the applied build {applied} does not match the uploaded one {expected} – "
              "the platform seems to have rolled the apply back",
    },
    "deploy.version-mismatch": {
        "ru": "применённая версия {applied} не совпадает с загруженной {expected} – "
              "похоже, платформа откатила применение",
        "en": "the applied version {applied} does not match the uploaded one {expected} – "
              "the platform seems to have rolled the apply back",
    },
    "deploy.verify-passed": {
        "ru": "проверка пройдена: сборка применена",
        "en": "verification passed: the build is applied",
    },
    "deploy.problem": {
        "ru": "проблема: {problem}",
        "en": "problem: {problem}",
    },
    "deploy.verify-failed": {
        "ru": "проверка НЕ пройдена",
        "en": "verification FAILED",
    },
    # -- probe.py -----------------------------------------------------------------
    "probe.built": {
        "ru": "собран архив {file} (версия {version})",
        "en": "built archive {file} (version {version})",
    },
    "probe.uploaded": {
        "ru": "сборка загружена (id: {assembly}, проект: {project})",
        "en": "build uploaded (id: {assembly}, project: {project})",
    },
    "probe.unknown": {
        "ru": "не определён",
        "en": "unknown",
    },
    "probe.creating": {
        "ru": "создаём одноразовое приложение {name} – это и есть компиляция...",
        "en": "creating the throwaway application {name} – that is the compilation...",
    },
    "probe.compiled": {
        "ru": "компиляция пройдена",
        "en": "compilation passed",
    },
    "probe.failed": {
        "ru": "компиляция НЕ пройдена, сообщений: {count}",
        "en": "compilation FAILED, messages: {count}",
    },
    "probe.no-assembly-id": {
        "ru": "платформа не вернула ид сборки в ответе на загрузку – компилировать нечего",
        "en": "the platform returned no build id in the upload response – nothing to compile",
    },
    "probe.no-app-id": {
        "ru": "платформа не вернула ид приложения в ответе на создание",
        "en": "the platform returned no application id in the create response",
    },
    "probe.kept": {
        "ru": "уборка отключена (--keep): приложение {app}, сборка {version} остались на стенде",
        "en": "cleanup is off (--keep): the application {app} and the build {version} are left in place",
    },
    "probe.app-still-there": {
        "ru": "приложение {app} не исчезло за отведённое время – сборку и проект оставили",
        "en": "the application {app} has not disappeared in time – the build and the project are left",
    },
    "probe.assembly-kept": {
        "ru": "сборка {version} осталась в проекте {project}: пока живо приложение из неё, "
              "платформа удалить её не даёт",
        "en": "the build {version} is left in project {project}: the platform refuses to delete it "
              "while an application created from it is alive",
    },
    "probe.cleanup-problem": {
        "ru": "уборка: {problem}",
        "en": "cleanup: {problem}",
    },
    # -- help: argparse help texts (cli.py) ---------------------------------------
    # CLI help strings. Key: cli.help.<command> or cli.help.<command>-<flag>.
    # Metavars that already read as English (NAME/APP_ID/FILE) are left untranslated.
    "cli.help.description": {
        "ru": "Управление приложениями платформы 1С:Предприятие.Элемент (Console API v2)",
        "en": "Manage 1C:Enterprise.Element platform applications (Console API v2)",
    },
    "cli.help.base-url": {
        "ru": "базовый URL платформы (ELEMENT_BASE_URL)",
        "en": "platform base URL (ELEMENT_BASE_URL)",
    },
    "cli.help.client-id": {
        "ru": "Client-Id для получения токена (ELEMENT_CLIENT_ID)",
        "en": "Client-Id for obtaining a token (ELEMENT_CLIENT_ID)",
    },
    "cli.help.client-secret": {
        "ru": "Client-Secret к этому Client-Id (ELEMENT_CLIENT_SECRET)",
        "en": "the Client-Secret for that Client-Id (ELEMENT_CLIENT_SECRET)",
    },
    # argparse always prints its own -h/--help in English (see i18n.ArgumentParser).
    "cli.help.group.positional": {
        "ru": "аргументы",
        "en": "positional arguments",
    },
    "cli.help.group.options": {
        "ru": "параметры",
        "en": "options",
    },
    "cli.help.help": {
        "ru": "показать эту справку и выйти",
        "en": "show this help message and exit",
    },
    "cli.help.version": {
        "ru": "показать версию и выйти",
        "en": "show the version and exit",
    },
    # -- identifier arguments shared by several commands --
    "cli.help.arg.app-id": {
        "ru": "ид приложения (по умолчанию ELEMENT_APP_ID)",
        "en": "the application id (default: ELEMENT_APP_ID)",
    },
    "cli.help.arg.app-id-required": {
        "ru": "ид приложения",
        "en": "the application id",
    },
    "cli.help.arg.app-ref": {
        "ru": "ид (UUID) либо точное имя приложения (по умолчанию ELEMENT_APP_ID)",
        "en": "the application id (UUID) or its exact name (default: ELEMENT_APP_ID)",
    },
    "cli.help.arg.app-ref-required": {
        "ru": "ид (UUID) либо точное имя приложения",
        "en": "the application id (UUID) or its exact name",
    },
    "cli.help.arg.project-id": {
        "ru": "ид проекта (по умолчанию ELEMENT_PROJECT_ID)",
        "en": "the project id (default: ELEMENT_PROJECT_ID)",
    },
    "cli.help.arg.project-id-required": {
        "ru": "ид проекта",
        "en": "the project id",
    },
    "cli.help.arg.app-name": {
        "ru": "имя приложения",
        "en": "the application name",
    },
    "cli.help.arg.assembly-version": {
        "ru": "версия сборки либо её ид",
        "en": "the assembly version or its id",
    },
    "cli.help.arg.assembly-file": {
        "ru": "файл сборки .xasm/.xlib",
        "en": "the .xasm/.xlib assembly file",
    },
    "cli.help.arg.space-id": {
        "ru": "пространство, в котором завести проект – нужно, когда --project-id не задан",
        "en": "the space to create the project in – needed when --project-id is omitted",
    },
    "cli.help.arg.branch-id": {
        "ru": "ид ветки",
        "en": "the branch id",
    },
    "cli.help.arg.branch-name": {
        "ru": "имя ветки",
        "en": "the branch name",
    },
    "cli.help.arg.dump-id": {
        "ru": "ид дампа",
        "en": "the dump id",
    },
    "cli.help.arg.task-id": {
        "ru": "ид групповой задачи",
        "en": "the group task id",
    },
    "cli.help.arg.tech-version": {
        "ru": "версия технологии, на которую перевести приложение",
        "en": "the technology version to move the application to",
    },
    "cli.help.branches-list-name": {
        "ru": "фильтр по имени ветки",
        "en": "filter by branch name",
    },
    "cli.help.deploy-project-dir": {
        "ru": "каталог проекта (по умолчанию ищется вглубь от текущего)",
        "en": "the project directory (by default searched downward from the current one)",
    },
    "cli.help.env-file": {
        "ru": "путь к .env-файлу (по умолчанию .env в текущем каталоге)",
        "en": "path to the .env file (default: .env in the current directory)",
    },
    "cli.help.timeout": {
        "ru": "таймаут запросов в секундах (по умолчанию 60)",
        "en": "request timeout in seconds (default 60)",
    },
    "cli.help.lang": {
        "ru": "язык вывода (по умолчанию: env ELEMCTL_LANG / локаль системы / ru)",
        "en": "output language (default: env ELEMCTL_LANG / system locale / ru)",
    },
    "cli.help.command-metavar": {
        "ru": "команда",
        "en": "command",
    },
    "cli.help.commands-title": {
        "ru": "команды",
        "en": "commands",
    },
    "cli.help.action-metavar": {
        "ru": "действие",
        "en": "action",
    },
    "cli.help.token": {
        "ru": "получить и напечатать токен",
        "en": "obtain and print a token",
    },
    "cli.help.apps": {
        "ru": "приложения",
        "en": "applications",
    },
    "cli.help.apps-list": {
        "ru": "список приложений",
        "en": "list applications",
    },
    "cli.help.apps-list-name": {
        "ru": "фильтр по подстроке имени без учёта регистра (выполняется на клиенте)",
        "en": "case-insensitive name substring filter (applied client-side)",
    },
    "cli.help.apps-list-brief": {
        "ru": "краткие карточки: ид, имя, статус, uri, применённая версия",
        "en": "brief cards: id, name, status, uri, applied version",
    },
    "cli.help.apps-get": {
        "ru": "карточка приложения",
        "en": "application details",
    },
    "cli.help.apps-find": {
        "ru": "найти приложение по имени (точное совпадение без учёта регистра)",
        "en": "find an application by name (exact, case-insensitive match)",
    },
    "cli.help.apps-find-include-deleted": {
        "ru": "искать и среди удалённых приложений (по умолчанию пропускаются)",
        "en": "search deleted applications too (skipped by default)",
    },
    "cli.help.apps-create": {
        "ru": "создать приложение",
        "en": "create an application",
    },
    "cli.help.apps-ensure": {
        "ru": "создать приложение, если его ещё нет (идемпотентно)",
        "en": "create the application if it does not exist yet (idempotent)",
    },
    "cli.help.apps-delete": {
        "ru": "удалить приложение (необратимо, URL меняется при пересоздании)",
        "en": "delete an application (irreversible; the URL changes on re-creation)",
    },
    "cli.help.apps-start": {
        "ru": "запустить приложение",
        "en": "start an application",
    },
    "cli.help.apps-stop": {
        "ru": "остановить приложение",
        "en": "stop an application",
    },
    "cli.help.apps-debug": {
        "ru": "данные для сессии отладки (debug-token, debug-address)",
        "en": "data for a debug session (debug-token, debug-address)",
    },
    "cli.help.create-project-id": {
        "ru": "проект-источник",
        "en": "source project",
    },
    "cli.help.create-version-id": {
        "ru": "id сборки-источника; нового проекта ещё нет – заведите его "
              "'builds upload <файл>.xasm --space-id <id>' без --project-id",
        "en": "id of the source assembly; if the project does not exist yet, create it with "
              "'builds upload <file>.xasm --space-id <id>' without --project-id",
    },
    "cli.help.create-latest-build": {
        "ru": "источник – последняя сборка проекта",
        "en": "source: the project's latest assembly",
    },
    "cli.help.create-space-id": {
        "ru": "пространство",
        "en": "space",
    },
    "cli.help.create-tech-version": {
        "ru": "версия технологии",
        "en": "technology version",
    },
    "cli.help.create-no-dev-mode": {
        "ru": "не создавать среду разработки",
        "en": "do not create a development environment",
    },
    "cli.help.create-wait": {
        "ru": "дождаться готовности приложения",
        "en": "wait until the application is ready",
    },
    "cli.help.spaces": {
        "ru": "пространства",
        "en": "spaces",
    },
    "cli.help.spaces-list": {
        "ru": "список пространств",
        "en": "list spaces",
    },
    "cli.help.projects": {
        "ru": "проекты",
        "en": "projects",
    },
    "cli.help.projects-list": {
        "ru": "список проектов",
        "en": "list projects",
    },
    "cli.help.projects-get": {
        "ru": "карточка проекта",
        "en": "project details",
    },
    "cli.help.projects-delete": {
        "ru": "удалить проект",
        "en": "delete a project",
    },
    "cli.help.builds": {
        "ru": "сборки проекта на платформе",
        "en": "project assemblies on the platform",
    },
    "cli.help.builds-list": {
        "ru": "список сборок проекта",
        "en": "list project assemblies",
    },
    "cli.help.builds-get": {
        "ru": "карточка сборки по версии либо ид",
        "en": "assembly details by version or id",
    },
    "cli.help.builds-upload": {
        "ru": "загрузить файл сборки (.xasm/.xlib)",
        "en": "upload an assembly file (.xasm/.xlib)",
    },
    "cli.help.builds-upload-new-project": {
        "ru": "загрузить сборку новым проектом, игнорируя ELEMENT_PROJECT_ID из "
              "окружения и .env-файла",
        "en": "upload the build as a new project, ignoring ELEMENT_PROJECT_ID from "
              "the environment and the .env file",
    },
    "cli.help.builds-upload-project-id": {
        "ru": "проект; БЕЗ него платформа заводит новый проект – это единственный "
              "способ создать проект через Console API",
        "en": "project; WITHOUT it the platform creates a new project – the only way "
              "to create a project through the Console API",
    },
    "cli.help.builds-upload-branch": {
        "ru": "имя git-ветки (метаданные)",
        "en": "git branch name (metadata)",
    },
    "cli.help.builds-upload-commit": {
        "ru": "хэш коммита (метаданные)",
        "en": "commit hash (metadata)",
    },
    "cli.help.builds-upload-commit-message": {
        "ru": "сообщение коммита (метаданные)",
        "en": "commit message (metadata)",
    },
    "cli.help.builds-delete": {
        "ru": "удалить сборку по версии либо ид",
        "en": "delete an assembly by version or id",
    },
    "cli.help.build": {
        "ru": "локально собрать архив сборки из исходников",
        "en": "build an assembly archive locally from sources",
    },
    "cli.help.build-project-dir": {
        "ru": "каталог проекта (по умолчанию ищется вглубь от текущего)",
        "en": "project directory (by default searched downward from the current one)",
    },
    "cli.help.build-output": {
        "ru": "каталог для архива (по умолчанию текущий)",
        "en": "directory for the archive (default: current)",
    },
    "cli.help.build-build-version": {
        "ru": "явная версия сборки, например 1.0-42",
        "en": "explicit assembly version, e.g. 1.0-42",
    },
    "cli.help.build-last-build": {
        "ru": "версия последней сборки проекта – для автоинкремента",
        "en": "the project's last assembly version – for auto-increment",
    },
    "cli.help.build-commit": {
        "ru": "хэш коммита в манифест (по умолчанию из git)",
        "en": "commit hash for the manifest (default: from git)",
    },
    "cli.help.build-branch": {
        "ru": "имя ветки в манифест (по умолчанию из git)",
        "en": "branch name for the manifest (default: from git)",
    },
    "cli.help.build-kind": {
        "ru": "вид проекта (по умолчанию из Проект.yaml)",
        "en": "project kind (default: from Проект.yaml)",
    },
    "cli.help.build-require-clean": {
        "ru": "прервать сборку, если в каталоге проекта есть незакоммиченные изменения",
        "en": "abort the build if the project directory has uncommitted changes",
    },
    "cli.help.inspect": {
        "ru": "разобрать готовый архив сборки (.xasm/.xlib)",
        "en": "inspect a prebuilt assembly archive (.xasm/.xlib)",
    },
    "cli.help.inspect-file": {
        "ru": "файл архива сборки",
        "en": "assembly archive file",
    },
    "cli.help.deploy": {
        "ru": "полный цикл: сборка -> загрузка -> применение -> перезапуск -> проверка применения",
        "en": "full cycle: build -> upload -> apply -> restart -> verify the apply",
    },
    "cli.help.deploy-output": {
        "ru": "каталог для архива (по умолчанию временный)",
        "en": "directory for the archive (default: a temporary one)",
    },
    "cli.help.deploy-build-version": {
        "ru": "явная версия сборки",
        "en": "explicit assembly version",
    },
    "cli.help.deploy-branch": {
        "ru": "имя ветки в метаданные (по умолчанию из git)",
        "en": "branch name for the metadata (default: from git)",
    },
    "cli.help.deploy-commit": {
        "ru": "хэш коммита в метаданные (по умолчанию из git)",
        "en": "commit hash for the metadata (default: from git)",
    },
    "cli.help.deploy-commit-message": {
        "ru": "сообщение коммита (метаданные загрузки)",
        "en": "commit message (upload metadata)",
    },
    "cli.help.deploy-dry-run": {
        "ru": "только сборка, без загрузки",
        "en": "build only, no upload",
    },
    "cli.help.deploy-require-clean": {
        "ru": "прервать деплой, если в каталоге проекта есть незакоммиченные изменения",
        "en": "abort the deploy if the project directory has uncommitted changes",
    },
    "cli.help.user-lists": {
        "ru": "списки пользователей и их настройки входа",
        "en": "user lists and their sign-in settings",
    },
    "cli.help.user-lists-list": {
        "ru": "список списков пользователей",
        "en": "list the user lists",
    },
    "cli.help.user-lists-list-name": {
        "ru": "фильтр по подстроке представления",
        "en": "filter by a presentation substring",
    },
    "cli.help.user-lists-get": {
        "ru": "карточка списка: регистрация, политика паролей, сервисы учётных записей",
        "en": "the list card: registration, password policy, account services",
    },
    "cli.help.user-lists-self-registration": {
        "ru": "самостоятельная регистрация пользователей: показать или переключить",
        "en": "self-registration of users: show or switch",
    },
    "cli.help.user-lists-password-login": {
        "ru": "вход по логину и паролю (сервис учётных записей Local): показать или переключить",
        "en": "signing in with a login and a password (the Local account service): show or switch",
    },
    "cli.help.user-lists-app": {
        "ru": "взять собственный список приложения (ид либо точное имя приложения)",
        "en": "take the application's own list (its id or exact name)",
    },
    "cli.help.arg.user-list": {
        "ru": "ид списка пользователей либо его точное представление",
        "en": "the user list id or its exact presentation",
    },
    "cli.help.user-lists-enable": {
        "ru": "включить",
        "en": "turn on",
    },
    "cli.help.user-lists-disable": {
        "ru": "выключить",
        "en": "turn off",
    },
    "cli.help.probe": {
        "ru": "изолированная проверка компиляции: сборка -> одноразовое приложение -> "
              "ошибки с файлом и позицией -> уборка",
        "en": "isolated compilation check: build -> throwaway application -> errors with "
              "file and position -> cleanup",
    },
    "cli.help.probe-project-dir": {
        "ru": "каталог проекта (по умолчанию ищется вглубь от текущего)",
        "en": "the project directory (by default searched downward from the current one)",
    },
    "cli.help.probe-output": {
        "ru": "каталог для архива (по умолчанию временный)",
        "en": "directory for the archive (default: a temporary one)",
    },
    "cli.help.probe-build-version": {
        "ru": "явная версия сборки (по умолчанию {{база}}-probe-{{токен}} – она обязана быть новой)",
        "en": "explicit build version (default {{base}}-probe-{{token}} – it has to be a new one)",
    },
    "cli.help.probe-name": {
        "ru": "имя одноразового приложения (по умолчанию elemctl-probe-{{токен}})",
        "en": "name of the throwaway application (default elemctl-probe-{{token}})",
    },
    "cli.help.probe-space-id": {
        "ru": "пространство для проекта и приложения (ELEMENT_SPACE_ID)",
        "en": "the space for the project and the application (ELEMENT_SPACE_ID)",
    },
    "cli.help.probe-keep": {
        "ru": "не убирать за собой: оставить приложение и сборку для разбора руками",
        "en": "skip the cleanup: leave the application and the build for a hands-on look",
    },
    "cli.help.probe-require-clean": {
        "ru": "прервать проверку, если в каталоге проекта есть незакоммиченные изменения",
        "en": "abort the check if the project directory has uncommitted changes",
    },
    "cli.help.branches": {
        "ru": "ветки среды разработки",
        "en": "development-environment branches",
    },
    "cli.help.branches-list": {
        "ru": "список веток",
        "en": "list branches",
    },
    "cli.help.branches-get": {
        "ru": "карточка ветки",
        "en": "branch details",
    },
    "cli.help.branches-create": {
        "ru": "создать ветку",
        "en": "create a branch",
    },
    "cli.help.branches-create-app-id": {
        "ru": "сразу привязать к приложению",
        "en": "bind to an application right away",
    },
    "cli.help.branches-update": {
        "ru": "изменить ветку (перепривязать к приложению)",
        "en": "update a branch (rebind to an application)",
    },
    "cli.help.branches-delete": {
        "ru": "удалить ветку",
        "en": "delete a branch",
    },
    "cli.help.branches-merge": {
        "ru": "принять изменения ветки",
        "en": "accept the branch's changes",
    },
    "cli.help.dumps": {
        "ru": "дампы приложений",
        "en": "application dumps",
    },
    "cli.help.dumps-create": {
        "ru": "создать дамп",
        "en": "create a dump",
    },
    "cli.help.dumps-create-description": {
        "ru": "описание дампа",
        "en": "dump description",
    },
    "cli.help.dumps-get": {
        "ru": "статус дампа",
        "en": "dump status",
    },
    "cli.help.tasks": {
        "ru": "задачи приложений",
        "en": "application tasks",
    },
    "cli.help.tasks-list": {
        "ru": "список задач приложений",
        "en": "list application tasks",
    },
    "cli.help.tasks-list-app-id": {
        "ru": "фильтр по приложению (на клиенте)",
        "en": "filter by application (client-side)",
    },
    "cli.help.tasks-get-group": {
        "ru": "статус групповой задачи",
        "en": "group task status",
    },
    "cli.help.tech": {
        "ru": "версия технологии",
        "en": "technology version",
    },
    "cli.help.tech-get": {
        "ru": "версия технологии приложения",
        "en": "the application's technology version",
    },
    "cli.help.tech-set": {
        "ru": "обновить версию технологии (групповая задача)",
        "en": "update the technology version (group task)",
    },
    "cli.help.debug-adapter": {
        "ru": "путь к debug-адаптеру платформы из плагина (для расширения VS Code)",
        "en": "path to the platform debug adapter from the plugin (for the VS Code extension)",
    },
    "cli.help.plugins": {
        "ru": "диагностика плагинов elemctl (точки расширения)",
        "en": "elemctl plugin diagnostics (extension points)",
    },
    "cli.help.self-update": {
        "ru": "обновить elemctl распаковкой колеса (безопасно, когда exe занят MCP-сервером)",
        "en": "update elemctl by unpacking the wheel (safe when the exe is held by the MCP server)",
    },
    "cli.help.self-update-version": {
        "ru": "целевая версия (по умолчанию – последняя с PyPI)",
        "en": "target version (default: the latest from PyPI)",
    },
    "cli.help.mcp": {
        "ru": "запустить MCP-сервер (транспорт stdio)",
        "en": "start the MCP server (stdio transport)",
    },
}


class MessageError(RuntimeError):
    pass


def register(messages: dict[str, dict[str, str]]) -> None:
    """Add messages to the catalog. Every key must carry every language of LANGS."""
    for key, per_lang in messages.items():
        missing = [lang for lang in LANGS if lang not in per_lang]
        if missing:
            raise MessageError(f"Message '{key}' has no translation for: {', '.join(missing)}")
        known = _catalog.get(key)
        if known is not None and known != per_lang:
            raise MessageError(f"Message '{key}' is already registered with a different wording")
        _catalog[key] = dict(per_lang)


def registered_keys() -> list[str]:
    return sorted(_catalog)


def translations(key: str) -> dict[str, str] | None:
    entry = _catalog.get(key)
    return dict(entry) if entry else None


def set_lang(lang: str | None) -> None:
    """Pin the output language for the process (CLI --lang). None restores the lookup order."""
    global _selected
    if lang is not None and lang not in LANGS:
        raise MessageError(f"Unknown language '{lang}'. Available: {', '.join(LANGS)}")
    _selected = lang


def lang_from_argv(argv) -> str | None:
    """Read --lang out of raw argv, before the parser is built.

    The parser is built with translated help=, but argparse learns --lang only when it parses –
    too late to choose the help language. So the value is scanned out of argv beforehand.
    Accepts "--lang en" and "--lang=en". A value outside LANGS returns None: the language stays
    at its default and argparse rejects the bad value with its own message. env / locale need no
    prescan – t() already reads them through current_lang() when the parser is built.
    """
    for i, arg in enumerate(argv):
        value = None
        if arg == "--lang" and i + 1 < len(argv):
            value = argv[i + 1]
        elif arg.startswith("--lang="):
            value = arg[len("--lang="):]
        if value is not None:
            return value if value in LANGS else None
    return None


def _system_lang() -> str | None:
    code = ""
    try:
        code = _locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        pass
    code = (code or os.environ.get("LC_ALL") or os.environ.get("LANG") or "").lower()
    # "ru_RU.UTF-8" and Windows' "Russian_Russia" both start with the language code.
    for lang in LANGS:
        if code.startswith(lang):
            return lang
    return None


def current_lang() -> str:
    if _selected is not None:
        return _selected
    env = os.environ.get(ENV_LANG, "").strip().lower()
    if env in LANGS:
        return env
    return _system_lang() or DEFAULT_LANG


def t(key: str, /, **fields) -> str:
    """Translate a key and substitute the fields. An unknown key is returned unchanged.

    A template is always run through str.format, so a literal brace must be doubled: `{{}}`.
    Formatting conditionally – only when fields are passed – would turn a literal brace into a
    field the day someone adds one, and the failure would surface as a crash at runtime.
    """
    entry = _catalog.get(key)
    if entry is None:
        return key
    template = entry.get(current_lang()) or entry[DEFAULT_LANG]
    return template.format(**fields)


class ArgumentParser(_argparse.ArgumentParser):
    """ArgumentParser with a localized `-h/--help`.

    argparse takes its own built-in strings from the gettext catalog, that is, always in
    English: in the Russian help of every command the `-h, --help` line stayed in a foreign
    language. Nested parsers inherit the class of their parent (`add_subparsers` passes
    `parser_class=type(self)`), so it is enough to create the root one with this class.
    """

    def __init__(self, *args, add_help: bool = True, **kwargs) -> None:
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = t("cli.help.group.positional")
        self._optionals.title = t("cli.help.group.options")
        if add_help:
            self.add_argument("-h", "--help", action="help", help=t("cli.help.help"))


register(MESSAGES)
