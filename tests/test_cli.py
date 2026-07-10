"""Тесты CLI: локальные команды и коды возврата (без сети)."""

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
    """Изолировать тесты от переменных окружения и .env разработчика."""
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


def test_module_entry_point():
    """python -m elemctl – запасной путь для вызывающих без консольной точки входа в PATH."""
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
        def find_app(self, name):
            if name == "site-dev":
                return {"id": "app-42", "display-name": "site-dev"}
            return None

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())

    rc = cli.main(["apps", "find", "site-dev"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"id": "app-42", "found": True}

    # Отсутствие приложения – штатный ответ: код возврата 0, признак несёт поле found.
    rc = cli.main(["apps", "find", "нет-такого"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"id": None, "found": False}


def test_apps_find_request_failure_is_an_error(monkeypatch, capsys):
    """Сбой запроса отличим от "не найдено": ненулевой код и error в stderr."""

    class FailingClient:
        def find_app(self, name):
            raise ApiError("нет доступа", status=403)

    monkeypatch.setattr(cli, "make_client", lambda config: FailingClient())

    rc = cli.main(["apps", "find", "site-dev"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_error_is_json_on_stderr(capsys):
    # app-id не задан ни аргументом, ни конфигурацией.
    rc = cli.main(["apps", "get"])
    assert rc == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert "error" in payload
    assert "app-id" in payload["error"]


def test_deploy_exit_code_reflects_ok(monkeypatch, capsys, project_factory, tmp_path):
    from tests.test_deploy import FakeDeployClient

    # Успех: применённая версия совпала.
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

    # Откат: версия не совпала – код возврата 1.
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
