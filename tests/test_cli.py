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


def test_help_text_follows_lang_flag(capsys):
    """--lang переводит и текст справки (--help), а не только рантайм-ошибки: язык
    определяется до сборки парсера. Проверяем оба направления явным флагом – это не
    зависит от локали машины. conftest закрепил ru; восстановим его после."""
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
        def find_app(self, name, *, include_deleted=False):
            if name == "demo-app":
                return {"id": "app-42", "display-name": "demo-app"}
            return None

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())

    rc = cli.main(["apps", "find", "demo-app"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"id": "app-42", "found": True}

    # Отсутствие приложения – штатный ответ: код возврата 0, признак несёт поле found.
    rc = cli.main(["apps", "find", "нет-такого"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"id": None, "found": False}


def test_apps_find_request_failure_is_an_error(monkeypatch, capsys):
    """Сбой запроса отличим от "не найдено": ненулевой код и error в stderr."""

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
    """По умолчанию удалённое приложение не находится; --include-deleted его возвращает."""

    class FakeClient:
        def find_app(self, name, *, include_deleted=False):
            # Приложение есть в списке платформы, но удалено: без флага его нет.
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
    """Существующее приложение не пересоздаётся: created=false, create_app не вызывается."""

    class FakeClient:
        def find_app(self, name, *, include_deleted=False):
            return {"id": "app-7", "display-name": name}

        def create_app(self, *args, **kwargs):
            raise AssertionError("создание не должно вызываться для существующего приложения")

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())

    rc = cli.main(["apps", "ensure", "demo-app", "--version-id", "asm-1"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"id": "app-7", "created": False}


def test_apps_ensure_missing_creates_and_returns_created_true(monkeypatch, capsys):
    """Отсутствующее приложение создаётся: created=true, источником идёт указанная сборка."""

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
            return {"id": "app-new", "display-name": display_name}

    monkeypatch.setattr(cli, "make_client", lambda config: FakeClient())

    rc = cli.main(["apps", "ensure", "site-new", "--version-id", "asm-9"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"id": "app-new", "created": True}


def test_apps_ensure_request_failure_is_an_error(monkeypatch, capsys):
    """Сбой запроса в ensure: код возврата 1, пустой stdout, error в stderr."""

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
    # app-id не задан ни аргументом, ни конфигурацией.
    rc = cli.main(["apps", "get"])
    assert rc == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert "error" in payload
    assert "app-id" in payload["error"]


def test_app_source_error_explains_how_to_get_a_project(capsys):
    """Без источника ошибка подсказывает путь к новому проекту.

    Пустого приложения в Console API нет, а команды создания проекта тоже нет:
    новый проект заводится загрузкой сборки без --project-id. Пока это не было
    написано в ошибке, способ приходилось искать перебором.
    """
    rc = cli.main(["apps", "create", "Имя"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().err)
    assert "builds upload" in payload["error"]
    assert "--project-id" in payload["error"]


class FakeUploadClient:
    """Клиент для тестов builds upload: запоминает вызовы, отвечает карточкой проекта."""

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
    """Собрать синтетический проект в архив; вернуть путь к файлу сборки."""
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
    """Цель из ELEMENT_PROJECT_ID больше не молчаливая: источник в JSON, подсказка в stderr.

    Сборка чужого проекта однажды легла в проект из env – рецепт "upload без
    --project-id создаёт новый проект" не работал, и об этом ничто не сообщало.
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
    # Имя сборки (crm) совпало с именем проекта – предупреждения о несовпадении нет.
    assert "внимание" not in captured.err


def test_builds_upload_new_project_ignores_env(monkeypatch, capsys, project_factory, tmp_path):
    """--new-project отключает env-привязку: платформа создаёт новый проект."""
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
    # Проекта-цели нет – карточка проекта не запрашивается.
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


def test_builds_upload_warns_when_assembly_name_differs(
    monkeypatch, capsys, project_factory, tmp_path
):
    """Несовпадение имени сборки и проекта-цели – предупреждение, но не отказ.

    Панель показывает проект под именем последней залитой сборки: чужая сборка
    молча переименовала проект, и это заметили только по панели.
    """
    archive = _built_archive(project_factory, tmp_path, capsys)
    fake = FakeUploadClient(project_name="Сайт")
    monkeypatch.setattr(cli, "make_client", lambda config: fake)

    rc = cli.main(["builds", "upload", archive, "--project-id", "proj-1"])

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["project-id-source"] == "flag"
    assert fake.get_project_calls == ["proj-1"]
    assert "'crm'" in captured.err
    assert "'Сайт'" in captured.err
    # Цель задана флагом, а не окружением – env-подсказки нет.
    assert "ELEMENT_PROJECT_ID" not in captured.err


def test_builds_upload_name_check_failure_does_not_block(
    monkeypatch, capsys, project_factory, tmp_path
):
    """Сверка имён вспомогательная: сбой карточки проекта не мешает загрузке."""
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


def test_mcp_command_forwards_env_file(monkeypatch, tmp_path):
    """mcp учитывает глобальный --env-file: конфигурация передаётся серверу."""
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
