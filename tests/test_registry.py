"""The local registry of uploads: written by every upload, read back by the listings.

The platform keeps the commit of a build uploaded into a project, and nothing else of where
it came from. Several sessions deploying from one machine left a build on an application that
nobody could trace to a working tree. No network: the clients are stand-ins.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from elemctl import cli
from elemctl.client import applied_build, brief_assembly, brief_assemblies
from elemctl.deploy import deploy_from_sources
from elemctl.probe import probe_project
from elemctl.registry import (
    DATA_DIR_ENV,
    REGISTRY_FILE,
    data_dir,
    registry_path,
    remember_upload,
    remembered_uploads,
)


def _entry(assembly_id, **fields):
    values = {
        "assembly_id": assembly_id,
        "project_id": "proj-1",
        "version": "1.0-7",
        "branch": "feature/tasks",
        "commit": "c0ffee",
        "dirty": False,
        "project_dir": "/work/acme/crm",
        "file": None,
        "stand": "https://stand.test",
        "command": "deploy",
    }
    values.update(fields)
    return remember_upload(**values)


# -- where the registry lives ---------------------------------------------------


def test_the_variable_names_the_directory_outright():
    assert data_dir({DATA_DIR_ENV: "/data/elemctl"}, platform="linux") == Path("/data/elemctl")


def test_windows_keeps_it_in_the_local_profile():
    """Local, not roaming: what is remembered is this machine's."""
    found = data_dir({"LOCALAPPDATA": r"X:\local-data"}, platform="win32")
    assert found == Path(r"X:\local-data") / "elemctl"


def test_elsewhere_it_follows_the_xdg_state_directory(monkeypatch, tmp_path):
    assert data_dir({"XDG_STATE_HOME": "/state"}, platform="linux") == Path("/state/elemctl")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert data_dir({}, platform="darwin") == tmp_path / ".local" / "state" / "elemctl"


def test_the_suite_writes_into_a_directory_of_its_own():
    """The conftest fixture: nothing a test uploads reaches the developer's registry."""
    assert registry_path().name == REGISTRY_FILE
    assert "elemctl-data" in str(registry_path())


# -- writing and reading ----------------------------------------------------------


def test_an_upload_is_written_down_and_read_back():
    assert _entry("asm-7") == ""

    remembered = remembered_uploads(["asm-7"])["asm-7"]

    assert remembered["branch"] == "feature/tasks"
    assert remembered["commit"] == "c0ffee"
    assert remembered["dirty"] is False
    assert remembered["project-dir"] == "/work/acme/crm"
    assert remembered["command"] == "deploy"
    assert remembered["uploaded-at"]  # the time, with the offset of the machine
    assert remembered["elemctl"]


def test_the_last_line_of_an_id_wins_and_other_ids_are_left_out():
    _entry("asm-7", branch="first")
    _entry("asm-8", branch="other")
    _entry("asm-7", branch="second")

    remembered = remembered_uploads(["asm-7"])

    assert set(remembered) == {"asm-7"}
    assert remembered["asm-7"]["branch"] == "second"
    assert set(remembered_uploads()) == {"asm-7", "asm-8"}


def test_a_broken_line_is_skipped_rather_than_breaking_the_listing():
    _entry("asm-7")
    with open(registry_path(), "a", encoding="utf-8", newline="") as stream:
        stream.write("{not json\n\n[1, 2]\n")
    _entry("asm-8")

    assert set(remembered_uploads()) == {"asm-7", "asm-8"}


def test_a_missing_registry_remembers_nothing():
    assert remembered_uploads(["asm-7"]) == {}


def test_a_registry_that_cannot_be_written_is_a_warning_not_a_failure(monkeypatch, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv(DATA_DIR_ENV, str(blocker / "below"))

    warning = _entry("asm-7")

    assert "не записана в локальный реестр" in warning
    assert remembered_uploads() == {}


# -- the brief card: the card first, the registry for what the card left empty ------


def test_the_brief_card_fills_the_empty_branch_from_the_registry_and_says_so():
    card = {"id": "asm-7", "assembly-version": "1.0-7", "branch-name": None, "commit-id": "c0ffee"}
    remembered = {"branch": "feature/tasks", "commit": "c0ffee", "dirty": True,
                  "project-dir": "/work/acme/crm"}

    brief = brief_assembly(card, remembered)

    assert brief["branch-name"] == "feature/tasks"
    assert brief["branch-name-source"] == "registry"
    assert brief["commit-id"] == "c0ffee"
    assert brief["commit-id-source"] == "platform"
    assert brief["dirty"] is True
    assert brief["project-dir"] == "/work/acme/crm"


def test_what_nobody_knows_stays_empty_with_no_source():
    brief = brief_assembly({"id": "asm-7", "branch-name": None, "commit-id": None})
    assert brief["branch-name"] is None and brief["branch-name-source"] is None
    assert brief["commit-id"] is None and brief["commit-id-source"] is None
    assert brief["dirty"] is None and brief["project-dir"] is None


def test_a_listing_reads_the_registry_for_every_card_it_shows():
    _entry("asm-7", commit="c7")
    cards = [
        {"id": "asm-8", "commit-id": None},
        {"image-id": "asm-7", "commit-id": None},  # the id may ride in another field
    ]

    briefs = brief_assemblies(cards)

    assert briefs[0]["commit-id"] is None
    assert briefs[1]["commit-id"] == "c7" and briefs[1]["commit-id-source"] == "registry"


# -- what an application runs ------------------------------------------------------


class _AppClient:
    def __init__(self, assemblies=None, fail=False):
        self._assemblies = assemblies or []
        self._fail = fail
        self.asked = []

    def resolve_app_id(self, value):
        return "app-1"

    def get_app(self, app_id):
        return {
            "id": app_id,
            "status": "Running",
            "project": {"id": "proj-1"},
            "source": {"project-version": "1.0-3", "project-version-id": "asm-7"},
        }

    def list_assemblies(self, project_id):
        self.asked.append(project_id)
        if self._fail:
            raise OSError("the list broke off")
        return self._assemblies


def test_the_applied_build_is_read_off_the_build_card_and_the_registry():
    _entry("asm-7")
    client = _AppClient([{"id": "asm-7", "assembly-version": "1.0-7", "commit-id": "c0ffee",
                          "branch-name": None}])

    build = applied_build(client, client.get_app("app-1"))

    assert client.asked == ["proj-1"]
    assert build["assembly-version"] == "1.0-7"
    assert build["commit-id-source"] == "platform"
    assert build["branch-name"] == "feature/tasks" and build["branch-name-source"] == "registry"


def test_a_list_that_cannot_be_read_leaves_the_registry_to_answer():
    _entry("asm-7")
    build = applied_build(_AppClient(fail=True), _AppClient().get_app("app-1"))
    assert build["id"] == "asm-7"
    assert build["commit-id"] == "c0ffee" and build["commit-id-source"] == "registry"


def test_an_application_without_an_applied_build_has_none():
    assert applied_build(_AppClient(), {"id": "app-1", "source": {}}) is None


def test_apps_get_prints_the_applied_build(monkeypatch, capsys):
    _entry("asm-7")
    monkeypatch.setattr(cli, "make_client", lambda config: _AppClient([{"id": "asm-7"}]))

    assert cli.main(["apps", "get", "crm-dev"]) == 0

    card = json.loads(capsys.readouterr().out)
    assert card["status"] == "Running"  # the card itself is untouched
    assert card["applied-build"]["branch-name"] == "feature/tasks"
    assert card["applied-build"]["project-dir"] == "/work/acme/crm"


def test_the_get_app_tool_carries_the_applied_build(monkeypatch):
    pytest.importorskip("mcp.server", reason="extra elemctl[mcp] не установлен")
    from elemctl import mcp_server
    from elemctl.config import Config

    _entry("asm-7")
    monkeypatch.setattr(mcp_server, "ElementClient", lambda config: _AppClient([{"id": "asm-7"}]))
    server = mcp_server.create_server(
        Config(base_url="https://api.test", client_id="cid", client_secret="secret")
    )

    result = asyncio.run(server.call_tool("get_app", {"app_id": "crm-dev"}))
    payload = json.loads(mcp_server.call_result_content(result)[0].text)

    assert payload["applied-build"]["branch-name-source"] == "registry"


# -- every upload is written down -------------------------------------------------


class _DeployClient:
    """What deploy_from_sources asks of a client, with the upload recorded."""

    def __init__(self):
        self.upload_kwargs = None
        self._applied = "asm-old"

    def get_app(self, app_id):
        return {"id": app_id, "status": "Running", "uri": "",
                "source": {"project-version-id": self._applied}}

    def list_assemblies(self, project_id):
        return []

    def upload_assembly(self, data, **kwargs):
        self.upload_kwargs = kwargs
        return {"image-id": "asm-new", "assembly-version": "1.0-12"}

    def apply_build(self, app_id, **kwargs):
        self._applied = kwargs.get("image_id")

    def ensure_running(self, app_id, log=None):
        return self.get_app(app_id)

    def list_app_tasks(self, app_id=""):
        return []

    def check_uri(self, uri):
        return None


def test_deploy_sends_the_commit_and_writes_the_upload_down(project_factory, tmp_path):
    client = _DeployClient()
    project_dir = project_factory()

    report = deploy_from_sources(
        client, "app-1", "proj-1", project_dir=project_dir, output_dir=tmp_path / "dist",
        version="1.0-12", branch="feature/tasks", commit="c0ffee",
    )

    assert report.ok is True
    assert client.upload_kwargs["commit_id"] == "c0ffee"
    remembered = remembered_uploads(["asm-new"])["asm-new"]
    assert remembered["branch"] == "feature/tasks"
    assert remembered["commit"] == "c0ffee"
    assert remembered["version"] == "1.0-12"
    assert remembered["project-id"] == "proj-1"
    assert remembered["command"] == "deploy"
    assert Path(remembered["project-dir"]) == project_dir.resolve()
    # Outside a repository nothing is known about the tree - and that is what is written.
    assert remembered["dirty"] is None


def test_a_registry_that_cannot_be_written_does_not_stop_a_deploy(
    project_factory, tmp_path, monkeypatch
):
    blocker = tmp_path / "a-file"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv(DATA_DIR_ENV, str(blocker / "below"))
    lines = []

    report = deploy_from_sources(
        _DeployClient(), "app-1", "proj-1", project_dir=project_factory(),
        output_dir=tmp_path / "dist", version="1.0-12", log=lines.append,
    )

    assert report.ok is True
    assert any("не записана в локальный реестр" in line for line in lines)


def test_builds_upload_sends_the_commit_of_the_archive_and_writes_it_down(
    monkeypatch, capsys, project_factory, tmp_path
):
    project_dir = project_factory()
    assert cli.main([
        "build", "--project-dir", str(project_dir), "--output", str(tmp_path / "dist"),
        "--branch", "feature/tasks", "--commit", "c0ffee",
    ]) == 0
    archive = json.loads(capsys.readouterr().out)["file"]

    class _UploadClient:
        upload_kwargs = None

        def get_project(self, project_id):
            return {"id": project_id, "name": "crm"}

        def upload_assembly(self, data, **kwargs):
            _UploadClient.upload_kwargs = kwargs
            return {"image-id": "asm-9", "assembly-version": "1.0-9"}

    monkeypatch.setattr(cli, "make_client", lambda config: _UploadClient())
    monkeypatch.setenv("ELEMENT_BASE_URL", "https://stand.test")
    monkeypatch.setenv("ELEMENT_CLIENT_ID", "cid")
    monkeypatch.setenv("ELEMENT_CLIENT_SECRET", "secret")

    assert cli.main(["builds", "upload", archive, "--project-id", "proj-1"]) == 0

    assert _UploadClient.upload_kwargs["commit_id"] == "c0ffee"
    remembered = remembered_uploads(["asm-9"])["asm-9"]
    assert remembered["branch"] == "feature/tasks" and remembered["commit"] == "c0ffee"
    assert remembered["command"] == "builds upload"
    assert remembered["stand"] == "https://stand.test"
    # An archive says nothing about the tree it was built from.
    assert remembered["dirty"] is None and remembered["project-dir"] is None
    assert Path(remembered["file"]) == Path(archive).resolve()


def test_a_probe_writes_its_upload_down(project_factory, tmp_path):
    from tests.test_probe import FakeProbeClient

    project_dir = project_factory(presentation="Пробник", language="Русский")
    report = probe_project(
        FakeProbeClient(), project_dir=project_dir, output_dir=tmp_path / "dist",
    )

    assert report.ok is True
    remembered = remembered_uploads(["asm-1"])["asm-1"]
    assert remembered["command"] == "probe"
    assert remembered["project-id"] == "proj-1"
