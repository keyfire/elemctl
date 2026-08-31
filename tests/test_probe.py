"""Tests of the compilation probe: the verdict, the parsed errors and the cleanup."""

from __future__ import annotations

import pytest

from elemctl.errors import ApiError, ElemctlError
from elemctl.probe import PROBE_PREFIX, parse_compilation_errors, probe_project

# A task message exactly as the platform gives it: the first line carries the
# platform's own prefix, the rest are bare.
TASK_MESSAGE = (
    "CreateApplication: Ошибка создания приложения: "
    'acme/crm/Основное/Проверка.xbsl [4:22]: <Сервер> Variable "Неизвестная" is not defined\n'
    'acme/crm/Основное/Проверка.xbsl [8:13]: <Клиент> Variable "Модуль" is not defined'
)


class FakeProbeClient:
    """A stub client with the public methods the probe uses."""

    def __init__(
        self,
        *,
        fail=False,
        projects=(("proj-1", ),),
        upload_response=None,
        messages=None,
        deleted=True,
        delete_assembly_error=None,
    ):
        self._fail = fail
        self._projects = [{"id": ids[0]} for ids in projects]
        self._upload_response = upload_response or {
            "image-id": "asm-1",
            "artifact": {"artifact-id": "proj-1"},
        }
        self._messages = messages if messages is not None else [TASK_MESSAGE]
        self._deleted = deleted
        self._delete_assembly_error = delete_assembly_error
        self.calls = []

    def list_projects(self):
        self.calls.append(("list_projects",))
        return self._projects

    def upload_assembly(self, data, **kwargs):
        assert data[:2] == b"PK"  # it has to be a real zip
        self.calls.append(("upload_assembly", kwargs))
        return self._upload_response

    def create_app(self, name, **kwargs):
        self.calls.append(("create_app", name, kwargs))
        return {"id": "app-1"}

    def wait_app_ready(self, app_id, log=None):
        self.calls.append(("wait_app_ready", app_id))
        if self._fail:
            raise ApiError("приложение app-1 создано со статусом Error", body={"status": "Error"})
        return {"id": app_id, "status": "Running", "uri": "https://app.test/x"}

    def failed_task_messages(self, app_id):
        return list(self._messages)

    def delete_app(self, app_id):
        self.calls.append(("delete_app", app_id))
        return None

    def wait_app_deleted(self, app_id, log=None):
        self.calls.append(("wait_app_deleted", app_id))
        return self._deleted

    def delete_assembly(self, project_id, version):
        self.calls.append(("delete_assembly", project_id, version))
        if self._delete_assembly_error:
            raise self._delete_assembly_error
        return None

    def delete_project(self, project_id):
        self.calls.append(("delete_project", project_id))
        return None

    def names(self):
        return [call[0] for call in self.calls]


def test_parse_compilation_errors_splits_position_and_environment():
    errors = parse_compilation_errors([TASK_MESSAGE], prefix="acme/crm/")

    assert len(errors) == 2
    first, second = errors
    # The archive prefix is stripped: file is the path relative to the project directory.
    assert first["file"] == "Основное/Проверка.xbsl"
    assert first["entry"] == "acme/crm/Основное/Проверка.xbsl"
    assert (first["line"], first["column"]) == (4, 22)
    assert first["environment"] == "Сервер"
    # Neither the platform prefix nor the environment marker is left in the text.
    assert first["message"] == 'Variable "Неизвестная" is not defined'
    assert (second["line"], second["column"], second["environment"]) == (8, 13, "Клиент")


def test_parse_compilation_errors_ignores_lines_without_a_position():
    errors = parse_compilation_errors(["Неизвестная ошибка. Обратитесь к администратору"])

    assert errors == []


def test_probe_success_cleans_up_after_itself(project_factory, tmp_path):
    client = FakeProbeClient()
    lines = []

    report = probe_project(
        client, project_dir=project_factory(), output_dir=tmp_path / "dist", log=lines.append
    )

    assert report.ok is True
    assert report.errors == []
    assert report.status == "Running"
    # The upload goes WITHOUT a project id: the platform routes the build by the
    # vendor and the name of the manifest, and the probe must not be able to
    # reach the project of the environment.
    upload = next(call for call in client.calls if call[0] == "upload_assembly")
    assert upload[1]["project_id"] is None
    # The throwaway application is created out of a specific build and without a
    # development environment; its name carries the probe prefix.
    create = next(call for call in client.calls if call[0] == "create_app")
    assert create[2]["project_version_id"] == "asm-1"
    assert create[2]["development_mode"] is False
    assert create[2].get("space_id") is None
    assert report.app_name.startswith(PROBE_PREFIX)
    # The cleanup order is forced by the platform: the application first, the
    # build only after it has really disappeared.
    assert client.names().index("delete_app") < client.names().index("delete_assembly")
    assert report.cleanup["app-deleted"] is True
    assert report.cleanup["assembly-deleted"] is True
    assert report.cleanup["problems"] == []


def test_probe_default_version_is_not_a_numeric_counter(project_factory, tmp_path):
    """The default version has to be new every time and must never look like the latest build.

    A repeated upload of the same version is rejected by the platform, and the
    project's latest build is picked by the numeric counter after the last hyphen –
    a probe build must not win that comparison.
    """
    from elemctl.versions import version_counter

    client = FakeProbeClient()

    report = probe_project(client, project_dir=project_factory(), output_dir=tmp_path / "dist")

    assert report.version.startswith("1.0-probe-")
    assert version_counter(report.version) == 0


def test_probe_skips_an_all_digit_token(monkeypatch, project_factory, tmp_path):
    """Eight hex digits come out all-numeric once in ~43 draws – CI caught one live
    (28229801): such a version parses as a numeric counter and would win the
    latest-build pick. An all-digit token must be redrawn, however many in a row."""
    import elemctl.probe as probe_module
    from elemctl.versions import version_counter

    class StubUuid:
        def __init__(self, hex_value):
            self.hex = hex_value

    draws = iter(["28229801", "31415926", "c0ffee12"])
    monkeypatch.setattr(
        probe_module.uuid, "uuid4", lambda: StubUuid(next(draws).ljust(32, "f"))
    )

    report = probe_project(
        FakeProbeClient(), project_dir=project_factory(), output_dir=tmp_path / "dist"
    )

    assert report.version.endswith("-probe-c0ffee12")
    assert version_counter(report.version) == 0


def test_probe_reports_compilation_errors_and_fails(project_factory, tmp_path):
    client = FakeProbeClient(fail=True)

    report = probe_project(client, project_dir=project_factory(), output_dir=tmp_path / "dist")

    assert report.ok is False
    assert report.status == "Error"
    assert [error["line"] for error in report.errors] == [4, 8]
    assert report.messages == [TASK_MESSAGE]
    # A failed compilation is cleaned up exactly like a successful one – that is
    # the whole point of the probe.
    assert report.cleanup["app-deleted"] is True
    assert report.cleanup["assembly-deleted"] is True


def test_probe_keeps_the_error_text_when_it_is_not_a_compilation_one(project_factory, tmp_path):
    client = FakeProbeClient(fail=True, messages=[])

    report = probe_project(client, project_dir=project_factory(), output_dir=tmp_path / "dist")

    assert report.ok is False
    assert report.errors == []
    assert "статусом Error" in report.messages[0]


def test_probe_deletes_the_project_it_created(project_factory, tmp_path):
    """A project that was not there before the upload is the probe's leftover as well."""
    client = FakeProbeClient(
        projects=(("other", ),),
        upload_response={"image-id": "asm-1", "artifact": {"artifact-id": "fresh"}},
    )

    report = probe_project(client, project_dir=project_factory(), output_dir=tmp_path / "dist")

    assert report.project_id == "fresh"
    assert report.cleanup["project-deleted"] is True
    assert ("delete_project", "fresh") in client.calls


def test_probe_keeps_an_existing_project(project_factory, tmp_path):
    """A project that already existed is not the probe's to delete."""
    client = FakeProbeClient()

    report = probe_project(client, project_dir=project_factory(), output_dir=tmp_path / "dist")

    assert report.cleanup["project-deleted"] is None
    assert "delete_project" not in client.names()


def test_probe_does_not_touch_the_build_while_the_application_is_alive(project_factory, tmp_path):
    """The application has not disappeared – the build and the project stay put.

    Deleting a build an application was created from is rejected by the platform
    with a 500, so the probe reports a leftover instead of running into it.
    """
    client = FakeProbeClient(deleted=False)

    report = probe_project(client, project_dir=project_factory(), output_dir=tmp_path / "dist")

    assert report.ok is True  # the compilation verdict does not depend on the cleanup
    assert report.cleanup["app-deleted"] is False
    assert report.cleanup["assembly-deleted"] is False
    assert "delete_assembly" not in client.names()
    assert len(report.cleanup["problems"]) == 2


def test_probe_reports_a_cleanup_failure_without_losing_the_verdict(project_factory, tmp_path):
    client = FakeProbeClient(delete_assembly_error=ApiError("Console API ответил 500", status=500))

    report = probe_project(client, project_dir=project_factory(), output_dir=tmp_path / "dist")

    assert report.ok is True
    assert report.cleanup["assembly-deleted"] is False
    assert "500" in report.cleanup["problems"][0]
    # A project is not deleted after a build that stayed behind.
    assert "delete_project" not in client.names()


def test_probe_keep_skips_the_cleanup(project_factory, tmp_path):
    client = FakeProbeClient(fail=True)

    report = probe_project(
        client, project_dir=project_factory(), output_dir=tmp_path / "dist", keep=True
    )

    assert report.cleanup["kept"] is True
    assert "delete_app" not in client.names()
    assert "delete_assembly" not in client.names()


def test_probe_without_an_assembly_id_is_an_error(project_factory, tmp_path):
    """No build id in the response means there is nothing to compile."""
    client = FakeProbeClient(upload_response={"artifact": {"artifact-id": "proj-1"}})

    with pytest.raises(ElemctlError):
        probe_project(client, project_dir=project_factory(), output_dir=tmp_path / "dist")

    assert "create_app" not in client.names()


# --- the stand does not know the compatibility mode of the project ------------

# What a stand older than the project answers: the refusal comes first, and the
# derived complaints follow - about types and properties of a mode the platform
# does not know, in files the change never touched.
COMPATIBILITY_MESSAGE = (
    "CreateApplication: Ошибка создания приложения: Неизвестный режим совместимости 99.0\n"
    'acme/crm/Основное/Карточка.xbsl [12:4]: <Сервер> Unknown type "ПанельЭтапов"\n'
    'acme/crm/Основное/Список.xbsl [3:9]: <Клиент> Unknown property "МинимальнаяШирина"'
)


def test_a_refused_compatibility_mode_stops_the_parsing(project_factory, tmp_path):
    """The verdict is about the stand: the avalanche behind it answers nothing."""
    client = FakeProbeClient(fail=True, messages=[COMPATIBILITY_MESSAGE])

    report = probe_project(client, project_dir=project_factory(), output_dir=tmp_path / "dist")

    assert report.ok is False
    assert report.compatibility_refused == "99.0"
    # The derived errors are NOT parsed - they would read as a verdict on the code.
    assert report.errors == []
    assert report.messages_dropped == 2
    assert len(report.messages) == 1 and "режим совместимости" in report.messages[0]


def test_a_refused_compatibility_mode_is_announced(project_factory, tmp_path):
    client = FakeProbeClient(fail=True, messages=[COMPATIBILITY_MESSAGE])
    lines = []

    probe_project(
        client, project_dir=project_factory(), output_dir=tmp_path / "dist", log=lines.append
    )

    said = "\n".join(lines)
    assert "старше проекта" in said and "99.0" in said


def test_the_project_compatibility_mode_is_named_in_the_refusal(project_factory, tmp_path):
    """The report says what the project asks for, not only what the stand refused."""
    project_dir = project_factory()
    descriptor = project_dir / "Проект.yaml"
    descriptor.write_text(
        descriptor.read_text(encoding="utf-8") + "РежимСовместимости: 99.0\n", encoding="utf-8"
    )
    client = FakeProbeClient(fail=True, messages=[COMPATIBILITY_MESSAGE])
    lines = []

    probe_project(client, project_dir=project_dir, output_dir=tmp_path / "dist", log=lines.append)

    assert any("99.0" in line for line in lines)


def test_an_ordinary_compilation_failure_is_still_parsed(project_factory, tmp_path):
    """The short circuit fires on the refusal alone - nothing else changes."""
    client = FakeProbeClient(fail=True)

    report = probe_project(client, project_dir=project_factory(), output_dir=tmp_path / "dist")

    assert report.compatibility_refused == ""
    assert report.messages_dropped == 0
    assert [error["line"] for error in report.errors] == [4, 8]


def test_the_english_wording_of_the_refusal_is_recognized(project_factory, tmp_path):
    client = FakeProbeClient(
        fail=True, messages=["CreateApplication: Unknown compatibility mode 99.0"]
    )

    report = probe_project(client, project_dir=project_factory(), output_dir=tmp_path / "dist")

    assert report.compatibility_refused == "99.0"
