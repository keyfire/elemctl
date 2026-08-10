"""CLI tests: the local commands and the exit codes (no network)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import elemctl
from elemctl import cli
from elemctl.errors import ApiError


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
    explicit flag – that does not depend on the machine locale. conftest pinned ru; restore
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
    """python -m elemctl – the fallback path for callers without the console entry point in PATH."""
    import_root = Path(elemctl.__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": str(import_root)}
    result = subprocess.run([sys.executable, "-m", "elemctl", "--version"],
                            capture_output=True, text=True, env=env)
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
    """create prints the card of the platform as before – the hint is an ADDITION to it."""

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

    An assembly of a foreign project once landed in the project from env – the recipe
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
    # The assembly name (crm) matched the project name – there is no mismatch warning.
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
    # There is no target project – the project card is not requested.
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
    foreign assembly renames the project and its group – and deleting the assembly does
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
    # The target is set by a flag rather than by the environment – there is no env hint.
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

    # A rollback: the version did not match – exit code 1.
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
    """mcp honours the global --env-file: the configuration is passed to the server."""
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

    def fake_main(config=None):
        captured["config"] = config

    monkeypatch.setattr(mcp_server, "main", fake_main)

    rc = cli.main(["--env-file", str(env_path), "mcp"])

    assert rc == 0
    assert captured["config"] is not None
    assert captured["config"].base_url == "https://example.test"


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
    """--require-clean: a dirty tree – a refusal BEFORE the build, no archive is created."""
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


def test_apps_list_brief_cards(monkeypatch, capsys):
    class FakeClient:
        def list_apps(self, name=""):
            assert name == "crm"
            return [
                {
                    "id": "1",
                    "name": "crm-dev",
                    "status": "Running",
                    "uri": "https://x",
                    "users": ["a", "b"],
                    "source": {"project-version": "1.0-9", "project-version-id": "asm-9"},
                }
            ]

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
