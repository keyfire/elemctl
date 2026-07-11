"""Деплой: сборка -> загрузка -> применение -> перезапуск -> проверка.

Главная особенность платформы: при ошибке применения она молча откатывает
приложение на предыдущую сборку и запускает его – статус Running ничего не
говорит об успехе. Поэтому отчёт деплоя строится по трём проверкам:
задачи приложения с ошибками после начала деплоя, сверка фактически
применённой версии и информационный HTTP-запрос по uri приложения.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import i18n
from .build import build_assembly
from .client import extract_assembly_id

# Статусы задач приложения, означающие ошибку (сравнение без учёта регистра).
FAILED_TASK_STATUSES = {"error", "failed"}


@dataclass
class DeployReport:
    """Отчёт деплоя.

    applied: True – версия совпала, False – не совпала (похоже на откат),
    None – фактическую версию определить не удалось. ok – итоговый вердикт:
    нет проблем и нет доказанного отката.
    """

    app_id: str = ""
    uri: str = ""
    status: str = ""
    version: str = ""
    assembly_id: str = ""
    applied_version: str = ""
    applied: bool | None = None
    uri_status: int | None = None
    problems: list = field(default_factory=list)
    ok: bool = False

    def to_dict(self):
        """Представить отчёт словарём с ключами в kebab-case (для JSON-вывода)."""
        return {
            "app-id": self.app_id,
            "uri": self.uri,
            "status": self.status,
            "version": self.version,
            "assembly-id": self.assembly_id,
            "applied-version": self.applied_version,
            "applied": self.applied,
            "uri-status": self.uri_status,
            "problems": list(self.problems),
            "ok": self.ok,
        }


def deploy_from_sources(
    client,
    app_id,
    project_id,
    *,
    project_dir=None,
    output_dir=None,
    version="",
    branch=None,
    commit=None,
    commit_message="",
    log=None,
):
    """Полный цикл деплоя из исходников с проверкой фактического применения.

    log – callback для строк прогресса (например print); библиотека сама
    ничего не печатает.
    """
    log = log or (lambda message: None)
    started_at = datetime.now(timezone.utc)

    # Версия сборки: явная либо автоинкремент от последней сборки проекта.
    last_version = ""
    if not version:
        latest = client.latest_assembly(project_id)
        if latest:
            last_version = str(latest.get("assembly-version") or "")

    result = build_assembly(
        project_dir,
        output_dir=output_dir or tempfile.mkdtemp(prefix="elemctl-build-"),
        version=version,
        last_build_version=last_version,
        branch=branch,
        commit=commit,
    )
    log(i18n.t("deploy.built", file=result.file, version=result.version))

    response = client.upload_assembly(
        result.file.read_bytes(),
        project_id=project_id,
        branch_name=result.branch or None,
        commit_id=result.commit or None,
        commit_message=commit_message or None,
    )
    assembly_id = extract_assembly_id(response) or ""
    log(i18n.t("deploy.uploaded", id=assembly_id or i18n.t("deploy.unknown")))

    if assembly_id:
        client.apply_build(app_id, image_id=assembly_id)
    else:
        # Ответ без id сборки: применяем по проекту и версии.
        client.apply_build(app_id, project_id=project_id, assembly_version=result.version)
    log(i18n.t("deploy.apply-started"))

    card = client.ensure_running(app_id, log=log)
    log(i18n.t("deploy.running-verifying"))

    report = _verify(
        client,
        app_id,
        card=card,
        expected_version=result.version,
        since=started_at,
    )
    report.assembly_id = assembly_id
    _log_outcome(report, log)
    return report


def verify_deploy(client, app_id, *, expected_version="", since=None, log=None):
    """Самостоятельная проверка применения (без деплоя).

    since – момент, раньше которого ошибки задач не учитываются (старые
    ошибки из истории не должны портить вердикт).
    """
    log = log or (lambda message: None)
    report = _verify(client, app_id, card=None, expected_version=expected_version, since=since)
    _log_outcome(report, log)
    return report


# -- внутреннее ---------------------------------------------------------------


def _verify(client, app_id, *, card, expected_version, since):
    problems = []

    # 1. Задачи приложения со статусами Error/Failed после начала деплоя.
    for task in client.list_app_tasks(app_id):
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "")
        if status.lower() not in FAILED_TASK_STATUSES:
            continue
        task_started = _parse_datetime(task.get("start-date"))
        if since is not None and task_started is not None and task_started < since:
            continue
        label = task.get("operation-type") or task.get("id") or "задача"
        message = task.get("error-message") or i18n.t("deploy.no-error-text")
        problems.append(f"задача {label} завершилась со статусом {status}: {message}")

    # 2. Сверка фактически применённой версии с загруженной.
    if card is None:
        card = client.get_app(app_id) or {}
    source = card.get("source") or {}
    applied_version = str(source.get("project-version") or "")
    applied = None
    if expected_version and applied_version:
        applied = applied_version == expected_version
        if not applied:
            problems.append(
                f"применённая версия {applied_version} не совпадает с загруженной "
                f"{expected_version} – похоже, платформа откатила применение"
            )

    # 3. Информационный GET по uri приложения (401/403 нормальны).
    uri = str(card.get("uri") or "")
    uri_status = client.check_uri(uri) if uri else None

    report = DeployReport(
        app_id=str(app_id),
        uri=uri,
        status=str(card.get("status") or ""),
        version=expected_version or "",
        applied_version=applied_version,
        applied=applied,
        uri_status=uri_status,
        problems=problems,
    )
    report.ok = not problems and applied is not False
    return report


def _log_outcome(report, log):
    if report.ok:
        log(i18n.t("deploy.verify-passed"))
    else:
        for problem in report.problems:
            log(i18n.t("deploy.problem", problem=problem))
        log(i18n.t("deploy.verify-failed"))


def _parse_datetime(value):
    """Разобрать дату ISO 8601 (допускается суффикс Z); наивную считать UTC."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
