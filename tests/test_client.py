"""Тесты клиента Console API на транспорте-заглушке (без сети)."""

from __future__ import annotations

import json

import pytest

from elemctl.auth import extract_token
from elemctl.client import ElementClient, extract_assembly_id
from elemctl.config import Config
from elemctl.errors import ApiError, ConfigError
from tests.conftest import FakeTransport

API = "/console/api/v2"


def test_extract_token_field_order_and_not_implemented():
    assert extract_token({"id_token": "A", "token": "B"}) == "A"
    assert extract_token({"token": "B", "value": "C"}) == "B"
    assert extract_token({"access_token": "Not implemented", "value": "C"}) == "C"
    assert extract_token({"access_token": "real-token"}) == "real-token"
    assert extract_token({"access_token": "Not implemented"}) is None
    assert extract_token({}) is None
    assert extract_token(None) is None


def test_token_request_uses_basic_auth(api):
    client, transport = api
    token = client.token()
    assert token == "TOKEN"
    call = transport.calls_to("POST", "/console/sys/token")[0]
    assert call["headers"]["Authorization"].startswith("Basic ")
    assert call["data"] == b"grant_type=client_credentials"


def test_retry_once_on_401(api):
    client, transport = api
    transport.add("GET", f"{API}/applications", status=401)
    transport.add("GET", f"{API}/applications", [{"id": "app-1"}])

    apps = client.list_apps()

    assert apps == [{"id": "app-1"}]
    # Токен запрошен дважды: первично и принудительно после 401.
    assert len(transport.calls_to("POST", "/console/sys/token")) == 2
    assert len(transport.calls_to("GET", f"{API}/applications")) == 2


def test_get_debug_info_posts_to_actions_debug(api):
    client, transport = api
    transport.add(
        "POST",
        f"{API}/applications/app-1/actions/debug",
        {"debug-token": "T0KEN", "debug-address": "wss://dbg.test:8080"},
    )

    info = client.get_debug_info("app-1")

    assert info == {"debug-token": "T0KEN", "debug-address": "wss://dbg.test:8080"}
    calls = transport.calls_to("POST", f"{API}/applications/app-1/actions/debug")
    assert len(calls) == 1
    # Экшен без тела запроса.
    assert calls[0]["data"] in (None, b"")


def test_find_app_exact_case_insensitive(api):
    client, transport = api
    transport.add(
        "GET",
        f"{API}/applications",
        [
            {"id": "1", "display-name": "Site Dev"},
            {"id": "2", "name": "crm", "publication-context": "apps/crm"},
        ],
    )
    assert client.find_app("SITE DEV")["id"] == "1"
    assert client.find_app("APPS/CRM")["id"] == "2"
    assert client.find_app("site") is None  # частичное совпадение не считается
    assert client.find_app("nope") is None


def test_find_app_skips_deleted(api):
    client, transport = api
    transport.add(
        "GET",
        f"{API}/applications",
        [
            {"id": "old", "display-name": "site", "status": "Deleted"},
            {"id": "live", "display-name": "site", "status": "Running"},
        ],
    )
    # Удалённая карточка пропускается – находится живое приложение с тем же именем.
    assert client.find_app("site")["id"] == "live"


def test_find_app_include_deleted_returns_deleted(api):
    client, transport = api
    # Единственный ответ повторяется на оба вызова find_app.
    transport.add(
        "GET",
        f"{API}/applications",
        [{"id": "old", "display-name": "site-old", "status": "DELETED"}],
    )
    # По умолчанию удалённое не находится...
    assert client.find_app("site-old") is None
    # ...а с include_deleted=True возвращается прежнее поведение (сравнение статуса без учёта регистра).
    assert client.find_app("site-old", include_deleted=True)["id"] == "old"


def test_delete_failed_precondition_hint(api):
    client, transport = api
    transport.add(
        "DELETE",
        f"{API}/applications/app-1",
        {"code": "FAILED_PRECONDITION", "message": "uncommitted changes"},
        status=400,
    )
    with pytest.raises(ApiError) as excinfo:
        client.delete_app("app-1")
    message = str(excinfo.value)
    assert "неопубликованные правки" in message
    assert "панель управления" in message
    assert excinfo.value.status == 400


def test_assemblies_list_normalization(api):
    client, transport = api
    path = f"{API}/projects/p1/assemblies"
    transport.add("GET", path, [{"assembly-version": "1.0-1"}])
    transport.add("GET", path, {"items": [{"assembly-version": "1.0-2"}]})
    transport.add("GET", path, {"assemblies": [{"assembly-version": "1.0-3"}]})

    assert client.list_assemblies("p1") == [{"assembly-version": "1.0-1"}]
    assert client.list_assemblies("p1") == [{"assembly-version": "1.0-2"}]
    assert client.list_assemblies("p1") == [{"assembly-version": "1.0-3"}]


def test_assembly_resolved_by_version(api):
    """get/delete сборки принимают версию: API адресует сборку только UUID, поэтому
    не-UUID аргумент резолвится в id по списку сборок (версию платформа перенумеровывает)."""
    client, transport = api
    assembly_id = "019f6d02-8606-7e4a-afc6-971f921eade5"
    transport.add(
        "GET", f"{API}/projects/p1/assemblies",
        [{"assembly-version": "1.0-39", "project-version": "1.0-39", "id": assembly_id}],
    )
    transport.add("DELETE", f"{API}/projects/p1/assemblies/{assembly_id}", {"deleted": True})
    assert client.delete_assembly("p1", "1.0-39") == {"deleted": True}
    # UUID проходит без похода за списком.
    transport.add("DELETE", f"{API}/projects/p1/assemblies/{assembly_id}", {"deleted": True})
    assert client.delete_assembly("p1", assembly_id) == {"deleted": True}
    assert len(transport.calls_to("GET", f"{API}/projects/p1/assemblies")) == 1


def test_assembly_unknown_version_is_config_error(api):
    client, transport = api
    transport.add("GET", f"{API}/projects/p1/assemblies", [])
    with pytest.raises(ConfigError, match="не найдена"):
        client.get_assembly("p1", "9.9-99")


def test_latest_assembly_numeric_order(api):
    client, transport = api
    transport.add(
        "GET",
        f"{API}/projects/p1/assemblies",
        [
            {"assembly-version": "1.0-9", "id": "old"},
            {"assembly-version": "1.0-10", "id": "new"},
        ],
    )
    assert client.latest_assembly("p1")["id"] == "new"


def test_extract_assembly_id_order():
    assert extract_assembly_id({"image-id": "i", "assembly-id": "a", "id": "d"}) == "i"
    assert extract_assembly_id({"assembly-id": "a", "id": "d"}) == "a"
    assert extract_assembly_id({"id": "d"}) == "d"
    assert extract_assembly_id({}) is None
    assert extract_assembly_id(None) is None


def test_upload_assembly_pascalcase_query(api):
    client, transport = api
    transport.add("POST", f"{API}/projects/p1/assemblies", {"image-id": "asm-1"})

    response = client.upload_assembly(
        b"PK-data",
        project_id="p1",
        space_id="s1",
        branch_name="feature/x",
        commit_id="abc",
        commit_message="msg",
    )

    assert response == {"image-id": "asm-1"}
    call = transport.calls_to("POST", f"{API}/projects/p1/assemblies")[0]
    assert "SpaceId=s1" in call["query"]
    assert "BranchName=feature%2Fx" in call["query"]
    assert "CommitId=abc" in call["query"]
    assert "CommitMessage=msg" in call["query"]
    assert call["data"] == b"PK-data"
    assert call["headers"]["Content-Type"] == "application/octet-stream"


def test_upload_without_project_creates_new_project(api):
    client, transport = api
    transport.add("POST", f"{API}/projects", {"id": "p-new"})
    response = client.upload_assembly(b"PK-data")
    assert response == {"id": "p-new"}


def test_update_branch_optimistic_locking_and_merge(api):
    client, transport = api
    transport.add(
        "GET",
        f"{API}/branches/b1",
        {
            "name": "dev",
            "kind": "development",
            "deletion-mark": False,
            "version-stamp": "stamp-42",
            "project": {"id": "p1", "name": "proj"},
            "source-branch": {"id": "b0", "name": "main"},
            "application": {"id": "app-1", "display-name": "х"},
        },
    )
    transport.add("PUT", f"{API}/branches/b1", {"ok": True})

    client.merge_branch("b1")

    call = transport.calls_to("PUT", f"{API}/branches/b1")[0]
    body = json.loads(call["data"].decode("utf-8"))
    assert body["version-stamp"] == "stamp-42"
    assert body["name"] == "dev"
    assert body["kind"] == "development"
    assert body["deletion-mark"] is False
    # Ссылки свёрнуты до {"id": ...}.
    assert body["source-branch"] == {"id": "b0"}
    assert body["application"] == {"id": "app-1"}
    assert body["write-parameters"] == {"merge": True}
    # Поле project в тело PUT не входит.
    assert "project" not in body


def test_list_app_tasks_client_side_filter(api):
    client, transport = api
    transport.add(
        "GET",
        f"{API}/tasks/application-tasks",
        [
            {"id": "t1", "application-id": "app-1", "status": "Done"},
            {"id": "t2", "application-id": "app-2", "status": "Error"},
        ],
    )
    tasks = client.list_app_tasks("app-2")
    assert [t["id"] for t in tasks] == ["t2"]


def test_api_error_details_serializable(api):
    client, transport = api
    transport.add("GET", f"{API}/applications/x", {"message": "нет такого"}, status=404)
    with pytest.raises(ApiError) as excinfo:
        client.get_app("x")
    payload = excinfo.value.to_dict()
    json.dumps(payload, ensure_ascii=False)  # не должно упасть
    assert payload["status"] == 404
    assert "нет такого" in payload["error"]


def _error_card(app_id="app-1"):
    return {"id": app_id, "status": "Error", "error": "Неизвестная ошибка. Обратитесь к администратору"}


def test_wait_app_ready_reports_task_errors(api):
    """Статус Error: к обобщённому тексту платформы добавляются ошибки задач.

    Ради этого метод и заведён – подробности компиляции лежат только в задаче,
    и без них причину приходится искать в логах сервера.
    """
    client, transport = api
    transport.add("GET", f"{API}/applications/app-1", _error_card())
    transport.add("GET", f"{API}/tasks/application-tasks", [
        {"application-id": "app-1", "status": "Completed", "error-message": "", "operation-type": "X"},
        {
            "application-id": "app-1",
            "status": "Failed",
            "operation-type": "CreateApplication",
            "error-message": 'Ошибка создания приложения: acme/Проект/Форма.yaml [22:27]: Тип "Х" не виден',
        },
        {"application-id": "other", "status": "Failed", "error-message": "чужая задача"},
    ])

    with pytest.raises(ApiError) as excinfo:
        client.wait_app_ready("app-1")

    message = str(excinfo.value)
    assert "Неизвестная ошибка" in message
    assert "CreateApplication" in message and "[22:27]" in message
    assert "чужая задача" not in message


def test_wait_app_ready_survives_unavailable_tasks(api):
    """Диагностика необязательна: сбой запроса задач не подменяет исходную ошибку."""
    client, transport = api
    transport.add("GET", f"{API}/applications/app-1", _error_card())
    transport.add("GET", f"{API}/tasks/application-tasks", {"message": "нет доступа"}, status=403)

    with pytest.raises(ApiError) as excinfo:
        client.wait_app_ready("app-1")
    assert "Неизвестная ошибка" in str(excinfo.value)


def test_failed_task_messages_skips_empty_and_successful(api):
    client, transport = api
    transport.add("GET", f"{API}/tasks/application-tasks", [
        {"application-id": "app-1", "status": "Failed", "error-message": "  "},
        {"application-id": "app-1", "status": "Completed", "error-message": "не ошибка"},
        {"application-id": "app-1", "status": "Error", "error-message": "первая"},
        {"application-id": "app-1", "status": "Failed", "error-message": "вторая", "operation-type": "Op"},
    ])
    # Свежие первыми: платформа отдаёт задачи в порядке появления.
    assert client.failed_task_messages("app-1") == ["Op: вторая", "первая"]


def test_token_cached_in_file(tmp_path):
    """Второй клиент с тем же кешем не ходит за токеном повторно."""
    cache_dir = tmp_path / "cache"
    config = Config(base_url="https://api.test", client_id="cid", client_secret="s", timeout=5.0)

    first_transport = FakeTransport()
    first_transport.add("POST", "/console/sys/token", {"token": "T1"})
    first = ElementClient(config, transport=first_transport, token_cache_dir=cache_dir)
    assert first.token() == "T1"

    second_transport = FakeTransport()  # маршрута токена нет: запрос был бы ошибкой
    second = ElementClient(config, transport=second_transport, token_cache_dir=cache_dir)
    assert second.token() == "T1"
    assert second_transport.calls == []


# -- фильтр списка приложений ------------------------------------------------------


def test_list_apps_filters_by_substring_on_the_client(api):
    """name – подстрока без учёта регистра; фильтр клиентский.

    Платформа query-параметр name игнорирует и возвращает полный список
    (проверено живым вызовом), поэтому запрос уходит без query.
    """
    client, transport = api
    transport.add(
        "GET",
        f"{API}/applications",
        [
            {"id": "1", "name": "crm-dev"},
            {"id": "2", "display-name": "Crm-Portal"},
            {"id": "3", "name": "warehouse-dev"},
            {"id": "4", "publication-context": "apps/crm-demo"},
        ],
    )
    assert [app["id"] for app in client.list_apps(name="CRM")] == ["1", "2", "4"]
    assert transport.calls_to("GET", f"{API}/applications")[0]["query"] == ""


def test_list_apps_without_name_returns_everything(api):
    client, transport = api
    transport.add("GET", f"{API}/applications", [{"id": "1"}, {"id": "2"}])
    assert len(client.list_apps()) == 2


# -- резолв приложения по имени -----------------------------------------------------


def test_resolve_app_id_uuid_passes_through_without_requests(api):
    client, transport = api
    uuid = "12345678-1234-1234-1234-123456789abc"
    # Транспорт без маршрута /applications: любой запрос упал бы AssertionError.
    assert client.resolve_app_id(uuid) == uuid
    assert transport.calls_to("GET", f"{API}/applications") == []


def test_resolve_app_id_by_exact_name(api):
    client, transport = api
    transport.add(
        "GET",
        f"{API}/applications",
        [
            {"id": "old", "display-name": "site-x", "status": "Deleted"},
            {"id": "live", "display-name": "Site-X", "status": "Running"},
        ],
    )
    # Точное имя без учёта регистра; удалённое приложение с тем же именем не мешает.
    assert client.resolve_app_id("site-x") == "live"


def test_resolve_app_id_unknown_name_is_config_error(api):
    client, transport = api
    transport.add("GET", f"{API}/applications", [{"id": "1", "name": "crm"}])
    with pytest.raises(ConfigError) as excinfo:
        client.resolve_app_id("nope")
    assert "nope" in str(excinfo.value)


def test_resolve_app_id_ambiguous_name_is_config_error(api):
    """Несколько совпадений – ошибка с перечнем ид: delete не должен угадывать."""
    client, transport = api
    transport.add(
        "GET",
        f"{API}/applications",
        [
            {"id": "a1", "name": "site", "status": "Running"},
            {"id": "a2", "display-name": "site", "status": "Stopped"},
        ],
    )
    with pytest.raises(ConfigError) as excinfo:
        client.resolve_app_id("site")
    message = str(excinfo.value)
    assert "a1" in message and "a2" in message


# -- Error как терминальный статус ожиданий ------------------------------------------


def _failed_compile_task(app_id="app-1"):
    return {
        "application-id": app_id,
        "status": "Failed",
        "operation-type": "UpdateApplication",
        "error-message": "acme/crm/Форма.yaml [10:5]: Тип \"Х\" не виден",
    }


def test_ensure_running_stops_immediately_on_error_status(api):
    """Стабильный Error после применения – немедленная ошибка с текстами задач.

    Раньше ensure_running пытался остановить такое приложение и ждал Stopped
    до полного таймаута (180 с), хотя из Error оно в Stopped не переходит.
    """
    client, transport = api
    transport.add("GET", f"{API}/applications/app-1", _error_card())
    transport.add("GET", f"{API}/tasks/application-tasks", [_failed_compile_task()])
    client._sleep = lambda seconds: pytest.fail("ожиданий быть не должно: Error стабилен")

    with pytest.raises(ApiError) as excinfo:
        client.ensure_running("app-1")

    message = str(excinfo.value)
    assert "Error" in message and "[10:5]" in message
    # До остановки и запуска дело не дошло.
    assert transport.calls_to("PUT", f"{API}/applications/app-1/status/stop") == []
    assert transport.calls_to("PUT", f"{API}/applications/app-1/status/start") == []


def test_wait_app_status_error_carries_task_details(api):
    client, transport = api
    transport.add("GET", f"{API}/applications/app-1", _error_card())
    transport.add("GET", f"{API}/tasks/application-tasks", [_failed_compile_task()])

    with pytest.raises(ApiError) as excinfo:
        client.wait_app_status("app-1", {"Stopped"}, timeout=30)

    message = str(excinfo.value)
    assert "Error" in message and "[10:5]" in message
