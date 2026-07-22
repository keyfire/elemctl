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
    p.add_argument("name", metavar="NAME", help=i18n.t("cli.help.arg.app-name"))
    p.add_argument("--project-id", help=i18n.t("cli.help.create-project-id"))
    p.add_argument("--version-id", help=i18n.t("cli.help.create-version-id"))
    p.add_argument("--latest-build", action="store_true", help=i18n.t("cli.help.create-latest-build"))
    p.add_argument("--space-id", help=i18n.t("cli.help.create-space-id"))
    p.add_argument("--tech-version", help=i18n.t("cli.help.create-tech-version"))
    p.add_argument("--no-dev-mode", action="store_true", help=i18n.t("cli.help.create-no-dev-mode"))
    p.add_argument("--wait", action="store_true", help=i18n.t("cli.help.create-wait"))


def build_parser():
    parser = i18n.ArgumentParser(
        prog="elemctl",
        description=i18n.t("cli.help.description"),
    )
    parser.add_argument("--base-url", help=i18n.t("cli.help.base-url"))
    parser.add_argument("--client-id", help=i18n.t("cli.help.client-id"))
    parser.add_argument("--client-secret", help=i18n.t("cli.help.client-secret"))
    parser.add_argument("--env-file", help=i18n.t("cli.help.env-file"))
    parser.add_argument("--timeout", type=float, default=None, help=i18n.t("cli.help.timeout"))
    parser.add_argument(
        "--lang",
        choices=i18n.LANGS,
        help=i18n.t("cli.help.lang"),
    )
    parser.add_argument("--version", action="version", help=i18n.t("cli.help.version"),
                        version=f"elemctl {__version__}")

    # title= renders the list under "команды:" instead of argparse's default
    # "positional arguments: команда" - the same heading the sibling tools use.
    sub = parser.add_subparsers(
        dest="command",
        metavar=i18n.t("cli.help.command-metavar"),
        title=i18n.t("cli.help.commands-title"),
    )
    action = i18n.t("cli.help.action-metavar")  # metavar подкоманд каждой группы

    p = sub.add_parser("token", help=i18n.t("cli.help.token"))
    p.set_defaults(handler=cmd_token)

    # apps ----------------------------------------------------------------
    apps = sub.add_parser("apps", help=i18n.t("cli.help.apps"))
    apps_sub = apps.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = apps_sub.add_parser("list", help=i18n.t("cli.help.apps-list"))
    p.add_argument("--name", help=i18n.t("cli.help.apps-list-name"))
    p.set_defaults(handler=cmd_apps_list)

    p = apps_sub.add_parser("get", help=i18n.t("cli.help.apps-get"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id"))
    p.set_defaults(handler=cmd_apps_get)

    p = apps_sub.add_parser("find", help=i18n.t("cli.help.apps-find"))
    p.add_argument("name", metavar="NAME", help=i18n.t("cli.help.arg.app-name"))
    p.add_argument(
        "--include-deleted",
        action="store_true",
        help=i18n.t("cli.help.apps-find-include-deleted"),
    )
    p.set_defaults(handler=cmd_apps_find)

    p = apps_sub.add_parser("create", help=i18n.t("cli.help.apps-create"))
    _add_create_flags(p)
    p.set_defaults(handler=cmd_apps_create)

    p = apps_sub.add_parser("ensure", help=i18n.t("cli.help.apps-ensure"))
    _add_create_flags(p)
    p.set_defaults(handler=cmd_apps_ensure)

    p = apps_sub.add_parser("delete", help=i18n.t("cli.help.apps-delete"))
    p.add_argument("app_id", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id-required"))
    p.set_defaults(handler=cmd_apps_delete)

    p = apps_sub.add_parser("start", help=i18n.t("cli.help.apps-start"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id"))
    p.set_defaults(handler=cmd_apps_start)

    p = apps_sub.add_parser("stop", help=i18n.t("cli.help.apps-stop"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id"))
    p.set_defaults(handler=cmd_apps_stop)

    p = apps_sub.add_parser("debug", help=i18n.t("cli.help.apps-debug"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id"))
    p.set_defaults(handler=cmd_apps_debug)

    # spaces ----------------------------------------------------------------
    spaces = sub.add_parser("spaces", help=i18n.t("cli.help.spaces"))
    spaces_sub = spaces.add_subparsers(dest="subcommand", metavar=action, required=True)
    p = spaces_sub.add_parser("list", help=i18n.t("cli.help.spaces-list"))
    p.set_defaults(handler=cmd_spaces_list)

    # projects --------------------------------------------------------------
    projects = sub.add_parser("projects", help=i18n.t("cli.help.projects"))
    projects_sub = projects.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = projects_sub.add_parser("list", help=i18n.t("cli.help.projects-list"))
    p.set_defaults(handler=cmd_projects_list)

    p = projects_sub.add_parser("get", help=i18n.t("cli.help.projects-get"))
    p.add_argument("project_id", nargs="?", metavar="PROJECT_ID", help=i18n.t("cli.help.arg.project-id"))
    p.set_defaults(handler=cmd_projects_get)

    p = projects_sub.add_parser("delete", help=i18n.t("cli.help.projects-delete"))
    p.add_argument("project_id", metavar="PROJECT_ID", help=i18n.t("cli.help.arg.project-id-required"))
    p.set_defaults(handler=cmd_projects_delete)

    # builds ----------------------------------------------------------------
    builds = sub.add_parser("builds", help=i18n.t("cli.help.builds"))
    builds_sub = builds.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = builds_sub.add_parser("list", help=i18n.t("cli.help.builds-list"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.set_defaults(handler=cmd_builds_list)

    p = builds_sub.add_parser("get", help=i18n.t("cli.help.builds-get"))
    p.add_argument("version", metavar="VERSION", help=i18n.t("cli.help.arg.assembly-version"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.set_defaults(handler=cmd_builds_get)

    p = builds_sub.add_parser("upload", help=i18n.t("cli.help.builds-upload"))
    p.add_argument("file", metavar="FILE", help=i18n.t("cli.help.arg.assembly-file"))
    p.add_argument("--project-id", help=i18n.t("cli.help.builds-upload-project-id"))
    p.add_argument("--space-id", help=i18n.t("cli.help.arg.space-id"))
    p.add_argument("--branch", help=i18n.t("cli.help.builds-upload-branch"))
    p.add_argument("--commit", help=i18n.t("cli.help.builds-upload-commit"))
    p.add_argument("--commit-message", help=i18n.t("cli.help.builds-upload-commit-message"))
    p.set_defaults(handler=cmd_builds_upload)

    p = builds_sub.add_parser("delete", help=i18n.t("cli.help.builds-delete"))
    p.add_argument("version", metavar="VERSION", help=i18n.t("cli.help.arg.assembly-version"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.set_defaults(handler=cmd_builds_delete)

    # build -----------------------------------------------------------------
    p = sub.add_parser("build", help=i18n.t("cli.help.build"))
    p.add_argument("--project-dir", help=i18n.t("cli.help.build-project-dir"))
    p.add_argument("--output", help=i18n.t("cli.help.build-output"))
    p.add_argument("--build-version", help=i18n.t("cli.help.build-build-version"))
    p.add_argument("--last-build", help=i18n.t("cli.help.build-last-build"))
    p.add_argument("--commit", help=i18n.t("cli.help.build-commit"))
    p.add_argument("--branch", help=i18n.t("cli.help.build-branch"))
    p.add_argument("--kind", choices=["application", "library"], help=i18n.t("cli.help.build-kind"))
    p.set_defaults(handler=cmd_build)

    # inspect ---------------------------------------------------------------
    p = sub.add_parser("inspect", help=i18n.t("cli.help.inspect"))
    p.add_argument("file", metavar="FILE", help=i18n.t("cli.help.inspect-file"))
    p.set_defaults(handler=cmd_inspect)

    # deploy ----------------------------------------------------------------
    p = sub.add_parser("deploy", help=i18n.t("cli.help.deploy"))
    p.add_argument("--app-id", help=i18n.t("cli.help.arg.app-id"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.add_argument("--project-dir", help=i18n.t("cli.help.deploy-project-dir"))
    p.add_argument("--output", help=i18n.t("cli.help.deploy-output"))
    p.add_argument("--build-version", help=i18n.t("cli.help.deploy-build-version"))
    p.add_argument("--branch", help=i18n.t("cli.help.deploy-branch"))
    p.add_argument("--commit", help=i18n.t("cli.help.deploy-commit"))
    p.add_argument("--commit-message", help=i18n.t("cli.help.deploy-commit-message"))
    p.add_argument("--dry-run", action="store_true", help=i18n.t("cli.help.deploy-dry-run"))
    p.set_defaults(handler=cmd_deploy)

    # branches ----------------------------------------------------------------
    branches = sub.add_parser("branches", help=i18n.t("cli.help.branches"))
    branches_sub = branches.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = branches_sub.add_parser("list", help=i18n.t("cli.help.branches-list"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.add_argument("--name", help=i18n.t("cli.help.branches-list-name"))
    p.set_defaults(handler=cmd_branches_list)

    p = branches_sub.add_parser("get", help=i18n.t("cli.help.branches-get"))
    p.add_argument("branch_id", metavar="ID", help=i18n.t("cli.help.arg.branch-id"))
    p.set_defaults(handler=cmd_branches_get)

    p = branches_sub.add_parser("create", help=i18n.t("cli.help.branches-create"))
    p.add_argument("name", metavar="NAME", help=i18n.t("cli.help.arg.branch-name"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.add_argument("--app-id", help=i18n.t("cli.help.branches-create-app-id"))
    p.set_defaults(handler=cmd_branches_create)

    p = branches_sub.add_parser("update", help=i18n.t("cli.help.branches-update"))
    p.add_argument("branch_id", metavar="ID", help=i18n.t("cli.help.arg.branch-id"))
    p.add_argument("--app-id", help=i18n.t("cli.help.arg.app-id"))
    p.set_defaults(handler=cmd_branches_update)

    p = branches_sub.add_parser("delete", help=i18n.t("cli.help.branches-delete"))
    p.add_argument("branch_id", metavar="ID", help=i18n.t("cli.help.arg.branch-id"))
    p.set_defaults(handler=cmd_branches_delete)

    p = branches_sub.add_parser("merge", help=i18n.t("cli.help.branches-merge"))
    p.add_argument("branch_id", metavar="ID", help=i18n.t("cli.help.arg.branch-id"))
    p.set_defaults(handler=cmd_branches_merge)

    # dumps ----------------------------------------------------------------
    dumps = sub.add_parser("dumps", help=i18n.t("cli.help.dumps"))
    dumps_sub = dumps.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = dumps_sub.add_parser("create", help=i18n.t("cli.help.dumps-create"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id"))
    p.add_argument("--description", help=i18n.t("cli.help.dumps-create-description"))
    p.set_defaults(handler=cmd_dumps_create)

    p = dumps_sub.add_parser("get", help=i18n.t("cli.help.dumps-get"))
    p.add_argument("app_id", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id-required"))
    p.add_argument("dump_id", metavar="DUMP_ID", help=i18n.t("cli.help.arg.dump-id"))
    p.set_defaults(handler=cmd_dumps_get)

    # tasks ----------------------------------------------------------------
    tasks = sub.add_parser("tasks", help=i18n.t("cli.help.tasks"))
    tasks_sub = tasks.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = tasks_sub.add_parser("list", help=i18n.t("cli.help.tasks-list"))
    p.add_argument("--app-id", help=i18n.t("cli.help.tasks-list-app-id"))
    p.set_defaults(handler=cmd_tasks_list)

    p = tasks_sub.add_parser("get-group", help=i18n.t("cli.help.tasks-get-group"))
    p.add_argument("task_id", metavar="TASK_ID", help=i18n.t("cli.help.arg.task-id"))
    p.set_defaults(handler=cmd_tasks_get_group)

    # tech ----------------------------------------------------------------
    tech = sub.add_parser("tech", help=i18n.t("cli.help.tech"))
    tech_sub = tech.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = tech_sub.add_parser("get", help=i18n.t("cli.help.tech-get"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id"))
    p.set_defaults(handler=cmd_tech_get)

    p = tech_sub.add_parser("set", help=i18n.t("cli.help.tech-set"))
    p.add_argument("app_id", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id-required"))
    p.add_argument("version", metavar="VERSION", help=i18n.t("cli.help.arg.tech-version"))
    p.set_defaults(handler=cmd_tech_set)

    # debug-adapter -------------------------------------------------------
    p = sub.add_parser("debug-adapter", help=i18n.t("cli.help.debug-adapter"))
    p.set_defaults(handler=cmd_debug_adapter)

    # plugins -------------------------------------------------------------
    p = sub.add_parser("plugins", help=i18n.t("cli.help.plugins"))
    p.set_defaults(handler=cmd_plugins)

    # self-update ---------------------------------------------------------
    p = sub.add_parser("self-update", help=i18n.t("cli.help.self-update"))
    p.add_argument("--version", help=i18n.t("cli.help.self-update-version"))
    p.set_defaults(handler=cmd_self_update)

    # mcp ----------------------------------------------------------------
    p = sub.add_parser("mcp", help=i18n.t("cli.help.mcp"))
    p.set_defaults(handler=cmd_mcp)

    return parser


def main(argv=None):
    """Точка входа CLI; возвращает код завершения процесса."""
    _reconfigure_streams()
    if argv is None:
        argv = sys.argv[1:]
    # Язык нужен ДО build_parser: справка (help=) собирается на выбранном языке. Предсканируем
    # argv на --lang; env и локаль t() учтёт сам через current_lang() при сборке парсера.
    i18n.set_lang(i18n.lang_from_argv(argv))
    parser = build_parser()
    args = parser.parse_args(argv)
    # Повторно закрепляем язык уже из разобранных аргументов: argparse принимает и сокращения
    # (--lan en), которых предскан не ловит; для рантайма это авторитетный источник.
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
