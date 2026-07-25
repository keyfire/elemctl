"""User lists: resolving, the sign-in settings and the commands over them.

Behind the control panel wording there are two different things, and that is what
the tests pin down: "allow users to register themselves" is the self-registration
settings of the list, while "allow signing in with a login and a password" is the
account service of type Local being enabled.
"""

from __future__ import annotations

import json

import pytest

from elemctl import cli
from elemctl.client import LOCAL_SERVICE
from elemctl.errors import ConfigError

API = "/console/api/v2"

PANEL = {"id": "list-panel", "presentation": "Список пользователей панели управления"}
SITE = {"id": "list-site", "presentation": 'Список пользователей приложения "site"'}

LOCAL = {
    "account-service-id": "svc-local",
    "account-service-type": LOCAL_SERVICE,
    "local-id": "",
    "enabled": True,
    "create-user-on-auth": True,
    "additional-settings": {"external_service_id": "svc-local"},
}
OIDC = {
    "account-service-id": "svc-oidc",
    "account-service-type": "OIDC",
    "local-id": "внешний вход",
    "enabled": True,
    "create-user-on-auth": True,
    "additional-settings": {"client_id": "acme"},
}


# --- the client ---------------------------------------------------------------------

def test_resolve_user_list_id_uuid_passes_through_without_requests(api):
    client, transport = api
    uuid = "12345678-1234-1234-1234-123456789abc"
    # The transport has no /user-lists route: any request would raise AssertionError.
    assert client.resolve_user_list_id(uuid) == uuid
    assert transport.calls_to("GET", f"{API}/user-lists") == []


def test_resolve_user_list_id_by_exact_presentation(api):
    client, transport = api
    transport.add("GET", f"{API}/user-lists", [PANEL, SITE])
    assert client.resolve_user_list_id('список пользователей приложения "site"') == "list-site"


def test_resolve_user_list_id_unknown_is_config_error(api):
    client, transport = api
    transport.add("GET", f"{API}/user-lists", [PANEL])
    with pytest.raises(ConfigError) as excinfo:
        client.resolve_user_list_id("нет такого")
    assert "нет такого" in str(excinfo.value)


def test_resolve_user_list_id_ambiguous_is_config_error(api):
    """Several matches – an error listing the ids: a setting must not be changed by a guess."""
    client, transport = api
    transport.add("GET", f"{API}/user-lists", [
        {"id": "l1", "presentation": "общий"}, {"id": "l2", "presentation": "Общий"},
    ])
    with pytest.raises(ConfigError) as excinfo:
        client.resolve_user_list_id("общий")
    assert "l1" in str(excinfo.value) and "l2" in str(excinfo.value)


def test_list_user_lists_filters_by_presentation_on_the_client(api):
    client, transport = api
    transport.add("GET", f"{API}/user-lists", [PANEL, SITE])
    assert [entry["id"] for entry in client.list_user_lists(name="ПРИЛОЖЕНИЯ")] == ["list-site"]


APP_UUID = "12345678-1234-1234-1234-1234567890ab"


def test_app_user_list_id_takes_the_applications_own_list(api):
    client, transport = api
    transport.add("GET", f"{API}/applications/{APP_UUID}", {
        "id": APP_UUID, "default-user-list": "list-site",
        "user-lists": ["list-panel", "list-site"],
    })
    assert client.app_user_list_id(APP_UUID) == "list-site"


def test_app_without_its_own_list_is_config_error(api):
    client, transport = api
    transport.add("GET", f"{API}/applications/{APP_UUID}", {"id": APP_UUID, "default-user-list": ""})
    with pytest.raises(ConfigError):
        client.app_user_list_id(APP_UUID)


def test_set_self_registration_keeps_the_other_requirements(api):
    """The platform wants the whole settings object – only the flag may change."""
    client, transport = api
    path = f"{API}/user-lists/list-site/settings/self-registration"
    transport.add("GET", path, {"enabled": True, "phone-required": True, "email-required": False})
    transport.add("PUT", path, None, status=204)
    transport.add("GET", path, {"enabled": False, "phone-required": True, "email-required": False})

    result = client.set_self_registration("list-site", enabled=False)

    sent = json.loads(transport.calls_to("PUT", path)[0]["data"])
    assert sent == {"enabled": False, "phone-required": True, "email-required": False}
    assert result["enabled"] is False


def test_set_password_login_switches_the_local_service(api):
    client, transport = api
    services = f"{API}/user-lists/list-site/settings/account-services-settings"
    transport.add("GET", services, [OIDC, LOCAL])
    transport.add("PUT", f"{services}/svc-local", None, status=204)

    outcome = client.set_password_login("list-site", enabled=False)

    assert outcome["changed"] is True
    sent = json.loads(transport.calls_to("PUT", f"{services}/svc-local")[0]["data"])
    assert sent["enabled"] is False
    # The rest of the entry goes back as it came: the platform expects the whole card.
    assert sent["additional-settings"] == LOCAL["additional-settings"]
    assert sent["create-user-on-auth"] is True


def test_set_password_login_is_idempotent(api):
    """Already in the wanted state – no request and changed: false."""
    client, transport = api
    services = f"{API}/user-lists/list-site/settings/account-services-settings"
    transport.add("GET", services, [{**LOCAL, "enabled": False}])

    outcome = client.set_password_login("list-site", enabled=False)

    assert outcome["changed"] is False
    assert transport.calls_to("PUT", f"{services}/svc-local") == []


def test_set_password_login_without_a_local_service_is_an_answer(api):
    """A list that signs in only through an external service has nothing to switch."""
    client, transport = api
    services = f"{API}/user-lists/list-site/settings/account-services-settings"
    transport.add("GET", services, [OIDC])

    outcome = client.set_password_login("list-site", enabled=False)

    assert outcome == {"service": None, "changed": False}


# --- the CLI ------------------------------------------------------------------------

class FakeListClient:
    """A stub client with the user-list methods of the real one."""

    def __init__(self, *, local="по умолчанию", self_registration=None):
        self.local = dict(LOCAL) if local == "по умолчанию" else local
        self.self_registration = self_registration or {
            "enabled": True, "phone-required": False, "email-required": False
        }
        self.calls = []

    def list_user_lists(self, name=""):
        self.calls.append(("list", name))
        return [PANEL, SITE]

    def resolve_user_list_id(self, name_or_id):
        self.calls.append(("resolve", name_or_id))
        return "list-site"

    def app_user_list_id(self, app_id):
        self.calls.append(("by-app", app_id))
        return "list-site"

    def get_user_list(self, list_id):
        return {"id": list_id, "presentation": SITE["presentation"]}

    def get_self_registration(self, list_id):
        return dict(self.self_registration)

    def set_self_registration(self, list_id, enabled):
        self.calls.append(("set-self-registration", enabled))
        self.self_registration["enabled"] = enabled
        return dict(self.self_registration)

    def list_account_services(self, list_id):
        return [OIDC] + ([self.local] if self.local else [])

    def set_password_login(self, list_id, enabled):
        self.calls.append(("set-password-login", enabled))
        if self.local is None:
            return {"service": None, "changed": False}
        changed = bool(self.local["enabled"]) != bool(enabled)
        self.local["enabled"] = enabled
        return {"service": self.local, "changed": changed}


def _install(monkeypatch, client):
    monkeypatch.setattr(cli, "make_client", lambda config: client)
    return client


def test_cli_user_lists_list(monkeypatch, capsys):
    _install(monkeypatch, FakeListClient())
    assert cli.main(["user-lists", "list"]) == 0
    assert [entry["id"] for entry in json.loads(capsys.readouterr().out)] == [
        "list-panel", "list-site"
    ]


def test_cli_self_registration_disable(monkeypatch, capsys):
    client = _install(monkeypatch, FakeListClient())
    assert cli.main(["user-lists", "self-registration", "--app", "site", "--disable"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["self-registration"]["enabled"] is False
    assert ("by-app", "site") in client.calls
    assert ("set-self-registration", False) in client.calls


def test_cli_self_registration_without_flags_only_shows(monkeypatch, capsys):
    """No flag – the command is a read: the same call answers "how is it now"."""
    client = _install(monkeypatch, FakeListClient())
    assert cli.main(["user-lists", "self-registration", "список"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["self-registration"]["enabled"] is True
    assert not [call for call in client.calls if call[0] == "set-self-registration"]


def test_cli_password_login_disable(monkeypatch, capsys):
    client = _install(monkeypatch, FakeListClient())
    assert cli.main(["user-lists", "password-login", "--app", "site", "--disable"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "list-id": "list-site", "enabled": False, "changed": True
    }


def test_cli_password_login_without_a_local_service_answers_null(monkeypatch, capsys):
    _install(monkeypatch, FakeListClient(local=None))
    assert cli.main(["user-lists", "password-login", "--app", "site"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "list-id": "list-site", "enabled": None, "changed": False
    }


def test_cli_enable_and_disable_together_is_an_error(monkeypatch, capsys):
    _install(monkeypatch, FakeListClient())
    assert cli.main(["user-lists", "password-login", "--app", "site", "--enable", "--disable"]) == 1
    assert "--enable" in json.loads(capsys.readouterr().err)["error"]


def test_cli_list_and_app_together_is_an_error(monkeypatch, capsys):
    _install(monkeypatch, FakeListClient())
    assert cli.main(["user-lists", "get", "список", "--app", "site"]) == 1
    assert "--app" in json.loads(capsys.readouterr().err)["error"]


def test_cli_without_a_target_is_an_error(monkeypatch, capsys):
    _install(monkeypatch, FakeListClient())
    assert cli.main(["user-lists", "get"]) == 1
    assert "LIST" in json.loads(capsys.readouterr().err)["error"]
