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

Scope: only runtime output is translated. argparse help=, docstrings and comments stay in
Russian, exactly as in the linter this mechanism is copied from.
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
