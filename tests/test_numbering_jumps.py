"""A jump in the numbering of builds is not the platform's housekeeping.

An upload without a project id keeps the version of its archive, a number far above the
project's count included, and the next upload into the project counts on from it. Seen live:
`1.0.0-3` was followed by `1.0.0-500` and `1.0.0-501`, the numbers between had never existed,
and the count line of `builds list` said the platform had deleted builds. The created stamps
cannot tell a jump from a deletion - the server hands numbers out ten a second - so the local
registry of uploads does: it remembers which way each build of this machine went.
"""

from __future__ import annotations

import json

from elemctl import cli
from elemctl.client import builds_summary
from elemctl.registry import (
    ROUTE_NO_PROJECT_ID,
    ROUTE_PROJECT,
    registry_path,
    remember_upload,
    remembered_uploads,
    upload_route,
)
from elemctl.versions import numbering_holes


def _card(version, number=None):
    return {"id": f"asm-{number or version}", "assembly-version": version,
            "project-version": version}


def _remember(assembly, *, route, command="builds upload", version="1.0-500"):
    assert remember_upload(
        assembly_id=assembly, project_id="proj-1", version=version, branch="", commit="",
        dirty=None, project_dir=None, file=None, stand="https://stand.test", command=command,
        route=route,
    ) == ""


# The live case: three builds uploaded into the project, one without a project id with a
# number of its own, and one more into the project after it.
JUMPED = [_card("1.0-1"), _card("1.0-2"), _card("1.0-3"), _card("1.0-500"), _card("1.0-501")]


# --- the holes themselves -------------------------------------------------------------------

def test_the_holes_are_found_between_builds_and_below_the_first_one():
    holes = numbering_holes([_card("1.0-2"), _card("1.0-3"), _card("1.0-7"), _card("2.0-1")])

    assert [(below and below["assembly-version"], above["assembly-version"])
            for below, above in holes] == [(None, "1.0-2"), ("1.0-3", "1.0-7")]


def test_an_unbroken_numbering_has_no_holes_and_what_is_not_numbered_takes_no_part():
    assert numbering_holes([_card("1.0-1"), _card("1.0-2"), _card("1.0-probe-ab12cd34"),
                            {"assembly-version": None}, "not-a-card"]) == []
    assert numbering_holes(None) == []


# --- the count line -------------------------------------------------------------------------

def test_a_jump_this_machine_made_is_named_and_the_listing_stays_whole():
    _remember("asm-1.0-500", route=ROUTE_NO_PROJECT_ID)

    line = builds_summary(JUMPED, 5)

    assert line.startswith("показано 5 из 5 – пропавших по нумерации сборок не видно")
    assert "Скачок 1.0-3 -> 1.0-500 – не удаление" in line
    assert "НЕ вся история" not in line


def test_a_line_an_older_elemctl_wrote_still_names_its_jump():
    """The route without a project id used to be written as `vendor-name`.

    A registry keeps a thousand uploads, so lines with the older value outlive the rename, and
    a jump one of them records must not turn back into a deletion.
    """
    _remember("asm-1.0-500", route="vendor-name")

    line = builds_summary(JUMPED, 5)

    assert "Скачок 1.0-3 -> 1.0-500 – не удаление" in line
    assert "НЕ вся история" not in line


def test_the_route_of_a_line_reads_the_older_value_as_the_new_one():
    assert upload_route({"route": "vendor-name"}) == ROUTE_NO_PROJECT_ID
    assert upload_route({"route": ROUTE_NO_PROJECT_ID}) == ROUTE_NO_PROJECT_ID
    assert upload_route({"route": ROUTE_PROJECT}) == ROUTE_PROJECT
    assert upload_route({"route": None}) == ""
    assert upload_route("not-a-line") == ""


def test_an_upload_without_a_project_id_is_written_under_the_new_value():
    _remember("asm-1.0-500", route=ROUTE_NO_PROJECT_ID)

    [line] = registry_path().read_text(encoding="utf-8").splitlines()

    assert json.loads(line)["route"] == "no-project-id"


def test_without_the_registry_a_hole_still_reads_as_a_deletion():
    """A build uploaded without a project id elsewhere is not in the registry."""
    line = builds_summary(JUMPED, 5)

    assert "есть пропуски" in line and "Скачок" not in line


def test_a_build_uploaded_into_the_project_does_not_explain_its_hole():
    """The server numbered it: the numbers under it were handed out, and the platform took
    them away."""
    _remember("asm-1.0-500", route=ROUTE_PROJECT)

    assert "есть пропуски" in builds_summary(JUMPED, 5)


def test_a_line_written_before_the_route_was_kept_is_judged_by_its_command():
    """A probe always uploads without a project id; `--build-version` gives the number."""
    _remember("asm-1.0-500", route=None, command="probe")

    assert "Скачок 1.0-3 -> 1.0-500" in builds_summary(JUMPED, 5)


def test_a_deletion_beside_a_jump_is_still_a_deletion():
    """Also live: the first build of the base was deleted by the platform minutes after it was
    uploaded, and a jump sat higher up. The listing is what survived, and the jump is named."""
    _remember("asm-1.0-500", route=ROUTE_NO_PROJECT_ID)

    line = builds_summary(JUMPED[1:], 4)

    assert "есть пропуски" in line and "НЕ вся история" in line
    assert "Скачок 1.0-3 -> 1.0-500" in line


def test_a_jump_under_the_first_build_of_a_base_is_named_by_that_build():
    """A project created by an upload of `1.0-500`: there is no build below the hole."""
    _remember("asm-1.0-500", route=ROUTE_NO_PROJECT_ID)

    line = builds_summary([_card("1.0-500"), _card("1.0-501")], 2)

    assert "пропавших по нумерации сборок не видно" in line
    assert "Скачок 1.0-500 – не удаление" in line


def test_several_jumps_are_named_together():
    _remember("asm-1.0-500", route=ROUTE_NO_PROJECT_ID)
    _remember("asm-1.0-900", route=ROUTE_NO_PROJECT_ID, version="1.0-900")

    line = builds_summary(JUMPED + [_card("1.0-900")], 6)

    assert "Скачки 1.0-3 -> 1.0-500, 1.0-501 -> 1.0-900 – не удаления" in line


def test_the_cli_prints_the_jump_after_the_answer(monkeypatch, capsys):
    _remember("asm-1.0-500", route=ROUTE_NO_PROJECT_ID)

    class Listing:
        def list_assemblies(self, project_id):
            return list(JUMPED)

        def get_project(self, project_id):
            return {"id": project_id, "project-kind": "Application"}

    monkeypatch.setattr(cli, "make_client", lambda config: Listing())

    assert cli.main(["builds", "list", "--project-id", "proj-1", "--limit", "0"]) == 0
    captured = capsys.readouterr()
    assert len(json.loads(captured.out)) == 5
    assert "Скачок 1.0-3 -> 1.0-500" in captured.err


# --- a jump and a deletion in one hole ------------------------------------------------------

def _listed(*versions, project="proj-1"):
    return [{**_card(version), "project-id": project} for version in versions]


def test_a_jump_that_lost_its_top_is_named_and_the_hole_stays_a_loss():
    """Seen live: after `1.0-50` (without a project id) and `1.0-51` were deleted, the
    listing went from `1.0-8` straight to `1.0-52`, and the hole read as a deletion alone."""
    _remember("asm-1.0-50", route=ROUTE_NO_PROJECT_ID, version="1.0-50")
    _remember("asm-1.0-51", route=ROUTE_PROJECT, version="1.0-51")
    _remember("asm-1.0-52", route=ROUTE_PROJECT, version="1.0-52")

    line = builds_summary(_listed(*[f"1.0-{n}" for n in range(1, 9)], "1.0-52"), 9)

    assert "есть пропуски" in line and "НЕ вся история" in line
    assert ("Пропуск 1.0-8 -> 1.0-52 – и скачок, и удаление: сборку 1.0-50 машина загрузила "
            "без ид проекта") in line
    assert line.endswith("в перечне уже нет 1.0-50, 1.0-51")


def test_a_jump_over_a_deleted_upload_of_this_machine_is_no_longer_called_whole():
    """Also live: the housekeeping deleted `1.0-4` under a jump to `1.0-10`, and the line said
    the listing had lost nothing and the hole was no deletion."""
    _remember("asm-1.0-4", route=ROUTE_PROJECT, version="1.0-4")
    _remember("asm-1.0-10", route=ROUTE_NO_PROJECT_ID, version="1.0-10")

    line = builds_summary(_listed("1.0-1", "1.0-2", "1.0-3", "1.0-10"), 4)

    assert "есть пропуски" in line and "не удаление" not in line
    assert "Пропуск 1.0-3 -> 1.0-10 – и скачок, и удаление: сборку 1.0-10" in line
    assert line.endswith("в перечне уже нет 1.0-4")


def test_uploads_into_another_project_do_not_touch_the_hole():
    _remember("asm-1.0-10", route=ROUTE_NO_PROJECT_ID, version="1.0-10")
    assert remember_upload(
        assembly_id="asm-other", project_id="proj-2", version="1.0-4", branch="", commit="",
        dirty=None, project_dir=None, file=None, stand="https://stand.test",
        command="builds upload", route=ROUTE_PROJECT,
    ) == ""

    line = builds_summary(_listed("1.0-1", "1.0-2", "1.0-3", "1.0-10"), 4)

    assert "пропавших по нумерации сборок не видно" in line
    assert "Скачок 1.0-3 -> 1.0-10 – не удаление" in line


def test_a_long_list_of_lost_uploads_is_cut_short():
    _remember("asm-1.0-10", route=ROUTE_NO_PROJECT_ID, version="1.0-10")
    for number in range(4, 10):
        _remember(f"asm-1.0-{number}", route=ROUTE_PROJECT, version=f"1.0-{number}")

    line = builds_summary(_listed("1.0-1", "1.0-2", "1.0-3", "1.0-10"), 4)

    assert line.endswith("в перечне уже нет 1.0-4, 1.0-5, 1.0-6 и еще 3")


def test_a_gap_under_the_first_build_names_the_build_above_it():
    _remember("asm-1.0-50", route=ROUTE_NO_PROJECT_ID, version="1.0-50")

    line = builds_summary(_listed("1.0-52"), 1)

    assert "Пропуск под 1.0-52 – и скачок, и удаление: сборку 1.0-50" in line


# --- nothing to judge by --------------------------------------------------------------------

def test_an_empty_listing_does_not_call_its_numbering_unbroken():
    line = builds_summary([], 0)

    assert line == "показано 0 из 0 – у проекта на платформе нет ни одной сборки"


def test_a_listing_without_a_single_number_does_not_judge_it_either():
    line = builds_summary([_card("1.0-probe-ab12cd34"), _card("1.0")], 2)

    assert "номера нет ни у одной сборки" in line and "сплошная" not in line


def test_the_cli_says_so_for_an_empty_project(monkeypatch, capsys):
    class Listing:
        def list_assemblies(self, project_id):
            return []

        def get_project(self, project_id):
            return {"id": project_id, "project-kind": "Application"}

    monkeypatch.setattr(cli, "make_client", lambda config: Listing())

    assert cli.main(["builds", "list", "--project-id", "proj-1"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert "нет ни одной сборки" in captured.err and "сплошная" not in captured.err


# --- the route every upload writes down -----------------------------------------------------

def test_builds_upload_writes_down_the_way_the_build_went(monkeypatch, project_factory, tmp_path,
                                                          capsys):
    project_dir = project_factory()
    assert cli.main([
        "build", "--project-dir", str(project_dir), "--output", str(tmp_path / "dist"),
        "--build-version", "1.0-500",
    ]) == 0
    archive = json.loads(capsys.readouterr().out)["file"]
    answers = iter([
        {"name": "1.0-500", "image-id": "asm-by-name", "artifact": {"artifact-id": "proj-1"}},
        {"image-id": "asm-into", "assembly-version": "1.0-501"},
    ])

    class Uploads:
        def get_project(self, project_id):
            return {"id": project_id}

        def list_projects(self, name="", include_deleted=False):
            return []

        def upload_assembly(self, data, **kwargs):
            return next(answers)

    monkeypatch.setattr(cli, "make_client", lambda config: Uploads())
    monkeypatch.setenv("ELEMENT_BASE_URL", "https://stand.test")
    monkeypatch.setenv("ELEMENT_CLIENT_ID", "cid")
    monkeypatch.setenv("ELEMENT_CLIENT_SECRET", "secret")
    monkeypatch.delenv("ELEMENT_PROJECT_ID", raising=False)

    assert cli.main(["builds", "upload", archive, "--new-project"]) == 0
    assert cli.main(["builds", "upload", archive, "--project-id", "proj-1"]) == 0

    remembered = remembered_uploads()
    assert remembered["asm-by-name"]["route"] == ROUTE_NO_PROJECT_ID
    assert remembered["asm-into"]["route"] == ROUTE_PROJECT


def test_a_probe_and_a_deploy_write_down_their_routes(project_factory, tmp_path):
    from elemctl.deploy import deploy_from_sources
    from elemctl.probe import probe_project
    from tests.test_probe import FakeProbeClient
    from tests.test_registry import _DeployClient

    probe_dir = project_factory(presentation="Пробник", language="Русский")
    probe_project(FakeProbeClient(), project_dir=probe_dir, output_dir=tmp_path / "probe")
    deploy_from_sources(
        _DeployClient(), "app-1", "proj-1", project_dir=probe_dir,
        output_dir=tmp_path / "deploy", version="1.0-12",
    )

    remembered = remembered_uploads()
    assert remembered["asm-1"]["route"] == ROUTE_NO_PROJECT_ID
    assert remembered["asm-new"]["route"] == ROUTE_PROJECT
