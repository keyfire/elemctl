"""The elemctl MCP server: platform operations as tools for AI agents.

The transport is stdio; the connection credentials come from the ELEMENT_*
environment variables or from the .env file in the current directory. Requires
the optional extra "elemctl[mcp]" (the mcp package, either major version).
"""

from __future__ import annotations

import inspect
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The whole difference between the two majors of the mcp package lives here.
#
# mcp 2.0 renamed the ergonomic server class and moved it: FastMCP from
# mcp.server.fastmcp became MCPServer in mcp.server.mcpserver, and the old
# module is gone rather than aliased - an untouched server meets the rename as
# a ModuleNotFoundError the moment the environment resolves mcp to 2.x. What
# the server itself uses of the class did not change: the constructor keyword
# "instructions", the @tool()/add_tool() registration with the same arguments,
# and run() over stdio. The one constructor trap is positional - 2.x inserts
# title and description before instructions - and it is avoided by passing
# instructions by keyword, which create_server does.
#
# The reading side did change, and that is what tool_input_schema and
# call_result_content below are for: in 2.x the wire types come from the
# mcp-types package with snake_case fields (inputSchema -> input_schema), and
# call_tool answers with a CallToolResult instead of a bare list of content
# blocks. Anything that reads a listing or a call result - the tests, an
# embedder driving the server in process - goes through those two helpers
# instead of forking on the version again.
try:
    from mcp.server.mcpserver import MCPServer as McpServer  # mcp 2.x
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as McpServer  # mcp 1.x
    except ImportError as error:  # neither home - the extra is not installed
        raise ImportError(
            'the MCP server needs the extra: pip install "elemctl[mcp]"'
        ) from error

from . import __version__, i18n, plugins
from .build import build_assembly, inspect_assembly
from .client import (
    SERVER_START_TIMEOUT,
    ElementClient,
    app_users_summary,
    applied_build,
    apps_summary,
    assembly_label,
    brief_app,
    brief_assemblies,
    build_owner,
    builds_summary,
    extract_assembly_id,
    is_extension_project,
    project_label,
    repeated_values,
    sign_in_hint,
    token_access_each,
)
from .config import Config
from .deploy import (
    deploy_from_sources,
    running_build,
    verify_deploy as _verify_deploy,
)
from .errors import ApiError, ElemctlError, PluginError
from .probe import cleanup_probe, cleanup_probes, probe_project
from .versions import newest_first

INSTRUCTIONS = (
    (
    "Инструменты управления сервером 1С:Элемент через Console API v2. При ошибке применения "
    "сервер без сообщения откатывает приложение на предыдущую сборку и запускает его; статус "
    "Running не подтверждает деплой. Проверяйте отчет deploy/verify_deploy: ok, problems и "
    "совпадение примененной сборки с загруженной, надежнее по applied-version-id. Сервер нумерует "
    "сборку, загруженную в проект: берет базовую Версию проекта и увеличивает на единицу "
    "наибольший выданный номер, включая удаленные сборки. Версия архива может не сохраниться; "
    "назначенная версия и изменение номера указаны в assembly-version и renumbered отчета deploy. "
    "build_assembly, deploy, probe, probe_cleanup, apply_build, create_app, ensure_app, "
    "delete_app и merge_branch могут выполняться минутами и блокируют MCP-вызов до завершения. "
    "Запускайте долгие операции CLI-командой elemctl в фоновом процессе агента, например через "
    "run_in_background; результат придет уведомлением. Для быстрых операций чтения используйте "
    "MCP-инструменты list_apps, get_app, find_app, list_builds и verify_deploy. По умолчанию "
    "используется окружение запуска сервера. Для другого стенда передайте путь к его .env в "
    "env_file; параметр доступен инструментам, обращающимся к серверу. build_assembly и "
    "inspect_assembly работают локально: они не используют окружение сервера и не занимают номер "
    "версии на сервере."
)
)


def tool_input_schema(tool):
    """The JSON schema of a tool taken from a list_tools() listing.

    mcp 1.x spells the field inputSchema, mcp 2.x spells it input_schema (the
    JSON on the wire stays camelCase either way - only the Python attribute
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
    dates - all of it redundant in a listing. The application counter is kept: it
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


#: Fields of overrides that name a stand's identity rather than a process-wide setting. They
#: apply only to a call that leaves out its own env_file (see create_server) - a call naming a
#: different stand explicitly is built from that stand's own file, the same as it always was.
_IDENTITY_OVERRIDE_KEYS = ("base_url", "client_id", "client_secret")


def _env_file_signature(path):
    """A cheap fingerprint of a .env file: its modification time, paired with the size for
    when a filesystem's clock is too coarse to tell two quick edits apart on its own.

    None means there is nothing at the path. A client built with no file behind it is cached
    under that same None, and a file that later appears there invalidates it exactly like an
    edit would - the signature only ever fails to change when the path keeps missing.

    What it will NOT notice: a file that turns unreadable without being edited, a permission
    change on the file itself rather than a rewrite of it, leaves both the modification time
    and the size exactly where they were, so the cache goes on handing back the client that
    last read the file successfully instead of ever attempting the read that would now fail.
    Left unfixed on purpose. Catching it would mean opening the file on every lookup instead
    of only on a change - paying that cost on every call of a session for the one call an
    edit actually touches - and even a lighter version, folding the POSIX mode bits into the
    signature, would still miss the same change on Windows, where read access is an ACL
    question os.stat does not surface at all; a fix that works on one platform elemctl runs
    on and not the other would be worse than none, standing as unearned reassurance. elemctl
    is a single operator's own tool over their own stand's file, not a boundary between
    untrusted parties, and the promise this cache makes is about the file getting EDITED - a
    permission flip with no edit at all is the rare case left outside it. Should it happen
    anyway, the fallback is the safe direction: the stand keeps working on the configuration
    last proven to read correctly, rather than a call failing over a file that has not, from
    the cache's own point of view, changed.
    """
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def _release_client(client):
    """Let an outgoing client give up whatever it holds, if it holds anything at all.

    ElementClient opens no lasting connection today - the transport is plain urllib, opened and
    closed per request - so this is a no-op in practice. It stays here so that a future
    transport which DOES keep a session is not leaked the moment its cache entry is replaced by
    the client of an edited file.
    """
    closer = getattr(client, "close", None)
    if callable(closer):
        closer()


def create_server(config=None, *, overrides=None, env_file=None):
    """Create the elemctl MCP server with all of its tools.

    Two ways to seed the connection, not meant to be combined:

    config - a ready configuration handed in programmatically (library use: an application
    embedding elemctl already built one). It is pinned for every call without its own
    env_file, for the life of the process - it has no file behind it for the cache below to
    watch, unlike the other path.

    overrides / env_file - what the CLI passes instead (cli.cmd_mcp checks an explicit
    env_file exists before the server ever starts, then hands it on as a path, unresolved).
    base_url, client_id and client_secret in overrides name the stand at the startup address,
    so they apply only to a call that leaves out its own env_file - a call naming a different
    stand explicitly is built from that stand's own file alone, exactly as it was before these
    parameters existed. timeout is a process-wide setting instead, not a stand's own, and is
    layered onto every call regardless. env_file is --env-file itself, if given; without one,
    a call that leaves out its own env_file falls back to the .env of the current directory.
    Either way that call is cached by its resolved path and a signature of the file (its
    modification time and size), rebuilt on an edit rather than on every call.

    Without any of the three, the configuration is assembled from the environment variables
    and the .env of the current directory the first time a call needs it.
    """
    # instructions goes by keyword on purpose: mcp 2.x inserted title and
    # description before it in the positional order. The version parameter is
    # 2.x only, and without it serverInfo comes out with an empty version there
    # (1.x had no such parameter and stamped the version of the mcp package
    # itself) - so it is passed wherever the class accepts it.
    options = {"instructions": INSTRUCTIONS}
    if "version" in inspect.signature(McpServer).parameters:
        options["version"] = __version__
    server = McpServer("elemctl", **options)
    state = {
        "clients": {},
        "config": config,
        "overrides": overrides or {},
        "default_env_file": env_file or None,
    }
    # Guards every read and write of state["clients"] below: a lookup that finds the cache
    # stale and the build-and-store that follows it have to run as one step, or two callers
    # racing for the same stand can both find it stale, each build their own client, and
    # overwrite one another's entry - the one that loses is never closed. Every tool call
    # runs to completion before the next one starts today, the mcp package dispatches them
    # one at a time over stdio, so nothing exercises the race yet; the lock is what keeps
    # that guarantee true if a future async or threaded dispatcher changes how calls arrive.
    clients_lock = threading.Lock()

    def client(env_file: str = ""):
        """A platform client for the requested environment.

        Without env_file and a configuration the server started with - that configuration,
        pinned for the life of the process (see create_server). Otherwise - a client for
        env_file, or without one the server's own default (--env-file at startup, or the
        .env of the current directory), cached under the resolved path together with a
        signature of that file (its modification time and size). An edit changes the
        signature, so the next call for the same path builds a fresh client instead of
        handing back the one that read the file before the edit; a stand's own
        ELEMCTL_NO_PROXY switch, say, takes effect on the next call rather than needing a
        restart. base_url, client_id and client_secret given at startup apply only to THIS
        call, the one without its own env_file - a call naming its own env_file is built from
        that file alone, the same as it was before these overrides existed; only timeout, a
        process-wide setting, still follows it. An env_file (or the server's own --env-file)
        that stops resolving to a file surfaces the same clear error Config.from_env always
        gave it, instead of the cache quietly going on with the last client that worked; the
        bare .env of the current directory has no such guarantee - nothing named it, and
        Config.from_env has always treated a missing one as no file at all.

        Called at most once per tool call (see _create_app), and everything from the lookup
        to the store below runs under clients_lock, so one call never sees a client built
        for another, concurrent one, however either is dispatched.
        """
        with clients_lock:
            if not env_file and state["config"] is not None:
                cached = state["clients"].get(None)
                if cached is None:
                    cached = (None, ElementClient(state["config"]))
                    state["clients"][None] = cached
                return cached[1]

            is_default_call = not env_file
            target = env_file or state["default_env_file"]
            overrides = state["overrides"]
            if is_default_call:
                applied = overrides
            else:
                applied = {"timeout": overrides["timeout"]} if overrides.get("timeout") else {}

            resolved = str(Path(target or ".env").resolve())
            # An identity override (see _IDENTITY_OVERRIDE_KEYS) applies only to the default
            # call, so it is the one thing that can make the default call and an explicit call
            # naming the very same path build two DIFFERENT configurations - the cache key
            # then has to keep them apart, or whichever call runs first would hand its answer
            # to the other. Without one, the two builds are identical and the plain resolved
            # path is left as the key, the shape that lets a.env, ./a.env and the no-env_file
            # call share one entry.
            has_identity_override = any(overrides.get(k) for k in _IDENTITY_OVERRIDE_KEYS)
            cache_key = (
                (resolved, "startup-identity") if is_default_call and has_identity_override
                else resolved
            )

            signature = _env_file_signature(resolved)
            cached = state["clients"].get(cache_key)
            if cached is not None and cached[0] == signature:
                return cached[1]

            new_client = ElementClient(Config.from_env(env_file=target or None, **applied))
            # The client being replaced is released AFTER the new one is stored, not before:
            # close() is foreign code (a future transport's own session teardown, say), and an
            # exception out of it must not cost the cache its already-built replacement. Store
            # first, so a failed close only fails the close - the next call still finds the
            # new, working client instead of retrying the same close on the one that just
            # failed it.
            previous = cached[1] if cached is not None else None
            state["clients"][cache_key] = (signature, new_client)
            if previous is not None:
                _release_client(previous)
            return new_client

    @server.tool()
    def list_apps(
        name: str = "",
        status: str = "",
        include_deleted: bool = False,
        brief: bool = True,
        env_file: str = "",
    ) -> dict:
        """Список приложений. Ответ: {total, live, shown, summary, applications}.

        Удаленные приложения со статусом Deleted по умолчанию исключены, хотя сервер
        сохраняет их в перечне с прежним id. total - число полученных карточек, live -
        число неудаленных, shown - число карточек в ответе, summary - текстовая сводка
        ("живых N из M"). include_deleted=true включает удаленные приложения.

        name фильтрует подстроку имени без учета регистра на клиенте, поскольку сервер
        игнорирует query-параметр. status фильтрует статус целиком (Running, Stopped,
        Error, Deleted); несколько статусов разделяются запятой. Явный статус Deleted
        также включает удаленные приложения.

        brief по умолчанию оставляет id, имя, статус, uri и примененную версию;
        brief=false возвращает полные карточки. env_file - путь к .env другого окружения.
        """
        listing = client(env_file).list_apps_counted(
            name=name, status=status, include_deleted=include_deleted
        )
        apps = listing["items"]
        if brief:
            apps = [brief_app(app) for app in apps if isinstance(app, dict)]
        return {
            "total": listing["total"],
            "live": listing["live"],
            "shown": listing["shown"],
            "summary": apps_summary(listing),
            "applications": apps,
        }

    @server.tool()
    def get_app(app_id: str, env_file: str = "") -> dict:
        """Карточка приложения: статус, uri, фактическая версия проекта (source.project-version). app_id - ид (UUID) либо точное имя приложения.

        Поле applied-build - краткая карточка примененной сборки: ветка и коммит (из
        карточки сборки, а если платформа их не заполнила - из локального реестра
        загрузок этой машины; источник назван полями branch-name-source и
        commit-id-source), а из реестра еще dirty (были ли незакоммиченные правки) и
        project-dir (каталог исходников). Сборки, загруженные с другой машины или из
        CI, реестру не известны.
        """
        target = client(env_file)
        card = target.get_app(target.resolve_app_id(app_id))
        if isinstance(card, dict):
            card = {**card, "applied-build": applied_build(target, card)}
        return card

    @server.tool()
    def find_app(name: str, include_deleted: bool = False, env_file: str = "") -> dict:
        """Найти приложение по точному имени без учета регистра; вернуть id и признак found.

        Удаленные приложения (статус Deleted) по умолчанию пропускаются: на их
        прежнем id get и deploy отвечают 404. include_deleted=True ищет среди
        всех приложений, включая удаленные.
        """
        app = client(env_file).find_app(name, include_deleted=include_deleted)
        if app is None:
            return {"id": None, "found": False}
        return {"id": app.get("id"), "found": True, "application": app}

    def _create_app(
        target, name, project_id, version_id, space_id, development_mode, verify=False
    ):
        """Create an application (the logic shared by create_app and ensure_app).

        target is the caller's own client(env_file), resolved once and handed in rather than
        resolved again here - latest_assembly, create_app, wait_app_ready and the client
        verify takes are up to four separate steps of one call, and each used to call
        client(env_file) on its own, so a file edited mid-call could in principle hand two of
        them two different clients. One resolution per tool call rules that out.

        The source is version_id (an assembly id) or the latest assembly of
        project_id (creating from a whole project can yield an empty skeleton).
        Returns (card, report, broken): with verify it waits for the application
        and checks that the assembly asked for is the one it really runs, otherwise
        report is None. broken is the error that ended the wait or the check: the
        application exists once the create has answered, so its card is returned
        beside the error rather than lost with it.
        """
        source_version_id = version_id
        if version_id:
            # The same check the CLI makes: a build the platform has deleted is named as such
            # before the create answers a bare 400. The project falls back to the stand's own
            # ELEMENT_PROJECT_ID, the way the CLI takes it from the environment, and that
            # default gives way to the project the build is in.
            stand_project = getattr(getattr(target, "config", None), "project_id", "") or ""
            if project_id or stand_project:
                _source_project(
                    target, project_id or stand_project, version_id,
                    project_from_env=not project_id,
                )
        if not source_version_id:
            if not project_id:
                raise ElemctlError(i18n.t("mcp.project-or-version-required"))
            latest = target.latest_assembly(project_id)
            if latest is None:
                raise ElemctlError(
                    i18n.t("mcp.project-has-no-builds", project_id=project_id)
                )
            source_version_id = extract_assembly_id(latest)
        started_at = datetime.now(timezone.utc)
        card = target.create_app(
            name,
            project_version_id=source_version_id,
            development_mode=development_mode,
            space_id=space_id or None,
        )
        if not verify:
            return card, None, None
        app_id = (card or {}).get("id")
        if not app_id:
            return card, None, None
        try:
            card = target.wait_app_ready(app_id)
            report = _verify_deploy(
                target,
                app_id,
                expected_assembly_id=source_version_id or "",
                since=started_at,
            )
        except ElemctlError as error:
            return card, None, error
        return card, report, None

    @server.tool()
    def create_app(
        name: str,
        project_id: str = "",
        version_id: str = "",
        space_id: str = "",
        development_mode: bool = True,
        verify: bool = False,
        env_file: str = "",
    ) -> dict:
        """Создать приложение. Если задан только project_id, источником служит последняя
        сборка проекта: создание из проекта целиком может дать пустой каркас.

        До создания version_id ищется в сборках project_id или, если он не задан,
        ELEMENT_PROJECT_ID стенда. Если сборка не найдена, инструмент ищет ее в других
        проектах. Проект по умолчанию может быть заменен проектом сборки; при явно
        заданном project_id инструмент возвращает ошибку с проектом сборки. Если сборки
        нет ни в одном проекте, инструмент сообщает об удалении до запроса на создание.

        verify=True ожидает готовности и проверяет примененную сборку. При неудачном
        применении сервер может без сообщения откатить сборку; статус Running не
        подтверждает успех. Отчет находится в поле verify (ok, problems,
        applied-version-id). Ожидание может занимать минуты; для длительного вызова
        используйте фоновую CLI-команду elemctl.

        Поле sign-in содержит адрес и учетную запись панели управления. Учетные записи
        других приложений не работают в новом приложении. Если ожидание прервано,
        приложение остается созданным: ответ содержит его карточку с id и wait-error
        с причиной.
        """
        card, report, broken = _create_app(
            client(env_file), name, project_id, version_id, space_id, development_mode, verify
        )
        if not isinstance(card, dict):
            return card
        answer = {**card, "sign-in": sign_in_hint(card)}
        if report is not None:
            answer["verify"] = report.to_dict()
        if broken is not None:
            answer["wait-error"] = _error_payload(broken)
        return answer

    @server.tool()
    def ensure_app(
        name: str,
        project_id: str = "",
        version_id: str = "",
        space_id: str = "",
        development_mode: bool = True,
        verify: bool = False,
        env_file: str = "",
    ) -> dict:
        """Создать приложение по имени, если его еще нет.

        Существующее приложение не пересоздается: ответ содержит
        {"id": ..., "created": false}. Удаленные приложения со статусом Deleted
        исключены из поиска. Параметры создания, как у create_app, действуют только
        при создании. Удаление и повторное создание изменили бы URL и внешние привязки,
        например OIDC redirect.

        version_id не применяется к существующему приложению. Поле applied показывает,
        работает ли приложение на запрошенной сборке, а applied-version-id содержит
        идентификатор фактической сборки. Для применения используйте apply_build или
        CLI-команду elemctl apps apply.

        Карточка приложения указывает только его собственную сборку. Если искомой сборки
        в ней нет, инструмент ищет ее среди проектов расширений и сверяет с расширениями
        приложения через Console API 2.1, как verify_deploy. applied-version-id тогда
        обозначает сборку расширения, а extension-project-id и extension содержат проект
        и запись расширения. Без Console API 2.1 результат проверки - applied: null.

        verify=True запускает полную проверку нового приложения после ожидания готовности.
        Для существующего приложения она выполняется, когда указан version_id и сборка
        уже определена как примененная. Отчет находится в поле verify. Сервер может без
        сообщения откатить неудачное применение; статус Running не подтверждает успех.
        Ожидание готовности может занимать минуты.

        Поле sign-in содержит адрес и учетную запись панели управления. Учетные записи
        других приложений не работают в новом приложении. Если ожидание создания прервано,
        ответ сохраняет id приложения; applied равен null, причина указана в wait-error.
        """
        started_at = datetime.now(timezone.utc)
        target = client(env_file)
        existing = target.find_app(name)
        if existing is not None:
            answer = {
                "id": existing.get("id"),
                "created": False,
                "sign-in": sign_in_hint(existing),
            }
            if version_id:
                answer.update(running_build(
                    target, str(existing.get("id") or ""), version_id, card=existing
                ).fields())
                if verify and answer["applied"]:
                    report = _verify_deploy(
                        target,
                        str(existing.get("id") or ""),
                        expected_assembly_id=version_id,
                        since=started_at,
                    )
                    answer["applied"] = bool(report.ok)
                    answer["verify"] = report.to_dict()
            return answer
        card, report, broken = _create_app(
            target, name, project_id, version_id, space_id, development_mode, verify
        )
        answer = {
            "id": (card or {}).get("id"),
            "created": True,
            "applied": None if broken is not None else (
                True if report is None else bool(report.ok)
            ),
            "sign-in": sign_in_hint(card),
        }
        if report is not None:
            answer["verify"] = report.to_dict()
        if broken is not None:
            answer["wait-error"] = _error_payload(broken)
        return answer

    @server.tool()
    def start_app(app_id: str, env_file: str = "") -> dict:
        """Запустить приложение. app_id - ид (UUID) либо точное имя приложения."""
        target = client(env_file)
        resolved = target.resolve_app_id(app_id)
        return target.start_app(resolved) or {"ok": True, "app-id": resolved}

    @server.tool()
    def stop_app(app_id: str, env_file: str = "") -> dict:
        """Остановить приложение. app_id - ид (UUID) либо точное имя приложения."""
        target = client(env_file)
        resolved = target.resolve_app_id(app_id)
        return target.stop_app(resolved) or {"ok": True, "app-id": resolved}

    @server.tool()
    def debug_info(app_id: str, env_file: str = "") -> dict:
        """Данные для сессии отладки приложения: debug-token и debug-address.

        app_id - ид (UUID) либо точное имя приложения. Требует включенной
        отладки на сервере (config/debug.yml: enabled: true).
        """
        target = client(env_file)
        resolved = target.resolve_app_id(app_id)
        return target.get_debug_info(resolved) or {"app-id": resolved}

    @server.tool()
    def debug_adapter() -> dict:
        """Путь к debug-адаптеру 1С:Элемент из плагина для расширения VS Code.

        Каталог содержит подкаталог repo/ с jar-файлами адаптера и подходит для настройки
        xbsl.debug.adapterPath. При отсутствии плагина возвращается found: false.
        Операция локальная и не обращается к серверу.
        """
        path = plugins.debug_adapter_path()
        if path is None:
            return {"path": None, "found": False}
        return {"path": str(path), "found": True, "adapter-class": plugins.ADAPTER_MAIN_CLASS}

    @server.tool()
    def delete_app(app_id: str, env_file: str = "") -> dict:
        """Удалить приложение. app_id - ид (UUID) либо точное имя (несколько совпадений - ошибка). Операция необратима: данные удаляются, а пересозданное приложение получит другой URL - внешние настройки (OIDC redirect и т.п.) придется обновлять."""
        target = client(env_file)
        resolved = target.resolve_app_id(app_id)
        return target.delete_app(resolved) or {"deleted": True, "app-id": resolved}

    @server.tool()
    def list_spaces(env_file: str = "") -> list:
        """Список пространств."""
        return client(env_file).list_spaces()

    @server.tool()
    def list_projects(
        name: str = "", include_deleted: bool = False, brief: bool = True, env_file: str = ""
    ) -> list:
        """Список проектов. name фильтрует подстроку имени без учета регистра на клиенте:
        сервер возвращает полный перечень.

        Удаленные проекты с признаком deleted по умолчанию исключены;
        include_deleted=true включает их в ответ. brief по умолчанию оставляет id,
        имя, вид проекта, пространство, счетчик приложений и признак удаления;
        brief=false возвращает полные карточки. env_file - путь к .env другого окружения.
        """
        projects = client(env_file).list_projects(name=name, include_deleted=include_deleted)
        if not brief:
            return projects
        return [_brief_project(project) for project in projects if isinstance(project, dict)]

    @server.tool()
    def list_builds(
        project_id: str, limit: int = 10, brief: bool = True, env_file: str = ""
    ) -> dict:
        """Сборки проекта, от новых к старым. Ответ: {total, shown, summary, builds}.

        Сервер удаляет сборки, которыми никто не пользуется, когда приложение
        заканчивает применение сборки, независимо от возраста. Сохраняются сборка работающего приложения, сборка с
        наибольшим номером базы, релизная и загруженные без id проекта, включая первую
        сборку проекта. Перечень не имеет страниц и может содержать не всю историю.
        total - число сборок в ответе сервера, shown - число после limit; summary
        описывает ограничение и наличие пропусков в нумерации.

        Сервер нумерует сборки одной базовой версии подряд. Пропуск может означать
        удаление или скачок номера при загрузке без id проекта, которая сохраняет номер
        архива. Для такой загрузки с этой машины локальный реестр позволяет назвать
        скачок. Если внутри пропуска есть другая загрузка этой машины в проект, summary
        указывает и скачок, и удаление. Автоматическая очистка не удаляет сборки
        проекта-расширения; они остаются до удаления вручную, что указано в summary.

        limit задает число карточек (по умолчанию 10, 0 - все). brief по умолчанию
        оставляет id, версии, дату, ветку и коммит. Если сервер не вернул ветку или
        коммит, они берутся из локального реестра этой машины; branch-name-source и
        commit-id-source указывают platform, registry или null. Из реестра также
        добавляются dirty и project-dir: наличие незакоммиченных правок и каталог
        исходников. Реестр не содержит сборки с других машин и из CI. brief=false
        возвращает полные карточки. env_file - путь к .env другого окружения.
        """
        target = client(env_file)
        assemblies = newest_first(target.list_assemblies(project_id))
        shown = assemblies[:limit] if limit > 0 else assemblies
        cards = brief_assemblies(shown) if brief else shown
        return {
            "total": len(assemblies),
            "shown": len(cards),
            # The whole answer is what the verdict is read off - the numbering of every
            # card the platform returned, not of the ones that survived the limit. An
            # extension project is outside the housekeeping, and the line says so for one.
            "summary": builds_summary(
                assemblies, len(cards), extension=is_extension_project(target, project_id)
            ),
            "builds": cards,
        }

    @server.tool()
    def get_build(project_id: str, version: str, env_file: str = "") -> dict:
        """Карточка сборки проекта целиком; version - ВЕРСИЯ сборки (`1.0-42`), ид тоже принимается.

        Метод платформы - `/projects/{id}/assemblies/{version}`, и последний сегмент
        адреса он называет версией: ид карточки адресом не является, на UUID платформа
        отвечает 404. Поэтому значение сначала ищется в перечне сборок проекта и версия
        берется оттуда, а на отказ по адресу пробуется и ид - на случай установки,
        которой нужна та форма. Сборка, которой в перечне нет, названа отсутствующей, а
        не превращается в отказ из глубины платформы.

        Перечень сборок с краткими карточками - list_builds; здесь карточка одна и
        целиком. env_file - путь к .env другого окружения.
        """
        return client(env_file).get_assembly(project_id, version)

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
        allow_data_loss: bool = False,
        server_start_timeout: int = int(SERVER_START_TIMEOUT),
        env_file: str = "",
        expected_app_name: str = "",
        expected_app_uri: str = "",
    ) -> dict:
        """Собрать, загрузить и применить исходники с проверкой результата. Итог - ok, детали - problems и log.

        expected_app_name и expected_app_uri сверяют точные имя и URI живого приложения
        до сборки и загрузки. Несовпадение останавливает деплой.

        До сборки сторож схемы сверяет исходники с коммитом примененной сборки. Сужение
        длины или смену типа реквизита, измерения или ресурса, снятое измерение и снятый
        целиком справочник, документ или регистр, в том числе описанный заново под новым
        Ид, деплой отклоняет ошибкой, ничего не собрав: данные будут пересозданы или
        удалены. allow_data_loss=true пропускает
        такие правки, как ключ --allow-data-loss в CLI, - только когда потеря данных
        допустима. Снятие реквизита, ресурса или табличной части флага не требует:
        деплой называет его в schema-warnings и идет дальше.

        Сборку, загруженную в проект, сервер нумерует сам: база - Версия проекта, номер -
        наибольший, какой он когда-либо выдавал в этой базе, плюс один, а суффикс из version
        (и из архива) не сохраняется. Номер удаленной сборки сервер повторно не выдает, а
        перечень ее уже не показывает, поэтому без version деплой считает номер по перечню и
        по локальному реестру загрузок этой машины. Версию, которую сервер дал сборке,
        называет поле assembly-version, а renumbered=true говорит, что она не совпала с
        version отчета.

        Сервер 1С:Элемент, который еще стартует (его консоль отвечает 404 "Application
        "console" not found"), деплой пережидает сам - до server_start_timeout секунд
        (по умолчанию 900; 0 - не ждать).

        Проект расширения деплой проверяет по расширениям приложения (Console API 2.1), а
        не по карточке: она называет только сборку приложения. Проект расширения и запись, использованную при проверке, содержат поля
        extension-project-id и extension.
        """
        lines: list[str] = []
        report = deploy_from_sources(
            client(env_file),
            app_id,
            project_id,
            project_dir=project_dir or None,
            version=version,
            branch=branch or None,
            # Both ids are required parameters of the tool, so they are always explicit.
            app_id_source="flag",
            project_id_source="flag",
            allow_data_loss=allow_data_loss,
            expected_app_name=expected_app_name,
            expected_app_uri=expected_app_uri,
            server_start_timeout=server_start_timeout,
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
        """Проверить компиляцию исходников серверным компилятором без изменения рабочего
        приложения.

        Инструмент собирает архив и загружает его без указания проекта. Сервер определяет
        проект по Ид из Проект.yaml. Для компиляции создается одноразовое приложение,
        после чего приложение и сборка удаляются. ELEMENT_APP_ID и ELEMENT_PROJECT_ID
        окружения не используются.

        ok содержит результат; errors - ошибки с файлом, строкой, колонкой, окружением
        и текстом; messages - исходные сообщения сервера; cleanup - результат удаления.
        keep=true сохраняет приложение и сборку для проверки вручную. В cleanup указаны
        команда удаления (command) и ручные шаги (steps); для удаления используется
        probe_cleanup.

        До сборки проверяется Проект.yaml: сервер требует Представление, ЯзыкРазработки
        и ЯзыкиЛокализации, если указан ЯзыкПоУмолчанию. Инструмент сообщает об отсутствующих
        ключах до отправки.
        """
        lines: list[str] = []
        report = probe_project(
            client(env_file),
            project_dir=project_dir or None,
            space_id=space_id or None,
            keep=keep,
            env_file=env_file or None,
            log=lines.append,
        )
        payload = report.to_dict()
        payload["log"] = lines
        return payload

    @server.tool()
    def probe_cleanup(app_id: str | list[str], env_file: str = "") -> dict:
        """Удалить ресурсы проверки компиляции, оставленные после probe с keep=true
        или прерванной очистки.

        app_id - id или имя одноразового приложения. Проект и сборка определяются по
        карточке приложения, а не по проекту окружения. Порядок удаления: приложение,
        ожидание его исчезновения, сборка проверки и проект. Проект удаляется только
        при отсутствии сборок и работающих приложений.

        Проверка с собственным именем и версией определяется по локальному реестру
        загрузок этой машины. Реестр также позволяет удалить сборки, которые позже
        применялись к одноразовому приложению. Постороннее приложение (имя без префикса
        elemctl-probe-, сборка не от проверки и запись в реестре отсутствует) и рабочее
        приложение окружения не удаляются; инструмент сообщает причину. Повторный вызов продолжает очистку, не завершенную ранее.

        Если локальный реестр содержит сборки этой проверки, клиент проверяет их
        использование другими приложениями и сохраняет используемые. Без записей
        реестра такой проверки нет: при распознавании только по имени или токену
        сохранение используемой другим приложением сборки не гарантируется.

        Результат находится в ok, результаты шагов - в app-deleted, builds,
        project-deleted и project-kept. app_id может быть списком: приложения
        обрабатываются по очереди, ответ имеет вид {ok, cleanups, log}. В cleanups
        находится отчет для каждого приложения в порядке списка. Ошибка одного
        приложения (не от проверки, рабочее приложение, не найдено) записывается в
        error и не останавливает остальные; ok истинен только при успехе всех операций.
        """
        lines: list[str] = []
        target = client(env_file)
        apps = repeated_values(app_id) or [""]
        if len(apps) == 1:
            payload = cleanup_probe(target, apps[0], log=lines.append).to_dict()
        else:
            payload = cleanup_probes(target, apps, log=lines.append)
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
        """Проверить фактическое применение сборки: задачи с ошибками за последние since_minutes минут, сверка примененной сборки (надежно - по expected_assembly_id, строка версии - запасной вариант), доступность uri.

        Сборку расширения карточка приложения не называет - она и после применения называет
        сборку приложения. Поэтому expected_assembly_id, которого нет в карточке, ищется среди
        сборок проектов расширений, и найденная там сборка сверяется с расширениями приложения
        (Console API 2.1): extension-project-id и extension в ответе. Сервер без 2.1 применение
        расширения проверить не даст: applied=null и причина в problems, а не откат.
        """
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
        """Списки пользователей; name - фильтр по подстроке представления (на клиенте).

        Собственный список приложения назван по нему же ("Список пользователей
        приложения ..."), список панели управления - один на стенд.
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

        Список задается list_id (ид либо точное представление) ЛИБО app_id -
        тогда берется собственный список приложения. Оба флага необязательны:
        без них команда только показывает состояние, поэтому ее же удобно звать
        для проверки. За "входом по логину и паролю" стоит сервис учетных
        записей типа Local; список без такого сервиса - не ошибка, в ответе
        password-login-enabled будет null. Состав ФОРМ аутентификации в Console
        API не живет вовсе - он остается ручным.
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
    def list_app_users(app_id: str, env_file: str = "") -> dict:
        """Кто подключен к приложению; ответ - объект {app-id, total, summary, users}.

        Каждый пользователь - так, как его отдает платформа: user-list-id, user-id,
        presentation, is-admin, token-access-enabled. Логина в ответе нет: пользователя
        панели управления платформа называет логином в presentation, остальных -
        представлением. summary - строка со счетчиками: сколько подключено, сколько из них
        администраторов и у скольких есть доступ по токену. Сам доступ по токену показывает
        и переключает token_access. app_id - ид (UUID) либо точное имя приложения; env_file -
        путь к .env другого окружения.
        """
        target = client(env_file)
        resolved = target.resolve_app_id(app_id)
        users = target.list_app_users(resolved)
        return {
            "app-id": resolved,
            "total": len(users),
            "summary": app_users_summary(users),
            "users": users,
        }

    @server.tool()
    def token_access(
        app_id: str,
        user: str | list[str] = "",
        enabled: bool | None = None,
        env_file: str = "",
    ) -> dict:
        """Доступ пользователя к HTTP-сервисам приложения по токену: показать или переключить.

        Без этого доступа вызов HTTP-сервиса приложения токеном пользователя получает
        500 "Token access is denied", какие бы права у пользователя ни были. app_id - ид
        (UUID) либо точное имя приложения, его нужно назвать явно. user - логин,
        представление или ид пользователя; пусто - учетная запись, под которой работает
        elemctl. Без enabled инструмент только показывает признак; enabled=true/false
        переключает его и перечитывает подключение, так что token-access-enabled в ответе -
        то, что хранит платформа после изменения, а changed говорит, менял ли вызов что-то.
        Пользователя, не подключенного к приложению, инструмент называет сам, а не
        отправляет на изменение. user может быть и списком: пользователи читаются или
        переключаются по очереди, ответ - {ok, app-id, users} с записью на каждого в порядке
        списка, пользователь, которого не удалось найти или переключить, - запись с error,
        которая не останавливает остальных, а ok - только если удались все.
        """
        target = client(env_file)
        resolved = target.resolve_app_id(app_id)
        users = repeated_values(user)
        if len(users) < 2:
            return target.token_access(resolved, user=users[0] if users else "", enabled=enabled)
        return token_access_each(target, resolved, users, enabled=enabled)

    @server.tool()
    def export_app(app_id: str, output: str = "", env_file: str = "") -> dict:
        """Выгрузить в файл сборку, на которой работает приложение.

        Операция чтения: сервер ничего не меняет. Консоль берет архив у сервера приложения,
        то есть это сборка, которую приложение исполняет; расширений в архиве нет, их
        выгружает export_extension. output - файл или каталог; пусто - текущий каталог
        сервера MCP и имя из манифеста архива, "<Имя> <Версия>.xasm". Ответ: file (полный
        путь), size и manifest архива. Сервер без этого метода получает понятный отказ, а не
        401 о токене. app_id - ид (UUID) либо точное имя приложения; env_file - путь к .env
        другого окружения.
        """
        target = client(env_file)
        return target.export_app(target.resolve_app_id(app_id), output=output)

    @server.tool()
    def export_extension(
        app_id: str,
        extension: str,
        output: str = "",
        env_file: str = "",
    ) -> dict:
        """Выгрузить в файл сборку расширения, примененного в приложении (Console API 2.1).

        Операция чтения: сервер ничего не меняет. extension - ид расширения, ид его проекта,
        имя или представление проекта; расширение ищется среди примененных в приложении, и
        промах назван вместе с теми, что есть. output - файл или каталог; пусто - текущий
        каталог сервера MCP и имя из манифеста архива, "<Имя> <Версия>.xasm". Ответ: file
        (полный путь), size, manifest архива и поля расширения. Сервер старше метода Console
        API 2.1 получает понятный отказ, а не 401 о токене. app_id - ид (UUID) либо точное
        имя приложения; env_file - путь к .env другого окружения.
        """
        target = client(env_file)
        return target.export_extension(target.resolve_app_id(app_id), extension, output=output)

    @server.tool()
    def list_app_tasks(app_id: str = "", env_file: str = "") -> list:
        """Задачи приложений; app_id - необязательный фильтр (выполняется на клиенте)."""
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


def _error_payload(error):
    """An error as a field of an answer: the details of an api error kept, like the CLI does."""
    return error.to_dict() if isinstance(error, ApiError) else {"error": str(error)}


def _source_project(target, project_id, version_id, *, project_from_env):
    """The tool twin of cli._source_project: the words name the tool parameters.

    A default project gives way to the project of the build without a line: a tool has no
    progress stream, and the card the create answers with names its project in `source`.
    """
    instead = target.missing_source(project_id, version_id)
    if instead is None:
        return project_id
    owner, searched = build_owner(target, project_id, version_id)
    if owner is not None:
        if project_from_env:
            return str(owner.get("id"))
        raise ElemctlError(i18n.t(
            "mcp.source-other-project", build=version_id, project=project_id,
            owner=project_label(owner), owner_id=owner.get("id"),
        ))
    parts = [i18n.t("client.source-missing", assembly=version_id, project=project_id)]
    if instead.get("version-id"):
        parts.append(i18n.t(
            "mcp.source-instead", app=instead.get("app") or instead.get("app-id"),
            build=assembly_label(instead["version-id"], instead.get("version")),
        ))
    else:
        parts.append(i18n.t("mcp.source-latest"))
    if searched:
        parts.append(i18n.t("client.source-nowhere"))
    elif project_from_env:
        parts.append(i18n.t("mcp.source-project-from-env"))
    raise ElemctlError(". ".join(parts))


def _plugin_tool(command, client_for_env):
    """Build the MCP tool function of a plugin command.

    The server derives the schema of a tool from the signature of the function,
    and the signature here is only known at runtime - so it is assembled by hand
    out of the declared arguments (checked against a live server of either major
    version: the schema comes out with the types and the defaults in place).
    env_file is added by the core to every such tool, exactly like the tools of
    the core have it. A multiple argument is an array of its declared type, the
    same list the CLI hands over for a key given several times or for several
    positional values.
    """
    parameters = [
        inspect.Parameter(
            argument.dest,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=list[argument.type] if argument.multiple else argument.type,
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
        context = plugins.CommandContext(
            target.config, client=target, log=lines.append, surface=plugins.SURFACE_MCP
        )
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
    renames it must not break the server - hence the fallback to an empty set:
    a clash would then be left to the server class itself.
    """
    lister = getattr(getattr(server, "_tool_manager", None), "list_tools", None)
    if lister is None:
        return set()
    return {tool.name for tool in lister()}


def add_plugin_tools(server, client_for_env):
    """Register the commands the plugins bring as tools of the server; return the failures.

    A name already taken by a tool of the core is not taken over - the same rule the
    CLI subcommands follow. Neither that nor a plugin that did not load stops the
    server any more: one broken plugin used to take every tool away from the agent.
    Such a plugin is left out and named on stderr, which a client keeps as the log of
    the server.
    """
    taken = _registered_tool_names(server)
    commands, failures = plugins.discover_commands()
    for command in commands:
        if not command.mcp:
            continue
        if command.tool_name in taken:
            failures.append(plugins.PluginFailure(command.source, PluginError(i18n.t(
                "plugins.tool-name-taken", where=command.source, name=command.tool_name
            ))))
            continue
        taken.add(command.tool_name)
        server.add_tool(
            _plugin_tool(command, client_for_env),
            name=command.tool_name,
            description=command.help,
        )
    for failure in failures:
        print(i18n.t("mcp.plugin-failed", source=failure.source, error=failure.error),
              file=sys.stderr)
    return failures


def main(config=None, *, overrides=None, env_file=None):
    """Start the MCP server on stdio.

    config, overrides and env_file are exactly create_server's own parameters - see there for
    what each means. The CLI (cli.cmd_mcp) passes overrides and env_file, never config: a
    pre-resolved Config would pin the default stand for the life of the process and no edit
    of its .env would ever reach a call again. Without any of the three, the configuration is
    assembled from the environment variables and .env on the first call to the platform.
    """
    create_server(config, overrides=overrides, env_file=env_file).run()


if __name__ == "__main__":
    main()
