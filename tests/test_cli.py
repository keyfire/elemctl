"""CLI tests: the local commands and the exit codes (no network)."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

import elemctl
from elemctl import cli
from elemctl import client as client_module
from elemctl.errors import ApiError, TransportError
from tests.conftest import UrlopenAnswer


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """Isolate the tests from the environment variables and from the developer's .env."""
    for key in (
        "ELEMENT_BASE_URL",
        "ELEMENT_CLIENT_ID",
        "ELEMENT_CLIENT_SECRET",
        "ELEMENT_APP_ID",
        "ELEMENT_PROJECT_ID",
        "ELEMENT_SPACE_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert f"elemctl {elemctl.__version__}" in capsys.readouterr().out


def test_help_text_follows_lang_flag(capsys):
    """--lang translates the help text (--help) as well, not only the runtime errors: the
    language is resolved before the parser is built. Both directions are checked with an
    explicit flag - that does not depend on the machine locale. conftest pinned ru; restore
    it afterwards."""
    from elemctl import i18n

    try:
        with pytest.raises(SystemExit) as info:
            cli.main(["--lang", "en", "--help"])
        assert info.value.code == 0
        assert "Manage 1C:Enterprise.Element" in capsys.readouterr().out

        with pytest.raises(SystemExit):
            cli.main(["--lang", "ru", "--help"])
        assert "Управление приложениями" in capsys.readouterr().out
    finally:
        i18n.set_lang("ru")


def test_module_entry_point():
    """python -m elemctl - the fallback path for callers without the console entry point in PATH."""
    import_root = Path(elemctl.__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": str(import_root)}
    result = subprocess.run([sys.executable, "-m", "elemctl", "--version"],
                            capture_output=True, text=True, env=env,
                            encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr
    assert f"elemctl {elemctl.__version__}" in result.stdout


def test_build_command(project_factory, tmp_path, capsys):
    project_dir = project_factory()
    out_dir = tmp_path / "dist"

    rc = cli.main(
        ["build", "--project-dir", str(project_dir), "--output", str(out_dir), "--branch", "", "--commit", ""]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    archive = Path(payload["file"])
    assert archive.exists()
    assert archive.name == "crm 1.0-1.xasm"


def test_deploy_dry_run_builds_only(project_factory, tmp_path, capsys):
    project_dir = project_factory()
    rc = cli.main(
        [
            "deploy",
            "--dry-run",
            "--project-dir",
            str(project_dir),
            "--output",
            str(tmp_path / "dist"),
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["file"]).exists()


def test_apps_find_found_and_not_found(monkeypatch, capsys):
    class FakeClient:
        def find_app(self, name, *, include_deleted=False):
            if name == "demo-app":
                return {"id": "app-42", "display-name": "demo-app"}
            return None

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())

    rc = cli.main(["apps", "find", "demo-app"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"id": "app-42", "found": True}

    # A missing application is a normal answer: exit code 0, the found field carries the flag.
    rc = cli.main(["apps", "find", "нет-такого"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"id": None, "found": False}


def test_apps_find_request_failure_is_an_error(monkeypatch, capsys):
    """A request failure differs from "not found": a non-zero code and error on stderr."""

    class FailingClient:
        def find_app(self, name, *, include_deleted=False):
            raise ApiError("нет доступа", status=403)

    monkeypatch.setattr(cli, "make_client", lambda config: FailingClient())

    rc = cli.main(["apps", "find", "demo-app"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_an_answer_that_breaks_off_ends_the_command_with_the_error_json(
    monkeypatch, capsys, tmp_path
):
    """http.client raises IncompleteRead outside OSError.

    A body cut short ended the command with a traceback instead of the error JSON on stderr.
    The real transport is used here, with urlopen replaced.
    """
    monkeypatch.delenv("ELEMCTL_NO_PROXY", raising=False)
    monkeypatch.setenv("ELEMENT_BASE_URL", "https://stand.example.ru")
    monkeypatch.setenv("ELEMENT_CLIENT_ID", "cid")
    monkeypatch.setenv("ELEMENT_CLIENT_SECRET", "secret")
    monkeypatch.setattr(
        cli,
        "make_client",
        lambda config: client_module.ElementClient(config, token_cache_dir=tmp_path / "tokens"),
    )

    def _urlopen(request, **_kwargs):
        if request.full_url.endswith("/console/sys/token"):
            return UrlopenAnswer(b'{"id_token": "TOKEN"}')
        return UrlopenAnswer(broken=http.client.IncompleteRead(b'[{"id": "app-1"', 4096))

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = cli.main(["apps", "list"])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "IncompleteRead" in json.loads(captured.err)["error"]


def test_apps_list_rejects_a_base_url_without_an_http_scheme(monkeypatch, capsys):
    """A malformed base URL reaches the CLI as a configuration error, not a traceback."""
    monkeypatch.setenv("ELEMENT_BASE_URL", "api.test")
    monkeypatch.setenv("ELEMENT_CLIENT_ID", "cid")
    monkeypatch.setenv("ELEMENT_CLIENT_SECRET", "secret")

    rc = cli.main(["apps", "list"])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "http://" in json.loads(captured.err)["error"]
    assert "Traceback" not in captured.err


def test_apps_find_skips_deleted_unless_flag(monkeypatch, capsys):
    """By default a deleted application is not found; --include-deleted brings it back."""

    class FakeClient:
        def find_app(self, name, *, include_deleted=False):
            # The application is in the platform's list but deleted: without the flag it is absent.
            if name == "site-old" and include_deleted:
                return {"id": "app-del", "display-name": "site-old", "status": "Deleted"}
            return None

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())

    rc = cli.main(["apps", "find", "site-old"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"id": None, "found": False}

    rc = cli.main(["apps", "find", "site-old", "--include-deleted"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"id": "app-del", "found": True}


def test_apps_ensure_existing_returns_created_false_without_creating(monkeypatch, capsys):
    """An existing application is not re-created: created=false, create_app is not called."""

    class FakeClient:
        def find_app(self, name, *, include_deleted=False):
            return {"id": "app-7", "display-name": name, "uri": "https://host/apps/demo-app"}

        def create_app(self, *args, **kwargs):
            raise AssertionError("создание не должно вызываться для существующего приложения")

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())

    rc = cli.main(["apps", "ensure", "demo-app", "--version-id", "asm-1"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "app-7"
    assert payload["created"] is False
    assert payload["sign-in"]["url"] == "https://host/apps/demo-app"


class FakeApplyClient:
    """An application that runs `applied` and records what was applied to it."""

    def __init__(self, applied="asm-old", ok=True):
        self.applied = applied
        self.ok = ok
        self.applied_calls = []

    def find_app(self, name, *, include_deleted=False):
        return {
            "id": "app-7",
            "display-name": name,
            "uri": "https://host/apps/demo-app",
            "source": {"project-version-id": self.applied},
        }

    def create_app(self, *args, **kwargs):
        raise AssertionError("создание не должно вызываться для существующего приложения")

    def resolve_app_id(self, app_id):
        return app_id

    def apply_build(self, app_id, *, image_id=None, **kwargs):
        self.applied_calls.append((app_id, image_id))
        self.applied = image_id
        return {"ok": True}

    def ensure_running(self, app_id, log=None):
        return {"id": app_id, "status": "Running", "uri": "https://host/apps/demo-app"}


def _stub_verify(monkeypatch, ok=True):
    """Verification is a separate mechanism with tests of its own - stubbed by its verdict."""

    class Report:
        def __init__(self):
            self.ok = ok

        def to_dict(self):
            return {"ok": ok}

    monkeypatch.setattr(cli, "verify_deploy", lambda *args, **kwargs: Report())


def test_apps_ensure_says_the_assembly_was_not_applied(monkeypatch, capsys):
    """The silence that cost a stand: ensure over an existing application applies nothing.

    The creation flags act on creation alone, so `--version-id` did nothing here - and the
    answer said created: false, exit code 0 and not a word about the assembly.
    """
    fake = FakeApplyClient(applied="asm-old")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    rc = cli.main(["apps", "ensure", "demo-app", "--version-id", "asm-1"])

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["created"] is False
    assert payload["applied"] is False
    assert payload["applied-version-id"] == "asm-old"
    # And the way to bring it there is named, with the command to run.
    assert "apps apply" in captured.err and "asm-1" in captured.err
    assert fake.applied_calls == []


def test_apps_ensure_with_apply_brings_the_application_to_the_assembly(monkeypatch, capsys):
    """--apply is the deliberate case: the same run applies the assembly and verifies it."""
    fake = FakeApplyClient(applied="asm-old")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)
    _stub_verify(monkeypatch, ok=True)

    rc = cli.main(["apps", "ensure", "demo-app", "--version-id", "asm-1", "--apply"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert fake.applied_calls == [("app-7", "asm-1")]


def test_apps_ensure_says_nothing_about_a_build_it_was_not_asked_about(monkeypatch, capsys):
    """Without an assembly ensure is about existence alone - and stays silent about builds."""
    fake = FakeApplyClient(applied="asm-old")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    rc = cli.main(["apps", "ensure", "demo-app"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "applied" not in payload


def test_apps_apply_applies_and_verifies(monkeypatch, capsys):
    """The subcommand the CLI had no answer for: applying was reachable through MCP alone."""
    fake = FakeApplyClient(applied="asm-old")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)
    _stub_verify(monkeypatch, ok=True)

    rc = cli.main(["apps", "apply", "app-7", "asm-1"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}
    assert fake.applied_calls == [("app-7", "asm-1")]


def test_apps_apply_fails_when_the_build_did_not_land(monkeypatch, capsys):
    """A failed apply is rolled back by the platform silently - the exit code must not be 0."""
    fake = FakeApplyClient(applied="asm-old")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)
    _stub_verify(monkeypatch, ok=False)

    rc = cli.main(["apps", "apply", "app-7", "asm-1"])

    assert rc == 1


def test_apps_ensure_missing_creates_and_returns_created_true(monkeypatch, capsys):
    """A missing application is created: created=true, the given assembly acts as the source."""

    class FakeClient:
        def find_app(self, name, *, include_deleted=False):
            return None

        def create_app(
            self,
            display_name,
            *,
            project_version_id=None,
            image_id=None,
            development_mode=True,
            space_id=None,
            technology_version=None,
        ):
            assert display_name == "site-new"
            assert project_version_id == "asm-9"
            assert image_id is None
            return {"id": "app-new", "display-name": display_name, "uri": "https://host/site-new"}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())

    rc = cli.main(["apps", "ensure", "site-new", "--version-id", "asm-9"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "app-new"
    assert payload["created"] is True
    assert payload["sign-in"]["url"] == "https://host/site-new"


def test_apps_ensure_says_how_to_sign_in(monkeypatch, capsys):
    """A stand nobody can get into is not raised: ensure ends with the way in.

    Both surfaces are checked, because they serve different callers: the human
    reads stderr, and a script (or an agent) reads only the JSON on stdout.
    """

    class FakeClient:
        def find_app(self, name, *, include_deleted=False):
            return {"id": "app-7", "display-name": name, "uri": "https://host/apps/demo-app"}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())

    rc = cli.main(["apps", "ensure", "demo-app"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "https://host/apps/demo-app" in captured.err
    assert "ПАНЕЛИ УПРАВЛЕНИЯ" in captured.err  # which account signs in
    assert "другие приложения" in captured.err  # and why accounts used elsewhere do not

    sign_in = json.loads(captured.out)["sign-in"]
    assert sign_in["account"] == "control-panel"
    assert "https://host/apps/demo-app" in sign_in["hint"]
    assert "другие приложения" in sign_in["note"]


def test_apps_create_adds_the_way_in_without_losing_the_card(monkeypatch, capsys):
    """create prints the card of the platform as before - the hint is an ADDITION to it."""

    class FakeClient:
        def create_app(self, display_name, **kwargs):
            return {
                "id": "app-new",
                "display-name": display_name,
                "status": "Running",
                "uri": "https://host/apps/crm-dev",
            }

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())

    rc = cli.main(["apps", "create", "crm-dev", "--version-id", "asm-9"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "app-new"
    assert payload["status"] == "Running"
    assert payload["uri"] == "https://host/apps/crm-dev"
    assert payload["sign-in"]["url"] == "https://host/apps/crm-dev"


def test_sign_in_address_is_not_invented_before_the_application_has_one(monkeypatch, capsys):
    """Without --wait the card has no uri yet: the address is missing, not made up.

    The hint then says where to get it, so the answer stays usable.
    """

    class FakeClient:
        def create_app(self, display_name, **kwargs):
            return {"id": "app-new", "display-name": display_name, "status": "Creating"}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())

    rc = cli.main(["apps", "create", "crm-dev", "--version-id", "asm-9"])
    assert rc == 0
    captured = capsys.readouterr()
    sign_in = json.loads(captured.out)["sign-in"]
    assert sign_in["url"] is None
    assert "apps get" in sign_in["hint"]
    assert "ПАНЕЛИ УПРАВЛЕНИЯ" in captured.err


class FakeCreateClient:
    """A platform that creates an application and reports what it was asked to do."""

    def __init__(self, exists=None):
        self.exists = exists
        self.waited = []

    def find_app(self, name, *, include_deleted=False):
        return self.exists

    def create_app(self, display_name, **kwargs):
        return {"id": "app-new", "display-name": display_name, "status": "Creating"}

    def wait_app_ready(self, app_id, log=None):
        self.waited.append(app_id)
        return {
            "id": app_id,
            "display-name": "crm-dev",
            "status": "Running",
            "uri": "https://host/apps/crm-dev",
        }


def _record_verify(monkeypatch, ok=True):
    """Stub the verification and keep the arguments it was called with."""
    calls = []

    class Report:
        ok_flag = ok

        def __init__(self):
            self.ok = ok

        def to_dict(self):
            return {"ok": ok, "applied": ok}

    def fake(client, app_id, **kwargs):
        calls.append((app_id, kwargs))
        return Report()

    monkeypatch.setattr(cli, "verify_deploy", fake)
    return calls


def test_apps_create_wait_now_proves_the_build_really_landed(monkeypatch, capsys):
    """--wait used to report a Running application and nothing more.

    A failed apply is rolled back by the platform to the previous build, and the
    application comes up Running all the same - so waiting without checking hands
    back a card that says success on a stand that has none.
    """
    fake = FakeCreateClient()
    monkeypatch.setattr(cli, "make_client", lambda config: fake)
    calls = _record_verify(monkeypatch, ok=False)

    rc = cli.main(["apps", "create", "crm-dev", "--version-id", "asm-9", "--wait"])

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["verify"]["ok"] is False
    # The check is made against the assembly asked for, not against a version string.
    assert calls[0][0] == "app-new"
    assert calls[0][1]["expected_assembly_id"] == "asm-9"
    assert calls[0][1]["since"] is not None


def test_apps_create_wait_that_passes_keeps_the_card_and_exit_code(monkeypatch, capsys):
    fake = FakeCreateClient()
    monkeypatch.setattr(cli, "make_client", lambda config: fake)
    _record_verify(monkeypatch, ok=True)

    rc = cli.main(["apps", "create", "crm-dev", "--version-id", "asm-9", "--wait"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["uri"] == "https://host/apps/crm-dev"
    assert payload["verify"]["ok"] is True
    assert payload["sign-in"]["url"] == "https://host/apps/crm-dev"


def test_apps_create_no_verify_brings_the_plain_wait_back(monkeypatch, capsys):
    """The old behaviour stays reachable: wait, and take the card on trust."""
    fake = FakeCreateClient()
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    def refuse(*args, **kwargs):
        raise AssertionError("проверка не должна вызываться при --no-verify")

    monkeypatch.setattr(cli, "verify_deploy", refuse)

    rc = cli.main(
        ["apps", "create", "crm-dev", "--version-id", "asm-9", "--wait", "--no-verify"]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "verify" not in payload
    assert fake.waited == ["app-new"]


def test_apps_create_verify_waits_by_itself(monkeypatch, capsys):
    """There is nothing to check on an application still being created - --verify waits."""
    fake = FakeCreateClient()
    monkeypatch.setattr(cli, "make_client", lambda config: fake)
    _record_verify(monkeypatch, ok=True)

    rc = cli.main(["apps", "create", "crm-dev", "--version-id", "asm-9", "--verify"])

    assert rc == 0
    assert fake.waited == ["app-new"]
    assert json.loads(capsys.readouterr().out)["verify"]["ok"] is True


def test_apps_create_without_wait_checks_nothing(monkeypatch, capsys):
    """Without --wait the command is as it was: no waiting, no requests, no verdict."""
    fake = FakeCreateClient()
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    def refuse(*args, **kwargs):
        raise AssertionError("без --wait проверка не запускается")

    monkeypatch.setattr(cli, "verify_deploy", refuse)

    rc = cli.main(["apps", "create", "crm-dev", "--version-id", "asm-9"])

    assert rc == 0
    assert fake.waited == []
    assert "verify" not in json.loads(capsys.readouterr().out)


def test_apps_ensure_created_application_stops_claiming_applied_on_trust(monkeypatch, capsys):
    """ensure answered applied: true for an application it had just created.

    It was created FROM the assembly, so what else could it be running? The build
    that the apply rolled back without a word.
    """
    fake = FakeCreateClient()
    monkeypatch.setattr(cli, "make_client", lambda config: fake)
    _record_verify(monkeypatch, ok=False)

    rc = cli.main(["apps", "ensure", "crm-dev", "--version-id", "asm-9", "--wait"])

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is True
    assert payload["applied"] is False
    assert payload["verify"]["ok"] is False


class BrokenWaitClient(FakeCreateClient):
    """The create answers, and the wait for the application breaks off on the network."""

    def wait_app_ready(self, app_id, log=None):
        self.waited.append(app_id)
        raise TransportError(
            "сетевая ошибка GET https://host/console/api/v2/tasks/application-tasks: обрыв"
        )


def test_apps_ensure_keeps_the_id_when_the_wait_breaks_off(monkeypatch, capsys):
    """The application exists once the create has answered, whatever happens to the wait.

    A read that broke off during the wait left a network error with no id in it, and the id of
    an application that came up minutes later had to be looked up by its name.
    """
    fake = BrokenWaitClient()
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    rc = cli.main(["apps", "ensure", "crm-dev", "--version-id", "asm-9", "--wait"])

    assert rc == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["id"] == "app-new"
    assert payload["created"] is True
    assert payload["applied"] is None  # nothing was checked, so nothing is claimed
    assert "обрыв" in payload["wait-error"]["error"]
    # The progress names the application and the way to check it later.
    assert "verify-deploy app-new --version-id asm-9" in captured.err


def test_apps_create_keeps_the_card_when_the_verification_breaks_off(monkeypatch, capsys):
    fake = FakeCreateClient()
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    def broken(*args, **kwargs):
        raise TransportError("сетевая ошибка: обрыв")

    monkeypatch.setattr(cli, "verify_deploy", broken)

    rc = cli.main(["apps", "create", "crm-dev", "--version-id", "asm-9", "--wait"])

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "app-new"
    assert payload["uri"] == "https://host/apps/crm-dev"  # the card the wait brought back
    assert "обрыв" in payload["wait-error"]["error"]
    assert "verify" not in payload


def test_apps_ensure_verify_checks_the_application_it_found(monkeypatch, capsys):
    """--verify over an existing application: the card matches, but is it alive?

    The comparison out of the card is free and answers the main question; the rest
    of the check - the failed tasks and the uri - is what --verify adds to it.
    """
    fake = FakeApplyClient(applied="asm-1")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)
    calls = _record_verify(monkeypatch, ok=False)

    rc = cli.main(["apps", "ensure", "demo-app", "--version-id", "asm-1", "--verify"])

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is False
    assert payload["applied"] is False
    assert payload["verify"]["ok"] is False
    assert calls[0][1]["expected_assembly_id"] == "asm-1"
    assert fake.applied_calls == []  # nothing was applied: ensure did not touch the build


def test_apps_ensure_existing_verdict_without_verify_costs_no_requests(monkeypatch, capsys):
    """Without --verify the answer about the build comes out of the card, as before."""
    fake = FakeApplyClient(applied="asm-1")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    def refuse(*args, **kwargs):
        raise AssertionError("без --verify проверка не запускается")

    monkeypatch.setattr(cli, "verify_deploy", refuse)

    rc = cli.main(["apps", "ensure", "demo-app", "--version-id", "asm-1"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert "verify" not in payload


def test_apps_ensure_request_failure_is_an_error(monkeypatch, capsys):
    """A request failure in ensure: exit code 1, an empty stdout, error on stderr."""

    class FailingClient:
        def find_app(self, name, *, include_deleted=False):
            raise ApiError("нет доступа", status=403)

    monkeypatch.setattr(cli, "make_client", lambda config: FailingClient())

    rc = cli.main(["apps", "ensure", "demo-app"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


# -- a source assembly the platform has already deleted -------------------------------

API = "/console/api/v2"


def _platform_with_builds(api, *, apps, assemblies, project="proj-1"):
    """The platform on the stub transport: its applications, the build list of one project,
    and a create answered the way the platform answers a deleted source, with a bare 400."""
    client, transport = api
    transport.add("GET", f"{API}/applications", apps)
    transport.add("GET", f"{API}/projects/{project}/assemblies", assemblies)
    transport.add(
        "POST", f"{API}/applications", {"message": "Can't create application"}, status=400
    )
    return client, transport


def test_apps_ensure_names_a_source_assembly_the_platform_has_deleted(api, monkeypatch, capsys):
    """The platform deletes the builds nobody uses, and a create from one of them is a bare 400.

    "Can't create application" reads like a limit on the number of applications. The build list
    tells the real reason before anything is created, and the build that a running application
    of the project runs is offered instead.
    """
    client, transport = _platform_with_builds(
        api,
        apps=[
            {"id": "app-1", "name": "crm-stage", "status": "Stopped",
             "source": {"project-version-id": "asm-5"}},
            {"id": "app-2", "name": "crm-main", "status": "Running",
             "source": {"project-version-id": "asm-7"}},
            {"id": "app-3", "name": "other", "status": "Running",
             "source": {"project-version-id": "asm-foreign"}},
        ],
        assemblies=[
            {"id": "asm-5", "assembly-version": "1.0-5"},
            {"id": "asm-7", "assembly-version": "1.0-7"},
        ],
    )
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(
        ["apps", "ensure", "crm-dev", "--version-id", "asm-3", "--project-id", "proj-1"]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert "asm-3" in error and "proj-1" in error
    assert "никто не пользуется" in error
    # A running application wins over a stopped one; its build is named with the version.
    assert "crm-main" in error and "asm-7" in error and "1.0-7" in error
    assert "--latest-build" in error
    assert transport.calls_to("POST", f"{API}/applications") == []


def test_apps_create_says_where_the_project_to_check_against_came_from(
    api, monkeypatch, capsys
):
    """The project may come from ELEMENT_PROJECT_ID while the assembly is another project's.

    The refusal then says where the project came from and how to name the right one, so a
    build of another project is not taken for a deleted one without a word.
    """
    client, transport = _platform_with_builds(
        api, apps=[], assemblies=[{"id": "asm-7", "assembly-version": "1.0-7"}]
    )
    monkeypatch.setattr(cli, "make_client", lambda config: client)
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "proj-1")

    rc = cli.main(["apps", "create", "crm-dev", "--version-id", "asm-3"])

    assert rc == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "ELEMENT_PROJECT_ID" in error and "--project-id" in error
    # No application of the project runs a build of it, so the newest build is offered.
    assert "--latest-build" in error
    assert transport.calls_to("POST", f"{API}/applications") == []


def test_apps_ensure_creates_from_a_source_the_project_still_lists(api, monkeypatch, capsys):
    client, transport = api
    transport.add("GET", f"{API}/applications", [])
    transport.add(
        "GET", f"{API}/projects/proj-1/assemblies", [{"id": "asm-7", "assembly-version": "1.0-7"}]
    )
    transport.add("POST", f"{API}/applications", {"id": "app-new"})
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(
        ["apps", "ensure", "crm-dev", "--version-id", "asm-7", "--project-id", "proj-1"]
    )

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["id"] == "app-new"
    body = json.loads(transport.calls_to("POST", f"{API}/applications")[0]["data"])
    assert body["source"]["project-version-id"] == "asm-7"


def test_apps_ensure_without_a_project_creates_as_before(api, monkeypatch, capsys):
    """Without a project there is no list to look in: no listing, the create goes as it did."""
    client, transport = api
    transport.add("GET", f"{API}/applications", [])
    transport.add("POST", f"{API}/applications", {"id": "app-new"})
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(["apps", "ensure", "crm-dev", "--version-id", "asm-3"])

    assert rc == 0
    assert not any("/assemblies" in call["path"] for call in transport.calls)


def test_error_is_json_on_stderr(capsys):
    # app-id is set neither by an argument nor by the configuration.
    rc = cli.main(["apps", "get"])
    assert rc == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert "error" in payload
    assert "app-id" in payload["error"]


def test_app_source_error_explains_how_to_get_a_project(capsys):
    """With no source the error hints at the way to a new project.

    Console API has no empty application, and there is no create-a-project command
    either: a new project is started by uploading an assembly without --project-id.
    Until that was written in the error, the way had to be found by trial and error.
    """
    rc = cli.main(["apps", "create", "Имя"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().err)
    assert "builds upload" in payload["error"]
    assert "--project-id" in payload["error"]


def _assembly_cards(count):
    """Synthetic assembly cards, oldest first: 1.0-1 .. 1.0-{count}."""
    return [
        {
            "id": f"asm-{number}",
            "assembly-version": f"1.0-{number}",
            "project-version": f"1.0-{number}",
            "created": f"2026-01-{number:02d}T10:00:00.000Z",
            "branch-name": None,
            "commit-id": f"c{number}",
            "project-name": "crm",
            "project-developer": "acme",
            "modified": False,
            "comment": "",
        }
        for number in range(1, count + 1)
    ]


class FakeAssembliesClient:
    def __init__(self, cards):
        self._cards = cards

    def list_assemblies(self, project_id):
        return self._cards


def test_builds_list_shows_the_latest_ten_and_says_so(monkeypatch, capsys):
    """A project accumulates assemblies by the thousand: the default answer is the ten
    newest, and the cut is not silent - the count of what was left out goes to stderr."""
    monkeypatch.setattr(cli, "make_client", lambda config: FakeAssembliesClient(_assembly_cards(15)))

    rc = cli.main(["builds", "list", "--project-id", "proj-1"])

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert [card["assembly-version"] for card in payload] == [
        f"1.0-{number}" for number in range(15, 5, -1)
    ]
    assert "10" in captured.err and "15" in captured.err
    # The full cards stay full by default - brevity is a separate flag.
    assert payload[0]["project-developer"] == "acme"


def test_builds_list_limit_zero_prints_everything(monkeypatch, capsys):
    """The whole answer in stdout - and the count line still in stderr: what the platform
    keeps is a fact about the answer, not about the cut, so it is said every time."""
    monkeypatch.setattr(cli, "make_client", lambda config: FakeAssembliesClient(_assembly_cards(15)))

    rc = cli.main(["builds", "list", "--project-id", "proj-1", "--limit", "0"])

    assert rc == 0
    captured = capsys.readouterr()
    assert len(json.loads(captured.out)) == 15
    assert "--limit" not in captured.err
    assert "все сборки проекта" in captured.err


def test_builds_list_says_the_listing_is_only_what_survived(monkeypatch, capsys):
    """A hole in the numbering is a build the platform has already taken away.

    "30 of 30" used to read as the project's whole history, and the line that said otherwise
    was chosen by the LENGTH of the listing - a threshold of thirty, measured once, from the
    days when we believed the platform capped the store. It does not: the platform numbers
    the builds of a base version one after another, so what is missing from the numbering is
    the proof, and it works on a listing of any length.
    """
    cards = [card for card in _assembly_cards(12) if card["assembly-version"] != "1.0-7"]
    monkeypatch.setattr(cli, "make_client", lambda config: FakeAssembliesClient(cards))

    rc = cli.main(["builds", "list", "--project-id", "proj-1", "--limit", "0"])

    assert rc == 0
    captured = capsys.readouterr()
    assert len(json.loads(captured.out)) == 11
    assert "НЕ вся история" in captured.err
    assert "есть пропуски" in captured.err


def test_builds_list_calls_the_short_listing_complete(monkeypatch, capsys):
    """The counter-check: a short listing is the whole of it, and the line says so."""
    monkeypatch.setattr(cli, "make_client", lambda config: FakeAssembliesClient(_assembly_cards(3)))

    assert cli.main(["builds", "list", "--project-id", "proj-1"]) == 0
    captured = capsys.readouterr()
    assert "все сборки проекта" in captured.err
    assert "НЕ вся история" not in captured.err


def test_builds_list_calls_an_unbroken_listing_complete_however_long(monkeypatch, capsys):
    """The case the threshold judged wrong: thirty-one builds in a row are thirty-one builds.

    Past thirty the old line declared the listing a remnant on the strength of its length
    alone - a project that really had built that many and deleted none was told its history
    was gone.
    """
    monkeypatch.setattr(
        cli, "make_client", lambda config: FakeAssembliesClient(_assembly_cards(31)))

    assert cli.main(["builds", "list", "--project-id", "proj-1", "--limit", "0"]) == 0
    captured = capsys.readouterr()
    assert "все сборки проекта" in captured.err
    assert "НЕ вся история" not in captured.err


def test_builds_list_brief_keeps_only_the_identifying_fields(monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_client", lambda config: FakeAssembliesClient(_assembly_cards(2)))

    rc = cli.main(["builds", "list", "--project-id", "proj-1", "--brief"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0] == {
        "id": "asm-2",
        "assembly-version": "1.0-2",
        "project-version": "1.0-2",
        "created": "2026-01-02T10:00:00.000Z",
        "branch-name": None,
        "commit-id": "c2",
    }


class FakeUploadClient:
    """A client for the builds upload tests: records the calls, answers with a project card."""

    def __init__(self, project_name="crm", fail_get_project=False):
        self.upload_kwargs = None
        self.get_project_calls = []
        self._project_name = project_name
        self._fail_get_project = fail_get_project

    def get_project(self, project_id):
        self.get_project_calls.append(project_id)
        if self._fail_get_project:
            raise ApiError("нет доступа", status=403)
        return {"id": project_id, "name": self._project_name}

    def upload_assembly(self, data, **kwargs):
        self.upload_kwargs = kwargs
        return {"image-id": "asm-1"}


def _built_archive(project_factory, tmp_path, capsys):
    """Build the synthetic project into an archive; return the path to the build file."""
    project_dir = project_factory()
    rc = cli.main(
        ["build", "--project-dir", str(project_dir), "--output", str(tmp_path / "dist"),
         "--branch", "", "--commit", ""]
    )
    assert rc == 0
    return json.loads(capsys.readouterr().out)["file"]


def test_builds_upload_reports_env_project_id_source(
    monkeypatch, capsys, project_factory, tmp_path
):
    """The target from ELEMENT_PROJECT_ID is no longer silent: the source in JSON, a hint on stderr.

    An assembly of a foreign project once landed in the project from env - the recipe
    "an upload without --project-id creates a new project" did not work, and nothing
    reported it.
    """
    archive = _built_archive(project_factory, tmp_path, capsys)
    fake = FakeUploadClient()
    monkeypatch.setattr(cli, "make_client", lambda config: fake)
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "proj-env")

    rc = cli.main(["builds", "upload", archive])

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["assembly-id"] == "asm-1"
    assert payload["project-id"] == "proj-env"
    assert payload["project-id-source"] == "env"
    assert fake.upload_kwargs["project_id"] == "proj-env"
    assert "ELEMENT_PROJECT_ID" in captured.err
    assert "--new-project" in captured.err
    # The assembly name (crm) matched the project name - there is no mismatch warning.
    assert "внимание" not in captured.err


def test_builds_upload_new_project_ignores_env(monkeypatch, capsys, project_factory, tmp_path):
    """--new-project turns off the env binding: the platform creates a new project."""
    archive = _built_archive(project_factory, tmp_path, capsys)
    fake = FakeUploadClient()
    monkeypatch.setattr(cli, "make_client", lambda config: fake)
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "proj-env")

    rc = cli.main(["builds", "upload", archive, "--new-project"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project-id"] is None
    assert payload["project-id-source"] is None
    assert fake.upload_kwargs["project_id"] is None
    # There is no target project - the project card is not requested.
    assert fake.get_project_calls == []


def test_builds_upload_new_project_conflicts_with_project_id(
    monkeypatch, capsys, project_factory, tmp_path
):
    archive = _built_archive(project_factory, tmp_path, capsys)
    fake = FakeUploadClient()
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    rc = cli.main(["builds", "upload", archive, "--new-project", "--project-id", "proj-1"])

    assert rc == 1
    captured = capsys.readouterr()
    assert "error" in json.loads(captured.err)
    assert fake.upload_kwargs is None


def test_builds_upload_refuses_when_assembly_name_differs(
    monkeypatch, capsys, project_factory, tmp_path
):
    """A mismatch between the assembly name and the target project is a refusal.

    The console shows the project under the name of the last uploaded assembly, so a
    foreign assembly renames the project and its group - and deleting the assembly does
    not undo it. A warning printed a moment before the irreversible act reads as a hint;
    the fork has to be taken deliberately.
    """
    archive = _built_archive(project_factory, tmp_path, capsys)
    fake = FakeUploadClient(project_name="acme-site")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    rc = cli.main(["builds", "upload", archive, "--project-id", "proj-1"])

    assert rc == 1
    captured = capsys.readouterr()
    error = json.loads(captured.err)["error"]
    assert "'crm'" in error and "'acme-site'" in error
    # The price is named right there: the rename is not undone by deleting the assembly.
    assert "--force-rename" in error and "--new-project" in error
    assert fake.get_project_calls == ["proj-1"]
    assert fake.upload_kwargs is None


def test_builds_upload_compares_the_presentation_not_the_technical_name(
    monkeypatch, capsys, project_factory, tmp_path
):
    """A project shown under a presentation accepts ITS OWN assembly without a fight.

    The manifest carries the technical name (`crm`) and the console shows the
    presentation ("Acme CRM"): comparing one against the other called every correct
    upload a rename and refused it, which left the assembly of a real project with no
    way in at all.
    """
    project_dir = project_factory(presentation="Acme CRM")
    rc = cli.main(
        ["build", "--project-dir", str(project_dir), "--output", str(tmp_path / "dist"),
         "--branch", "", "--commit", ""]
    )
    assert rc == 0
    archive = json.loads(capsys.readouterr().out)["file"]
    fake = FakeUploadClient(project_name="Acme CRM")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    rc = cli.main(["builds", "upload", archive, "--project-id", "proj-1"])

    assert rc == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["assembly-id"] == "asm-1"
    assert fake.upload_kwargs["project_id"] == "proj-1"
    assert "--force-rename" not in captured.err


def test_builds_upload_still_refuses_a_foreign_assembly_by_presentation(
    monkeypatch, capsys, project_factory, tmp_path
):
    """And the guard still stands: what the console would be renamed TO is named in the refusal."""
    project_dir = project_factory(presentation="Acme CRM")
    rc = cli.main(
        ["build", "--project-dir", str(project_dir), "--output", str(tmp_path / "dist"),
         "--branch", "", "--commit", ""]
    )
    assert rc == 0
    archive = json.loads(capsys.readouterr().out)["file"]
    fake = FakeUploadClient(project_name="Globex Portal")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    rc = cli.main(["builds", "upload", archive, "--project-id", "proj-1"])

    assert rc == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "'Acme CRM'" in error and "'Globex Portal'" in error
    # The way out of the refusal for an assembly of the SAME project is named too.
    assert "--new-project" in error
    assert fake.upload_kwargs is None


def test_builds_upload_force_rename_uploads_and_names_the_price(
    monkeypatch, capsys, project_factory, tmp_path
):
    """The deliberate case: the flag lets the upload through, the warning stays."""
    archive = _built_archive(project_factory, tmp_path, capsys)
    fake = FakeUploadClient(project_name="acme-site")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    rc = cli.main(["builds", "upload", archive, "--project-id", "proj-1", "--force-rename"])

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["project-id-source"] == "flag"
    assert fake.upload_kwargs["project_id"] == "proj-1"
    assert "'crm'" in captured.err and "'acme-site'" in captured.err
    # The target is set by a flag rather than by the environment - there is no env hint.
    assert "ELEMENT_PROJECT_ID" not in captured.err


def test_builds_upload_name_check_failure_does_not_block(
    monkeypatch, capsys, project_factory, tmp_path
):
    """A guard that cannot compare must not refuse: not being able to compare is no proof
    of danger. An unreachable project card leaves the upload exactly as it was before."""
    archive = _built_archive(project_factory, tmp_path, capsys)
    fake = FakeUploadClient(fail_get_project=True)
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    rc = cli.main(["builds", "upload", archive, "--project-id", "proj-1"])

    assert rc == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["assembly-id"] == "asm-1"
    assert "внимание" not in captured.err


def test_deploy_exit_code_reflects_ok(monkeypatch, capsys, project_factory, tmp_path):
    from tests.test_deploy import FakeDeployClient

    # Success: the applied version matched.
    monkeypatch.setattr(
        cli, "make_client", lambda config: FakeDeployClient(applied_version="1.0-1")
    )
    rc = cli.main(
        [
            "deploy",
            "--app-id",
            "app-1",
            "--project-id",
            "proj-1",
            "--project-dir",
            str(project_factory(repo_name="repo-ok")),
            "--output",
            str(tmp_path / "d1"),
            "--build-version",
            "1.0-1",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert json.loads(captured.out)["ok"] is True

    # A rollback: the version did not match - exit code 1.
    monkeypatch.setattr(
        cli, "make_client", lambda config: FakeDeployClient(applied_version="1.0-0")
    )
    rc = cli.main(
        [
            "deploy",
            "--app-id",
            "app-1",
            "--project-id",
            "proj-1",
            "--project-dir",
            str(project_factory(repo_name="repo-fail")),
            "--output",
            str(tmp_path / "d2"),
            "--build-version",
            "1.0-1",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    report = json.loads(captured.out)
    assert report["ok"] is False
    assert report["applied"] is False


def test_mcp_command_forwards_env_file(monkeypatch, tmp_path):
    """mcp honours the global --env-file: the PATH is passed to the server, not a
    configuration resolved from it up front.

    A pre-resolved Config would pin the server to whatever the file said at that one instant
    - mcp_server.client() only re-reads a file it was itself handed a path to watch.
    """
    pytest.importorskip("mcp", reason="extra elemctl[mcp] не установлен")
    from elemctl import mcp_server

    env_path = tmp_path / "custom.env"
    env_path.write_text(
        "ELEMENT_BASE_URL=https://example.test\n"
        "ELEMENT_CLIENT_ID=id\n"
        "ELEMENT_CLIENT_SECRET=secret\n",
        encoding="utf-8",
    )

    captured = {}

    def fake_main(config=None, *, overrides=None, env_file=None):
        captured["config"] = config
        captured["env_file"] = env_file

    monkeypatch.setattr(mcp_server, "main", fake_main)

    rc = cli.main(["--env-file", str(env_path), "mcp"])

    assert rc == 0
    assert captured["config"] is None
    assert captured["env_file"] == str(env_path)


def test_mcp_command_forwards_startup_overrides(monkeypatch):
    """The connection flags actually given on the mcp command line reach the server as
    overrides, not folded once into a pre-resolved configuration the way
    test_mcp_command_forwards_env_file shows env_file itself no longer is.

    What mcp_server.client() does with them once they arrive - base_url/client_id/
    client_secret applied only to a call without its own env_file, timeout applied to every
    stand - is that function's own contract, covered where it is implemented."""
    pytest.importorskip("mcp", reason="extra elemctl[mcp] не установлен")
    from elemctl import mcp_server

    captured = {}

    def fake_main(config=None, *, overrides=None, env_file=None):
        captured["overrides"] = overrides

    monkeypatch.setattr(mcp_server, "main", fake_main)

    rc = cli.main([
        "--base-url", "https://cli.test",
        "--client-id", "cid",
        "--client-secret", "sec",
        "--timeout", "5",
        "mcp",
    ])

    assert rc == 0
    assert captured["overrides"] == {
        "base_url": "https://cli.test",
        "client_id": "cid",
        "client_secret": "sec",
        "timeout": 5.0,
    }


def test_build_json_carries_version_and_source(project_factory, tmp_path, capsys):
    """CI must not dig the version out of the file name: it is there in the JSON fields."""
    project_dir = project_factory()
    rc = cli.main(
        ["build", "--project-dir", str(project_dir), "--output", str(tmp_path / "dist")]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == "1.0-1"
    assert payload["version-source"] == "default"
    assert payload["name"] == "crm" and payload["vendor"] == "acme"
    assert payload["kind"] == "Application"
    # The synthetic project is outside a git repository: there is nothing to judge cleanliness by.
    assert payload["dirty"] is None


def test_build_version_from_ci_env_via_cli(project_factory, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "88")
    rc = cli.main(
        ["build", "--project-dir", str(project_factory()), "--output", str(tmp_path / "dist")]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == "1.0-88"
    assert payload["version-source"] == "GITHUB_RUN_NUMBER"
    assert Path(payload["file"]).name == "crm 1.0-88.xasm"


def test_build_require_clean_dirty_tree_aborts(project_factory, tmp_path, capsys, monkeypatch):
    """--require-clean: a dirty tree - a refusal BEFORE the build, no archive is created."""
    monkeypatch.setattr(cli, "git_dirty_files", lambda directory: ["acme/crm/Проект.xbsl"])
    out_dir = tmp_path / "dist"
    rc = cli.main(
        ["build", "--project-dir", str(project_factory()), "--output", str(out_dir),
         "--require-clean"]
    )
    assert rc == 1
    error = json.loads(capsys.readouterr().err)
    assert "--require-clean" in error["error"]
    assert not out_dir.exists()


def test_build_require_clean_without_git_aborts(project_factory, tmp_path, capsys, monkeypatch):
    """An unavailable git with --require-clean is a refusal too: cleanliness cannot be confirmed."""
    monkeypatch.setattr(cli, "git_dirty_files", lambda directory: None)
    rc = cli.main(
        ["build", "--project-dir", str(project_factory()), "--output", str(tmp_path / "d"),
         "--require-clean"]
    )
    assert rc == 1
    assert "--require-clean" in json.loads(capsys.readouterr().err)["error"]


def test_build_require_clean_clean_tree_builds(project_factory, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "git_dirty_files", lambda directory: [])
    rc = cli.main(
        ["build", "--project-dir", str(project_factory()), "--output", str(tmp_path / "d"),
         "--require-clean"]
    )
    assert rc == 0
    assert Path(json.loads(capsys.readouterr().out)["file"]).exists()


def test_build_refuses_connection_options(project_factory, tmp_path, capsys):
    """--env-file on a local build is a refusal, not a silently dropped option.

    The option changed nothing, and a call carrying it read as a build bound to a
    stand - twice that left the reader asking whether the build talks to the server.
    The refusal comes BEFORE the work: no archive is written.
    """
    env_file = tmp_path / "stand.env"
    env_file.write_text("ELEMENT_BASE_URL=https://example.invalid", encoding="utf-8")
    out_dir = tmp_path / "dist"

    rc = cli.main(
        ["build", "--project-dir", str(project_factory()), "--output", str(out_dir),
         "--env-file", str(env_file)]
    )

    assert rc == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "--env-file" in error and "build" in error
    # The refusal names where the platform IS reached from.
    assert "deploy" in error
    assert not out_dir.exists()


def test_build_refuses_every_connection_option(project_factory, tmp_path, capsys):
    """Not only --env-file: --base-url and the credentials are just as inert here."""
    project_dir = project_factory()
    for option, value in (
        ("--base-url", "https://example.invalid"),
        ("--client-id", "someone"),
        ("--client-secret", "secret"),
        ("--timeout", "5"),
    ):
        rc = cli.main(
            ["build", "--project-dir", str(project_dir), "--output",
             str(tmp_path / "dist"), option, value]
        )
        assert rc == 1, option
        assert option in json.loads(capsys.readouterr().err)["error"]


def test_inspect_refuses_connection_options(project_factory, tmp_path, capsys):
    rc = cli.main(
        ["build", "--project-dir", str(project_factory()), "--output", str(tmp_path / "dist")]
    )
    assert rc == 0
    archive = json.loads(capsys.readouterr().out)["file"]

    rc = cli.main(["inspect", archive, "--base-url", "https://example.invalid"])

    assert rc == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "--base-url" in error and "inspect" in error


def test_build_still_works_with_the_environment_around(project_factory, tmp_path, capsys,
                                                       monkeypatch):
    """Only the OPTIONS are refused: a .env on disk and ELEMENT_* variables change nothing.

    A developer always has a configured environment around, and a local build must not
    start depending on whether it is there.
    """
    monkeypatch.setenv("ELEMENT_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("ELEMENT_CLIENT_ID", "someone")
    (tmp_path / ".env").write_text("ELEMENT_CLIENT_SECRET=secret", encoding="utf-8")

    rc = cli.main(
        ["build", "--project-dir", str(project_factory()), "--output", str(tmp_path / "dist")]
    )

    assert rc == 0
    assert Path(json.loads(capsys.readouterr().out)["file"]).exists()


def test_deploy_require_clean_checked_before_any_work(
    project_factory, tmp_path, capsys, monkeypatch
):
    """In deploy the cleanliness check runs before the build, let alone before the upload."""
    monkeypatch.setattr(cli, "git_dirty_files", lambda directory: ["правка"])

    class MustNotBeCalled:
        def __getattr__(self, name):
            raise AssertionError("клиент не должен создаваться при грязном дереве")

    monkeypatch.setattr(cli, "make_client", lambda config: MustNotBeCalled())
    out_dir = tmp_path / "dist"
    rc = cli.main(
        ["deploy", "--project-dir", str(project_factory()), "--output", str(out_dir),
         "--require-clean", "--app-id", "app-1", "--project-id", "proj-1"]
    )
    assert rc == 1
    assert "--require-clean" in json.loads(capsys.readouterr().err)["error"]
    assert not out_dir.exists()


def test_apps_delete_accepts_application_name(monkeypatch, capsys):
    """apps delete site-x: the name is resolved into a UUID, the platform receives the id."""
    deleted = []

    class FakeClient:
        def resolve_app_id(self, value):
            assert value == "crm-x"
            return "6b3a2f00-0000-0000-0000-000000000001"

        def delete_app(self, app_id):
            deleted.append(app_id)
            return None

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    rc = cli.main(["apps", "delete", "crm-x"])
    assert rc == 0
    assert deleted == ["6b3a2f00-0000-0000-0000-000000000001"]
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"deleted": True, "app-id": "6b3a2f00-0000-0000-0000-000000000001"}


def test_deploy_accepts_application_name(monkeypatch, capsys, project_factory, tmp_path):
    """deploy --app-id crm-x: the name is resolved, and the deploy receives the id.

    The other commands addressing one application have always accepted a name; deploy took the
    value as it was and sent the name straight to the API, where it is not an id at all.
    """
    project = project_factory()
    seen = {}

    class FakeClient:
        def resolve_app_id(self, value):
            seen["asked"] = value
            return "6b3a2f00-0000-0000-0000-000000000002"

    class FakeReport:
        ok = True

        def __init__(self, app_id):
            self.app_id = app_id

        def to_dict(self):
            return {"ok": True, "app-id": self.app_id}

    def fake_deploy(client, app_id, project_id, **kwargs):
        seen["deployed"] = app_id
        return FakeReport(app_id)

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    monkeypatch.setattr(cli, "deploy_from_sources", fake_deploy)
    rc = cli.main([
        "deploy", "--project-dir", str(project), "--output", str(tmp_path / "out"),
        "--app-id", "crm-x", "--project-id", "proj-1",
    ])
    assert rc == 0
    assert seen["asked"] == "crm-x"
    assert seen["deployed"] == "6b3a2f00-0000-0000-0000-000000000002"
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_apps_get_resolves_name(monkeypatch, capsys):
    class FakeClient:
        def resolve_app_id(self, value):
            return "app-uuid"

        def get_app(self, app_id):
            assert app_id == "app-uuid"
            return {"id": app_id, "status": "Running"}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    rc = cli.main(["apps", "get", "crm-x"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["id"] == "app-uuid"


def test_apps_get_takes_the_reference_as_an_option(monkeypatch, capsys):
    """`deploy` and `apps ensure` take `--app-id`; the apps commands take it too."""
    class FakeClient:
        def resolve_app_id(self, value):
            assert value == "crm-x"
            return "app-uuid"

        def get_app(self, app_id):
            return {"id": app_id, "status": "Running"}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    rc = cli.main(["apps", "get", "--app-id", "crm-x"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["id"] == "app-uuid"


def test_apps_stop_takes_the_reference_as_an_option(monkeypatch, capsys):
    class FakeClient:
        def resolve_app_id(self, value):
            return "app-uuid"

        def stop_app(self, app_id):
            return {"id": app_id, "status": "Stopped"}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    assert cli.main(["apps", "stop", "--app-id", "crm-x"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "Stopped"


def test_two_different_references_are_refused(capsys):
    """Silently preferring one of them would deploy commands to the wrong application."""
    rc = cli.main(["apps", "get", "crm-x", "--app-id", "crm-y"])
    assert rc == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "crm-x" in error and "crm-y" in error


def test_the_same_reference_written_twice_is_accepted(monkeypatch, capsys):
    class FakeClient:
        def resolve_app_id(self, value):
            return "app-uuid"

        def get_app(self, app_id):
            return {"id": app_id}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    assert cli.main(["apps", "get", "crm-x", "--app-id", "crm-x"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "app-uuid"


def test_apps_list_brief_cards(monkeypatch, capsys):
    class FakeClient:
        def list_apps_counted(self, name="", status="", include_deleted=False):
            assert name == "crm"
            items = [
                {
                    "id": "1",
                    "name": "crm-dev",
                    "status": "Running",
                    "uri": "https://x",
                    "users": ["a", "b"],
                    "source": {"project-version": "1.0-9", "project-version-id": "asm-9"},
                }
            ]
            return {"items": items, "total": 1, "live": 1, "shown": 1}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    rc = cli.main(["apps", "list", "--name", "crm", "--brief"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "id": "1",
            "name": "crm-dev",
            "status": "Running",
            "uri": "https://x",
            "project-version": "1.0-9",
            "project-version-id": "asm-9",
        }
    ]


def test_apps_list_hides_the_deleted_ones_and_counts_them_out_loud(monkeypatch, capsys):
    """The listing of a long-lived stand is nearly all deleted cards. They are cut,
    and the count line says how much was cut - on stderr, so stdout stays the JSON
    array a script parses."""

    class FakeClient:
        def list_apps_counted(self, name="", status="", include_deleted=False):
            assert (name, status, include_deleted) == ("", "", False)
            return {
                "items": [{"id": "1", "name": "crm-dev", "status": "Running"}],
                "total": 324,
                "live": 1,
                "shown": 1,
            }

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    assert cli.main(["apps", "list"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == [{"id": "1", "name": "crm-dev", "status": "Running"}]
    assert captured.err.strip() == "живых 1 из 324"


def test_apps_list_include_deleted_reaches_the_client(monkeypatch, capsys):
    class FakeClient:
        def list_apps_counted(self, name="", status="", include_deleted=False):
            assert include_deleted is True
            items = [
                {"id": "1", "status": "Running"},
                {"id": "2", "status": "Deleted"},
            ]
            return {"items": items, "total": 2, "live": 1, "shown": 2}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    assert cli.main(["apps", "list", "--include-deleted"]) == 0
    captured = capsys.readouterr()
    assert [app["id"] for app in json.loads(captured.out)] == ["1", "2"]
    assert captured.err.strip() == "живых 1 из 2, показано 2"


@pytest.mark.parametrize(
    "argv,client_attr,answer",
    [
        (["spaces", "list"], "list_spaces", [{"id": "s1"}]),
        (["user-lists", "list"], "list_user_lists", [{"id": "l1"}]),
        (["branches", "list"], "list_branches", [{"id": "b1"}]),
        (["tasks", "list"], "list_app_tasks", [{"id": "t1"}]),
    ],
)
def test_other_list_commands_answer_in_stdout_alone(monkeypatch, capsys, argv, client_attr, answer):
    """Every other list command prints nothing of its own before or after the answer - stdout
    is the array, start to finish, and stderr is empty. None of them call _progress at all, so
    there is no line that could ever race the answer."""
    client = type("FakeClient", (), {client_attr: lambda self, *a, **k: answer})()
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    assert cli.main(argv) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == answer
    assert captured.err == ""


def test_projects_list_passes_the_filters_to_the_client(monkeypatch, capsys):
    class FakeClient:
        def list_projects(self, name="", include_deleted=False):
            assert name == "crm"
            assert include_deleted is True
            return [{"id": "p1", "name": "crm", "deleted": True}]

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    rc = cli.main(["projects", "list", "--name", "crm", "--include-deleted"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == [{"id": "p1", "name": "crm", "deleted": True}]


def test_projects_list_without_flags_asks_for_the_live_projects_only(monkeypatch, capsys):
    class FakeClient:
        def list_projects(self, name="", include_deleted=False):
            assert name == ""
            assert include_deleted is False
            return []

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    assert cli.main(["projects", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_global_option_is_accepted_after_the_subcommand(tmp_path, capsys):
    """--env-file after the subcommand used to die with "unrecognized arguments"."""
    from elemctl.cli import _hoist_global_options

    assert _hoist_global_options(["deploy", "--env-file", ".env", "--app-id", "a"]) == [
        "--env-file", ".env", "deploy", "--app-id", "a",
    ]
    assert _hoist_global_options(["apps", "get", "--lang=en", "--app-id", "a"]) == [
        "--lang=en", "apps", "get", "--app-id", "a",
    ]


def test_hoisting_leaves_the_order_alone_when_it_is_already_right():
    from elemctl.cli import _hoist_global_options

    argv = ["--env-file", ".env", "deploy", "--app-id", "a"]
    assert _hoist_global_options(argv) == argv


def test_hoisting_does_not_touch_tokens_after_a_double_dash():
    """After "--" the tokens belong to the command, not to the parser."""
    from elemctl.cli import _hoist_global_options

    argv = ["probe", "--", "--env-file", "not-ours"]
    assert _hoist_global_options(argv) == argv


# -- --json: the machine-readable channel --------------------------------------


def test_json_flag_is_accepted_after_the_subcommand():
    """A global flag takes no value, so it is hoisted as a single token."""
    from elemctl.cli import _hoist_global_options

    assert _hoist_global_options(["apps", "get", "--json", "--app-id", "a"]) == [
        "--json", "apps", "get", "--app-id", "a",
    ]
    assert _hoist_global_options(["probe", "--", "--json"]) == ["probe", "--", "--json"]


def test_json_keeps_a_stray_print_out_of_stdout(monkeypatch, capsys):
    """The promise of --json is kept by the streams, not by the discipline of handlers.

    A command that prints a line of its own - a plugin's report, a library's warning -
    used to leave that line in stdout ahead of the JSON, which is exactly what made
    callers hunt for the first brace instead of parsing the stream whole.
    """
    class FakeClient:
        def list_spaces(self):
            print("a line nobody asked for")
            return [{"id": "s1"}]

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    assert cli.main(["--json", "spaces", "list"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == [{"id": "s1"}]
    assert "a line nobody asked for" in captured.err


def test_without_json_a_stray_print_still_lands_in_stdout(monkeypatch, capsys):
    """The counter-check: without the flag nothing is redirected, so the flag does work."""
    class FakeClient:
        def list_spaces(self):
            print("a line nobody asked for")
            return [{"id": "s1"}]

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    assert cli.main(["spaces", "list"]) == 0
    assert capsys.readouterr().out.startswith("a line nobody asked for")


def test_json_leaves_progress_lines_on_stderr(monkeypatch, capsys):
    """The summary of apps list goes to stderr as before - stdout holds the cards alone."""
    cards = [{"id": "a1", "name": "crm-dev", "status": "Running"}]

    class FakeClient:
        def list_apps_counted(self, name="", status="", include_deleted=False):
            return {"items": cards, "total": 2, "live": 1, "shown": 1}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    assert cli.main(["--json", "apps", "list"]) == 0
    captured = capsys.readouterr()
    assert [card["name"] for card in json.loads(captured.out)] == ["crm-dev"]
    assert captured.err.strip()


def _run_cli_child(tmp_path, script_body, argv):
    """Run elemctl's own cli.main(argv) in a real child process, with a fake client poked into
    the module before the call; return (stdout captured alone, stdout+stderr merged into one).

    A real process is the only way to see this class of bug: capsys replaces sys.stdout/stderr
    with in-memory objects and never exercises the operating system's own buffering, which is
    exactly where it lives - off a terminal Python block-buffers stdout while stderr goes
    through right away, so bytes can leave in a different order than the calls that wrote them.
    """
    script = tmp_path / "probe.py"
    script.write_text(
        "import sys\n"
        "from elemctl import cli\n"
        "\n"
        f"{script_body}\n"
        f"sys.exit(cli.main({argv!r}))\n",
        encoding="utf-8",
    )
    import_root = Path(elemctl.__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": str(import_root), "PYTHONIOENCODING": "utf-8"}
    alone = subprocess.run(
        [sys.executable, str(script)], capture_output=True, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", env=env,
    )
    merged = subprocess.run(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", env=env,
    )
    return alone, merged


_APPS_LIST_PROBE_CLIENT = (
    "class FakeClient:\n"
    "    def list_apps_counted(self, name='', status='', include_deleted=False):\n"
    "        return {'items': [{'id': '1'}], 'total': 410, 'live': 7, 'shown': 7}\n"
    "\n"
    "cli.make_client = lambda config: FakeClient()\n"
)

_BUILDS_LIST_PROBE_CLIENT = (
    "class FakeClient:\n"
    "    def list_assemblies(self, project_id):\n"
    "        return [\n"
    "            {'id': str(n), 'assembly-version': f'1.0-{n}', 'project-version': f'1.0-{n}'}\n"
    "            for n in range(1, 4)\n"
    "        ]\n"
    "\n"
    "cli.make_client = lambda config: FakeClient()\n"
)


@pytest.mark.parametrize(
    "script_body,argv,note_substring",
    [
        (_APPS_LIST_PROBE_CLIENT, ["apps", "list"], "живых 7 из 410"),
        (
            _BUILDS_LIST_PROBE_CLIENT,
            ["builds", "list", "--project-id", "p1"],
            "все сборки проекта",
        ),
    ],
    ids=["apps-list", "builds-list"],
)
def test_the_answer_is_the_json_a_merged_stream_starts_with(
    tmp_path, script_body, argv, note_substring
):
    """The contract: stdout captured alone is pure JSON (that is what --json guarantees, and
    what a caller who separates the streams - the normal way to call a CLI tool - already
    gets). In a merged capture (`2>&1`, or stderr=STDOUT - a plain way to catch "everything the
    tool printed" for a log) a whole-string json.loads is NOT promised: the notes still follow
    the answer as "extra data" once decoded, and that is fine, because the answer is what a
    parser needs and it is exactly where raw_decode expects the first value to start. What IS
    promised, and what this checks: the JSON decodes from the very first character of a merged
    capture, in full, and only the explanatory notes - never part of the answer - trail it.
    """
    alone, merged = _run_cli_child(tmp_path, script_body, argv)
    assert alone.returncode == 0, alone.stderr
    answer = json.loads(alone.stdout)

    assert merged.returncode == 0, merged.stdout
    stripped = merged.stdout.lstrip()
    value, end = json.JSONDecoder().raw_decode(stripped)
    assert value == answer, "the merged stream's leading JSON is not the same answer"
    notes = stripped[end:].strip()
    assert notes, "no notes followed the answer in the merged stream"
    assert note_substring in notes, notes


def test_json_leaves_stdout_empty_on_a_failure(monkeypatch, capsys):
    """A failure answers stderr and the exit code; a document in stdout would read as an answer."""
    class FakeClient:
        def list_spaces(self):
            raise ApiError("Console API ответил 500", status=500)

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    assert cli.main(["--json", "spaces", "list"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]


def test_json_survives_an_exception_and_restores_stdout(monkeypatch, capsys):
    """After a failed call the streams are back: the guard restores them in finally."""
    class FakeClient:
        def list_spaces(self):
            raise ApiError("Console API ответил 500", status=500)

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())
    cli.main(["--json", "spaces", "list"])
    capsys.readouterr()
    assert cli._answer_stream is None
    print("back to stdout")
    assert capsys.readouterr().out.strip() == "back to stdout"


# -- the shape of a group call --------------------------------------------------


def test_tasks_help_names_the_whole_form():
    """The documents asked for `tasks --app-id`; the flag belongs to `tasks list`.

    The group help now spells both forms out, so the reader does not have to infer
    where the flag goes from a table of action names.
    """
    parser = cli.build_parser()
    tasks = cli._choices_of(parser, "command")["tasks"]
    assert "tasks list [--app-id" in (tasks.description or "")
    assert "tasks get-group TASK_ID" in tasks.description


def test_a_group_called_with_a_flag_gets_the_action_first_hint(capsys):
    """argparse blames the VALUE of the flag; the missing word is the action."""
    with pytest.raises(SystemExit):
        cli.main(["tasks", "--app-id", "app-1"])
    err = capsys.readouterr().err
    assert "invalid choice" in err
    assert "elemctl tasks list" in err
    assert "list, get-group" in err


def test_the_hint_keeps_quiet_where_it_would_be_noise(capsys):
    """Not every refusal is that mistake: a plain command and a help call get no hint."""
    parser = cli.build_parser()
    assert cli._action_first_hint(parser, ["tasks", "--help"]) == ""
    assert cli._action_first_hint(parser, ["deploy", "--app-id", "a"]) == ""
    assert cli._action_first_hint(parser, ["tasks", "list", "--app-id", "a"]) == ""
    assert "elemctl apps list" in cli._action_first_hint(parser, ["apps", "--brief"])


# -- verify-deploy --------------------------------------------------------------


def test_verify_deploy_checks_without_deploying(monkeypatch, capsys):
    """The check the library and MCP had, and the CLI did not: a script in CI
    rebuilt it out of `apps get` and `tasks list` by hand."""
    seen = {}

    class Report:
        ok = True

        def to_dict(self):
            return {"ok": True, "applied": True}

    def fake_verify(client, app_id, **kwargs):
        seen.update({"app-id": app_id, **kwargs})
        return Report()

    fake = FakeApplyClient(applied="asm-1")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)
    monkeypatch.setattr(cli, "verify_deploy", fake_verify)

    rc = cli.main(["verify-deploy", "--app-id", "app-7", "--version-id", "asm-1"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["applied"] is True
    assert seen["app-id"] == "app-7"
    assert seen["expected_assembly_id"] == "asm-1"
    # Nothing was deployed: the command only reads.
    assert fake.applied_calls == []


def test_verify_deploy_fails_when_the_build_did_not_land(monkeypatch, capsys):
    """A silent rollback must cost the exit code, otherwise CI calls the deploy green."""
    class Report:
        ok = False

        def to_dict(self):
            return {"ok": False, "problems": ["Модуль.xbsl:12 – ошибка компиляции"]}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeApplyClient(applied="asm-old"))
    monkeypatch.setattr(cli, "verify_deploy", lambda *args, **kwargs: Report())

    assert cli.main(["verify-deploy", "app-7", "--version-id", "asm-1"]) == 1
    assert "ошибка компиляции" in capsys.readouterr().out
