"""Тесты логики итога деплоя (ok/applied) на клиенте-заглушке."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from elemctl.deploy import deploy_from_sources, verify_deploy


class FakeDeployClient:
    """Клиент-заглушка с публичными методами, которые использует deploy."""

    def __init__(
        self,
        *,
        applied_version="1.0-5",
        status="Running",
        uri="https://app.test/x",
        tasks=None,
        latest=None,
        uri_status=200,
        upload_response=None,
    ):
        self._applied_version = applied_version
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
        assert data[:2] == b"PK"  # это должен быть настоящий zip
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
        card = {"id": "app-1", "status": self._status, "uri": self._uri}
        if self._applied_version is not None:
            card["source"] = {"project-version": self._applied_version}
        else:
            card["source"] = {}
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

    # Версия – автоинкремент от последней сборки проекта.
    assert report.version == "1.0-5"
    assert report.assembly_id == "asm-777"
    assert report.applied is True
    assert report.applied_version == "1.0-5"
    assert report.ok is True
    assert report.problems == []
    assert report.uri_status == 200
    assert client.apply_calls == [("app-1", {"image_id": "asm-777"})]
    assert log_lines  # прогресс отдан через callback


def test_deploy_detects_silent_rollback(project_factory, tmp_path):
    # Платформа откатила: применённая версия осталась старой.
    client = FakeDeployClient(
        latest={"assembly-version": "1.0-4", "id": "asm-4"}, applied_version="1.0-4"
    )
    report = deploy_from_sources(
        client, "app-1", "proj-1", project_dir=project_factory(), output_dir=tmp_path / "d"
    )
    assert report.applied is False
    assert report.ok is False
    assert any("не совпадает" in problem for problem in report.problems)


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
    # Старая ошибка из истории (до начала деплоя) не должна портить вердикт.
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
    # Карточка без source.project-version: применение не подтверждено и не опровергнуто.
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
    # Закрытое приложение отвечает 401 – это информация, а не проблема.
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
        "uri",
        "status",
        "version",
        "assembly-id",
        "applied-version",
        "applied",
        "uri-status",
        "problems",
        "ok",
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
