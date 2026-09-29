"""The project of a build: where an upload without a project id went, and where a build lives.

An upload without a project id leaves the choice of the project to the server, which puts the
build into the live project that carries the Ид of its descriptor, or creates one. The answer of
the server names that project, and `builds upload` used to drop it and print `project-id: null`.
The server also renames a project it finds that way after the build, and nothing said so. A
create from a build of such a project then took ELEMENT_PROJECT_ID for the project of the build
and refused the build as a deleted one.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from elemctl import cli
from elemctl.build import read_assembly_project
from elemctl.client import builds_summary, landed_project, uploaded_project
from elemctl.registry import (
    ROUTE_NAME,
    ROUTE_NO_PROJECT_ID,
    remember_upload,
    remembered_uploads,
    upload_route,
)

API = "/console/api/v2"
DESCRIPTOR_ID = "5b7e0a52-2f4c-4d6e-9a1b-3c8d7e6f5a40"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """No stand of the developer: every test names what it needs."""
    for key in ("ELEMENT_BASE_URL", "ELEMENT_CLIENT_ID", "ELEMENT_CLIENT_SECRET",
                "ELEMENT_APP_ID", "ELEMENT_PROJECT_ID", "ELEMENT_SPACE_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def _archive(project_factory, tmp_path, capsys, *, presentation="Acme CRM"):
    """A built archive of a project whose descriptor carries an Ид."""
    project_dir = project_factory(presentation=presentation)
    descriptor = project_dir / "Проект.yaml"
    descriptor.write_text(
        f"Ид: {DESCRIPTOR_ID}\n" + descriptor.read_text(encoding="utf-8"),
        encoding="utf-8", newline="",
    )
    assert cli.main([
        "build", "--project-dir", str(project_dir), "--output", str(tmp_path / "dist"),
        "--build-version", "1.0-7", "--branch", "", "--commit", "",
    ]) == 0
    return json.loads(capsys.readouterr().out)["file"]


def _artifact(project_id, name, configuration_id=DESCRIPTOR_ID):
    return {"artifact-id": project_id, "configuration-id": configuration_id, "name": name}


# --- what the answer of the upload says -------------------------------------------------------

def test_the_answer_names_a_project_the_upload_created():
    answer = {"image-id": "asm-1", "artifact": _artifact("proj-new", "Acme CRM")}

    landed = landed_project(answer, {"proj-old": "Globex Portal"})

    assert landed == {
        "id": "proj-new", "name": "Acme CRM", "configuration-id": DESCRIPTOR_ID,
        "created": True, "renamed-from": None, "found-by": "response",
    }


def test_the_answer_names_a_project_the_upload_found_and_left_alone():
    answer = {"image-id": "asm-1", "artifact": _artifact("proj-1", "Acme CRM")}

    landed = landed_project(answer, {"proj-1": "Acme CRM"})

    assert (landed["created"], landed["renamed-from"]) == (False, None)


def test_a_project_known_under_another_name_was_renamed_by_the_upload():
    """Seen live: the server put the build into the project of its Ид and gave the project,
    and its group, the name of the build; the answer of the upload did not mention it."""
    answer = {"image-id": "asm-2", "artifact": _artifact("proj-1", "Acme CRM Next")}

    landed = landed_project(answer, {"proj-1": "Acme CRM"})

    assert landed["created"] is False
    assert landed["renamed-from"] == "Acme CRM"


def test_without_the_projects_of_before_nothing_is_claimed():
    answer = {"image-id": "asm-1", "artifact": _artifact("proj-1", "Acme CRM")}

    landed = landed_project(answer, None)

    assert landed["id"] == "proj-1"
    assert (landed["created"], landed["renamed-from"]) == (None, None)


def test_an_answer_without_an_artifact_names_no_project():
    landed = landed_project({"image-id": "asm-1"}, {"proj-1": "crm"})

    assert (landed["id"], landed["found-by"], landed["created"]) == ("", None, None)


def test_the_archive_names_the_id_of_its_descriptor(project_factory, tmp_path, capsys):
    archive = _archive(project_factory, tmp_path, capsys)

    assert read_assembly_project(archive)["id"] == DESCRIPTOR_ID


# --- a build found by the build lists ---------------------------------------------------------

def _projects(*cards):
    return [
        {"project-kind": "Application", "deleted": False, **card} for card in cards
    ]


def test_a_build_the_answer_does_not_place_is_found_by_the_build_lists(api):
    """Newest projects first: an upload without a project id tends to create its project."""
    client, transport = api
    transport.add("GET", f"{API}/projects", _projects(
        {"id": "grp-1", "name": "Acme CRM(Группа)", "project-kind": "Group",
         "date-created": "2026-09-02T10:00:00Z"},
        {"id": "proj-old", "name": "Globex Portal", "date-created": "2026-01-01T10:00:00Z"},
        {"id": "proj-new", "name": "Acme CRM", "date-created": "2026-09-02T10:00:01Z"},
        {"id": "proj-gone", "name": "Old", "deleted": True, "date-created": "2026-09-03T10:00:00Z"},
    ))
    transport.add("GET", f"{API}/projects/proj-new/assemblies", [{"id": "asm-9"}])

    landed = uploaded_project(client, {"image-id": "asm-9"}, {"proj-old": "Globex Portal"})

    assert landed["id"] == "proj-new"
    assert (landed["name"], landed["created"], landed["found-by"]) == (
        "Acme CRM", True, "build-list"
    )
    listed = [call["path"] for call in transport.calls if call["path"].endswith("/assemblies")]
    # The group lists no builds, the deleted project does not count, and the newest came first.
    assert listed == [f"{API}/projects/proj-new/assemblies"]


def test_the_registry_names_the_project_to_look_at_first(api):
    client, transport = api
    transport.add("GET", f"{API}/projects", _projects(
        {"id": "proj-new", "name": "Acme CRM", "date-created": "2026-09-02T10:00:00Z"},
        {"id": "proj-old", "name": "Globex Portal", "date-created": "2026-01-01T10:00:00Z"},
    ))
    transport.add("GET", f"{API}/projects/proj-old/assemblies", [{"id": "asm-5"}])
    remember_upload(
        assembly_id="asm-5", project_id="proj-old", version="1.0-5", branch="", commit="",
        dirty=None, project_dir=None, file=None, stand="https://api.test",
        command="builds upload",
    )

    project, assembly = client.find_build_project("asm-5")

    assert project["id"] == "proj-old" and assembly["id"] == "asm-5"
    assert transport.calls_to("GET", f"{API}/projects/proj-new/assemblies") == []


def test_a_version_is_no_address_across_projects(api):
    """Every project has a `1.0-1` of its own, so only the id of a card finds a build."""
    client, transport = api
    transport.add("GET", f"{API}/projects", _projects({"id": "proj-1", "name": "crm"}))
    transport.add(
        "GET", f"{API}/projects/proj-1/assemblies", [{"id": "asm-1", "assembly-version": "1.0-1"}]
    )

    assert client.find_build_project("1.0-1") is None


# --- builds upload without a project id -------------------------------------------------------

def _upload_platform(api, *, before, answer, after=None):
    """The platform of an upload without a project id: the projects before and after it."""
    client, transport = api
    transport.add("GET", f"{API}/projects", before)
    if after is not None:
        transport.add("GET", f"{API}/projects", after)
    transport.add("POST", f"{API}/projects", answer)
    return client, transport


def test_builds_upload_names_the_project_the_server_created(
    api, monkeypatch, capsys, project_factory, tmp_path
):
    archive = _archive(project_factory, tmp_path, capsys)
    client, transport = _upload_platform(
        api,
        before=_projects({"id": "proj-env", "name": "Globex Portal"}),
        answer={"name": "1.0-7", "image-id": "asm-7", "artifact": _artifact("proj-new", "Acme CRM")},
    )
    monkeypatch.setattr(cli, "make_client", lambda config: client)
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "proj-env")

    assert cli.main(["builds", "upload", archive, "--new-project"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["project-id"] == "proj-new"
    assert payload["project-id-source"] == "server"
    assert payload["project"] == {
        "id": "proj-new", "name": "Acme CRM", "configuration-id": DESCRIPTOR_ID,
        "created": True, "renamed-from": None, "found-by": "response",
    }
    assert "новый проект 'Acme CRM' (proj-new)" in captured.err
    # The upload went to POST /projects: the project of the environment was left out.
    assert transport.calls_to("POST", f"{API}/projects")
    assert remembered_uploads()["asm-7"]["project-id"] == "proj-new"


def test_builds_upload_says_out_loud_that_it_renamed_a_project(
    api, monkeypatch, capsys, project_factory, tmp_path
):
    archive = _archive(project_factory, tmp_path, capsys, presentation="Acme CRM Next")
    client, _ = _upload_platform(
        api,
        before=_projects({"id": "proj-1", "name": "Acme CRM"}),
        answer={"image-id": "asm-8", "artifact": _artifact("proj-1", "Acme CRM Next")},
    )
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    assert cli.main(["builds", "upload", archive, "--new-project"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["project"]["created"] is False
    assert payload["project"]["renamed-from"] == "Acme CRM"
    assert "внимание" in captured.err
    assert "было 'Acme CRM', стало 'Acme CRM Next'" in captured.err


def test_builds_upload_names_an_existing_project_it_went_into(
    api, monkeypatch, capsys, project_factory, tmp_path
):
    archive = _archive(project_factory, tmp_path, capsys)
    client, _ = _upload_platform(
        api,
        before=_projects({"id": "proj-1", "name": "Acme CRM"}),
        answer={"image-id": "asm-8", "artifact": _artifact("proj-1", "Acme CRM")},
    )
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    assert cli.main(["builds", "upload", archive, "--new-project"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["project"]["created"] is False
    assert "существующий проект 'Acme CRM' (proj-1)" in captured.err
    assert "внимание" not in captured.err


def test_builds_upload_finds_the_project_the_answer_left_out(
    api, monkeypatch, capsys, project_factory, tmp_path
):
    """The Ид it was found by comes from the archive when the answer does not repeat it."""
    archive = _archive(project_factory, tmp_path, capsys)
    client, transport = _upload_platform(
        api,
        before=_projects({"id": "proj-old", "name": "Globex Portal"}),
        after=_projects(
            {"id": "proj-old", "name": "Globex Portal", "date-created": "2026-01-01T10:00:00Z"},
            {"id": "proj-new", "name": "Acme CRM", "date-created": "2026-09-02T10:00:00Z"},
        ),
        answer={"image-id": "asm-7"},
    )
    transport.add("GET", f"{API}/projects/proj-new/assemblies", [{"id": "asm-7"}])
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    assert cli.main(["builds", "upload", archive, "--new-project"]) == 0

    captured = capsys.readouterr()
    project = json.loads(captured.out)["project"]
    assert (project["id"], project["found-by"], project["created"]) == (
        "proj-new", "build-list", True
    )
    assert project["configuration-id"] == DESCRIPTOR_ID
    assert "найден по перечням сборок" in captured.err


def test_builds_upload_says_when_nothing_names_the_project(
    api, monkeypatch, capsys, project_factory, tmp_path
):
    archive = _archive(project_factory, tmp_path, capsys)
    client, _ = _upload_platform(api, before=[], answer={"image-id": "asm-7"})
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    assert cli.main(["builds", "upload", archive, "--new-project"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert (payload["project-id"], payload["project-id-source"]) == (None, None)
    assert "не назвал проект сборки asm-7" in captured.err


def test_builds_upload_goes_on_when_the_projects_cannot_be_read(
    api, monkeypatch, capsys, project_factory, tmp_path
):
    """The build is what was asked for: a project list that failed costs the verdict alone."""
    archive = _archive(project_factory, tmp_path, capsys)
    client, transport = api
    transport.add("GET", f"{API}/projects", {"message": "internal error"}, status=500)
    transport.add(
        "POST", f"{API}/projects", {"image-id": "asm-7", "artifact": _artifact("proj-1", "Acme CRM")}
    )
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    assert cli.main(["builds", "upload", archive, "--new-project"]) == 0

    captured = capsys.readouterr()
    project = json.loads(captured.out)["project"]
    assert (project["id"], project["created"]) == ("proj-1", None)
    assert "сказать нельзя" in captured.err


def test_an_upload_into_a_project_keeps_its_answer(
    api, monkeypatch, capsys, project_factory, tmp_path
):
    """The project of an upload into a project is the one the caller named: no snapshot."""
    archive = _archive(project_factory, tmp_path, capsys)
    client, transport = api
    transport.add("GET", f"{API}/projects/proj-1", {"id": "proj-1", "name": "Acme CRM"})
    transport.add("POST", f"{API}/projects/proj-1/assemblies", {"id": "asm-8"})
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    assert cli.main(["builds", "upload", archive, "--project-id", "proj-1"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert (payload["project-id"], payload["project-id-source"]) == ("proj-1", "flag")
    assert "project" not in payload
    assert transport.calls_to("GET", f"{API}/projects") == []


# --- apps create takes the project of the build -----------------------------------------------

def _create_platform(api, *, env_project_builds, projects, owner_builds):
    """A stand whose ELEMENT_PROJECT_ID is proj-1 while the build sits in proj-2."""
    client, transport = api
    transport.add("GET", f"{API}/projects/proj-1/assemblies", env_project_builds)
    transport.add("GET", f"{API}/applications", [])
    transport.add("GET", f"{API}/projects", projects)
    transport.add("GET", f"{API}/projects/proj-2/assemblies", owner_builds)
    transport.add("POST", f"{API}/applications", {"id": "app-new"})
    return client, transport


def test_apps_create_takes_the_project_of_the_build_over_the_env_one(api, monkeypatch, capsys):
    """Seen live: a build uploaded without a project id sat in the project the server made for
    it, and the create took ELEMENT_PROJECT_ID for its project and refused it as deleted."""
    client, transport = _create_platform(
        api,
        env_project_builds=[{"id": "asm-1", "assembly-version": "1.0-1"}],
        projects=_projects(
            {"id": "proj-1", "name": "Globex Portal"}, {"id": "proj-2", "name": "Acme CRM"}
        ),
        owner_builds=[{"id": "asm-7", "assembly-version": "1.0-7"}],
    )
    monkeypatch.setattr(cli, "make_client", lambda config: client)
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "proj-1")

    assert cli.main(["apps", "create", "demo-app", "--version-id", "asm-7"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["id"] == "app-new"
    assert "проекте 'Acme CRM' (proj-2)" in captured.err
    body = json.loads(transport.calls_to("POST", f"{API}/applications")[0]["data"])
    assert body["source"]["project-version-id"] == "asm-7"


def test_apps_create_names_the_project_of_the_build_instead_of_a_wrong_flag(
    api, monkeypatch, capsys
):
    """A project the caller named is not replaced behind the caller's back."""
    client, transport = _create_platform(
        api,
        env_project_builds=[{"id": "asm-1", "assembly-version": "1.0-1"}],
        projects=_projects(
            {"id": "proj-1", "name": "Globex Portal"}, {"id": "proj-2", "name": "Acme CRM"}
        ),
        owner_builds=[{"id": "asm-7", "assembly-version": "1.0-7"}],
    )
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(["apps", "create", "demo-app", "--version-id", "asm-7", "--project-id", "proj-1"])

    assert rc == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "'Acme CRM' (proj-2)" in error and "--project-id proj-2" in error
    assert transport.calls_to("POST", f"{API}/applications") == []


def _mcp_server_on(monkeypatch, client):
    pytest.importorskip("mcp.server", reason="extra elemctl[mcp] не установлен")
    from elemctl import mcp_server
    from elemctl.config import Config

    monkeypatch.setattr(mcp_server, "ElementClient", lambda config: client)
    return mcp_server.create_server(
        Config(base_url="https://api.test", client_id="cid", client_secret="secret")
    )


def test_the_create_tool_takes_the_project_of_the_build_over_the_stand_one(api, monkeypatch):
    client, transport = _create_platform(
        api,
        env_project_builds=[{"id": "asm-1", "assembly-version": "1.0-1"}],
        projects=_projects(
            {"id": "proj-1", "name": "Globex Portal"}, {"id": "proj-2", "name": "Acme CRM"}
        ),
        owner_builds=[{"id": "asm-7", "assembly-version": "1.0-7"}],
    )
    client.config.project_id = "proj-1"
    server = _mcp_server_on(monkeypatch, client)
    from elemctl.mcp_server import call_result_content

    result = asyncio.run(server.call_tool("create_app", {"name": "demo-app", "version_id": "asm-7"}))

    assert json.loads(call_result_content(result)[0].text)["id"] == "app-new"
    assert transport.calls_to("POST", f"{API}/applications")


def test_the_create_tool_names_the_project_of_the_build_instead_of_a_wrong_one(api, monkeypatch):
    client, transport = _create_platform(
        api,
        env_project_builds=[{"id": "asm-1", "assembly-version": "1.0-1"}],
        projects=_projects(
            {"id": "proj-1", "name": "Globex Portal"}, {"id": "proj-2", "name": "Acme CRM"}
        ),
        owner_builds=[{"id": "asm-7", "assembly-version": "1.0-7"}],
    )
    server = _mcp_server_on(monkeypatch, client)
    from tests.test_mcp import _root_elemctl_error_message

    with pytest.raises(Exception) as excinfo:
        asyncio.run(server.call_tool(
            "create_app", {"name": "demo-app", "version_id": "asm-7", "project_id": "proj-1"}
        ))

    message = _root_elemctl_error_message(excinfo.value)
    assert "'Acme CRM' (proj-2)" in message and "project_id proj-2" in message
    assert transport.calls_to("POST", f"{API}/applications") == []


# --- builds list of an extension project ------------------------------------------------------

def _cards(*numbers):
    return [{"id": f"asm-{n}", "assembly-version": f"1.0-{n}"} for n in numbers]


def test_a_gap_in_an_extension_project_is_a_deletion_by_hand():
    line = builds_summary(_cards(4, 2, 1), 3, remembered={}, extension=True)

    assert "удалены вручную" in line
    assert "НЕ вся история" in line
    assert "заканчивает применение" not in line


def test_an_unbroken_extension_project_says_nothing_takes_its_builds():
    line = builds_summary(_cards(3, 2, 1), 3, remembered={}, extension=True)

    assert "все сборки проекта" in line
    assert "Уборки у проекта-расширения нет" in line


def test_an_extension_project_without_numbers_says_it_too():
    line = builds_summary([{"id": "asm-1", "assembly-version": "1.0"}], 1, extension=True)

    assert "номера нет ни у одной сборки" in line
    assert "Уборки у проекта-расширения нет" in line


def test_an_empty_extension_project_has_nothing_to_say_about_its_builds():
    line = builds_summary([], 0, extension=True)

    assert "нет ни одной сборки" in line
    assert "Уборки" not in line


def test_an_application_project_keeps_its_line():
    line = builds_summary(_cards(4, 2, 1), 3, remembered={})

    assert "заканчивает применение" in line
    assert "Уборки у проекта-расширения нет" not in line


class _Listing:
    """A client of a build listing: the builds and the card of their project."""

    def __init__(self, cards, kind="Extension", card_error=None):
        self._cards = cards
        self._kind = kind
        self._card_error = card_error

    def list_assemblies(self, project_id):
        return list(self._cards)

    def get_project(self, project_id):
        if self._card_error is not None:
            raise self._card_error
        return {"id": project_id, "project-kind": self._kind}


def test_builds_list_of_an_extension_project_says_it_keeps_its_builds(monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_client", lambda config: _Listing(_cards(3, 2, 1)))

    assert cli.main(["builds", "list", "--project-id", "ext-1"]) == 0

    captured = capsys.readouterr()
    assert len(json.loads(captured.out)) == 3
    assert "Уборки у проекта-расширения нет" in captured.err
    assert "elemctl builds delete" in captured.err


def test_builds_list_keeps_the_common_line_when_the_card_is_unreadable(monkeypatch, capsys):
    from elemctl.errors import ApiError

    listing = _Listing(_cards(3, 2, 1), card_error=ApiError("нет доступа", status=403))
    monkeypatch.setattr(cli, "make_client", lambda config: listing)

    assert cli.main(["builds", "list", "--project-id", "ext-1"]) == 0

    captured = capsys.readouterr()
    assert "все сборки проекта" in captured.err
    assert "Уборки" not in captured.err


def test_the_list_builds_tool_says_it_for_an_extension_project(monkeypatch):
    server = _mcp_server_on(monkeypatch, _Listing(_cards(4, 2, 1)))
    from elemctl.mcp_server import call_result_content

    result = asyncio.run(server.call_tool("list_builds", {"project_id": "ext-1"}))
    payload = json.loads(call_result_content(result)[0].text)

    assert "удалены вручную" in payload["summary"]


# --- the probe, the other upload without a project id -----------------------------------------

def test_a_probe_says_it_renamed_the_project_of_its_sources(project_factory, tmp_path):
    from elemctl.probe import probe_project
    from tests.test_probe import FakeProbeClient

    client = FakeProbeClient(upload_response={
        "image-id": "asm-1", "artifact": _artifact("proj-1", "Acme CRM Next"),
    })
    client._projects = [{"id": "proj-1", "name": "Acme CRM"}]
    lines = []

    report = probe_project(
        client, project_dir=project_factory(presentation="Acme CRM Next", language="Русский"),
        output_dir=tmp_path / "dist", log=lines.append,
    )

    assert report.project_renamed_from == "Acme CRM"
    assert report.to_dict()["project-renamed-from"] == "Acme CRM"
    assert any("было 'Acme CRM', стало 'Acme CRM Next'" in line for line in lines)


def test_a_probe_that_renamed_nothing_says_nothing(project_factory, tmp_path):
    from elemctl.probe import probe_project
    from tests.test_probe import FakeProbeClient

    client = FakeProbeClient(upload_response={
        "image-id": "asm-1", "artifact": _artifact("proj-1", "Acme CRM"),
    })
    client._projects = [{"id": "proj-1", "name": "Acme CRM"}]

    report = probe_project(
        client, project_dir=project_factory(presentation="Acme CRM", language="Русский"),
        output_dir=tmp_path / "dist",
    )

    assert report.to_dict()["project-renamed-from"] is None


# --- the name the route was published under ---------------------------------------------------

def test_the_route_keeps_the_name_it_was_published_under():
    """`ROUTE_NAME` went out in a release before the route got its present name."""
    assert ROUTE_NAME == ROUTE_NO_PROJECT_ID
    assert upload_route({"route": ROUTE_NAME}) == ROUTE_NO_PROJECT_ID
    assert upload_route({"route": "vendor-name"}) == ROUTE_NO_PROJECT_ID
