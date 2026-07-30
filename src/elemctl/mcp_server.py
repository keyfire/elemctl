"""The elemctl MCP server: platform operations as tools for AI agents.

The transport is stdio; the connection credentials come from the ELEMENT_*
environment variables or from the .env file in the current directory. Requires
the optional extra "elemctl[mcp]" (the mcp package, either major version).
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

# The whole difference between the two majors of the mcp package lives here.
#
# mcp 2.0 renamed the ergonomic server class and moved it: FastMCP from
# mcp.server.fastmcp became MCPServer in mcp.server.mcpserver, and the old
# module is gone rather than aliased – an untouched server meets the rename as
# a ModuleNotFoundError the moment the environment resolves mcp to 2.x. What
# the server itself uses of the class did not change: the constructor keyword
# "instructions", the @tool()/add_tool() registration with the same arguments,
# and run() over stdio. The one constructor trap is positional – 2.x inserts
# title and description before instructions – and it is avoided by passing
# instructions by keyword, which create_server does.
#
# The reading side did change, and that is what tool_input_schema and
# call_result_content below are for: in 2.x the wire types come from the
# mcp-types package with snake_case fields (inputSchema -> input_schema), and
# call_tool answers with a CallToolResult instead of a bare list of content
# blocks. Anything that reads a listing or a call result – the tests, an
# embedder driving the server in process – goes through those two helpers
# instead of forking on the version again.
try:
    from mcp.server.mcpserver import MCPServer as McpServer  # mcp 2.x
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as McpServer  # mcp 1.x
    except ImportError as error:  # neither home – the extra is not installed
        raise ImportError(
            'the MCP server needs the extra: pip install "elemctl[mcp]"'
        ) from error

from . import __version__, i18n, plugins
from .build import build_assembly, inspect_assembly
from .client import ElementClient, brief_app, extract_assembly_id, sign_in_hint
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


def tool_input_schema(tool):
    """The JSON schema of a tool taken from a list_tools() listing.

    mcp 1.x spells the field inputSchema, mcp 2.x spells it input_schema (the
    JSON on the wire stays camelCase either way – only the Python attribute
    changed). An absent schema comes back as an empty dictionary.
    """
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = getattr(tool, "inputSchema", None)
    return schema or {}


def call_result_content(result):
    """The content blocks of a call_tool() answer, as a list.

    mcp 1.x hands back the blocks themselves, mcp 2.x wraps them into a
    CallToolResult whose .content holds them.
    """
    content = getattr(result, "content", None)
    if content is None:
        return list(result)
    return list(content)


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
    # instructions goes by keyword on purpose: mcp 2.x inserted title and
    # description before it in the positional order. The version parameter is
    # 2.x only, and without it serverInfo comes out with an empty version there
    # (1.x had no such parameter and stamped the version of the mcp package
    # itself) – so it is passed wherever the class accepts it.
    options = {"instructions": INSTRUCTIONS}
    if "version" in inspect.signature(McpServer).parameters:
        options["version"] = __version__
    server = McpServer("elemctl", **options)
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
        """Создать приложение. При задании только project_id источником берётся последняя сборка проекта (создание из проекта целиком может дать пустой каркас).

        К карточке добавляется поле sign-in – способ войти в новое приложение:
        адрес и учётная запись ПАНЕЛИ УПРАВЛЕНИЯ (учётные записи, которыми
        входят в другие приложения, в новом не работают).
        """
        card = _create_app(name, project_id, version_id, space_id, development_mode, env_file)
        if not isinstance(card, dict):
            return card
        return {**card, "sign-in": sign_in_hint(card)}

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

        Поле sign-in обоих ответов говорит, как войти в приложение: адрес и
        учётная запись ПАНЕЛИ УПРАВЛЕНИЯ (учётные записи, которыми входят в
        другие приложения, в новом не работают).
        """
        existing = client(env_file).find_app(name)
        if existing is not None:
            return {
                "id": existing.get("id"),
                "created": False,
                "sign-in": sign_in_hint(existing),
            }
        card = _create_app(name, project_id, version_id, space_id, development_mode, env_file)
        return {
            "id": (card or {}).get("id"),
            "created": True,
            "sign-in": sign_in_hint(card),
        }

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
            # Both ids are required parameters of the tool, so they are always explicit.
            app_id_source="flag",
            project_id_source="flag",
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
    def list_user_lists(name: str = "", env_file: str = "") -> list:
        """Списки пользователей; name – фильтр по подстроке представления (на клиенте).

        Собственный список приложения назван по нему же ("Список пользователей
        приложения ..."), список панели управления – один на стенд.
        """
        return client(env_file).list_user_lists(name=name)

    @server.tool()
    def configure_user_list(
        list_id: str = "",
        app_id: str = "",
        self_registration: bool | None = None,
        password_login: bool | None = None,
        env_file: str = "",
    ) -> dict:
        """Настройки входа списка пользователей: самостоятельная регистрация и вход по паролю.

        Список задаётся list_id (ид либо точное представление) ЛИБО app_id –
        тогда берётся собственный список приложения. Оба флага необязательны:
        без них команда только показывает состояние, поэтому её же удобно звать
        для проверки. За "входом по логину и паролю" стоит сервис учётных
        записей типа Local; список без такого сервиса – не ошибка, в ответе
        password-login-enabled будет null. Состав ФОРМ аутентификации в Console
        API не живёт вовсе – он остаётся ручным.
        """
        target = client(env_file)
        if list_id and app_id:
            raise ElemctlError(i18n.t("cli.user-list-source-conflict"))
        if app_id:
            resolved = target.app_user_list_id(app_id)
        elif list_id:
            resolved = target.resolve_user_list_id(list_id)
        else:
            raise ElemctlError(i18n.t("cli.user-list-required"))

        changed = []
        if self_registration is not None:
            target.set_self_registration(resolved, enabled=self_registration)
            changed.append("self-registration")
        if password_login is not None:
            outcome = target.set_password_login(resolved, enabled=password_login)
            if outcome["changed"]:
                changed.append("password-login")

        local = next(
            (
                service for service in target.list_account_services(resolved)
                if isinstance(service, dict)
                and str(service.get("account-service-type") or "").lower() == "local"
            ),
            None,
        )
        return {
            "list-id": resolved,
            "self-registration-enabled": bool(
                (target.get_self_registration(resolved) or {}).get("enabled")
            ),
            "password-login-enabled": None if local is None else bool(local.get("enabled")),
            "changed": changed,
        }

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

    The server derives the schema of a tool from the signature of the function,
    and the signature here is only known at runtime – so it is assembled by hand
    out of the declared arguments (checked against a live server of either major
    version: the schema comes out with the types and the defaults in place).
    env_file is added by the core to every such tool, exactly like the tools of
    the core have it.
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

    Neither major version has a synchronous public listing (list_tools is a
    coroutine in both), so the tool manager is asked directly. A version that
    renames it must not break the server – hence the fallback to an empty set:
    a clash would then be left to the server class itself.
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
