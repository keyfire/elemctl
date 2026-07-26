"""Tests of the deploy verdict logic (ok/applied) on a stub client."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from elemctl.deploy import deploy_from_sources, verify_deploy


class FakeDeployClient:
    """A stub client carrying the public methods that deploy uses."""

    def __init__(
        self,
        *,
        applied_version="1.0-5",
        applied_version_id=None,
        status="Running",
        uri="https://app.test/x",
        tasks=None,
        latest=None,
        uri_status=200,
        upload_response=None,
    ):
        self._applied_version = applied_version
        self._applied_version_id = applied_version_id
        self._status = status
        self._uri = uri
        self._tasks = tasks or []
        self._latest = latest
        self._uri_status = uri_status
        self._upload_response = upload_response or {"image-id": "asm-777"}
        self.apply_calls = []
        self.upload_kwargs = None

    def latest_assembly(self, project_id):
        return self._latest

    def upload_assembly(self, data, **kwargs):
        assert data[:2] == b"PK"  # it has to be a real zip
        self.upload_kwargs = kwargs
        return self._upload_response

    def apply_build(self, app_id, **kwargs):
        self.apply_calls.append((app_id, kwargs))

    def ensure_running(self, app_id, log=None):
        return self._card()

    def get_app(self, app_id):
        return self._card()

    def list_app_tasks(self, app_id=""):
        return self._tasks

    def check_uri(self, uri):
        return self._uri_status

    def _card(self):
        card = {"id": "app-1", "name": "site-dev", "status": self._status, "uri": self._uri}
        source = {}
        if self._applied_version is not None:
            source["project-version"] = self._applied_version
        if self._applied_version_id is not None:
            source["project-version-id"] = self._applied_version_id
        card["source"] = source
        return card


def _future_iso(minutes=5):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def test_deploy_success(project_factory, tmp_path):
    client = FakeDeployClient(
        latest={"assembly-version": "1.0-4", "id": "asm-4"}, applied_version="1.0-5"
    )
    log_lines = []

    report = deploy_from_sources(
        client,
        "app-1",
        "proj-1",
        project_dir=project_factory(),
        output_dir=tmp_path / "dist",
        log=log_lines.append,
    )

    # The version is auto-incremented from the project's latest assembly.
    assert report.version == "1.0-5"
    assert report.assembly_id == "asm-777"
    assert report.applied is True
    assert report.applied_version == "1.0-5"
    assert report.ok is True
    assert report.problems == []
    assert report.uri_status == 200
    assert client.apply_calls == [("app-1", {"image_id": "asm-777"})]
    assert log_lines  # progress was reported through the callback


def test_deploy_detects_silent_rollback(project_factory, tmp_path):
    # The platform rolled back: the applied version stayed the old one.
    client = FakeDeployClient(
        latest={"assembly-version": "1.0-4", "id": "asm-4"}, applied_version="1.0-4"
    )
    report = deploy_from_sources(
        client, "app-1", "proj-1", project_dir=project_factory(), output_dir=tmp_path / "d"
    )
    assert report.applied is False
    assert report.ok is False
    assert any("не совпадает" in problem for problem in report.problems)


def test_deploy_trusts_assembly_id_over_renumbered_version(project_factory, tmp_path):
    # A freshly created application numbers versions from scratch (archive 1.0-1139 is
    # applied as 1.0-3) – matching by the version string reported a false rollback. What
    # confirms the apply is the id of the applied assembly matching the uploaded one.
    client = FakeDeployClient(
        latest={"assembly-version": "1.0-1138", "id": "asm-old"},
        applied_version="1.0-3",
        applied_version_id="asm-777",
    )
    report = deploy_from_sources(
        client, "app-1", "proj-1", project_dir=project_factory(), output_dir=tmp_path / "d"
    )
    assert report.applied is True
    assert report.ok is True
    assert report.applied_version_id == "asm-777"
    assert report.problems == []


def test_deploy_detects_rollback_by_assembly_id(project_factory, tmp_path):
    # A rollback with the id known: the previously applied assembly stayed in place.
    client = FakeDeployClient(
        latest={"assembly-version": "1.0-4", "id": "asm-4"},
        applied_version="1.0-5",
        applied_version_id="asm-old",
    )
    report = deploy_from_sources(
        client, "app-1", "proj-1", project_dir=project_factory(), output_dir=tmp_path / "d"
    )
    assert report.applied is False
    assert report.ok is False
    assert any("применённая сборка" in problem for problem in report.problems)


def test_deploy_fails_on_fresh_error_task(project_factory, tmp_path):
    client = FakeDeployClient(
        applied_version="1.0-1",
        tasks=[
            {
                "id": "t1",
                "status": "Failed",
                "operation-type": "ProjectUpdate",
                "error-message": "ошибка компиляции",
                "start-date": _future_iso(),
            }
        ],
    )
    report = deploy_from_sources(
        client,
        "app-1",
        "proj-1",
        project_dir=project_factory(),
        output_dir=tmp_path / "d",
        version="1.0-1",
    )
    assert report.ok is False
    assert any("ошибка компиляции" in problem for problem in report.problems)


def test_deploy_ignores_old_error_tasks(project_factory, tmp_path):
    # An old error out of the history (from before the deploy started) must not spoil the verdict.
    client = FakeDeployClient(
        applied_version="1.0-1",
        tasks=[
            {
                "id": "t0",
                "status": "Error",
                "start-date": "2020-01-01T00:00:00Z",
                "error-message": "древняя ошибка",
            }
        ],
    )
    report = deploy_from_sources(
        client,
        "app-1",
        "proj-1",
        project_dir=project_factory(),
        output_dir=tmp_path / "d",
        version="1.0-1",
    )
    assert report.ok is True
    assert report.problems == []


def test_deploy_applied_none_when_version_unknown(project_factory, tmp_path):
    # A card with no source.project-version: the apply is neither confirmed nor refuted.
    client = FakeDeployClient(applied_version=None)
    report = deploy_from_sources(
        client,
        "app-1",
        "proj-1",
        project_dir=project_factory(),
        output_dir=tmp_path / "d",
        version="1.0-1",
    )
    assert report.applied is None
    assert report.ok is True


def test_uri_status_401_is_not_a_problem(project_factory, tmp_path):
    # A closed application answers 401 – that is information, not a problem.
    client = FakeDeployClient(applied_version="1.0-1", uri_status=401)
    report = deploy_from_sources(
        client,
        "app-1",
        "proj-1",
        project_dir=project_factory(),
        output_dir=tmp_path / "d",
        version="1.0-1",
    )
    assert report.uri_status == 401
    assert report.ok is True


def test_report_to_dict_kebab_case(project_factory, tmp_path):
    client = FakeDeployClient(applied_version="1.0-1")
    report = deploy_from_sources(
        client,
        "app-1",
        "proj-1",
        project_dir=project_factory(),
        output_dir=tmp_path / "d",
        version="1.0-1",
    )
    payload = report.to_dict()
    assert set(payload) == {
        "app-id",
        "app-name",
        "app-id-source",
        "project-id",
        "project-id-source",
        "uri",
        "status",
        "version",
        "assembly-id",
        "applied-version",
        "applied-version-id",
        "applied",
        "uri-status",
        "problems",
        "ok",
        "dirty",
        "dirty-files",
    }
    assert payload["ok"] is True


def test_verify_deploy_standalone():
    client = FakeDeployClient(applied_version="1.0-7")
    since = datetime.now(timezone.utc) - timedelta(minutes=30)

    good = verify_deploy(client, "app-1", expected_version="1.0-7", since=since)
    assert good.applied is True
    assert good.ok is True

    bad = verify_deploy(client, "app-1", expected_version="1.0-8", since=since)
    assert bad.applied is False
    assert bad.ok is False


def test_verify_deploy_standalone_by_assembly_id():
    # The id outweighs the version string: a renumbered version that does not match is harmless.
    client = FakeDeployClient(applied_version="1.0-3", applied_version_id="asm-9")
    since = datetime.now(timezone.utc) - timedelta(minutes=30)

    good = verify_deploy(
        client, "app-1", expected_version="1.0-1139", expected_assembly_id="asm-9", since=since
    )
    assert good.applied is True
    assert good.ok is True

    bad = verify_deploy(client, "app-1", expected_assembly_id="asm-10", since=since)
    assert bad.applied is False
    assert bad.ok is False


def test_deploy_reports_dirty_tree(project_factory, tmp_path, monkeypatch):
    """Uncommitted changes of the project directory show up in the log and in the report.

    The build captures the disk as of the moment it starts: with edits going on in
    parallel a half-baked state lands in the archive, and that must not be kept quiet.
    """
    from elemctl import deploy as deploy_module

    original = deploy_module.build_assembly

    def dirty_build(*args, **kwargs):
        result = original(*args, **kwargs)
        result.dirty_files = ["acme/crm/Проект.xbsl", "acme/crm/Новый.yaml"]
        return result

    monkeypatch.setattr(deploy_module, "build_assembly", dirty_build)
    client = FakeDeployClient(applied_version="1.0-1")
    log_lines = []

    report = deploy_from_sources(
        client,
        "app-1",
        "proj-1",
        project_dir=project_factory(),
        output_dir=tmp_path / "dist",
        version="1.0-1",
        log=log_lines.append,
    )

    assert report.dirty_files == ["acme/crm/Проект.xbsl", "acme/crm/Новый.yaml"]
    payload = report.to_dict()
    assert payload["dirty"] is True
    assert payload["dirty-files"] == ["acme/crm/Проект.xbsl", "acme/crm/Новый.yaml"]
    warning = [line for line in log_lines if "незакоммиченные" in line]
    assert warning and "Проект.xbsl" in warning[0]
    # Tree cleanliness is a warning, not a problem with the apply.
    assert report.problems == [] and report.ok is True


def test_deploy_outside_repository_dirty_unknown(project_factory, tmp_path):
    """Outside a git repository cleanliness is unknown: dirty is null and no warning is issued."""
    client = FakeDeployClient(applied_version="1.0-1")
    log_lines = []
    report = deploy_from_sources(
        client,
        "app-1",
        "proj-1",
        project_dir=project_factory(),
        output_dir=tmp_path / "dist",
        version="1.0-1",
        log=log_lines.append,
    )
    assert report.dirty_files is None
    assert report.to_dict()["dirty"] is None
    assert not [line for line in log_lines if "незакоммиченные" in line]


def test_report_names_the_target_and_where_it_came_from(project_factory, tmp_path):
    """The report names the application, its name and the origin of each id.

    A deploy to the wrong application is the mistake this closes: an id taken from
    the environment must not look the same as one given explicitly.
    """
    client = FakeDeployClient(applied_version="1.0-1")
    report = deploy_from_sources(
        client,
        "app-1",
        "proj-1",
        project_dir=project_factory(),
        output_dir=tmp_path / "dist",
        version="1.0-1",
        app_id_source="env",
        project_id_source="flag",
    )
    payload = report.to_dict()
    assert payload["app-id"] == "app-1" and payload["app-name"] == "site-dev"
    assert payload["app-id-source"] == "env"
    assert payload["project-id"] == "proj-1" and payload["project-id-source"] == "flag"


def test_target_is_announced_before_the_build(project_factory, tmp_path):
    """The target line comes FIRST - while there is still time to interrupt."""
    client = FakeDeployClient(applied_version="1.0-1")
    log_lines = []
    deploy_from_sources(
        client,
        "app-1",
        "proj-1",
        project_dir=project_factory(),
        output_dir=tmp_path / "dist",
        version="1.0-1",
        app_id_source="env",
        project_id_source="env",
        log=log_lines.append,
    )
    assert "app-1" in log_lines[0] and "proj-1" in log_lines[0]
    assert "окружения" in log_lines[0]
