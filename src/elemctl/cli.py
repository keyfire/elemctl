"""Консольный интерфейс elemctl.

Соглашения вывода: результат – JSON в stdout (ensure_ascii=False, отступ 2);
прогресс длительных операций – строки в stderr; ошибки – JSON с полем error
в stderr и код возврата 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, i18n, plugins
from .build import build_assembly, inspect_assembly
from .client import ElementClient, extract_assembly_id
from .config import Config
from .deploy import deploy_from_sources
from .errors import ApiError, ConfigError, ElemctlError


def make_client(config):
    """Фабрика клиента; выделена, чтобы тесты могли её подменить."""
    return ElementClient(config)


# -- вывод ---------------------------------------------------------------------


def _emit(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _progress(message):
    print(message, file=sys.stderr)


def _fail(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    return 1


def _reconfigure_streams():
    """Перевести вывод консоли в UTF-8 – иначе на Windows ломается кириллица."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


# -- конфигурация и разрешение идентификаторов ------------------------------------


def _config(args):
    return Config.from_env(
        env_file=args.env_file,
        base_url=args.base_url,
        client_id=args.client_id,
        client_secret=args.client_secret,
        timeout=args.timeout,
    )


def _require(explicit, fallback, what):
    """Взять явное значение либо значение из конфигурации; иначе ошибка."""
    value = explicit or fallback
    if not value:
        raise ConfigError(i18n.t("cli.not-set", what=what))
    return value


# -- обработчики команд -----------------------------------------------------------


def cmd_token(args):
    client = make_client(_config(args))
    _emit({"token": client.token()})
    return 0


def cmd_apps_list(args):
    client = make_client(_config(args))
    _emit(client.list_apps(name=args.name or ""))
    return 0


def cmd_apps_get(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    _emit(client.get_app(app_id))
    return 0


def cmd_apps_find(args):
    """Поиск приложения по имени. Отсутствие приложения – это ответ, а не ошибка.

    Код возврата 0 в обоих случаях: признак несёт поле found. Ненулевой код возврата
    означает сбой запроса (нет доступа, сеть, конфигурация) и сопровождается JSON'ом
    с полем error в stderr – иначе вызывающий не отличит "стенда нет" от "не смогли спросить".

    Удалённые приложения (статус Deleted) по умолчанию пропускаются, чтобы найденный id
    был пригоден для работы; флаг --include-deleted возвращает поиск среди всех приложений.
    """
    client = make_client(_config(args))
    app = client.find_app(args.name, include_deleted=args.include_deleted)
    if app is None:
        _emit({"id": None, "found": False})
        return 0
    _emit({"id": app.get("id"), "found": True})
    return 0


def _create_app_from_args(client, config, args):
    """Создать приложение по флагам создания; вернуть карточку.

    Общая логика apps create и apps ensure. Источник – указанная сборка
    (--version-id), последняя сборка проекта (--latest-build) либо проект
    целиком (--project-id, чревато пустым каркасом). При --wait дожидается
    готовности приложения.
    """
    project_id = args.project_id or config.project_id
    version_id = args.version_id

    if args.latest_build and not version_id:
        if not project_id:
            raise ConfigError(i18n.t("cli.latest-build-needs-project"))
        latest = client.latest_assembly(project_id)
        if latest is None:
            raise ElemctlError(
                f"у проекта {project_id} нет сборок – загрузите сборку (builds upload) "
                "или укажите --version-id"
            )
        version_id = extract_assembly_id(latest)

    kwargs = {
        "development_mode": not args.no_dev_mode,
        "space_id": args.space_id or config.space_id or None,
        "technology_version": args.tech_version or None,
    }
    if version_id:
        card = client.create_app(args.name, project_version_id=version_id, **kwargs)
    elif project_id:
        _progress(
            "внимание: источник – проект целиком; на части конфигураций платформы "
            "это даёт пустой каркас (надёжнее --latest-build)"
        )
        card = client.create_app(args.name, image_id=project_id, **kwargs)
    else:
        raise ConfigError(i18n.t("cli.app-source-required"))

    if args.wait:
        app_id = (card or {}).get("id")
        if app_id:
            card = client.wait_app_ready(app_id, log=_progress)
    return card


def cmd_apps_create(args):
    config = _config(args)
    client = make_client(config)
    _emit(_create_app_from_args(client, config, args))
    return 0


def cmd_apps_ensure(args):
    """Идемпотентно привести приложение с данным именем в существование.

    Ищет приложение по правилам apps find (удалённые в статусе Deleted не в
    счёт): если оно уже есть – ничего не делает и возвращает created: false;
    если нет – создаёт по флагам создания и возвращает created: true.
    Существующее приложение никогда не пересоздаётся: delete + create дают
    новый URL и рвут внешние привязки к прежнему. Код возврата 0 в обоих
    случаях; сбой запроса – JSON с полем error в stderr и код возврата 1.
    """
    config = _config(args)
    client = make_client(config)
    existing = client.find_app(args.name)
    if existing is not None:
        _emit({"id": existing.get("id"), "created": False})
        return 0
    card = _create_app_from_args(client, config, args)
    _emit({"id": (card or {}).get("id"), "created": True})
    return 0


def cmd_apps_delete(args):
    client = make_client(_config(args))
    response = client.delete_app(args.app_id)
    _emit(response if response is not None else {"deleted": True, "app-id": args.app_id})
    return 0


def cmd_apps_debug(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    _emit(client.get_debug_info(app_id) or {})
    return 0


def cmd_apps_start(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    response = client.start_app(app_id)
    _emit(response if response is not None else {"ok": True, "app-id": app_id})
    return 0


def cmd_apps_stop(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    response = client.stop_app(app_id)
    _emit(response if response is not None else {"ok": True, "app-id": app_id})
    return 0


def cmd_spaces_list(args):
    client = make_client(_config(args))
    _emit(client.list_spaces())
    return 0


def cmd_projects_list(args):
    client = make_client(_config(args))
    _emit(client.list_projects())
    return 0


def cmd_projects_get(args):
    config = _config(args)
    client = make_client(config)
    project_id = _require(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-arg")
    )
    _emit(client.get_project(project_id))
    return 0


def cmd_projects_delete(args):
    client = make_client(_config(args))
    response = client.delete_project(args.project_id)
    _emit(response if response is not None else {"deleted": True, "project-id": args.project_id})
    return 0


def cmd_builds_list(args):
    config = _config(args)
    client = make_client(config)
    project_id = _require(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-flag")
    )
    _emit(client.list_assemblies(project_id))
    return 0


def cmd_builds_get(args):
    config = _config(args)
    client = make_client(config)
    project_id = _require(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-flag")
    )
    _emit(client.get_assembly(project_id, args.version))
    return 0


def cmd_builds_upload(args):
    config = _config(args)
    client = make_client(config)
    file_path = Path(args.file)
    if not file_path.is_file():
        raise ElemctlError(i18n.t("cli.build-file-not-found", path=file_path))
    response = client.upload_assembly(
        file_path.read_bytes(),
        project_id=args.project_id or config.project_id or None,
        space_id=args.space_id or config.space_id or None,
        branch_name=args.branch or None,
        commit_id=args.commit or None,
        commit_message=args.commit_message or None,
    )
    _emit({"assembly-id": extract_assembly_id(response), "response": response})
    return 0


def cmd_builds_delete(args):
    config = _config(args)
    client = make_client(config)
    project_id = _require(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-flag")
    )
    response = client.delete_assembly(project_id, args.version)
    _emit(response if response is not None else {"deleted": True, "version": args.version})
    return 0


def cmd_build(args):
    result = build_assembly(
        args.project_dir,
        output_dir=args.output,
        version=args.build_version or "",
        last_build_version=args.last_build or "",
        branch=args.branch,
        commit=args.commit,
        kind=args.kind or "",
    )
    _emit({"file": str(result.file)})
    return 0


def cmd_inspect(args):
    _emit(inspect_assembly(args.file))
    return 0


def cmd_deploy(args):
    if args.dry_run:
        result = build_assembly(
            args.project_dir,
            output_dir=args.output,
            version=args.build_version or "",
            branch=args.branch,
            commit=args.commit,
        )
        _emit({"file": str(result.file)})
        return 0

    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-flag"))
    project_id = _require(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-flag")
    )
    report = deploy_from_sources(
        client,
        app_id,
        project_id,
        project_dir=args.project_dir,
        output_dir=args.output,
        version=args.build_version or "",
        branch=args.branch,
        commit=args.commit,
        commit_message=args.commit_message or "",
        log=_progress,
    )
    _emit(report.to_dict())
    return 0 if report.ok else 1


def cmd_branches_list(args):
    client = make_client(_config(args))
    _emit(client.list_branches(project_id=args.project_id or "", name=args.name or ""))
    return 0


def cmd_branches_get(args):
    client = make_client(_config(args))
    _emit(client.get_branch(args.branch_id))
    return 0


def cmd_branches_create(args):
    config = _config(args)
    client = make_client(config)
    project_id = _require(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-flag")
    )
    _emit(client.create_branch(args.name, project_id, app_id=args.app_id or None))
    return 0


def cmd_branches_update(args):
    client = make_client(_config(args))
    _emit(client.update_branch(args.branch_id, app_id=args.app_id or None))
    return 0


def cmd_branches_delete(args):
    client = make_client(_config(args))
    response = client.delete_branch(args.branch_id)
    _emit(response if response is not None else {"deleted": True, "branch-id": args.branch_id})
    return 0


def cmd_branches_merge(args):
    client = make_client(_config(args))
    response = client.merge_branch(args.branch_id)
    _emit(response if response is not None else {"merged": True, "branch-id": args.branch_id})
    return 0


def cmd_dumps_create(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    _emit(client.create_dump(app_id, description=args.description or ""))
    return 0


def cmd_dumps_get(args):
    client = make_client(_config(args))
    _emit(client.get_dump(args.app_id, args.dump_id))
    return 0


def cmd_tasks_list(args):
    client = make_client(_config(args))
    _emit(client.list_app_tasks(args.app_id or ""))
    return 0


def cmd_tasks_get_group(args):
    client = make_client(_config(args))
    _emit(client.get_group_task(args.task_id))
    return 0


def cmd_tech_get(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    _emit({"app-id": app_id, "technology-version": client.get_technology_version(app_id)})
    return 0


def cmd_tech_set(args):
    client = make_client(_config(args))
    _emit(client.set_technology_version(args.version, [args.app_id]))
    return 0


def cmd_debug_adapter(args):
    """Путь к каталогу debug-адаптера платформы, принесённому плагином.

    Каталог содержит подкаталог repo/ с jar-файлами адаптера – это готовое значение
    настройки xbslDebug.adapterPath для расширения VS Code. Отсутствие плагина – это
    ответ (found: false, код 0), а не ошибка: ненулевой код означал бы сбой.
    """
    path = plugins.debug_adapter_path()
    if path is None:
        _emit({"path": None, "found": False})
        return 0
    _emit({"path": str(path), "found": True, "adapter-class": plugins.ADAPTER_MAIN_CLASS})
    return 0


def cmd_plugins(args):
    """Диагностика плагинов: объявленные каталоги debug-адаптера (в т.ч. без jar)."""
    paths = plugins.debug_adapter_paths()
    _emit(
        {
            "debug-adapter": [
                {"path": str(p), "has-jars": plugins.has_adapter_jars(p)} for p in paths
            ]
        }
    )
    return 0


def cmd_self_update(args):
    """Обновить установленный elemctl распаковкой колеса (безопасно при занятом exe)."""
    from . import selfupdate

    old, new = selfupdate.self_update(version=args.version, log=_progress)
    _emit({"updated": old != new, "from": old, "to": new})
    return 0


def cmd_mcp(args):
    try:
        from . import mcp_server
    except ImportError:
        raise ElemctlError(
            'MCP-зависимость не установлена – выполните: pip install "elemctl[mcp]"'
        )
    mcp_server.main(config=_config(args))
    return 0


# -- парсер --------------------------------------------------------------------


def _add_create_flags(p):
    """Добавить флаги источника и создания приложения (общие для apps create и apps ensure)."""
    p.add_argument("name", metavar="NAME")
    p.add_argument("--project-id", help="проект-источник")
    p.add_argument("--version-id", help="id сборки-источника")
    p.add_argument("--latest-build", action="store_true", help="источник – последняя сборка проекта")
    p.add_argument("--space-id", help="пространство")
    p.add_argument("--tech-version", help="версия технологии")
    p.add_argument("--no-dev-mode", action="store_true", help="не создавать среду разработки")
    p.add_argument("--wait", action="store_true", help="дождаться готовности приложения")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="elemctl",
        description="Управление приложениями платформы 1С:Предприятие.Элемент (Console API v2)",
    )
    parser.add_argument("--base-url", help="базовый URL платформы (ELEMENT_BASE_URL)")
    parser.add_argument("--client-id", help="Client-Id для получения токена (ELEMENT_CLIENT_ID)")
    parser.add_argument("--client-secret", help="Client-Secret (ELEMENT_CLIENT_SECRET)")
    parser.add_argument("--env-file", help="путь к .env-файлу (по умолчанию .env в текущем каталоге)")
    parser.add_argument("--timeout", type=float, default=None, help="таймаут запросов в секундах (по умолчанию 60)")
    parser.add_argument(
        "--lang",
        choices=i18n.LANGS,
        help="язык вывода (по умолчанию: env ELEMCTL_LANG / локаль системы / ru)",
    )
    parser.add_argument("--version", action="version", version=f"elemctl {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="команда")

    p = sub.add_parser("token", help="получить и напечатать токен")
    p.set_defaults(handler=cmd_token)

    # apps ----------------------------------------------------------------
    apps = sub.add_parser("apps", help="приложения")
    apps_sub = apps.add_subparsers(dest="subcommand", metavar="действие", required=True)

    p = apps_sub.add_parser("list", help="список приложений")
    p.add_argument("--name", help="фильтр по имени")
    p.set_defaults(handler=cmd_apps_list)

    p = apps_sub.add_parser("get", help="карточка приложения")
    p.add_argument("app_id", nargs="?", metavar="APP_ID")
    p.set_defaults(handler=cmd_apps_get)

    p = apps_sub.add_parser("find", help="найти приложение по имени (точное совпадение без учёта регистра)")
    p.add_argument("name", metavar="NAME")
    p.add_argument(
        "--include-deleted",
        action="store_true",
        help="искать и среди удалённых приложений (по умолчанию пропускаются)",
    )
    p.set_defaults(handler=cmd_apps_find)

    p = apps_sub.add_parser("create", help="создать приложение")
    _add_create_flags(p)
    p.set_defaults(handler=cmd_apps_create)

    p = apps_sub.add_parser("ensure", help="создать приложение, если его ещё нет (идемпотентно)")
    _add_create_flags(p)
    p.set_defaults(handler=cmd_apps_ensure)

    p = apps_sub.add_parser("delete", help="удалить приложение (необратимо, URL меняется при пересоздании)")
    p.add_argument("app_id", metavar="APP_ID")
    p.set_defaults(handler=cmd_apps_delete)

    p = apps_sub.add_parser("start", help="запустить приложение")
    p.add_argument("app_id", nargs="?", metavar="APP_ID")
    p.set_defaults(handler=cmd_apps_start)

    p = apps_sub.add_parser("stop", help="остановить приложение")
    p.add_argument("app_id", nargs="?", metavar="APP_ID")
    p.set_defaults(handler=cmd_apps_stop)

    p = apps_sub.add_parser("debug", help="данные для сессии отладки (debug-token, debug-address)")
    p.add_argument("app_id", nargs="?", metavar="APP_ID")
    p.set_defaults(handler=cmd_apps_debug)

    # spaces ----------------------------------------------------------------
    spaces = sub.add_parser("spaces", help="пространства")
    spaces_sub = spaces.add_subparsers(dest="subcommand", metavar="действие", required=True)
    p = spaces_sub.add_parser("list", help="список пространств")
    p.set_defaults(handler=cmd_spaces_list)

    # projects --------------------------------------------------------------
    projects = sub.add_parser("projects", help="проекты")
    projects_sub = projects.add_subparsers(dest="subcommand", metavar="действие", required=True)

    p = projects_sub.add_parser("list", help="список проектов")
    p.set_defaults(handler=cmd_projects_list)

    p = projects_sub.add_parser("get", help="карточка проекта")
    p.add_argument("project_id", nargs="?", metavar="PROJECT_ID")
    p.set_defaults(handler=cmd_projects_get)

    p = projects_sub.add_parser("delete", help="удалить проект")
    p.add_argument("project_id", metavar="PROJECT_ID")
    p.set_defaults(handler=cmd_projects_delete)

    # builds ----------------------------------------------------------------
    builds = sub.add_parser("builds", help="сборки проекта на платформе")
    builds_sub = builds.add_subparsers(dest="subcommand", metavar="действие", required=True)

    p = builds_sub.add_parser("list", help="список сборок проекта")
    p.add_argument("--project-id")
    p.set_defaults(handler=cmd_builds_list)

    p = builds_sub.add_parser("get", help="карточка сборки по версии")
    p.add_argument("version", metavar="VERSION")
    p.add_argument("--project-id")
    p.set_defaults(handler=cmd_builds_get)

    p = builds_sub.add_parser("upload", help="загрузить файл сборки (.xasm/.xlib)")
    p.add_argument("file", metavar="FILE")
    p.add_argument("--project-id", help="проект (без него создаётся новый проект)")
    p.add_argument("--space-id")
    p.add_argument("--branch", help="имя git-ветки (метаданные)")
    p.add_argument("--commit", help="хэш коммита (метаданные)")
    p.add_argument("--commit-message", help="сообщение коммита (метаданные)")
    p.set_defaults(handler=cmd_builds_upload)

    p = builds_sub.add_parser("delete", help="удалить сборку по версии")
    p.add_argument("version", metavar="VERSION")
    p.add_argument("--project-id")
    p.set_defaults(handler=cmd_builds_delete)

    # build -----------------------------------------------------------------
    p = sub.add_parser("build", help="локально собрать архив сборки из исходников")
    p.add_argument("--project-dir", help="каталог проекта (по умолчанию ищется вглубь от текущего)")
    p.add_argument("--output", help="каталог для архива (по умолчанию текущий)")
    p.add_argument("--build-version", help="явная версия сборки, например 1.0-42")
    p.add_argument("--last-build", help="версия последней сборки проекта – для автоинкремента")
    p.add_argument("--commit", help="хэш коммита в манифест (по умолчанию из git)")
    p.add_argument("--branch", help="имя ветки в манифест (по умолчанию из git)")
    p.add_argument("--kind", choices=["application", "library"], help="вид проекта (по умолчанию из Проект.yaml)")
    p.set_defaults(handler=cmd_build)

    # inspect ---------------------------------------------------------------
    p = sub.add_parser("inspect", help="разобрать готовый архив сборки (.xasm/.xlib)")
    p.add_argument("file", metavar="FILE", help="файл архива сборки")
    p.set_defaults(handler=cmd_inspect)

    # deploy ----------------------------------------------------------------
    p = sub.add_parser(
        "deploy",
        help="полный цикл: сборка -> загрузка -> применение -> перезапуск -> проверка применения",
    )
    p.add_argument("--app-id")
    p.add_argument("--project-id")
    p.add_argument("--project-dir")
    p.add_argument("--output", help="каталог для архива (по умолчанию временный)")
    p.add_argument("--build-version", help="явная версия сборки")
    p.add_argument("--branch", help="имя ветки в метаданные (по умолчанию из git)")
    p.add_argument("--commit", help="хэш коммита в метаданные (по умолчанию из git)")
    p.add_argument("--commit-message", help="сообщение коммита (метаданные загрузки)")
    p.add_argument("--dry-run", action="store_true", help="только сборка, без загрузки")
    p.set_defaults(handler=cmd_deploy)

    # branches ----------------------------------------------------------------
    branches = sub.add_parser("branches", help="ветки среды разработки")
    branches_sub = branches.add_subparsers(dest="subcommand", metavar="действие", required=True)

    p = branches_sub.add_parser("list", help="список веток")
    p.add_argument("--project-id")
    p.add_argument("--name")
    p.set_defaults(handler=cmd_branches_list)

    p = branches_sub.add_parser("get", help="карточка ветки")
    p.add_argument("branch_id", metavar="ID")
    p.set_defaults(handler=cmd_branches_get)

    p = branches_sub.add_parser("create", help="создать ветку")
    p.add_argument("name", metavar="NAME")
    p.add_argument("--project-id")
    p.add_argument("--app-id", help="сразу привязать к приложению")
    p.set_defaults(handler=cmd_branches_create)

    p = branches_sub.add_parser("update", help="изменить ветку (перепривязать к приложению)")
    p.add_argument("branch_id", metavar="ID")
    p.add_argument("--app-id")
    p.set_defaults(handler=cmd_branches_update)

    p = branches_sub.add_parser("delete", help="удалить ветку")
    p.add_argument("branch_id", metavar="ID")
    p.set_defaults(handler=cmd_branches_delete)

    p = branches_sub.add_parser("merge", help="принять изменения ветки")
    p.add_argument("branch_id", metavar="ID")
    p.set_defaults(handler=cmd_branches_merge)

    # dumps ----------------------------------------------------------------
    dumps = sub.add_parser("dumps", help="дампы приложений")
    dumps_sub = dumps.add_subparsers(dest="subcommand", metavar="действие", required=True)

    p = dumps_sub.add_parser("create", help="создать дамп")
    p.add_argument("app_id", nargs="?", metavar="APP_ID")
    p.add_argument("--description", help="описание дампа")
    p.set_defaults(handler=cmd_dumps_create)

    p = dumps_sub.add_parser("get", help="статус дампа")
    p.add_argument("app_id", metavar="APP_ID")
    p.add_argument("dump_id", metavar="DUMP_ID")
    p.set_defaults(handler=cmd_dumps_get)

    # tasks ----------------------------------------------------------------
    tasks = sub.add_parser("tasks", help="задачи приложений")
    tasks_sub = tasks.add_subparsers(dest="subcommand", metavar="действие", required=True)

    p = tasks_sub.add_parser("list", help="список задач приложений")
    p.add_argument("--app-id", help="фильтр по приложению (на клиенте)")
    p.set_defaults(handler=cmd_tasks_list)

    p = tasks_sub.add_parser("get-group", help="статус групповой задачи")
    p.add_argument("task_id", metavar="TASK_ID")
    p.set_defaults(handler=cmd_tasks_get_group)

    # tech ----------------------------------------------------------------
    tech = sub.add_parser("tech", help="версия технологии")
    tech_sub = tech.add_subparsers(dest="subcommand", metavar="действие", required=True)

    p = tech_sub.add_parser("get", help="версия технологии приложения")
    p.add_argument("app_id", nargs="?", metavar="APP_ID")
    p.set_defaults(handler=cmd_tech_get)

    p = tech_sub.add_parser("set", help="обновить версию технологии (групповая задача)")
    p.add_argument("app_id", metavar="APP_ID")
    p.add_argument("version", metavar="VERSION")
    p.set_defaults(handler=cmd_tech_set)

    # debug-adapter -------------------------------------------------------
    p = sub.add_parser(
        "debug-adapter",
        help="путь к debug-адаптеру платформы из плагина (для расширения VS Code)",
    )
    p.set_defaults(handler=cmd_debug_adapter)

    # plugins -------------------------------------------------------------
    p = sub.add_parser("plugins", help="диагностика плагинов elemctl (точки расширения)")
    p.set_defaults(handler=cmd_plugins)

    # self-update ---------------------------------------------------------
    p = sub.add_parser(
        "self-update",
        help="обновить elemctl распаковкой колеса (безопасно, когда exe занят MCP-сервером)",
    )
    p.add_argument("--version", help="целевая версия (по умолчанию – последняя с PyPI)")
    p.set_defaults(handler=cmd_self_update)

    # mcp ----------------------------------------------------------------
    p = sub.add_parser("mcp", help="запустить MCP-сервер (транспорт stdio)")
    p.set_defaults(handler=cmd_mcp)

    return parser


def main(argv=None):
    """Точка входа CLI; возвращает код завершения процесса."""
    _reconfigure_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    i18n.set_lang(args.lang)  # None сохраняет порядок env / локаль / ru
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return 1
    try:
        result = handler(args)
        return 0 if result is None else int(result)
    except ApiError as error:
        return _fail(error.to_dict())
    except ElemctlError as error:
        return _fail({"error": str(error)})
    except OSError as error:
        return _fail({"error": str(error)})


if __name__ == "__main__":
    sys.exit(main())
