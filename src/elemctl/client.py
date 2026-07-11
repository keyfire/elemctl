"""Клиент Console API v2 платформы 1С:Предприятие.Элемент.

Клиент не печатает ничего сам: прогресс длительных операций отдаётся через
callback log, который передаёт вызывающая сторона.
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlencode

from .auth import TokenManager
from .errors import ApiError, ConfigError
from .transport import UrllibTransport
from .versions import pick_latest

API_PREFIX = "/console/api/v2"

# Стабильные статусы приложения; всё прочее (в т.ч. пустая строка) – переходное.
STABLE_STATUSES = {"Running", "Stopped", "Error"}

# Таймауты ожиданий (секунды) по разделу 6 спецификации.
POLL_INTERVAL = 10.0
STOP_TIMEOUT = 180.0
START_TIMEOUT = 300.0
READY_TIMEOUT = 600.0


def extract_assembly_id(payload):
    """Достать id сборки из ответа платформы.

    Проверяются поля image-id, assembly-id и id – именно в этом порядке.
    """
    if not isinstance(payload, dict):
        return None
    for key in ("image-id", "assembly-id", "id"):
        value = payload.get(key)
        if value:
            return value
    return None


def _as_list(payload, *keys):
    """Привести ответ-список к списку.

    Платформа может вернуть как массив, так и объект со списком в одном из
    полей (например items или assemblies).
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _collapse_reference(value):
    """Свернуть ссылочный объект до {"id": ...} или {"name": ...}."""
    if not isinstance(value, dict):
        return None
    if value.get("id"):
        return {"id": value["id"]}
    if value.get("name"):
        return {"name": value["name"]}
    return None


# Статус удалённого приложения (сравнение без учёта регистра).
DELETED_STATUS = "Deleted"


def _is_deleted(app):
    """Признак удалённого приложения.

    Платформа не убирает удалённые приложения из списка, а помечает их
    статусом Deleted, сохраняя прежний id. На таком id последующие get и
    deploy отвечают 404, поэтому поиск по умолчанию их пропускает.
    """
    status = app.get("status")
    return isinstance(status, str) and status.strip().lower() == DELETED_STATUS.lower()


class ElementClient:
    """Программный клиент Console API v2."""

    def __init__(self, config, transport=None, token_cache_dir=None):
        self.config = config
        self._transport = transport or UrllibTransport()
        self._tokens = TokenManager(config, self._transport, cache_dir=token_cache_dir)
        # Точка подмены для тестов: ожидания не должны реально спать.
        self._sleep = time.sleep

    # -- низкий уровень --------------------------------------------------

    def token(self):
        """Получить действующий Bearer-токен."""
        return self._tokens.get_token()

    def _request(self, method, path, *, query=None, json_body=None, data=None, content_type=None):
        """Выполнить запрос с Bearer-токеном; при 401 обновить токен и повторить один раз."""
        config = self.config.require()
        url = config.base_url + path
        if query:
            filtered = {k: v for k, v in query.items() if v not in (None, "")}
            if filtered:
                url += "?" + urlencode(filtered)

        body = data
        headers = {}
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif content_type:
            headers["Content-Type"] = content_type

        token = self._tokens.get_token()
        response = None
        for attempt in (1, 2):
            headers["Authorization"] = f"Bearer {token}"
            response = self._transport.request(
                method, url, headers=headers, data=body, timeout=config.timeout
            )
            if response.status == 401 and attempt == 1:
                token = self._tokens.get_token(force=True)
                continue
            break

        if 200 <= response.status < 300:
            if not response.body:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text()
        raise self._api_error(method, url, response)

    def _api(self, method, path, **kwargs):
        """Запрос к Console API v2 (общий префикс /console/api/v2)."""
        return self._request(method, API_PREFIX + path, **kwargs)

    @staticmethod
    def _api_error(method, url, response):
        try:
            body = response.json()
        except ValueError:
            body = response.text()
        message = f"Console API ответил {response.status} на {method} {url}"
        if isinstance(body, dict):
            for key in ("message", "error", "detail"):
                detail = body.get(key)
                if isinstance(detail, str) and detail.strip():
                    message += f": {detail.strip()}"
                    break
        return ApiError(message, status=response.status, method=method, url=url, body=body)

    def check_uri(self, uri, timeout=15.0):
        """Контрольный GET по адресу приложения; вернуть HTTP-статус или None.

        Проверка информационная: 401/403 нормальны для закрытых приложений.
        """
        if not uri:
            return None
        try:
            response = self._transport.request("GET", uri, timeout=timeout)
            return response.status
        except Exception:
            return None

    # -- приложения --------------------------------------------------------

    def list_apps(self, name=""):
        """Список приложений; name – необязательный фильтр платформы."""
        payload = self._api("GET", "/applications", query={"name": name})
        return _as_list(payload, "items", "applications")

    def get_app(self, app_id):
        """Карточка приложения (статус, uri, source.project-version и др.)."""
        return self._api("GET", f"/applications/{app_id}")

    def find_app(self, name, *, include_deleted=False):
        """Найти приложение по точному совпадению имени без учёта регистра.

        Имя сверяется с полями name, display-name и publication-context.
        Удалённые приложения (статус Deleted) по умолчанию пропускаются: на их
        прежнем id последующие get и deploy отвечают 404. include_deleted=True
        возвращает прежнее поведение – поиск среди всех приложений, включая
        удалённые. Возвращается карточка из списка либо None.
        """
        target = (name or "").strip().lower()
        if not target:
            return None
        for app in self.list_apps():
            if not isinstance(app, dict):
                continue
            if not include_deleted and _is_deleted(app):
                continue
            for key in ("name", "display-name", "publication-context"):
                value = app.get(key)
                if isinstance(value, str) and value.strip().lower() == target:
                    return app
        return None

    def create_app(
        self,
        display_name,
        *,
        publication_context=None,
        project_version_id=None,
        image_id=None,
        development_mode=True,
        space_id=None,
        technology_version=None,
    ):
        """Создать приложение.

        Источник – ровно один из project_version_id (id сборки, надёжный
        путь) либо image_id (id проекта; на части конфигураций платформы
        даёт пустой каркас без данных).
        """
        if bool(project_version_id) == bool(image_id):
            raise ConfigError(
                "источник приложения – ровно один из параметров: project_version_id либо image_id"
            )
        source = {"type": "repository"}
        if project_version_id:
            source["project-version-id"] = project_version_id
        else:
            source["image-id"] = image_id
        body = {
            "source": source,
            "display-name": display_name,
            "publication-context": publication_context or display_name,
            "development-mode": bool(development_mode),
        }
        if space_id:
            body["space-id"] = space_id
        if technology_version:
            body["technology-version"] = technology_version
        return self._api("POST", "/applications", json_body=body)

    def delete_app(self, app_id):
        """Удалить приложение.

        Необратимо: пересозданное приложение получает другой URL. Если в
        среде разработки есть неопубликованные правки, платформа отвечает
        400 FAILED_PRECONDITION – в этом случае к ошибке добавляется
        подсказка.
        """
        try:
            return self._api("DELETE", f"/applications/{app_id}")
        except ApiError as error:
            body_text = json.dumps(error.body, ensure_ascii=False) if error.body is not None else ""
            if error.status == 400 and "FAILED_PRECONDITION" in body_text:
                error.hint = (
                    "в среде разработки приложения есть неопубликованные правки – "
                    "платформа не удаляет такие приложения через API; опубликуйте "
                    "или отмените правки, либо удалите приложение через панель управления"
                )
                error.message += " – " + error.hint
                error.args = (error.message,)
            raise

    def start_app(self, app_id):
        """Запустить приложение."""
        return self._api("PUT", f"/applications/{app_id}/status/start")

    def stop_app(self, app_id):
        """Остановить приложение."""
        return self._api("PUT", f"/applications/{app_id}/status/stop")

    def get_debug_info(self, app_id):
        """Данные для сессии отладки приложения: {debug-token, debug-address}.

        Обёртка над POST /applications/{app_id}/actions/debug (ApplicationDebugInfo).
        Требует включённой отладки на сервере (config/debug.yml: enabled: true);
        адрес указывает на debug-сервер платформы (протокол WebSocket), токен –
        разовый ключ сессии. Управлением приложением не является – только чтение
        параметров подключения отладчика.
        """
        return self._api("POST", f"/applications/{app_id}/actions/debug")

    def apply_build(self, app_id, *, image_id=None, project_id=None, assembly_version=None):
        """Применить сборку к приложению (project/update).

        Источник – либо image_id (id сборки), либо project_id с
        необязательной assembly_version.
        """
        if image_id:
            source = {"type": "repository", "image-id": image_id}
        elif project_id:
            source = {"type": "repository", "project-id": project_id}
            if assembly_version:
                source["assembly-version"] = assembly_version
        else:
            raise ConfigError("нужен источник применения: image_id либо project_id")
        return self._api(
            "POST", f"/applications/{app_id}/project/update", json_body={"source": source}
        )

    def create_dump(self, app_id, *, include_users=True, include_binary_data=True, description=""):
        """Создать дамп приложения."""
        body = {
            "include-users": bool(include_users),
            "include-binary-data": bool(include_binary_data),
            "description": description or "",
        }
        return self._api("POST", f"/applications/{app_id}/dumps", json_body=body)

    def get_dump(self, app_id, dump_id):
        """Статус дампа приложения."""
        return self._api("GET", f"/applications/{app_id}/dumps/{dump_id}")

    # -- версия технологии -------------------------------------------------

    def get_technology_version(self, app_id):
        """Версия технологии – из карточки приложения."""
        card = self.get_app(app_id) or {}
        return card.get("technology-version")

    def set_technology_version(self, version, app_ids):
        """Обновить версию технологии приложений; возвращает групповую задачу."""
        body = {"technology-version": version, "applications": list(app_ids)}
        return self._api(
            "POST", "/tasks/group-tasks/update-applications-technology", json_body=body
        )

    def get_group_task(self, task_id):
        """Статус групповой задачи."""
        return self._api("GET", f"/tasks/group-tasks/{task_id}")

    # -- пространства и проекты ---------------------------------------------

    def list_spaces(self):
        """Список пространств."""
        return _as_list(self._api("GET", "/spaces"), "items", "spaces")

    def list_projects(self):
        """Список проектов."""
        return _as_list(self._api("GET", "/projects"), "items", "projects")

    def get_project(self, project_id):
        """Карточка проекта."""
        return self._api("GET", f"/projects/{project_id}")

    def delete_project(self, project_id):
        """Удалить проект."""
        return self._api("DELETE", f"/projects/{project_id}")

    # -- сборки проектов -----------------------------------------------------

    def upload_assembly(
        self,
        data,
        *,
        project_id=None,
        space_id=None,
        branch_name=None,
        commit_id=None,
        commit_message=None,
    ):
        """Загрузить файл сборки (.xasm/.xlib) на платформу.

        С project_id сборка добавляется в существующий проект, без него
        создаётся новый проект. Имена query-параметров у платформы – в
        PascalCase.
        """
        path = f"/projects/{project_id}/assemblies" if project_id else "/projects"
        query = {
            "SpaceId": space_id,
            "BranchName": branch_name,
            "CommitId": commit_id,
            "CommitMessage": commit_message,
        }
        return self._api(
            "POST",
            path,
            query=query,
            data=bytes(data),
            content_type="application/octet-stream",
        )

    def list_assemblies(self, project_id):
        """Список сборок проекта (нормализован к списку)."""
        payload = self._api("GET", f"/projects/{project_id}/assemblies")
        return _as_list(payload, "items", "assemblies")

    def get_assembly(self, project_id, version):
        """Карточка сборки по версии."""
        return self._api("GET", f"/projects/{project_id}/assemblies/{version}")

    def delete_assembly(self, project_id, version):
        """Удалить сборку по версии."""
        return self._api("DELETE", f"/projects/{project_id}/assemblies/{version}")

    def latest_assembly(self, project_id):
        """Последняя сборка проекта по числовому счётчику версии, либо None."""
        return pick_latest(self.list_assemblies(project_id))

    # -- ветки среды разработки ----------------------------------------------

    def list_branches(self, project_id="", name=""):
        """Список веток; фильтры project-id и name необязательны."""
        payload = self._api(
            "GET", "/branches", query={"project-id": project_id, "name": name}
        )
        return _as_list(payload, "items", "branches")

    def get_branch(self, branch_id):
        """Карточка ветки."""
        return self._api("GET", f"/branches/{branch_id}")

    def create_branch(self, name, project_id, app_id=None):
        """Создать ветку среды разработки."""
        body = {"name": name, "kind": "development", "project": {"id": project_id}}
        if app_id:
            body["application"] = {"id": app_id}
        return self._api("POST", "/branches", json_body=body)

    def update_branch(self, branch_id, *, app_id=None, merge=False):
        """Изменить ветку с учётом оптимистической блокировки платформы.

        Сначала читается карточка, затем отправляется тело из текущих
        значений (version-stamp обязательно возвращается как есть);
        app_id перепривязывает ветку к приложению, merge=True добавляет
        write-parameters и означает принятие изменений ветки.
        """
        card = self.get_branch(branch_id) or {}
        body = {
            "name": card.get("name"),
            "kind": card.get("kind"),
            "deletion-mark": card.get("deletion-mark", False),
            "version-stamp": card.get("version-stamp"),
        }
        for key in ("source-branch", "application"):
            collapsed = _collapse_reference(card.get(key))
            if collapsed is not None:
                body[key] = collapsed
        if app_id:
            body["application"] = {"id": app_id}
        if merge:
            body["write-parameters"] = {"merge": True}
        return self._api("PUT", f"/branches/{branch_id}", json_body=body)

    def merge_branch(self, branch_id):
        """Принять изменения ветки (merge)."""
        return self.update_branch(branch_id, merge=True)

    def delete_branch(self, branch_id):
        """Удалить ветку."""
        return self._api("DELETE", f"/branches/{branch_id}")

    # -- задачи приложений ----------------------------------------------------

    def list_app_tasks(self, app_id=""):
        """Задачи приложений; серверного фильтра нет – фильтруем на клиенте."""
        payload = self._api("GET", "/tasks/application-tasks")
        tasks = _as_list(payload, "items", "tasks")
        if not app_id:
            return tasks
        return [
            task
            for task in tasks
            if isinstance(task, dict) and task.get("application-id") == app_id
        ]

    # -- ожидания состояний -----------------------------------------------------

    def wait_app_status(
        self,
        app_id,
        target_statuses,
        *,
        timeout,
        poll=POLL_INTERVAL,
        log=None,
        error_is_fatal=True,
    ):
        """Дождаться одного из целевых статусов приложения; вернуть карточку.

        При error_is_fatal статус Error (если он не целевой) – немедленная
        ошибка; по истечении таймаута тоже ошибка.
        """
        deadline = time.monotonic() + timeout
        while True:
            card = self.get_app(app_id) or {}
            status = (card.get("status") or "").strip()
            if status in target_statuses:
                return card
            if error_is_fatal and status == "Error":
                raise ApiError(
                    f"приложение {app_id} в статусе Error: {card.get('error') or 'без текста ошибки'}",
                    body=card,
                )
            if time.monotonic() >= deadline:
                expected = "/".join(sorted(target_statuses))
                raise ApiError(
                    f"не дождались статуса {expected} приложения {app_id} "
                    f"за {int(timeout)} с (текущий: {status or 'переходный'})"
                )
            if log:
                log(f"статус приложения: {status or '(переходный)'} – ждём...")
            self._sleep(poll)

    def wait_app_stable(self, app_id, *, timeout=START_TIMEOUT, poll=POLL_INTERVAL, log=None):
        """Дождаться выхода приложения из переходных статусов."""
        return self.wait_app_status(
            app_id, STABLE_STATUSES, timeout=timeout, poll=poll, log=log, error_is_fatal=False
        )

    def wait_app_ready(self, app_id, *, timeout=READY_TIMEOUT, poll=POLL_INTERVAL, log=None):
        """Дождаться готовности нового приложения: стабильный статус и uri.

        Статус Error во время ожидания – немедленная ошибка.
        """
        deadline = time.monotonic() + timeout
        while True:
            card = self.get_app(app_id) or {}
            status = (card.get("status") or "").strip()
            if status == "Error":
                raise ApiError(
                    f"приложение {app_id} создано со статусом Error: "
                    f"{card.get('error') or 'без текста ошибки'}",
                    body=card,
                )
            if status in ("Running", "Stopped") and card.get("uri"):
                return card
            if time.monotonic() >= deadline:
                raise ApiError(
                    f"приложение {app_id} не стало готовым за {int(timeout)} с "
                    f"(статус: {status or 'переходный'}, uri: {card.get('uri') or 'нет'})"
                )
            if log:
                log(f"ждём готовности приложения: статус {status or '(переходный)'}...")
            self._sleep(poll)

    def ensure_running(self, app_id, *, log=None):
        """Довести приложение до статуса Running после применения сборки.

        Применение может само перезапустить приложение: ждём стабилизации;
        если итог не Running – останавливаем (если нужно), дожидаемся
        Stopped, запускаем и дожидаемся Running.
        """
        card = self.wait_app_stable(app_id, timeout=START_TIMEOUT, log=log)
        status = card.get("status")
        if status == "Running":
            return card
        if status != "Stopped":
            if log:
                log(f"статус {status} – останавливаем приложение...")
            self.stop_app(app_id)
            self.wait_app_status(
                app_id, {"Stopped"}, timeout=STOP_TIMEOUT, log=log, error_is_fatal=False
            )
        if log:
            log("запускаем приложение...")
        self.start_app(app_id)
        return self.wait_app_status(app_id, {"Running"}, timeout=START_TIMEOUT, log=log)
