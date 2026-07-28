"""Console API client tests on a stub transport (no network)."""

from __future__ import annotations

import json

import pytest

from elemctl.auth import extract_token
from elemctl.client import ElementClient, extract_assembly_id, sign_in_hint
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
    # The token was requested twice: initially and forcibly after the 401.
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
    # The action carries no request body.
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
    assert client.find_app("site") is None  # a partial match does not count
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
    # The deleted card is skipped – the live application with the same name is found.
    assert client.find_app("site")["id"] == "live"


def test_find_app_include_deleted_returns_deleted(api):
    client, transport = api
    # The single response is replayed for both find_app calls.
    transport.add(
        "GET",
        f"{API}/applications",
        [{"id": "old", "display-name": "site-old", "status": "DELETED"}],
    )
    # By default a deleted application is not found...
    assert client.find_app("site-old") is None
    # ...and with include_deleted=True the former behaviour is back (status compared case-insensitively).
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
    """Assembly get/delete accept a version: the API addresses an assembly by UUID only, so a
    non-UUID argument is resolved to an id through the assembly list (the platform renumbers
    versions)."""
    client, transport = api
    assembly_id = "0a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d"
    transport.add(
        "GET", f"{API}/projects/p1/assemblies",
        [{"assembly-version": "1.0-39", "project-version": "1.0-39", "id": assembly_id}],
    )
    transport.add("DELETE", f"{API}/projects/p1/assemblies/{assembly_id}", {"deleted": True})
    assert client.delete_assembly("p1", "1.0-39") == {"deleted": True}
    # A UUID goes straight through, without fetching the list.
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
    # References are collapsed down to {"id": ...}.
    assert body["source-branch"] == {"id": "b0"}
    assert body["application"] == {"id": "app-1"}
    assert body["write-parameters"] == {"merge": True}
    # The project field is not part of the PUT body.
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
    json.dumps(payload, ensure_ascii=False)  # must not raise
    assert payload["status"] == 404
    assert "нет такого" in payload["error"]


def _error_card(app_id="app-1"):
    return {"id": app_id, "status": "Error", "error": "Неизвестная ошибка. Обратитесь к администратору"}


def test_wait_app_ready_reports_task_errors(api):
    """Status Error: the platform's generic text is enriched with the task errors.

    That is the very reason the method exists – the compilation details live in the task
    alone, and without them the cause has to be dug out of the server logs.
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
    """Diagnostics are optional: a failing task request does not replace the original error."""
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
    # Freshest first: the platform returns tasks in the order they appeared.
    assert client.failed_task_messages("app-1") == ["Op: вторая", "первая"]


def test_token_cached_in_file(tmp_path):
    """A second client sharing the cache does not fetch the token again."""
    cache_dir = tmp_path / "cache"
    config = Config(base_url="https://api.test", client_id="cid", client_secret="s", timeout=5.0)

    first_transport = FakeTransport()
    first_transport.add("POST", "/console/sys/token", {"token": "T1"})
    first = ElementClient(config, transport=first_transport, token_cache_dir=cache_dir)
    assert first.token() == "T1"

    second_transport = FakeTransport()  # no token route: a request would be an error
    second = ElementClient(config, transport=second_transport, token_cache_dir=cache_dir)
    assert second.token() == "T1"
    assert second_transport.calls == []


# -- application list filter -------------------------------------------------------


def test_list_apps_filters_by_substring_on_the_client(api):
    """name is a case-insensitive substring; the filter is applied client-side.

    The platform ignores the name query parameter and returns the full list
    (verified with a live call), so the request goes out with no query at all.
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


# -- resolving an application by name -----------------------------------------------


def test_resolve_app_id_uuid_passes_through_without_requests(api):
    client, transport = api
    uuid = "12345678-1234-1234-1234-123456789abc"
    # The transport has no /applications route: any request would raise AssertionError.
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
    # An exact, case-insensitive name; a deleted application with the same name is no obstacle.
    assert client.resolve_app_id("site-x") == "live"


def test_resolve_app_id_unknown_name_is_config_error(api):
    client, transport = api
    transport.add("GET", f"{API}/applications", [{"id": "1", "name": "crm"}])
    with pytest.raises(ConfigError) as excinfo:
        client.resolve_app_id("nope")
    assert "nope" in str(excinfo.value)


def test_resolve_app_id_ambiguous_name_is_config_error(api):
    """Several matches – an error listing the ids: delete must never guess which one is meant."""
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


# -- Error as a terminal status for the waits ----------------------------------------


def _failed_compile_task(app_id="app-1"):
    return {
        "application-id": app_id,
        "status": "Failed",
        "operation-type": "UpdateApplication",
        "error-message": "acme/crm/Форма.yaml [10:5]: Тип \"Х\" не виден",
    }


def test_ensure_running_stops_immediately_on_error_status(api):
    """A steady Error after the apply – an immediate error carrying the task texts.

    ensure_running used to try to stop such an application and waited for Stopped
    until the full timeout (180 s), even though Error never turns into Stopped.
    """
    client, transport = api
    transport.add("GET", f"{API}/applications/app-1", _error_card())
    transport.add("GET", f"{API}/tasks/application-tasks", [_failed_compile_task()])
    client._sleep = lambda seconds: pytest.fail("ожиданий быть не должно: Error стабилен")

    with pytest.raises(ApiError) as excinfo:
        client.ensure_running("app-1")

    message = str(excinfo.value)
    assert "Error" in message and "[10:5]" in message
    # Neither the stop nor the start was ever reached.
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


def test_retry_once_on_a_400_that_rejects_the_token(api):
    """A rejected token comes back as 400, not 401.

    The server answers error_code=invalid_request with the reason in
    error_description ("JWT strings must contain exactly 2 period characters",
    "Unable to verify RSA signature ..."). The refresh-and-retry used to watch only
    for 401, so a token the server had rejected survived its whole TTL in the cache
    file and the cure was written down as deleting that file by hand.
    """
    client, transport = api
    transport.add(
        "GET",
        f"{API}/applications",
        {
            "error_code": "invalid_request",
            "error_description": "JWT strings must contain exactly 2 period characters. Found: 0",
        },
        status=400,
    )
    transport.add("GET", f"{API}/applications", [{"id": "app-1"}])

    apps = client.list_apps()

    assert apps == [{"id": "app-1"}]
    assert len(transport.calls_to("POST", "/console/sys/token")) == 2


def test_an_ordinary_400_is_not_retried(api):
    """A bad request must not send us after a new token: the description says nothing about a token."""
    client, transport = api
    transport.add(
        "GET",
        f"{API}/applications",
        {"error_code": "invalid_request", "error_description": "name must not be empty"},
        status=400,
    )

    with pytest.raises(ApiError):
        client.list_apps()

    assert len(transport.calls_to("POST", "/console/sys/token")) == 1
    assert len(transport.calls_to("GET", f"{API}/applications")) == 1


# --- The way into a freshly created application ---------------------------------


def test_sign_in_hint_names_the_address_and_the_account():
    """The hint answers both questions of a fresh stand: where and as whom."""
    hint = sign_in_hint({"id": "app-1", "uri": "https://host/apps/crm-dev"})

    assert hint["url"] == "https://host/apps/crm-dev"
    assert hint["account"] == "control-panel"
    assert "https://host/apps/crm-dev" in hint["hint"]


def test_sign_in_hint_warns_that_accounts_used_elsewhere_do_not_work_here():
    """The note is the part that saves the hours: accounts used elsewhere do not work.

    Connecting the user list of another application and enabling the local
    sign-in look like a fix and are not one - a new application has no
    account service of its own.
    """
    note = sign_in_hint({"uri": "https://host/apps/crm-dev"})["note"]

    assert "другие приложения" in note
    assert "https://host/apps/crm-dev" not in note  # the note is about the accounts, not the address


def test_sign_in_hint_does_not_invent_an_address():
    """An application that is still starting has no uri: the address is None, not a guess."""
    for card in ({"id": "app-1"}, {"id": "app-1", "uri": ""}, {"id": "app-1", "uri": "   "}, None):
        hint = sign_in_hint(card)
        assert hint["url"] is None, card
        assert hint["account"] == "control-panel", card
        assert "apps get" in hint["hint"], card  # where the address comes from later
