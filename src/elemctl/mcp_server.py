"""The elemctl MCP server: platform operations as tools for AI agents.

The transport is stdio; the connection credentials come from the ELEMENT_*
environment variables or from the .env file in the current directory. Requires
the optional extra "elemctl[mcp]" (the mcp>=1.2 package, FastMCP is used).
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as error:  # pragma: no cover - the branch without the extra
    raise ImportError(
        'the MCP server needs the extra: pip install "elemctl[mcp]"'
    ) from error

from . import i18n, plugins
from .build import build_assembly, inspect_assembly
from .client import ElementClient, brief_app, extract_assembly_id
from .config import Config
from .deploy import (
    deploy_from_sources,
    verify_deploy as _verify_deploy,
)
from .errors import ElemctlError, PluginError
from .probe import probe_project

INSTRUCTIONS = (
    "Инструменты управления платформой 1С:Предприятие.Элемент (Console API v2). "
    "Важно: при ошибке применения сборки платформа МОЛЧА откатывает приложение "
    "на предыдущую сборку и запускает его – статус Running не означает успех "
    "деплоя. Доверяйте только отчёту инструментов deploy/verify_deploy: поле ok, "
    "список problems и сверка применённой сборки с загруженной (надёжно - по applied-version-id; строка версии у нового приложения нумеруется заново). "
    "Асинхронность: build_assembly, deploy, probe, apply_build, create_app, "
    "ensure_app, delete_app и merge_branch выполняются минутами и синхронно блокируют вызов "
    "до конца – в чате это выглядит зависанием без вывода. Такие операции "
    "запускать CLI-командой elemctl фоновым процессом (у агента – механизм "
    "фонового запуска вроде run_in_background, результат придёт нотификацией), а "
    "не синхронным вызовом MCP-инструмента; сами MCP-инструменты предпочтительны "
    "для быстрых операций чтения (list/get/find/list-builds/verify-deploy). "
    "Окружение: по умолчанию используется то, с которым запущен сервер; чтобы "
    "обратиться к другому стенду (например, к локальному вместо облачного), "
    "передайте его .env параметром env_file – он есть у каждого инструмента."
)


def _brief_project(project):
    """A brief project card: what the project is recognized and picked by.

    The full card carries the group, the default image, the artifact code and the
    dates – all of it redundant in a listing. The application counter is kept: it
    shows which projects are actually in use.
    """
    return {
        "id": project.get("id"),
        "name": project.get("name"),
        "project-kind": project.get("project-kind"),
        "space-id": project.get("space-id"),
        "application-count": project.get("application-count"),
        "deleted": project.get("deleted"),
    }


def create_server(config=None):
    """Create the elemctl MCP server with all of its tools.

    config – a ready configuration; without it the configuration is assembled
    from the environment variables and .env on the first call to the platform.
    """
    server = FastMCP("elemctl", instructions=INSTRUCTIONS)
    state = {"clients": {}, "config": config}

    def client(env_file: str = ""):
        """A platform client for the requested environment.

        Without env_file – the configuration the server was started with; with it –
        a separate client for the given .env, cached by that path. This way a single
        server serves both the cloud and a local installation: previously the
        environment was set only at startup, and the second one stayed out of reach.
        """
        key = env_file or ""
        if key not in state["clients"]:
            cfg = (
                state["config"] if not key and state["config"]
                else Config.from_env(env_file=key or None)
            )
            state["clients"][key] = ElementClient(cfg)
        return state["clients"][key]

    @server.tool()
    def list_apps(name: str = "", brief: bool = True, env_file: str = "") -> list:
        """Список приложений платформы; name – фильтр по подстроке имени без учёта регистра (выполняется на клиенте: платформа query-параметр игнорирует).

        brief (по умолчанию) оставляет от карточки только id, имя, статус, uri и
        применённую версию: полные карточки всего пространства – это десятки тысяч
        символов, которые в ответе агенту почти всегда лишние. brief=false отдаёт
        карточки целиком. env_file – путь к .env другого окружения.
        """
        apps = client(env_file).list_apps(name=name)
        if not brief:
            return apps
        return [brief_app(app) for app in apps if isinstance(app, dict)]

    @server.tool()
    def get_app(app_id: str, env_file: str = "") -> dict:
        """Карточка приложения: статус, uri, фактическая версия проекта (source.project-version). app_id – ид (UUID) либо точное имя приложения."""
        target = client(env_file)
        return target.get_app(target.resolve_app_id(app_id))

    @server.tool()
    def find_app(name: str, include_deleted: bool = False, env_file: str = "") -> dict:
        """Найти приложение по точному имени без учёта регистра; вернуть id и признак found.

        Удалённые приложения (статус Deleted) по умолчанию пропускаются: на их
        прежнем id get и deploy отвечают 404. include_deleted=True ищет среди
        всех приложений, включая удалённые.
        """
        app = client(env_file).find_app(name, include_deleted=include_deleted)
        if app is None:
            return {"id": None, "found": False}
        return {"id": app.get("id"), "found": True, "application": app}

    def _create_app(name, project_id, version_id, space_id, development_mode, env_file=""):
        """Create an application (the logic shared by create_app and ensure_app).

        The source is version_id (an assembly id) or the latest assembly of
        project_id (creating from a whole project can yield an empty skeleton).
        """
        source_version_id = version_id
        if not source_version_id:
            if not project_id:
                raise ElemctlError(i18n.t("mcp.project-or-version-required"))
            latest = client(env_file).latest_assembly(project_id)
            if latest is None:
                raise ElemctlError(
                    i18n.t("mcp.project-has-no-builds", project_id=project_id)
                )
            source_version_id = extract_assembly_id(latest)
        return client(env_file).create_app(
            name,
            project_version_id=source_version_id,
            development_mode=development_mode,
            space_id=space_id or None,
        )

    @server.tool()
    def create_app(
        name: str,
        project_id: str = "",
        version_id: str = "",
        space_id: str = "",
        development_mode: bool = True,
        env_file: str = "",
    ) -> dict:
        """Создать приложение. При задании только project_id источником берётся последняя сборка проекта (создание из проекта целиком может дать пустой каркас)."""
        return _create_app(name, project_id, version_id, space_id, development_mode, env_file)

    @server.tool()
    def ensure_app(
        name: str,
        project_id: str = "",
        version_id: str = "",
        space_id: str = "",
        development_mode: bool = True,
        env_file: str = "",
    ) -> dict:
        """Идемпотентно создать приложение по имени, если его ещё нет.

        Существующее приложение НЕ пересоздаётся: при наличии возвращается
        {"id": ..., "created": false} без изменений (delete + create дали бы
        новый URL и порвали внешние привязки – OIDC redirect и т.п.). Удалённые
        приложения (статус Deleted) не в счёт. Параметры создания – как у
        create_app; они действуют, только когда создание происходит.
        """
        existing = client(env_file).find_app(name)
        if existing is not None:
            return {"id": existing.get("id"), "created": False}
        card = _create_app(name, project_id, version_id, space_id, development_mode, env_file)
        return {"id": (card or {}).get("id"), "created": True}

    @server.tool()
    def start_app(app_id: str, env_file: str = "") -> dict:
        """Запустить приложение. app_id – ид (UUID) либо точное имя приложения."""
        target = client(env_file)
        resolved = target.resolve_app_id(app_id)
        return target.start_app(resolved) or {"ok": True, "app-id": resolved}

    @server.tool()
    def stop_app(app_id: str, env_file: str = "") -> dict:
        """Остановить приложение. app_id – ид (UUID) либо точное имя приложения."""
        target = client(env_file)
        resolved = target.resolve_app_id(app_id)
        return target.stop_app(resolved) or {"ok": True, "app-id": resolved}

    @server.tool()
    def debug_info(app_id: str, env_file: str = "") -> dict:
        """Данные для сессии отладки приложения: debug-token и debug-address.

        app_id – ид (UUID) либо точное имя приложения. Требует включённой
        отладки на сервере (config/debug.yml: enabled: true).
        """
        target = client(env_file)
        resolved = target.resolve_app_id(app_id)
        return target.get_debug_info(resolved) or {"app-id": resolved}

    @server.tool()
    def debug_adapter() -> dict:
        """Путь к debug-адаптеру платформы из плагина (для расширения VS Code).

        Каталог содержит подкаталог repo/ с jar-файлами адаптера – готовое значение
        настройки xbslDebug.adapterPath. Отсутствие плагина – это ответ (found: false),
        а не ошибка. Локальная операция, к платформе не обращается.
        """
        path = plugins.debug_adapter_path()
        if path is None:
            return {"path": None, "found": False}
        return {"path": str(path), "found": True, "adapter-class": plugins.ADAPTER_MAIN_CLASS}

    @server.tool()
    def delete_app(app_id: str, env_file: str = "") -> dict:
        """Удалить приложение. app_id – ид (UUID) либо точное имя (несколько совпадений – ошибка). НЕОБРАТИМО: данные теряются, а пересозданное приложение получит другой URL – внешние настройки (OIDC redirect и т.п.) придётся обновлять."""
        target = client(env_file)
        resolved = target.resolve_app_id(app_id)
        return target.delete_app(resolved) or {"deleted": True, "app-id": resolved}

    @server.tool()
    def list_spaces(env_file: str = "") -> list:
        """Список пространств."""
        return client(env_file).list_spaces()

    @server.tool()
    def list_projects(brief: bool = True, env_file: str = "") -> list:
        """Список проектов.

        brief (по умолчанию) оставляет от карточки id, имя, вид проекта,
        пространство, счётчик приложений и признак удаления; brief=false
        отдаёт карточки целиком. env_file – путь к .env другого окружения.
        """
        projects = client(env_file).list_projects()
        if not brief:
            return projects
        return [_brief_project(project) for project in projects if isinstance(project, dict)]

    @server.tool()
    def list_builds(project_id: str, env_file: str = "") -> list:
        """Список сборок проекта."""
        return client(env_file).list_assemblies(project_id)

    # The function name differs from the tool name so that it does not shadow
    # build_assembly imported from the build module.
    @server.tool(name="build_assembly")
    def build_assembly_tool(project_dir: str = "", output_dir: str = "", version: str = "") -> dict:
        """Локально собрать архив .xasm/.xlib из исходников проекта."""
        result = build_assembly(
            project_dir or None, output_dir=output_dir or None, version=version
        )
        return {"file": str(result.file), "version": result.version, "kind": result.kind}

    # The function name differs from the tool name for the same reason as build_assembly.
    @server.tool(name="inspect_assembly")
    def inspect_assembly_tool(file: str) -> dict:
        """Разобрать архив сборки (.xasm/.xlib): манифест, свойства проекта, подсистемы и глобальные типы с полными именами."""
        return inspect_assembly(file)

    @server.tool()
    def deploy(
        app_id: str,
        project_id: str,
        project_dir: str = "",
        version: str = "",
        branch: str = "",
        commit_message: str = "",
        env_file: str = "",
    ) -> dict:
        """Полный цикл деплоя из исходников с честной проверкой применения; итог – поле ok, детали – problems и log."""
        lines: list[str] = []
        report = deploy_from_sources(
            client(env_file),
            app_id,
            project_id,
            project_dir=project_dir or None,
            version=version,
            branch=branch or None,
            commit_message=commit_message,
            log=lines.append,
        )
        payload = report.to_dict()
        payload["log"] = lines
        return payload

    @server.tool()
    def probe(
        project_dir: str = "",
        space_id: str = "",
        keep: bool = False,
        env_file: str = "",
    ) -> dict:
        """Проверить компиляцию исходников серверным компилятором, НЕ трогая рабочее приложение.

        Собирает архив, заливает его без указания проекта (платформа сама кладёт
        сборку в проект этих исходников – он определяется поставщиком и именем),
        создаёт по ней одноразовое приложение – это и есть компиляция, – а затем
        убирает за собой приложение и сборку. ELEMENT_APP_ID и ELEMENT_PROJECT_ID
        окружения намеренно не используются. Итог – поле ok; ошибки в errors
        (файл, строка, колонка, окружение, текст), исходные сообщения платформы –
        в messages, итог уборки – в cleanup. keep=true оставляет приложение и
        сборку на стенде для разбора руками.
        """
        lines: list[str] = []
        report = probe_project(
            client(env_file),
            project_dir=project_dir or None,
            space_id=space_id or None,
            keep=keep,
            log=lines.append,
        )
        payload = report.to_dict()
        payload["log"] = lines
        return payload

    @server.tool()
    def apply_build(app_id: str, version_id: str, env_file: str = "") -> dict:
        """Применить загруженную сборку (по id) к приложению; после применения проверьте итог инструментом verify_deploy."""
        response = client(env_file).apply_build(app_id, image_id=version_id)
        return response or {"ok": True, "app-id": app_id, "version-id": version_id}

    @server.tool()
    def verify_deploy(
        app_id: str,
        expected_version: str = "",
        expected_assembly_id: str = "",
        since_minutes: int = 30,
        env_file: str = "",
    ) -> dict:
        """Проверить фактическое применение сборки: задачи с ошибками за последние since_minutes минут, сверка применённой сборки (надёжно - по expected_assembly_id, строка версии - запасной вариант), доступность uri."""
        since = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        report = _verify_deploy(
            client(env_file),
            app_id,
            expected_version=expected_version,
            expected_assembly_id=expected_assembly_id,
            since=since,
        )
        return report.to_dict()

    @server.tool()
    def list_app_tasks(app_id: str = "", env_file: str = "") -> list:
        """Задачи приложений; app_id – необязательный фильтр (выполняется на клиенте)."""
        return client(env_file).list_app_tasks(app_id)

    @server.tool()
    def list_branches(project_id: str = "", name: str = "", env_file: str = "") -> list:
        """Список веток среды разработки; фильтры project_id и name необязательны."""
        return client(env_file).list_branches(project_id=project_id, name=name)

    @server.tool()
    def merge_branch(branch_id: str, env_file: str = "") -> dict:
        """Принять изменения ветки среды разработки (merge)."""
        return client(env_file).merge_branch(branch_id) or {"merged": True, "branch-id": branch_id}

    add_plugin_tools(server, client)
    return server


def _plugin_tool(command, client_for_env):
    """Build the MCP tool function of a plugin command.

    FastMCP derives the schema of a tool from the signature of the function, and
    the signature here is only known at runtime – so it is assembled by hand out
    of the declared arguments (checked against a live FastMCP: the schema comes
    out with the types and the defaults in place). env_file is added by the core
    to every such tool, exactly like the tools of the core have it.
    """
    parameters = [
        inspect.Parameter(
            argument.dest,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=argument.type,
            default=argument.value_default,
        )
        for argument in command.arguments
    ]
    parameters.append(
        inspect.Parameter("env_file", inspect.Parameter.KEYWORD_ONLY, annotation=str, default="")
    )

    def tool(**values):
        env_file = values.pop("env_file", "")
        lines: list[str] = []
        target = client_for_env(env_file)
        context = plugins.CommandContext(target.config, client=target, log=lines.append)
        result = command.handler(context, **values)
        if isinstance(result, dict):
            return {**result, "log": lines}
        return result

    tool.__name__ = command.tool_name
    tool.__doc__ = command.help
    tool.__signature__ = inspect.Signature(parameters)
    tool.__annotations__ = {p.name: p.annotation for p in parameters}
    return tool


def _registered_tool_names(server):
    """The names of the tools already registered on the server.

    FastMCP has no synchronous public listing (its list_tools is a coroutine), so
    the tool manager is asked directly. A version that renames it must not break
    the server – hence the fallback to an empty set: a clash would then be left
    to FastMCP itself.
    """
    lister = getattr(getattr(server, "_tool_manager", None), "list_tools", None)
    if lister is None:
        return set()
    return {tool.name for tool in lister()}


def add_plugin_tools(server, client_for_env):
    """Register the commands the plugins bring as tools of the server.

    A name already taken by a tool of the core is an error rather than a silent
    override – the same rule the CLI subcommands follow.
    """
    taken = _registered_tool_names(server)
    for command in plugins.plugin_commands():
        if not command.mcp:
            continue
        if command.tool_name in taken:
            raise PluginError(i18n.t(
                "plugins.tool-name-taken", where=command.source, name=command.tool_name
            ))
        taken.add(command.tool_name)
        server.add_tool(
            _plugin_tool(command, client_for_env),
            name=command.tool_name,
            description=command.help,
        )


def main(config=None):
    """Start the MCP server on stdio.

    config – a ready configuration (the one the CLI assembled from --env-file
    and the rest of the global arguments, for instance); without it the
    configuration is assembled from the environment variables and .env on the
    first call to the platform.
    """
    create_server(config).run()


if __name__ == "__main__":
    main()
