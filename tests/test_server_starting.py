"""A server whose console is still starting: named as such, and waited out by a deploy.

While the server starts, every console request is answered with a 404 whose text names the
console application. The commands used to hand that 404 over as it came, and a deploy died
on the listing of builds with nothing to say why. No network: the transport is stubbed.
"""

from __future__ import annotations

import json

import pytest

from elemctl import cli
from elemctl.client import ElementClient, server_starting
from elemctl.config import Config
from elemctl.deploy import deploy_from_sources
from elemctl.errors import ApiError, ServerStartingError
from tests.conftest import FakeTransport

API = "/console/api/v2"
STARTING_TEXT = b'Application "console" not found'
STARTING_JSON = json.dumps({"message": 'Application "console" not found'}).encode("utf-8")


def _client(transport, tmp_path):
    config = Config(
        base_url="https://api.test", client_id="cid", client_secret="secret", timeout=5.0
    )
    client = ElementClient(config, transport=transport, token_cache_dir=tmp_path / "tokens")
    client._sleep = lambda seconds: None
    return client


class _Clock:
    """A clock the waits read, moved forward by the sleeps they take."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_the_recognizer_reads_the_text_and_the_json_spelling_alike():
    assert server_starting(404, 'Application "console" not found')
    assert server_starting(404, {"message": 'Application "console" not found'})
    assert server_starting(404, "application 'console' not found")
    # Another application being absent is an ordinary 404.
    assert not server_starting(404, {"message": 'Application "crm-dev" not found'})
    # The words alone under another status are not the starting server.
    assert not server_starting(500, 'Application "console" not found')
    assert not server_starting(404, None)


@pytest.mark.parametrize("body", [STARTING_TEXT, STARTING_JSON])
def test_a_request_to_a_starting_server_says_so(api, body):
    client, transport = api
    transport.add("GET", f"{API}/applications/app-1", status=404, body=body)

    with pytest.raises(ServerStartingError) as error:
        client.get_app("app-1")

    message = str(error.value)
    assert "стартует" in message and "302" in message
    assert "https://api.test/console" in message  # the address to watch
    # Still an api error: whoever catches ApiError keeps catching it, status and all.
    assert isinstance(error.value, ApiError)
    assert error.value.status == 404
    assert len(transport.calls_to("GET", f"{API}/applications/app-1")) == 1


def test_a_missing_application_stays_an_ordinary_404(api):
    client, transport = api
    transport.add(
        "GET",
        f"{API}/applications/app-9",
        status=404,
        body=json.dumps({"message": 'Application "app-9" not found'}).encode("utf-8"),
    )

    with pytest.raises(ApiError) as error:
        client.get_app("app-9")

    assert not isinstance(error.value, ServerStartingError)


def test_a_token_request_refused_by_a_starting_server_is_not_a_failed_sign_in(tmp_path):
    """Without a cached token the token request is the first thing a starting server refuses."""
    transport = FakeTransport()
    transport.add("POST", "/console/sys/token", status=404, body=STARTING_TEXT)
    client = _client(transport, tmp_path)

    with pytest.raises(ServerStartingError) as error:
        client.get_app("app-1")

    assert "стартует" in str(error.value)
    assert "/console/sys/token" in str(error.value)
    assert transport.calls_to("GET", f"{API}/applications/app-1") == []


def test_inside_the_wait_the_request_goes_through_once_the_console_is_up(api):
    client, transport = api
    transport.add("GET", f"{API}/applications/app-1", status=404, body=STARTING_TEXT)
    transport.add("GET", f"{API}/applications/app-1", status=404, body=STARTING_JSON)
    transport.add("GET", f"{API}/applications/app-1", {"id": "app-1", "status": "Running"})
    lines = []

    with client.waiting_for_server(120, poll=10, log=lines.append):
        card = client.get_app("app-1")

    assert card == {"id": "app-1", "status": "Running"}
    assert len(transport.calls_to("GET", f"{API}/applications/app-1")) == 3
    # The wait is announced once, and so is its end: a deploy that stalls for minutes has
    # to say what it is waiting for.
    assert len([line for line in lines if "стартует" in line]) == 1
    assert any("поднялась" in line for line in lines)


def test_the_wait_gives_up_after_its_limit_and_says_how_long_it_waited(api):
    client, transport = api
    clock = _Clock()
    client._clock = clock
    client._sleep = clock.sleep
    transport.add("GET", f"{API}/applications/app-1", status=404, body=STARTING_TEXT)

    with pytest.raises(ServerStartingError) as error:
        with client.waiting_for_server(30, poll=10):
            client.get_app("app-1")

    assert "30 с" in str(error.value)
    # Asked at 0, 10, 20 and 30 seconds: the clock starts at the first refusal.
    assert len(transport.calls_to("GET", f"{API}/applications/app-1")) == 4


def test_a_zero_limit_fails_at_once(api):
    client, transport = api
    transport.add("GET", f"{API}/applications/app-1", status=404, body=STARTING_TEXT)

    with pytest.raises(ServerStartingError):
        with client.waiting_for_server(0):
            client.get_app("app-1")

    assert len(transport.calls_to("GET", f"{API}/applications/app-1")) == 1


def test_outside_the_wait_nothing_is_repeated(api):
    """Only a deploy waits; the other commands name the cause and stop."""
    client, transport = api
    transport.add("GET", f"{API}/applications/app-1", status=404, body=STARTING_TEXT)
    with client.waiting_for_server(60):
        pass

    with pytest.raises(ServerStartingError):
        client.get_app("app-1")

    assert len(transport.calls_to("GET", f"{API}/applications/app-1")) == 1


def test_apps_get_prints_the_cause_instead_of_a_bare_404(monkeypatch, capsys, tmp_path):
    for key in ("ELEMENT_APP_ID", "ELEMENT_PROJECT_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ELEMENT_BASE_URL", "https://api.test")
    monkeypatch.setenv("ELEMENT_CLIENT_ID", "cid")
    monkeypatch.setenv("ELEMENT_CLIENT_SECRET", "secret")
    monkeypatch.chdir(tmp_path)
    transport = FakeTransport()
    transport.add("POST", "/console/sys/token", {"id_token": "TOKEN"})
    transport.add(
        "GET", f"{API}/applications/019f0000-0000-7000-8000-000000000001",
        status=404, body=STARTING_TEXT,
    )
    monkeypatch.setattr(cli, "make_client", lambda config: _client(transport, tmp_path))

    rc = cli.main(["apps", "get", "019f0000-0000-7000-8000-000000000001"])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert "стартует" in payload["error"] and "302" in payload["error"]
    assert payload["status"] == 404


def _deploy_routes(transport):
    """A deploy against a server that is still starting when the deploy begins."""
    card_before = {
        "id": "app-1", "name": "demo-app", "status": "Running", "uri": "https://app.test/x",
        "source": {"project-version": "1.0-1", "project-version-id": "asm-old"},
    }
    card_after = dict(card_before, source={
        "project-version": "1.0-2", "project-version-id": "asm-new",
    })
    transport.add("GET", f"{API}/applications/app-1", status=404, body=STARTING_TEXT)
    transport.add("GET", f"{API}/applications/app-1", status=404, body=STARTING_TEXT)
    transport.add("GET", f"{API}/applications/app-1", card_before)
    transport.add("GET", f"{API}/applications/app-1", card_after)
    transport.add("GET", f"{API}/projects/proj-1/assemblies", [{"id": "asm-old", "commit-id": None}])
    transport.add("POST", f"{API}/projects/proj-1/assemblies", {"image-id": "asm-new"})
    transport.add("POST", f"{API}/applications/app-1/project/update", {})
    transport.add("GET", f"{API}/tasks/application-tasks", [])
    transport.add("GET", "/x", {})


def test_deploy_waits_for_a_starting_server_and_goes_on(api, project_factory, tmp_path):
    client, transport = api
    _deploy_routes(transport)
    lines = []

    report = deploy_from_sources(
        client, "app-1", "proj-1", project_dir=project_factory(),
        output_dir=tmp_path / "dist", version="1.0-2", log=lines.append,
    )

    assert report.ok is True
    assert report.assembly_id == "asm-new"
    assert any("стартует" in line for line in lines)
    assert any("поднялась" in line for line in lines)
    # The upload happened after the wait, once.
    assert len(transport.calls_to("POST", f"{API}/projects/proj-1/assemblies")) == 1


def test_deploy_with_a_zero_limit_names_the_starting_server(api, project_factory, tmp_path):
    client, transport = api
    _deploy_routes(transport)

    with pytest.raises(ServerStartingError) as error:
        deploy_from_sources(
            client, "app-1", "proj-1", project_dir=project_factory(),
            output_dir=tmp_path / "dist", version="1.0-2", server_start_timeout=0,
        )

    assert "стартует" in str(error.value)
    assert transport.calls_to("POST", f"{API}/projects/proj-1/assemblies") == []


def test_cli_deploy_resolves_the_name_inside_the_wait(monkeypatch, capsys, tmp_path, project_factory):
    """A name is resolved through the listing, which a starting server refuses as well."""
    for key in ("ELEMENT_APP_ID", "ELEMENT_PROJECT_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ELEMENT_BASE_URL", "https://api.test")
    monkeypatch.setenv("ELEMENT_CLIENT_ID", "cid")
    monkeypatch.setenv("ELEMENT_CLIENT_SECRET", "secret")
    project_dir = project_factory()
    monkeypatch.chdir(tmp_path)
    transport = FakeTransport()
    transport.add("POST", "/console/sys/token", {"id_token": "TOKEN"})
    transport.add("GET", f"{API}/applications", status=404, body=STARTING_TEXT)
    transport.add("GET", f"{API}/applications", [{"id": "app-1", "name": "demo-app"}])
    _deploy_routes(transport)
    monkeypatch.setattr(cli, "make_client", lambda config: _client(transport, tmp_path))

    rc = cli.main([
        "deploy", "--app-id", "demo-app", "--project-id", "proj-1",
        "--project-dir", str(project_dir), "--output", str(tmp_path / "dist"),
        "--build-version", "1.0-2", "--server-start-timeout", "60",
    ])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert json.loads(captured.out)["ok"] is True
    assert "стартует" in captured.err
    assert len(transport.calls_to("GET", f"{API}/applications")) == 2
