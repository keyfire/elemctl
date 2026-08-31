"""Deploy: build -> upload -> apply -> restart -> verify.

The defining trait of the platform: when an apply fails, it silently rolls the
application back to the previous build and starts it – the Running status says
nothing about success. That is why the deploy report rests on three checks:
application tasks that failed after the deploy started, a comparison of the
version actually applied and an informational HTTP request to the application uri.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import i18n
from .build import PROJECT_FILES, build_assembly
from .client import FAILED_TASK_STATUSES, extract_assembly_id
from .errors import ElemctlError
from .schema import narrowing_in_tree

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

    problems – the refusal texts as the platform gave them, newlines and tabs
    included; to_dict adds problems-lines, the same thing broken into plain lines.
    A JSON report escapes a multi-line string into \n and \t, and the refusal
    stops being readable exactly where it matters - the object and the keys that
    made the apply fail.

    app_id_source / project_id_source – where the target came from: "flag" – an
    explicit --app-id / --project-id, "env" – ELEMENT_APP_ID / ELEMENT_PROJECT_ID
    of the environment or the .env file. A deploy to the wrong application is the
    cheapest mistake to make and the most expensive to notice, so the report names
    the target and the reason it was chosen rather than the id alone.
    """

    app_id: str = ""
    app_name: str = ""
    app_id_source: str = ""
    project_id: str = ""
    project_id_source: str = ""
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
    # The schema guard's verdict: "clean" - ran and found nothing, "allowed" - narrowings
    # overridden by --allow-data-loss, "skipped:<reason>" - there was nothing to compare
    # against ("skipped:no-commit-id" means the project has no repository link, so the
    # check can never run for it). "" - the guard was not involved (verify without deploy).
    # Named in the report on purpose: a skipped check must not read as a passed one.
    schema_check: str = ""

    def to_dict(self):
        """Render the report as a dict with kebab-case keys (for JSON output)."""
        return {
            "app-id": self.app_id,
            "app-name": self.app_name,
            "app-id-source": self.app_id_source,
            "project-id": self.project_id,
            "project-id-source": self.project_id_source,
            "uri": self.uri,
            "status": self.status,
            "version": self.version,
            "assembly-id": self.assembly_id,
            "applied-version": self.applied_version,
            "applied-version-id": self.applied_version_id,
            "applied": self.applied,
            "uri-status": self.uri_status,
            "problems": list(self.problems),
            "problems-lines": problem_lines(self.problems),
            "ok": self.ok,
            "dirty": None if self.dirty_files is None else bool(self.dirty_files),
            "dirty-files": None if self.dirty_files is None else list(self.dirty_files),
            "schema-check": self.schema_check or None,
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
    app_id_source="",
    project_id_source="",
    allow_data_loss=False,
    log=None,
):
    """The full deploy cycle from sources, verifying that the build really applied.

    log – a callback for progress lines (print, for instance); the library itself
    prints nothing. app_id_source / project_id_source are carried through to the
    report and named in the very first progress line: the target is announced
    BEFORE the build, while there is still time to interrupt a deploy aimed at the
    wrong application.
    """
    log = log or (lambda message: None)
    started_at = datetime.now(timezone.utc)

    log(i18n.t(
        "deploy.target",
        app_id=app_id,
        app_source=_source_label(app_id_source),
        project_id=project_id,
        project_source=_source_label(project_id_source),
    ))

    # The schema guard runs BEFORE the build: a narrowing recreates the data of the
    # object, and refusing here means nothing was built and nothing uploaded.
    changes, blocked_reason = check_destructive_changes(
        client, app_id, project_id, project_dir, log=log
    )
    if changes and not allow_data_loss:
        raise ElemctlError(i18n.t(
            "deploy.destructive-changes",
            count=len(changes),
            changes="; ".join(changes),
        ))
    if changes:
        log(i18n.t("deploy.destructive-allowed", count=len(changes),
                   changes="; ".join(changes)))
        schema_check = "allowed"
    elif blocked_reason:
        # "no-commit-id" is not a version quirk: an assembly gets a commit only from the
        # project's link to its repository, so without the link the guard can NEVER run -
        # that has to be said plainly instead of looking like a passed check.
        key = (
            "deploy.schema-check-no-repo-link"
            if blocked_reason == "no-commit-id"
            else "deploy.schema-check-skipped"
        )
        log(i18n.t(key, reason=blocked_reason))
        schema_check = f"skipped:{blocked_reason}"
    else:
        schema_check = "clean"

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
    if result.skipped_files:
        # Said BEFORE the apply: the platform reports the same thing as
        # "Неизвестный ресурс", but only after the upload and with no file named.
        log(i18n.t(
            "deploy.skipped-files",
            count=len(result.skipped_files),
            files=_shorten_list(result.skipped_files),
        ))
    if result.clients_without_description:
        # Also before the apply: a client with no description is an apply failure,
        # and a failed apply rolls the application back without naming the cause.
        log(i18n.t(
            "deploy.soap-without-description",
            count=len(result.clients_without_description),
            files=_shorten_list(result.clients_without_description),
        ))

    # The branch and the commit travel INSIDE the archive (the build wrote the manifest);
    # the upload method has no such parameters and the server ignores them when sent -
    # the commit of an assembly card comes from the project's repository link.
    response = client.upload_assembly(result.file.read_bytes(), project_id=project_id)
    assembly_id = extract_assembly_id(response) or ""
    log(i18n.t("deploy.uploaded", id=assembly_id or i18n.t("deploy.unknown")))

    if assembly_id:
        client.apply_build(app_id, image_id=assembly_id, log=log)
    else:
        # The response carries no assembly id: apply by project and version.
        client.apply_build(
            app_id, project_id=project_id, assembly_version=result.version, log=log
        )
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
    report.schema_check = schema_check
    report.app_id_source = app_id_source or ""
    report.project_id = str(project_id or "")
    report.project_id_source = project_id_source or ""
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


def _applied_commit(client, app_id, project_id):
    """The commit the currently applied build was made from ("" when unknown).

    The Console API does NOT hand out the contents of an assembly - there is no
    download method - so an archive-to-archive comparison is impossible. What the
    assembly card does carry is commit-id, which makes the sources of that commit
    the thing to compare against.
    """
    try:
        card = client.get_app(app_id) or {}
        applied_id = str((card.get("source") or {}).get("project-version-id") or "")
        if not applied_id:
            return ""
        for assembly in client.list_assemblies(project_id):
            if isinstance(assembly, dict) and str(assembly.get("id") or "") == applied_id:
                return str(assembly.get("commit-id") or "")
    except Exception:
        # The guard is auxiliary: no failure of it may get in the way of a deploy.
        return ""
    return ""


def _git_show(project_dir, commit, relative_path):
    """The text of a file at a commit, or None when git cannot produce it."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_dir), "show", f"{commit}:./{relative_path}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def check_destructive_changes(client, app_id, project_id, project_dir, log=None):
    """The narrowings between the sources on disk and the applied build's commit.

    Returns (changes, blocked_reason). blocked_reason is filled when there is
    nothing to compare against - no commit-id on the card, or the commit is not in
    the local repository. That case must NOT block a deploy: the guard says it
    cannot judge and steps aside, because being unable to compare is not evidence
    of danger.
    """
    log = log or (lambda message: None)
    if not project_dir:
        return [], "no-project-dir"
    commit = _applied_commit(client, app_id, project_id)
    if not commit:
        return [], "no-commit-id"
    if all(_git_show(project_dir, commit, name) is None for name in PROJECT_FILES):
        return [], "commit-unavailable"
    changes = narrowing_in_tree(
        project_dir, lambda relative: _git_show(project_dir, commit, relative)
    )
    return changes, ""


def _source_label(source):
    """The human label of where a target id came from ("" – it was not tracked)."""
    if source == "flag":
        return i18n.t("deploy.source-flag")
    if source == "env":
        return i18n.t("deploy.source-env")
    return i18n.t("deploy.unknown")


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
        app_name=str(card.get("name") or ""),
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


def problem_lines(problems):
    """The refusal texts broken into plain lines, with tabs expanded.

    The platform hands a refusal over as ONE string carrying newlines and tabs,
    and json.dumps turns those into escape sequences. Lines survive the trip
    through JSON as they are, so the report carries both: the raw texts and this.
    """
    lines = []
    for problem in problems or []:
        for raw in str(problem).expandtabs(4).splitlines():
            text = raw.rstrip()
            if text:
                lines.append(text)
    return lines


def _log_outcome(report, log):
    if report.ok:
        log(i18n.t("deploy.verify-passed"))
    else:
        # The first line of a problem is marked, the rest are indented under it:
        # a refusal several lines long has to stay one readable block.
        for problem in report.problems:
            lines = problem_lines([problem])
            if not lines:
                continue
            log(i18n.t("deploy.problem", problem=lines[0]))
            for extra in lines[1:]:
                log("    " + extra)
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
