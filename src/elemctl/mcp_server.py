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

from . import i18n
from .build import build_assembly
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
    "список problems и сверка applied-version с загруженной версией. "
    "Асинхронность: build_assembly, deploy, apply_build, create_app, ensure_app, "
    "delete_app и merge_branch выполняются минутами и синхронно блокируют вызов "
    "до конца – в чате это выглядит зависанием без вывода. Такие операции "
    "запускать CLI-командой elemctl фоновым процессом (у агента – механизм "
    "фонового запуска вроде run_in_background, результат придёт нотификацией), а "
    "не синхронным вызовом MCP-инструмента; сами MCP-инструменты предпочтительны "
    "для быстрых операций чтения (list/get/find/list-builds/verify-deploy)."
)


def create_server(config=None):
    """Создать MCP-сервер elemctl со всеми инструментами.

    config – готовая конфигурация; без неё она собирается из переменных
    окружения и .env при первом обращении к платформе.
    """
    server = FastMCP("elemctl", instructions=INSTRUCTIONS)
    state = {"client": None, "config": config}

    def client():
        if state["client"] is None:
            cfg = state["config"] or Config.from_env()
            state["client"] = ElementClient(cfg)
        return state["client"]

    @server.tool()
    def list_apps(name: str = "") -> list:
        """Список приложений платформы; name – необязательный фильтр по имени."""
        return client().list_apps(name=name)

    @server.tool()
    def get_app(app_id: str) -> dict:
        """Карточка приложения: статус, uri, фактическая версия проекта (source.project-version)."""
        return client().get_app(app_id)

    @server.tool()
    def find_app(name: str, include_deleted: bool = False) -> dict:
        """Найти приложение по точному имени без учёта регистра; вернуть id и признак found.

        Удалённые приложения (статус Deleted) по умолчанию пропускаются: на их
        прежнем id get и deploy отвечают 404. include_deleted=True ищет среди
        всех приложений, включая удалённые.
        """
        app = client().find_app(name, include_deleted=include_deleted)
        if app is None:
            return {"id": None, "found": False}
        return {"id": app.get("id"), "found": True, "application": app}

    def _create_app(name, project_id, version_id, space_id, development_mode):
        """Создать приложение (общая логика create_app и ensure_app).

        Источник – version_id (id сборки) либо последняя сборка project_id
        (создание из проекта целиком может дать пустой каркас).
        """
        source_version_id = version_id
        if not source_version_id:
            if not project_id:
                raise ElemctlError(i18n.t("mcp.project-or-version-required"))
            latest = client().latest_assembly(project_id)
            if latest is None:
                raise ElemctlError(
                    f"у проекта {project_id} нет сборок – загрузите сборку или укажите version_id"
                )
            source_version_id = extract_assembly_id(latest)
        return client().create_app(
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
    ) -> dict:
        """Создать приложение. При задании только project_id источником берётся последняя сборка проекта (создание из проекта целиком может дать пустой каркас)."""
        return _create_app(name, project_id, version_id, space_id, development_mode)

    @server.tool()
    def ensure_app(
        name: str,
        project_id: str = "",
        version_id: str = "",
        space_id: str = "",
        development_mode: bool = True,
    ) -> dict:
        """Идемпотентно создать приложение по имени, если его ещё нет.

        Существующее приложение НЕ пересоздаётся: при наличии возвращается
        {"id": ..., "created": false} без изменений (delete + create дали бы
        новый URL и порвали внешние привязки – OIDC redirect и т.п.). Удалённые
        приложения (статус Deleted) не в счёт. Параметры создания – как у
        create_app; они действуют, только когда создание происходит.
        """
        existing = client().find_app(name)
        if existing is not None:
            return {"id": existing.get("id"), "created": False}
        card = _create_app(name, project_id, version_id, space_id, development_mode)
        return {"id": (card or {}).get("id"), "created": True}

    @server.tool()
    def start_app(app_id: str) -> dict:
        """Запустить приложение."""
        return client().start_app(app_id) or {"ok": True, "app-id": app_id}

    @server.tool()
    def stop_app(app_id: str) -> dict:
        """Остановить приложение."""
        return client().stop_app(app_id) or {"ok": True, "app-id": app_id}

    @server.tool()
    def debug_info(app_id: str) -> dict:
        """Данные для сессии отладки приложения: debug-token и debug-address.

        Требует включённой отладки на сервере (config/debug.yml: enabled: true).
        """
        return client().get_debug_info(app_id) or {"app-id": app_id}

    @server.tool()
    def delete_app(app_id: str) -> dict:
        """Удалить приложение. НЕОБРАТИМО: данные теряются, а пересозданное приложение получит другой URL – внешние настройки (OIDC redirect и т.п.) придётся обновлять."""
        return client().delete_app(app_id) or {"deleted": True, "app-id": app_id}

    @server.tool()
    def list_spaces() -> list:
        """Список пространств."""
        return client().list_spaces()

    @server.tool()
    def list_projects() -> list:
        """Список проектов."""
        return client().list_projects()

    @server.tool()
    def list_builds(project_id: str) -> list:
        """Список сборок проекта."""
        return client().list_assemblies(project_id)

    # Имя функции отличается от имени инструмента, чтобы не затенять
    # импортированный build_assembly из модуля build.
    @server.tool(name="build_assembly")
    def build_assembly_tool(project_dir: str = "", output_dir: str = "", version: str = "") -> dict:
        """Локально собрать архив .xasm/.xlib из исходников проекта."""
        result = build_assembly(
            project_dir or None, output_dir=output_dir or None, version=version
        )
        return {"file": str(result.file), "version": result.version, "kind": result.kind}

    @server.tool()
    def deploy(
        app_id: str,
        project_id: str,
        project_dir: str = "",
        version: str = "",
        branch: str = "",
        commit_message: str = "",
    ) -> dict:
        """Полный цикл деплоя из исходников с честной проверкой применения; итог – поле ok, детали – problems и log."""
        lines: list[str] = []
        report = deploy_from_sources(
            client(),
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
    def apply_build(app_id: str, version_id: str) -> dict:
        """Применить загруженную сборку (по id) к приложению; после применения проверьте итог инструментом verify_deploy."""
        response = client().apply_build(app_id, image_id=version_id)
        return response or {"ok": True, "app-id": app_id, "version-id": version_id}

    @server.tool()
    def verify_deploy(app_id: str, expected_version: str = "", since_minutes: int = 30) -> dict:
        """Проверить фактическое применение сборки: задачи с ошибками за последние since_minutes минут, сверка версии, доступность uri."""
        since = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        report = _verify_deploy(
            client(), app_id, expected_version=expected_version, since=since
        )
        return report.to_dict()

    @server.tool()
    def list_app_tasks(app_id: str = "") -> list:
        """Задачи приложений; app_id – необязательный фильтр (выполняется на клиенте)."""
        return client().list_app_tasks(app_id)

    @server.tool()
    def list_branches(project_id: str = "", name: str = "") -> list:
        """Список веток среды разработки; фильтры project_id и name необязательны."""
        return client().list_branches(project_id=project_id, name=name)

    @server.tool()
    def merge_branch(branch_id: str) -> dict:
        """Принять изменения ветки среды разработки (merge)."""
        return client().merge_branch(branch_id) or {"merged": True, "branch-id": branch_id}

    return server


def main():
    """Запустить MCP-сервер на stdio."""
    create_server().run()


if __name__ == "__main__":
    main()
