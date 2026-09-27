"""Who is connected to an application: `apps users` and the MCP tool `list_app_users`.

The reference documents GET /applications/{id}/users as the users connected to the application,
and the client already read it to switch token access. The list itself was seen only inside a
refusal of `apps token-access`, which names the connected users when the one asked for is not
among them. The tests pin down that the command shows the list as the platform gives it and
counts it in one line.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from elemctl import cli
from elemctl.client import app_users_summary

API = "/console/api/v2"
APP = "11111111-2222-3333-4444-555555555555"
USERS = f"{API}/applications/{APP}/users"

ADMIN = {"user-list-id": "list-panel", "user-id": "user-admin", "presentation": "admin",
         "is-admin": True, "token-access-enabled": False}
JDOE = {"user-list-id": "list-app", "user-id": "user-jdoe", "presentation": "John Doe",
        "is-admin": False, "token-access-enabled": True}


def _cli(monkeypatch, api):
    client, transport = api
    monkeypatch.setattr(cli, "make_client", lambda config: client)
    return transport


def test_the_summary_counts_the_administrators_and_the_token_access():
    assert app_users_summary([ADMIN, JDOE]) == (
        "подключено 2: администраторов 1, с доступом по токену 1"
    )
    assert app_users_summary([]) == "подключено 0: администраторов 0, с доступом по токену 0"


def test_cli_prints_the_users_as_the_platform_gives_them_and_counts_them(
    monkeypatch, capsys, api
):
    transport = _cli(monkeypatch, api)
    transport.add("GET", USERS, [ADMIN, JDOE])

    rc = cli.main(["apps", "users", APP])

    assert rc == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == [ADMIN, JDOE]
    assert "подключено 2: администраторов 1, с доступом по токену 1" in captured.err
    # Reading only: nothing is switched on the way.
    assert [call["method"] for call in transport.calls] == ["POST", "GET"]


def test_cli_finds_the_application_by_its_name(monkeypatch, capsys, api):
    transport = _cli(monkeypatch, api)
    transport.add("GET", f"{API}/applications", [{"id": APP, "name": "crm-dev"}])
    transport.add("GET", USERS, [ADMIN])

    assert cli.main(["apps", "users", "crm-dev"]) == 0
    assert json.loads(capsys.readouterr().out) == [ADMIN]


def test_cli_reads_the_application_of_the_environment(monkeypatch, capsys, api):
    """A read names no application to open, so the one of the environment will do."""
    transport = _cli(monkeypatch, api)
    monkeypatch.setenv("ELEMENT_APP_ID", APP)
    transport.add("GET", USERS, [])

    assert cli.main(["apps", "users"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert "подключено 0" in captured.err


def test_mcp_tool_resolves_the_application_and_counts_the_users(monkeypatch):
    pytest.importorskip("mcp.server", reason="extra elemctl[mcp] не установлен")
    from elemctl import mcp_server
    from elemctl.config import Config

    class FakeClient:
        def resolve_app_id(self, name_or_id):
            return APP if name_or_id == "crm-dev" else name_or_id

        def list_app_users(self, app_id):
            assert app_id == APP
            return [ADMIN, JDOE]

    monkeypatch.setattr(mcp_server, "ElementClient", lambda config: FakeClient())
    server = mcp_server.create_server(
        Config(base_url="https://api.test", client_id="cid", client_secret="secret")
    )

    result = asyncio.run(server.call_tool("list_app_users", {"app_id": "crm-dev"}))
    payload = json.loads(mcp_server.call_result_content(result)[0].text)

    assert payload["app-id"] == APP
    assert payload["total"] == 2
    assert payload["users"] == [ADMIN, JDOE]
    assert payload["summary"] == "подключено 2: администраторов 1, с доступом по токену 1"
