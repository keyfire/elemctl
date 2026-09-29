"""The verification of an extension apply: `apps apply`, `verify-deploy` and `deploy`.

An extension is applied beside the build of the application, and the card of the application
goes on naming the build of the application. A check that compared the card with the uploaded
build called every extension apply a rollback, the successful ones included. The evidence is
`extension-projects` of Console API 2.1; a server without 2.1 leaves the apply unverifiable,
and the check has to say so rather than report a rollback.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from elemctl.deploy import deploy_from_sources, verify_deploy

API = "/console/api/v2"
API_2_1 = "/console/api/v2.1"
APP = "0a1b2c3d-0000-4000-8000-000000000001"
APP_PROJECT = "0a1b2c3d-0000-4000-8000-0000000000a0"
APP_BUILD = "0a1b2c3d-0000-4000-8000-0000000000b1"
EXT_PROJECT = "0a1b2c3d-0000-4000-8000-0000000000e0"
EXT_BUILD_1 = "0a1b2c3d-0000-4000-8000-0000000000e1"
EXT_BUILD_2 = "0a1b2c3d-0000-4000-8000-0000000000e2"
EXT_BUILD_3 = "0a1b2c3d-0000-4000-8000-0000000000e3"
EXTENSION_ID = "0a1b2c3d-0000-4000-8000-0000000000ee"

CARD_PATH = f"{API}/applications/{APP}"
TASKS_PATH = f"{API}/tasks/application-tasks"
PROJECTS_PATH = f"{API}/projects"
EXT_BUILDS_PATH = f"{API}/projects/{EXT_PROJECT}/assemblies"
EXTENSIONS_PATH = f"{API_2_1}/applications/{APP}/project"

# The card keeps naming the build of the application after an extension is applied.
CARD = {
    "id": APP,
    "name": "demo-app",
    "status": "Running",
    "source": {"project-version-id": APP_BUILD, "project-version": "1.0-7"},
}

PROJECTS = [
    {"id": APP_PROJECT, "name": "crm", "project-kind": "Application", "deleted": False},
    {"id": EXT_PROJECT, "name": "crm-extras", "project-kind": "Extension", "deleted": False},
]


def _build(build_id, version):
    return {
        "id": build_id,
        "assembly-version": version,
        "project-version": version,
        "project-id": EXT_PROJECT,
        "project-developer": "acme",
        "project-name": "crm-extras",
    }


EXT_BUILDS = [_build(EXT_BUILD_1, "1.0-1"), _build(EXT_BUILD_2, "1.0-2")]


def _extension(version, *, enabled=True):
    """A row of `extension-projects` the way the console gives it."""
    return {
        "id": EXTENSION_ID,
        "project-id": EXT_PROJECT,
        # The console fills assembly-id of an extension with the id of its project.
        "assembly-id": EXT_PROJECT,
        "enabled": enabled,
        "order": 1,
        "vendor-name": "acme",
        "project-name": "crm-extras",
        "project-presentation": "CRM extras",
        "project-version": "1.0",
        "assembly-version": version,
    }


def _extensions(*rows):
    return {
        "application-project": {"project-name": "crm", "assembly-version": "1.0-7"},
        "extension-projects": list(rows),
    }


# What a console without a handler for the path answers - a 401 that names the path.
NO_HANDLER = {
    "error": {
        "code": 16,
        "status": "UNAUTHENTICATED",
        "message": f'Handler of HTTP request "[GET] /v2.1/applications/{APP}/project" in '
                   'application "console" not found.',
        "details": [],
    }
}


def _stand(transport, *, extensions=None, extensions_status=200):
    transport.add("GET", CARD_PATH, CARD)
    transport.add("GET", TASKS_PATH, [])
    transport.add("GET", PROJECTS_PATH, PROJECTS)
    transport.add("GET", EXT_BUILDS_PATH, EXT_BUILDS)
    if extensions_status == 200:
        transport.add("GET", EXTENSIONS_PATH, extensions)
    else:
        transport.add("GET", EXTENSIONS_PATH, NO_HANDLER, status=extensions_status)


def _since():
    return datetime.now(timezone.utc) - timedelta(minutes=30)


def test_an_applied_extension_passes_although_the_card_names_the_application_build(api):
    client, transport = api
    _stand(transport, extensions=_extensions(_extension("1.0-2")))

    report = verify_deploy(client, APP, expected_assembly_id=EXT_BUILD_2, since=_since())

    assert report.applied is True
    assert report.ok is True
    assert report.problems == []
    # The report names the build the extension runs, not the build on the card.
    assert report.applied_version == "1.0-2"
    assert report.applied_version_id == EXT_BUILD_2
    assert report.extension_project_id == EXT_PROJECT
    assert report.extension["id"] == EXTENSION_ID
    payload = report.to_dict()
    assert payload["extension-project-id"] == EXT_PROJECT
    assert payload["extension"]["assembly-version"] == "1.0-2"


def test_an_extension_left_on_its_previous_build_is_a_rollback(api):
    client, transport = api
    _stand(transport, extensions=_extensions(_extension("1.0-1")))

    report = verify_deploy(client, APP, expected_assembly_id=EXT_BUILD_2, since=_since())

    assert report.applied is False
    assert report.ok is False
    assert report.applied_version_id == EXT_BUILD_1
    [problem] = report.problems
    assert "работает на сборке" in problem
    assert EXT_BUILD_1 in problem and EXT_BUILD_2 in problem
    # The build of the application is not what the extension is compared with.
    assert APP_BUILD not in problem


def test_an_extension_the_application_does_not_have_is_a_rollback(api):
    """A first apply that failed leaves no extension at all."""
    client, transport = api
    _stand(transport, extensions=_extensions())

    report = verify_deploy(client, APP, expected_assembly_id=EXT_BUILD_2, since=_since())

    assert report.applied is False
    assert report.ok is False
    assert report.extension is None
    assert report.extension_project_id == EXT_PROJECT
    [problem] = report.problems
    assert "среди расширений приложения его нет" in problem
    assert "acme/crm-extras" in problem


def test_a_server_without_console_api_2_1_refuses_the_check_rather_than_failing_it(api):
    """The card alone would call the apply a rollback: the check says it cannot tell."""
    client, transport = api
    _stand(transport, extensions_status=401)

    report = verify_deploy(client, APP, expected_assembly_id=EXT_BUILD_2, since=_since())

    assert report.applied is None
    assert report.ok is False
    [problem] = report.problems
    assert problem.startswith("применение не проверить")
    assert "Console API 2.1" in problem
    assert "откатила" not in problem
    # The answer is not about the token: it is not renewed.
    assert len(transport.calls_to("POST", "/console/sys/token")) == 1


def test_a_disabled_extension_is_applied_and_named(api):
    client, transport = api
    _stand(transport, extensions=_extensions(_extension("1.0-2", enabled=False)))

    report = verify_deploy(client, APP, expected_assembly_id=EXT_BUILD_2, since=_since())

    assert report.applied is True
    assert report.ok is False
    [problem] = report.problems
    assert "выключено" in problem


def test_a_build_of_the_application_the_card_does_not_name_is_still_a_rollback(api):
    """No extension project lists the build, so the card judges it, and 2.1 is not asked."""
    client, transport = api
    _stand(transport, extensions=_extensions(_extension("1.0-2")))
    older = "0a1b2c3d-0000-4000-8000-0000000000b0"

    report = verify_deploy(client, APP, expected_assembly_id=older, since=_since())

    assert report.applied is False
    assert report.extension_project_id == ""
    [problem] = report.problems
    assert "не совпадает с загруженной" in problem
    assert transport.calls_to("GET", EXTENSIONS_PATH) == []


def test_a_lookup_that_fails_leaves_the_verdict_to_the_card_and_says_so(api):
    """The lookup only explains a mismatch: its failure must not take the report away."""
    client, transport = api
    transport.add("GET", CARD_PATH, CARD)
    transport.add("GET", TASKS_PATH, [])
    transport.add("GET", PROJECTS_PATH, {"message": "internal"}, status=500)

    report = verify_deploy(client, APP, expected_assembly_id=EXT_BUILD_2, since=_since())

    assert report.applied is False
    assert report.ok is False
    assert len(report.problems) == 2
    assert "не совпадает с загруженной" in report.problems[0]
    assert report.problems[1].startswith("не удалось узнать, не сборка ли")


def test_the_build_the_card_names_needs_no_lookup_of_extensions(api):
    client, transport = api
    _stand(transport, extensions=_extensions(_extension("1.0-2")))

    report = verify_deploy(client, APP, expected_assembly_id=APP_BUILD, since=_since())

    assert report.applied is True
    assert report.ok is True
    assert transport.calls_to("GET", PROJECTS_PATH) == []
    assert transport.calls_to("GET", EXTENSIONS_PATH) == []


def _extension_sources(project_factory):
    project_dir = project_factory(name="crm-extras", kind="Расширение")
    descriptor = project_dir / "Проект.yaml"
    descriptor.write_text(
        descriptor.read_text(encoding="utf-8")
        + "РасширяемыеПроекты:\n    -\n        Поставщик: acme\n        Имя: crm\n",
        encoding="utf-8",
    )
    return project_dir


def _deploy_stand(transport, *, after):
    """A stand a deploy of the extension goes through; after - the extension once applied."""
    transport.add("GET", CARD_PATH, CARD)
    transport.add("GET", TASKS_PATH, [])
    # Read by the schema guard and by the version count, then by the check after the upload.
    transport.add("GET", EXT_BUILDS_PATH, EXT_BUILDS)
    transport.add("GET", EXT_BUILDS_PATH, EXT_BUILDS)
    transport.add("GET", EXT_BUILDS_PATH, EXT_BUILDS + [_build(EXT_BUILD_3, "1.0-3")])
    transport.add("GET", EXTENSIONS_PATH, _extensions(_extension("1.0-2")))
    transport.add("GET", EXTENSIONS_PATH, _extensions(after))
    transport.add("POST", EXT_BUILDS_PATH, {
        "id": EXT_BUILD_3, "assembly-version": "1.0-3", "project-id": EXT_PROJECT,
    })
    transport.add("POST", f"{API}/applications/{APP}/project/update", CARD)


def test_a_deployed_extension_is_verified_by_the_extensions_of_the_application(
    api, project_factory, tmp_path
):
    client, transport = api
    _deploy_stand(transport, after=_extension("1.0-3"))
    lines = []

    report = deploy_from_sources(
        client, APP, EXT_PROJECT, project_dir=_extension_sources(project_factory),
        output_dir=tmp_path / "dist", log=lines.append,
    )

    assert report.assembly_id == EXT_BUILD_3
    assert report.applied is True
    assert report.ok is True
    assert report.applied_version_id == EXT_BUILD_3
    assert report.extension_project_id == EXT_PROJECT
    # The kind came from the archive: nobody had to look the project up.
    assert transport.calls_to("GET", PROJECTS_PATH) == []
    assert any("перечню его расширений" in line for line in lines)
    # The schema guard compared with the build the extension runs, not with the card: that
    # build has no commit, and the guard says so rather than naming another project.
    assert report.schema_check == "skipped:no-commit-id"


def test_a_deployed_extension_the_platform_rolled_back_fails_the_check(
    api, project_factory, tmp_path
):
    client, transport = api
    _deploy_stand(transport, after=_extension("1.0-2"))

    report = deploy_from_sources(
        client, APP, EXT_PROJECT, project_dir=_extension_sources(project_factory),
        output_dir=tmp_path / "dist",
    )

    assert report.applied is False
    assert report.ok is False
    assert report.applied_version_id == EXT_BUILD_2
    assert any("работает на сборке" in problem for problem in report.problems)


def test_the_schema_guard_of_a_first_extension_apply_has_nothing_to_compare(
    api, project_factory, tmp_path
):
    client, transport = api
    transport.add("GET", EXTENSIONS_PATH, _extensions())
    transport.add("GET", EXTENSIONS_PATH, _extensions(_extension("1.0-3")))
    transport.add("GET", CARD_PATH, CARD)
    transport.add("GET", TASKS_PATH, [])
    transport.add("GET", EXT_BUILDS_PATH, EXT_BUILDS)
    transport.add("GET", EXT_BUILDS_PATH, EXT_BUILDS + [_build(EXT_BUILD_3, "1.0-3")])
    transport.add("POST", EXT_BUILDS_PATH, {"id": EXT_BUILD_3, "assembly-version": "1.0-3"})
    transport.add("POST", f"{API}/applications/{APP}/project/update", CARD)

    report = deploy_from_sources(
        client, APP, EXT_PROJECT, project_dir=_extension_sources(project_factory),
        output_dir=tmp_path / "dist",
    )

    assert report.schema_check == "skipped:no-applied-extension"
    assert report.ok is True
