"""MCP-сервер elemctl: операции платформы как инструменты для AI-агентов.

Транспорт – stdio; реквизиты подключения – из переменных окружения
ELEMENT_* или .env-файла в текущем каталоге. Требует optional extra
"elemctl[mcp]" (пакет mcp>=1.2, используется FastMCP).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as error:  # pragma: no cover - ветка без extra
    raise ImportError(
        'для MCP-сервера нужен extra: pip install "elemctl[mcp]"'
    ) from error

from . import i18n, plugins
from .build import build_assembly, inspect_assembly
from .client import ElementClient, extract_assembly_id
from .config import Config
from .deploy import (
    deploy_from_sources,
    verify_deploy as _verify_deploy,
)
from .errors import ElemctlError

INSTRUCTIONS = (
    "Инструменты управления платформой 1С:Предприятие.Элемент (Console API v2). "
    "Важно: при ошибке применения сборки платформа МОЛЧА откатывает приложение "
    "на предыдущую сборку и запускает его – статус Running не означает успех "
    "деплоя. Доверяйте только отчёту инструментов deploy/verify_deploy: поле ok, "
    "список problems и сверка применённой сборки с загруженной (надёжно - по applied-version-id; строка версии у нового приложения нумеруется заново). "
    "Асинхронность: build_assembly, deploy, apply_build, create_app, ensure_app, "
    "delete_app и merge_branch выполняются минутами и синхронно блокируют вызов "
    "до конца – в чате это выглядит зависанием без вывода. Такие операции "
    "запускать CLI-командой elemctl фоновым процессом (у агента – механизм "
    "фонового запуска вроде run_in_background, результат придёт нотификацией), а "
    "не синхронным вызовом MCP-инструмента; сами MCP-инструменты предпочтительны "
    "для быстрых операций чтения (list/get/find/list-builds/verify-deploy). "
    "Окружение: по умолчанию используется то, с которым запущен сервер; чтобы "
    "обратиться к другому стенду (например, к локальному вместо облачного), "
    "передайте его .env параметром env_file – он есть у каждого инструмента."
)


def _brief_app(app):
    """Краткая карточка приложения: то, по чему его узнают и выбирают.

    Полная карточка несёт списки пользователей, флаги среды разработки и прочее,
    что в списке не нужно: пространство из полусотни приложений даёт десятки
    тысяч символов ответа. Версия берётся из source – это фактически применённая
    сборка, по ней сверяют деплой.
    """
    source = app.get("source") or {}
    return {
        "id": app.get("id"),
        "name": app.get("name") or app.get("display-name"),
        "status": app.get("status"),
        "uri": app.get("uri"),
        "project-version": source.get("project-version"),
        "project-version-id": source.get("project-version-id"),
    }


def _brief_project(project):
    """Краткая карточка проекта: то, по чему его узнают и выбирают.

    Полная карточка несёт группу, default-image, код артефакта и даты – в
    списке это лишнее. Счётчик приложений оставлен: по нему видно, какие
    проекты реально применяются.
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
    """Создать MCP-сервер elemctl со всеми инструментами.

    config – готовая конфигурация; без неё она собирается из переменных
    окружения и .env при первом обращении к платформе.
    """
    server = FastMCP("elemctl", instructions=INSTRUCTIONS)
    state = {"clients": {}, "config": config}

    def client(env_file: str = ""):
        """Клиент платформы для нужного окружения.

        Без env_file – конфигурация, с которой запущен сервер; с ним –
        отдельный клиент по указанному .env, он кэшируется по пути. Так один
        сервер обслуживает и облако, и локальный стенд: раньше окружение
        задавалось только при запуске, и второй стенд оставался недоступен.
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
        """Список приложений платформы; name – необязательный фильтр по имени.

        brief (по умолчанию) оставляет от карточки только id, имя, статус, uri и
        применённую версию: полные карточки всего пространства – это десятки тысяч
        символов, которые в ответе агенту почти всегда лишние. brief=false отдаёт
        карточки целиком. env_file – путь к .env другого окружения.
        """
        apps = client(env_file).list_apps(name=name)
        if not brief:
            return apps
        return [_brief_app(app) for app in apps if isinstance(app, dict)]

    @server.tool()
    def get_app(app_id: str, env_file: str = "") -> dict:
        """Карточка приложения: статус, uri, фактическая версия проекта (source.project-version)."""
        return client(env_file).get_app(app_id)

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
        """Создать приложение (общая логика create_app и ensure_app).

        Источник – version_id (id сборки) либо последняя сборка project_id
        (создание из проекта целиком может дать пустой каркас).
        """
        source_version_id = version_id
        if not source_version_id:
            if not project_id:
                raise ElemctlError(i18n.t("mcp.project-or-version-required"))
            latest = client(env_file).latest_assembly(project_id)
            if latest is None:
                raise ElemctlError(
                    f"у проекта {project_id} нет сборок – загрузите сборку или укажите version_id"
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
        """Запустить приложение."""
        return client(env_file).start_app(app_id) or {"ok": True, "app-id": app_id}

    @server.tool()
    def stop_app(app_id: str, env_file: str = "") -> dict:
        """Остановить приложение."""
        return client(env_file).stop_app(app_id) or {"ok": True, "app-id": app_id}

    @server.tool()
    def debug_info(app_id: str, env_file: str = "") -> dict:
        """Данные для сессии отладки приложения: debug-token и debug-address.

        Требует включённой отладки на сервере (config/debug.yml: enabled: true).
        """
        return client(env_file).get_debug_info(app_id) or {"app-id": app_id}

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
        """Удалить приложение. НЕОБРАТИМО: данные теряются, а пересозданное приложение получит другой URL – внешние настройки (OIDC redirect и т.п.) придётся обновлять."""
        return client(env_file).delete_app(app_id) or {"deleted": True, "app-id": app_id}

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

    # Имя функции отличается от имени инструмента, чтобы не затенять
    # импортированный build_assembly из модуля build.
    @server.tool(name="build_assembly")
    def build_assembly_tool(project_dir: str = "", output_dir: str = "", version: str = "") -> dict:
        """Локально собрать архив .xasm/.xlib из исходников проекта."""
        result = build_assembly(
            project_dir or None, output_dir=output_dir or None, version=version
        )
        return {"file": str(result.file), "version": result.version, "kind": result.kind}

    # Имя функции отличается от имени инструмента по той же причине, что и у build_assembly.
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

    return server


def main(config=None):
    """Запустить MCP-сервер на stdio.

    config – готовая конфигурация (например, собранная CLI из --env-file
    и остальных глобальных аргументов); без неё она собирается из
    переменных окружения и .env при первом обращении к платформе.
    """
    create_server(config).run()


if __name__ == "__main__":
    main()
