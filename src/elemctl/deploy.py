"""Deploy: build -> upload -> apply -> restart -> verify.

The defining trait of the platform: when an apply fails, it silently rolls the
application back to the previous build and starts it – the Running status says
nothing about success. That is why the deploy report rests on three checks:
application tasks that failed after the deploy started, a comparison of the
version actually applied and an informational HTTP request to the application uri.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import i18n
from .build import build_assembly
from .client import FAILED_TASK_STATUSES, extract_assembly_id

__all__ = ["FAILED_TASK_STATUSES"]  # the name stays where importers already expect it


@dataclass
class DeployReport:
    """Deploy report.

    applied: True – the version matched, False – it did not (this looks like a
    rollback), None – the actual version could not be determined. ok – the final
    verdict: no problems and no proven rollback. dirty_files – the uncommitted
    changes of the project directory at build time (None – git is unavailable or
    no build ran in this invocation): a build captures the disk as it is, so any
    divergence from HEAD has to be visible in the report.
    """

    app_id: str = ""
    uri: str = ""
    status: str = ""
    version: str = ""
    assembly_id: str = ""
    applied_version: str = ""
    applied_version_id: str = ""
    applied: bool | None = None
    uri_status: int | None = None
    problems: list = field(default_factory=list)
    ok: bool = False
    dirty_files: list | None = None

    def to_dict(self):
        """Render the report as a dict with kebab-case keys (for JSON output)."""
        return {
            "app-id": self.app_id,
            "uri": self.uri,
            "status": self.status,
            "version": self.version,
            "assembly-id": self.assembly_id,
            "applied-version": self.applied_version,
            "applied-version-id": self.applied_version_id,
            "applied": self.applied,
            "uri-status": self.uri_status,
            "problems": list(self.problems),
            "ok": self.ok,
            "dirty": None if self.dirty_files is None else bool(self.dirty_files),
            "dirty-files": None if self.dirty_files is None else list(self.dirty_files),
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
    """The full deploy cycle from sources, verifying that the build really applied.

    log – a callback for progress lines (print, for instance); the library itself
    prints nothing.
    """
    log = log or (lambda message: None)
    started_at = datetime.now(timezone.utc)

    # The build version: either explicit or auto-incremented from the project's last build.
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
    if result.dirty_files:
        log(i18n.t(
            "deploy.dirty-tree",
            count=len(result.dirty_files),
            files=_shorten_list(result.dirty_files),
        ))

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
        # The response carries no assembly id: apply by project and version.
        client.apply_build(app_id, project_id=project_id, assembly_version=result.version)
    log(i18n.t("deploy.apply-started"))

    card = client.ensure_running(app_id, log=log)
    log(i18n.t("deploy.running-verifying"))

    report = _verify(
        client,
        app_id,
        card=card,
        expected_version=result.version,
        expected_assembly_id=assembly_id,
        since=started_at,
    )
    report.assembly_id = assembly_id
    report.dirty_files = result.dirty_files
    _log_outcome(report, log)
    return report


def verify_deploy(client, app_id, *, expected_version="", expected_assembly_id="", since=None, log=None):
    """A standalone check that the build applied (without deploying).

    since – the moment before which task failures are ignored (old failures from
    the history must not spoil the verdict). expected_assembly_id – the id of the
    uploaded build: comparing by it is reliable, unlike the version string.
    """
    log = log or (lambda message: None)
    report = _verify(
        client,
        app_id,
        card=None,
        expected_version=expected_version,
        expected_assembly_id=expected_assembly_id,
        since=since,
    )
    _log_outcome(report, log)
    return report


# -- internals ----------------------------------------------------------------


def _shorten_list(items, limit=5):
    """The first limit items joined by commas; the tail as a counter."""
    shown = ", ".join(str(item) for item in items[:limit])
    rest = len(items) - limit
    if rest > 0:
        shown += i18n.t("deploy.and-more", count=rest)
    return shown


def _verify(client, app_id, *, card, expected_version, since, expected_assembly_id=""):
    problems = []

    # 1. Application tasks in status Error/Failed raised after the deploy started.
    for task in client.list_app_tasks(app_id):
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "")
        if status.lower() not in FAILED_TASK_STATUSES:
            continue
        task_started = _parse_datetime(task.get("start-date"))
        if since is not None and task_started is not None and task_started < since:
            continue
        label = task.get("operation-type") or task.get("id") or i18n.t("deploy.task")
        message = task.get("error-message") or i18n.t("deploy.no-error-text")
        problems.append(i18n.t(
            "deploy.task-failed", label=label, status=status, message=message
        ))

    # 2. Compare the build actually applied with the uploaded one. The reliable
    # signal is source.project-version-id being equal to the id of the uploaded
    # build: the version string will not do, because a freshly created application
    # numbers its versions from scratch (archive 1.0-1139 is applied as 1.0-3) and
    # comparing the strings used to report a false rollback. The version string
    # stays as a fallback check for when the build id is unknown.
    if card is None:
        card = client.get_app(app_id) or {}
    source = card.get("source") or {}
    applied_version = str(source.get("project-version") or "")
    applied_version_id = str(source.get("project-version-id") or "")
    applied = None
    if expected_assembly_id and applied_version_id:
        applied = applied_version_id == expected_assembly_id
        if not applied:
            problems.append(i18n.t(
                "deploy.assembly-mismatch",
                applied=applied_version_id,
                expected=expected_assembly_id,
            ))
    elif expected_version and applied_version:
        applied = applied_version == expected_version
        if not applied:
            problems.append(i18n.t(
                "deploy.version-mismatch",
                applied=applied_version,
                expected=expected_version,
            ))

    # 3. An informational GET to the application uri (401/403 are fine).
    uri = str(card.get("uri") or "")
    uri_status = client.check_uri(uri) if uri else None

    report = DeployReport(
        app_id=str(app_id),
        uri=uri,
        status=str(card.get("status") or ""),
        version=expected_version or "",
        applied_version=applied_version,
        applied_version_id=applied_version_id,
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
    """Parse an ISO 8601 date (a Z suffix is allowed); treat a naive one as UTC."""
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
