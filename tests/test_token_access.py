"""Access of a user to the HTTP services of an application by a token.

A call of an application's HTTP service with a user's token is refused with a 500 "Token
access is denied" until the flag of the user's connection to the application,
`token-access-enabled`, is on. The console switches it with
PUT /applications/{id}/users/change-token-access and shows it in GET /applications/{id}/users;
the tests pin down that the switch names the connection exactly, reads the flag back, and says
so when a user is not connected at all instead of letting the platform answer a bare 500.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from elemctl import cli
from elemctl.client import repeated_values
from elemctl.errors import ConfigError, ElemctlError

API = "/console/api/v2"
APP = "11111111-2222-3333-4444-555555555555"
PANEL = "list-panel"
USERS = f"{API}/applications/{APP}/users"
CHANGE = f"{USERS}/change-token-access"

ADMIN = {"user-list-id": PANEL, "user-id": "user-admin", "presentation": "admin",
         "is-admin": True, "token-access-enabled": False}
JDOE = {"user-list-id": PANEL, "user-id": "user-jdoe", "presentation": "jdoe",
        "is-admin": True, "token-access-enabled": False}


def _flag(entry, value):
    return {**entry, "token-access-enabled": value}


# --- the client ---------------------------------------------------------------------

def test_reading_changes_nothing(api):
    client, transport = api
    transport.add("GET", USERS, [ADMIN, JDOE])

    report = client.token_access(APP, user="jdoe")

    assert report == {
        "app-id": APP, "user": "jdoe", "user-id": "user-jdoe", "user-list-id": PANEL,
        "token-access-enabled": False, "changed": False,
    }
    assert transport.calls_to("PUT", CHANGE) == []


def test_enabling_names_the_connection_and_reads_the_flag_back(api):
    client, transport = api
    transport.add("GET", USERS, [ADMIN, JDOE])
    transport.add("PUT", CHANGE, _flag(JDOE, True))
    transport.add("GET", USERS, [ADMIN, _flag(JDOE, True)])

    report = client.token_access(APP, user="jdoe", enabled=True)

    sent = json.loads(transport.calls_to("PUT", CHANGE)[0]["data"])
    assert sent == {"user-list-id": PANEL, "user-id": "user-jdoe", "enable-access": True}
    assert report["token-access-enabled"] is True and report["changed"] is True
    # The flag in the answer is the one read back, not the one asked for.
    assert len(transport.calls_to("GET", USERS)) == 2


def test_disabling_goes_the_same_way(api):
    client, transport = api
    transport.add("GET", USERS, [_flag(JDOE, True)])
    transport.add("PUT", CHANGE, JDOE)
    transport.add("GET", USERS, [JDOE])

    report = client.token_access(APP, user="jdoe", enabled=False)

    assert json.loads(transport.calls_to("PUT", CHANGE)[0]["data"])["enable-access"] is False
    assert report["token-access-enabled"] is False and report["changed"] is True


def test_the_state_already_there_sends_no_request(api):
    client, transport = api
    transport.add("GET", USERS, [_flag(JDOE, True)])

    report = client.token_access(APP, user="jdoe", enabled=True)

    assert report["changed"] is False and report["token-access-enabled"] is True
    assert transport.calls_to("PUT", CHANGE) == []


def test_a_flag_that_did_not_move_is_an_error(api):
    client, transport = api
    transport.add("GET", USERS, [JDOE])
    transport.add("PUT", CHANGE, JDOE)
    transport.add("GET", USERS, [JDOE])

    with pytest.raises(ElemctlError, match="token-access-enabled: false вместо true"):
        client.token_access(APP, user="jdoe", enabled=True)


def test_a_connection_gone_after_the_change_is_an_error(api):
    client, transport = api
    transport.add("GET", USERS, [JDOE])
    transport.add("PUT", CHANGE, _flag(JDOE, True))
    transport.add("GET", USERS, [ADMIN])

    with pytest.raises(ElemctlError, match="не называет"):
        client.token_access(APP, user="jdoe", enabled=True)


def test_without_a_user_the_account_of_the_credentials_is_meant(api):
    """elemctl signs in as a user, and that user is the one a live check calls services as."""
    client, transport = api
    transport.add("GET", USERS, [ADMIN, JDOE])
    transport.add("GET", f"{API}/me", {"id": "user-jdoe", "login": "jdoe",
                                       "presentation": "John Doe", "user-list-id": PANEL})

    report = client.token_access(APP)

    assert report["user-id"] == "user-jdoe"
    assert len(transport.calls_to("GET", f"{API}/me")) == 1


def test_a_login_that_is_not_a_presentation_is_looked_up_in_the_list(api):
    """The application's listing names a user by a presentation; the login lives in the list.

    The list carries the access tokens of its users, and none of that reaches the answer.
    """
    client, transport = api
    transport.add("GET", USERS, [ADMIN, {**JDOE, "presentation": "John Doe"}])
    transport.add("GET", f"{API}/user-lists/{PANEL}/users", [
        {"id": "user-admin", "login": "admin", "access-tokens": [{"client-secret": "s1"}]},
        {"id": "user-jdoe", "login": "JDoe", "access-tokens": [{"client-secret": "s2"}]},
    ])

    report = client.token_access(APP, user="jdoe")

    assert report["user-id"] == "user-jdoe" and report["user"] == "John Doe"
    assert "s2" not in json.dumps(report)


def test_a_user_id_is_matched_without_any_lookup(api):
    client, transport = api
    uid = "99999999-8888-7777-6666-555555555555"
    transport.add("GET", USERS, [ADMIN, {**JDOE, "user-id": uid}])

    assert client.token_access(APP, user=uid)["user"] == "jdoe"
    assert transport.calls_to("GET", f"{API}/me") == []


def test_a_user_not_connected_is_named_and_nothing_is_sent(api):
    """The platform answers such a change with a bare 500; the refusal says what is wrong."""
    client, transport = api
    transport.add("GET", USERS, [ADMIN, JDOE])
    transport.add("GET", f"{API}/user-lists/{PANEL}/users", [{"id": "user-admin", "login": "admin"}])

    with pytest.raises(ConfigError) as error:
        client.token_access(APP, user="ghost", enabled=True)

    message = str(error.value)
    assert "ghost" in message and "не подключён" in message and "admin, jdoe" in message
    assert transport.calls_to("PUT", CHANGE) == []


def test_two_connections_of_one_name_are_not_guessed_between(api):
    client, transport = api
    transport.add("GET", USERS, [JDOE, {**JDOE, "user-id": "user-jdoe-2", "user-list-id": "list-app"}])

    with pytest.raises(ConfigError, match="user-jdoe, user-jdoe-2"):
        client.token_access(APP, user="jdoe", enabled=True)
    assert transport.calls_to("PUT", CHANGE) == []


# --- the CLI ------------------------------------------------------------------------

def _cli(monkeypatch, api):
    client, transport = api
    monkeypatch.setattr(cli, "make_client", lambda config: client)
    return transport


def test_cli_switches_and_prints_the_flag_read_back(monkeypatch, capsys, api):
    transport = _cli(monkeypatch, api)
    transport.add("GET", USERS, [JDOE])
    transport.add("PUT", CHANGE, _flag(JDOE, True))
    transport.add("GET", USERS, [_flag(JDOE, True)])

    rc = cli.main(["apps", "token-access", APP, "--user", "jdoe", "--enable"])

    assert rc == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["token-access-enabled"] is True and answer["changed"] is True


def test_cli_without_flags_only_reads(monkeypatch, capsys, api):
    transport = _cli(monkeypatch, api)
    transport.add("GET", USERS, [JDOE])

    assert cli.main(["apps", "token-access", "--app-id", APP, "--user", "jdoe"]) == 0
    assert json.loads(capsys.readouterr().out)["changed"] is False
    assert transport.calls_to("PUT", CHANGE) == []


def test_cli_takes_no_application_from_the_environment(monkeypatch, capsys, api):
    """ELEMENT_APP_ID names the working application; a switch of access must name its own."""
    _cli(monkeypatch, api)
    monkeypatch.setenv("ELEMENT_APP_ID", APP)

    rc = cli.main(["apps", "token-access", "--user", "jdoe", "--enable"])

    assert rc == 1
    assert "ELEMENT_APP_ID" in json.loads(capsys.readouterr().err)["error"]


def test_cli_enable_and_disable_together_is_an_error(monkeypatch, capsys, api):
    _cli(monkeypatch, api)
    rc = cli.main(["apps", "token-access", APP, "--enable", "--disable"])
    assert rc == 1
    assert "--enable" in json.loads(capsys.readouterr().err)["error"]


# --- a repeated --user --------------------------------------------------------------
#
# The key was a single one, and a second --user replaced the first without a word: the answer
# spoke about the last user only, and the access of the others stayed as it was.


def test_the_values_of_a_repeated_key_keep_their_order_and_come_once():
    assert repeated_values(None) == []
    assert repeated_values("jdoe") == ["jdoe"]
    assert repeated_values(["jdoe", " jdoe ", "admin", ""]) == ["jdoe", "admin", ""]


def test_cli_takes_the_user_key_several_times():
    args = cli.build_parser().parse_args(
        ["apps", "token-access", APP, "--user", "jdoe", "--user", "admin"]
    )
    assert args.user == ["jdoe", "admin"]


def test_cli_help_says_the_user_key_repeats(capsys):
    with pytest.raises(SystemExit):
        cli.main(["apps", "token-access", "--help"])
    assert "ключ можно повторить" in " ".join(capsys.readouterr().out.split())


def test_cli_switches_every_user_and_one_that_fails_stops_nobody(monkeypatch, capsys, api):
    transport = _cli(monkeypatch, api)
    transport.add("GET", USERS, [ADMIN, JDOE])  # jdoe is found
    transport.add("GET", USERS, [ADMIN, _flag(JDOE, True)])  # jdoe is read back
    transport.add("GET", USERS, [ADMIN, _flag(JDOE, True)])  # ghost is not connected
    transport.add("GET", USERS, [ADMIN, _flag(JDOE, True)])  # admin is found
    transport.add("GET", USERS, [_flag(ADMIN, True), _flag(JDOE, True)])  # admin is read back
    transport.add("PUT", CHANGE, {})
    transport.add("GET", f"{API}/user-lists/{PANEL}/users", [{"id": "user-admin", "login": "admin"}])

    rc = cli.main([
        "apps", "token-access", APP, "--user", "jdoe", "--user", "ghost", "--user", "admin",
        "--enable",
    ])

    assert rc == 1
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False and answer["app-id"] == APP
    jdoe, ghost, admin = answer["users"]
    assert jdoe["ok"] is True and jdoe["user"] == "jdoe" and jdoe["changed"] is True
    assert ghost["ok"] is False and ghost["user"] == "ghost"
    assert "не подключён" in ghost["error"]
    assert admin["ok"] is True and admin["token-access-enabled"] is True
    switched = [json.loads(call["data"])["user-id"] for call in transport.calls_to("PUT", CHANGE)]
    assert switched == ["user-jdoe", "user-admin"]


def test_cli_repeated_users_that_all_read_well_end_with_zero(monkeypatch, capsys, api):
    transport = _cli(monkeypatch, api)
    transport.add("GET", USERS, [ADMIN, JDOE])

    assert cli.main(["apps", "token-access", APP, "--user", "jdoe", "--user", "admin"]) == 0

    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is True
    assert [entry["user"] for entry in answer["users"]] == ["jdoe", "admin"]
    assert transport.calls_to("PUT", CHANGE) == []


def test_cli_the_same_user_given_twice_answers_as_one(monkeypatch, capsys, api):
    """One user is one answer, and it keeps the shape a single key always printed."""
    transport = _cli(monkeypatch, api)
    transport.add("GET", USERS, [JDOE])

    assert cli.main(["apps", "token-access", APP, "--user", "jdoe", "--user", "jdoe"]) == 0

    answer = json.loads(capsys.readouterr().out)
    assert answer["user"] == "jdoe" and "users" not in answer
    assert len(transport.calls_to("GET", USERS)) == 1


# --- the MCP tool -------------------------------------------------------------------

def test_mcp_tool_resolves_the_application_and_switches(monkeypatch):
    pytest.importorskip("mcp.server", reason="extra elemctl[mcp] не установлен")
    from elemctl import mcp_server
    from elemctl.config import Config

    calls = []

    class FakeClient:
        def resolve_app_id(self, name_or_id):
            return APP if name_or_id == "crm-dev" else name_or_id

        def token_access(self, app_id, user="", enabled=None):
            calls.append((app_id, user, enabled))
            return {"app-id": app_id, "token-access-enabled": True, "changed": True}

    monkeypatch.setattr(mcp_server, "ElementClient", lambda config: FakeClient())
    server = mcp_server.create_server(
        Config(base_url="https://api.test", client_id="cid", client_secret="secret")
    )

    result = asyncio.run(server.call_tool(
        "token_access", {"app_id": "crm-dev", "user": "jdoe", "enabled": True}
    ))
    payload = json.loads(mcp_server.call_result_content(result)[0].text)

    assert calls == [(APP, "jdoe", True)]
    assert payload["changed"] is True


def _mcp_server_over(monkeypatch, fake):
    pytest.importorskip("mcp.server", reason="extra elemctl[mcp] не установлен")
    from elemctl import mcp_server
    from elemctl.config import Config

    monkeypatch.setattr(mcp_server, "ElementClient", lambda config: fake)
    return mcp_server, mcp_server.create_server(
        Config(base_url="https://api.test", client_id="cid", client_secret="secret")
    )


class _FakeUsersClient:
    """The two client methods the tool calls; ghost is the user that is not connected."""

    def __init__(self):
        self.calls = []

    def resolve_app_id(self, name_or_id):
        return APP

    def token_access(self, app_id, user="", enabled=None):
        self.calls.append(user)
        if user == "ghost":
            raise ConfigError("пользователь 'ghost' не подключён")
        return {"app-id": app_id, "user": user, "token-access-enabled": True, "changed": True}


def test_mcp_tool_takes_an_array_of_users_and_answers_with_an_entry_each(monkeypatch):
    fake = _FakeUsersClient()
    mcp_server, server = _mcp_server_over(monkeypatch, fake)

    result = asyncio.run(server.call_tool(
        "token_access",
        {"app_id": "crm-dev", "user": ["jdoe", "ghost", "admin"], "enabled": True},
    ))
    payload = json.loads(mcp_server.call_result_content(result)[0].text)

    assert fake.calls == ["jdoe", "ghost", "admin"]
    assert payload["ok"] is False and payload["app-id"] == APP
    assert [entry["ok"] for entry in payload["users"]] == [True, False, True]
    assert payload["users"][1] == {
        "ok": False, "user": "ghost", "error": "пользователь 'ghost' не подключён",
    }


def test_mcp_tool_schema_takes_a_string_or_an_array_and_one_user_keeps_the_old_answer(monkeypatch):
    fake = _FakeUsersClient()
    mcp_server, server = _mcp_server_over(monkeypatch, fake)

    tool = next(t for t in asyncio.run(server.list_tools()) if t.name == "token_access")
    shapes = mcp_server.tool_input_schema(tool)["properties"]["user"]["anyOf"]
    assert {"type": "string"} in shapes
    assert {"items": {"type": "string"}, "type": "array"} in shapes

    result = asyncio.run(server.call_tool("token_access", {"app_id": APP, "user": ["jdoe"]}))
    payload = json.loads(mcp_server.call_result_content(result)[0].text)
    assert payload == {"app-id": APP, "user": "jdoe", "token-access-enabled": True, "changed": True}
