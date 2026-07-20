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
code comments stay in Russian.
"""

from __future__ import annotations

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
    "cli.latest-build-needs-project": {
        "ru": "для --latest-build нужен --project-id (или ELEMENT_PROJECT_ID)",
        "en": "--latest-build requires --project-id (or ELEMENT_PROJECT_ID)",
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
    # -- client.py ----------------------------------------------------------------
    "client.assembly-not-found": {
        "ru": "сборка '{version}' не найдена в проекте {project} (ни по версии, ни по ид)",
        "en": "assembly '{version}' not found in project {project} (neither by version nor by id)",
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
    # -- mcp_server.py ------------------------------------------------------------
    "mcp.project-or-version-required": {
        "ru": "нужен project_id или version_id",
        "en": "project_id or version_id is required",
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
    # -- deploy.py ----------------------------------------------------------------
    "deploy.built": {
        "ru": "собран архив {file} (версия {version})",
        "en": "built archive {file} (version {version})",
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
        "ru": "Client-Secret (ELEMENT_CLIENT_SECRET)",
        "en": "Client-Secret (ELEMENT_CLIENT_SECRET)",
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
        "ru": "фильтр по имени",
        "en": "filter by name",
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


register(MESSAGES)
