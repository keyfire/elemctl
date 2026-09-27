"""Deploy: build -> upload -> apply -> restart -> verify.

The defining trait of the platform: when an apply fails, it silently rolls the
application back to the previous build and starts it - the Running status says
nothing about success. That is why the deploy report rests on three checks:
application tasks that failed after the deploy started, a comparison of the
version actually applied and an informational HTTP request to the application uri.
"""

from __future__ import annotations

import contextlib
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import i18n
from .build import PROJECT_FILES, build_assembly, find_project_dir, read_project_meta
from .client import (
    ASSEMBLY_ID_KEYS,
    FAILED_TASK_STATUSES,
    SERVER_START_TIMEOUT,
    assembly_label,
    extract_assembly_id,
)
from .errors import ApiError, ElemctlError, ServerStartingError
from .probe import server_log_hint
from .registry import remember_build, remembered_uploads
from .schema import review_tree
from .versions import server_may_keep

__all__ = ["FAILED_TASK_STATUSES"]  # the name stays where importers already expect it


@dataclass
class DeployReport:
    """Deploy report.

    applied: True - the version matched, False - it did not (this looks like a
    rollback), None - the actual version could not be determined. ok - the final
    verdict: no problems and no proven rollback. dirty_files - the uncommitted
    changes of the project directory at build time (None - git is unavailable or
    no build ran in this invocation): a build captures the disk as it is, so any
    divergence from HEAD has to be visible in the report.

    problems - the refusal texts as the platform gave them, newlines and tabs
    included; to_dict adds problems-lines, the same thing broken into plain lines.
    A JSON report escapes a multi-line string into \n and \t, and the refusal
    stops being readable exactly where it matters - the object and the keys that
    made the apply fail.

    app_id_source / project_id_source - where the target came from: "flag" - an
    explicit --app-id / --project-id, "env" - ELEMENT_APP_ID / ELEMENT_PROJECT_ID
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
    # The version the server gave the uploaded build, and whether it differs from the version
    # of the archive (None - the upload answered without one). A build uploaded into a project
    # is numbered by the server: the Версия of the project descriptor and the highest number
    # of that base plus one, whatever the archive said - `1.0.0-i1` lands as `1.0.0-6`.
    assembly_version: str = ""
    renumbered: bool | None = None
    applied_version: str = ""
    applied_version_id: str = ""
    applied: bool | None = None
    uri_status: int | None = None
    problems: list = field(default_factory=list)
    ok: bool = False
    dirty_files: list | None = None
    # The schema guard's verdict: "clean" - ran and found nothing, "warned" - found only
    # removals, which are named in schema_warnings and do not stop a deploy, "allowed" -
    # what the guard refuses (a narrowing, an element with data of its own removed whole)
    # let through by --allow-data-loss, "skipped:<reason>" - there was nothing to
    # compare against (the reasons are listed at review_schema). "" - the guard was not
    # involved (verify without deploy). Named in the report on purpose: a skipped check
    # must not read as a passed one.
    schema_check: str = ""
    # What the apply took away: the attributes, resources and tabular parts the sources no
    # longer have, one line each. Their data went with them; the server does not ask.
    schema_warnings: list = field(default_factory=list)
    # The commit the guard compared the sources against, and where it came from: "platform" -
    # the card of the applied build, "registry" - the local registry of uploads, which
    # remembers the commit of a build whose card carries none. "" when nothing was compared.
    schema_commit: str = ""
    schema_commit_source: str = ""
    # Where to look when a task was refused without a compilation error in its text: the
    # log of the server (probe.server_log_hint). "" when the report itself names the cause.
    hint: str = ""

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
            "assembly-version": self.assembly_version or None,
            "renumbered": self.renumbered,
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
            "schema-warnings": list(self.schema_warnings),
            "schema-commit": self.schema_commit or None,
            "schema-commit-source": self.schema_commit_source or None,
            "hint": self.hint or None,
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
    server_start_timeout=SERVER_START_TIMEOUT,
    log=None,
):
    """The full deploy cycle from sources, verifying that the build really applied.

    log - a callback for progress lines (print, for instance); the library itself
    prints nothing. app_id_source / project_id_source are carried through to the
    report and named in the very first progress line: the target is announced
    BEFORE the build, while there is still time to interrupt a deploy aimed at the
    wrong application. server_start_timeout - how many seconds a server whose console
    is still starting is waited out, at any step of the cycle; 0 fails at once.
    """
    log = log or (lambda message: None)
    with server_wait(client, server_start_timeout, log):
        return _deploy_from_sources(
            client,
            app_id,
            project_id,
            project_dir=project_dir,
            output_dir=output_dir,
            version=version,
            branch=branch,
            commit=commit,
            app_id_source=app_id_source,
            project_id_source=project_id_source,
            allow_data_loss=allow_data_loss,
            log=log,
        )


def server_wait(client, timeout, log=None):
    """The block inside which the client waits out a starting server.

    A client without waiting_for_server - a stand-in of the tests or of a caller that
    brings its own - gets an empty block rather than a failure: the wait is a courtesy
    of the real client, not a requirement of the deploy.
    """
    waiting = getattr(client, "waiting_for_server", None)
    if waiting is None:
        return contextlib.nullcontext()
    return waiting(timeout, log=log)


def _deploy_from_sources(
    client,
    app_id,
    project_id,
    *,
    project_dir,
    output_dir,
    version,
    branch,
    commit,
    app_id_source,
    project_id_source,
    allow_data_loss,
    log,
):
    started_at = datetime.now(timezone.utc)

    log(i18n.t(
        "deploy.target",
        app_id=app_id,
        app_source=_source_label(app_id_source),
        project_id=project_id,
        project_source=_source_label(project_id_source),
    ))

    # The schema guard runs BEFORE the build: a narrowing recreates the data of the
    # object, a removed catalog takes its table away, and refusing here means nothing was
    # built and nothing uploaded. A removal of a field is named here too, while the deploy
    # can still be interrupted.
    verdict = review_schema(client, app_id, project_id, project_dir)
    if verdict.commit_source == "registry":
        # The commit is this machine's memory of the upload, not the platform's record, so
        # the report says which one the sources were compared against.
        log(i18n.t(
            "deploy.schema-commit-from-registry-dirty" if verdict.commit_dirty
            else "deploy.schema-commit-from-registry",
            commit=verdict.commit,
            build=verdict.build,
        ))
    for removal in verdict.removals:
        log(i18n.t("deploy.schema-removal", change=removal))
    if verdict.changes and not allow_data_loss:
        raise ElemctlError(i18n.t(
            "deploy.destructive-changes",
            count=len(verdict.changes),
            changes="; ".join(verdict.changes),
        ))
    if verdict.changes:
        log(i18n.t("deploy.destructive-allowed", count=len(verdict.changes),
                   changes="; ".join(verdict.changes)))
        schema_check = "allowed"
    elif verdict.skipped:
        log(_skip_message(verdict, project_id))
        schema_check = f"skipped:{verdict.skipped}"
    elif verdict.removals:
        schema_check = "warned"
    else:
        schema_check = "clean"

    # The build version: either explicit or auto-incremented from the project's last build
    # OF THE SAME BASE VERSION - a bumped project starts counting from 1 again. The server
    # numbers the upload by the same rule, so an explicit version it cannot keep is said
    # now, before anything is built, rather than discovered on the card afterwards.
    base_version = read_project_meta(
        find_project_dir(project_dir) if project_dir else find_project_dir()
    ).base_version
    last_version = ""
    if version and version.strip():
        if not server_may_keep(version, base_version):
            log(i18n.t("deploy.version-not-kept", version=version.strip(), base=base_version))
    else:
        latest = client.latest_assembly(project_id, base_version=base_version)
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

    # The commit goes along as `commit-id`, and the server puts it on the assembly card:
    # that is what the schema guard of the next deploy compares against. The branch, the
    # state of the tree and the directory the platform does not keep, so the local registry
    # of uploads does - written right after the upload, whatever the apply does next.
    response = client.upload_assembly(
        result.file.read_bytes(), project_id=project_id, commit_id=result.commit or None
    )
    assembly_id = extract_assembly_id(response) or ""
    log(i18n.t("deploy.uploaded", id=assembly_id or i18n.t("deploy.unknown")))
    assembly_version = uploaded_version(response)
    if assembly_version and assembly_version != result.version:
        log(i18n.t("deploy.renumbered", built=result.version, given=assembly_version))
    warning = remember_build(
        result, response=response, project_id=project_id, stand=_stand(client), command="deploy"
    )
    if warning:
        log(warning)

    if assembly_id:
        client.apply_build(app_id, image_id=assembly_id, log=log)
    else:
        # The response carries no assembly id: apply by project and version - the version
        # the server gave the build, when it said which.
        client.apply_build(
            app_id, project_id=project_id,
            assembly_version=assembly_version or result.version, log=log,
        )
    log(i18n.t("deploy.apply-started"))

    try:
        card = client.ensure_running(app_id, log=log)
    except ApiError as error:
        _add_server_log_hint(error)
        raise
    log(i18n.t("deploy.running-verifying"))

    report = _verify(
        client,
        app_id,
        card=card,
        expected_version=result.version,
        expected_assembly_id=assembly_id,
        since=started_at,
        uploaded_version=assembly_version,
    )
    report.assembly_id = assembly_id
    report.assembly_version = assembly_version
    report.renumbered = (assembly_version != result.version) if assembly_version else None
    report.dirty_files = result.dirty_files
    report.schema_check = schema_check
    report.schema_warnings = list(verdict.removals)
    report.schema_commit = verdict.commit
    report.schema_commit_source = verdict.commit_source
    report.app_id_source = app_id_source or ""
    report.project_id = str(project_id or "")
    report.project_id_source = project_id_source or ""
    _log_outcome(report, log)
    return report


def verify_deploy(client, app_id, *, expected_version="", expected_assembly_id="", since=None, log=None):
    """A standalone check that the build applied (without deploying).

    since - the moment before which task failures are ignored (old failures from
    the history must not spoil the verdict). expected_assembly_id - the id of the
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


@dataclass
class SchemaVerdict:
    """What the schema guard found, or why it could not look.

    changes - what a deploy refuses without --allow-data-loss: the narrowings and the
    elements with data of their own removed whole; removals - what the apply takes away,
    named without stopping it; skipped - why nothing was compared
    ("" when it was), with detail naming what could not be read or found. commit - what the
    sources were compared against, commit_source - where it came from ("platform" or
    "registry"), commit_dirty - the registry's word on whether that build was made from a
    tree with uncommitted changes (None when it does not know), build - the applied build
    as a person reads it.
    """

    changes: list = field(default_factory=list)
    removals: list = field(default_factory=list)
    skipped: str = ""
    detail: str = ""
    commit: str = ""
    commit_source: str = ""
    commit_dirty: bool | None = None
    build: str = ""


@dataclass
class _AppliedCommit:
    """The commit of the applied build, where it came from, or why it is not known.

    reason is "" when the commit is known; otherwise it names the way of not having it, and
    detail says what could not be read or found. build names the applied build for a
    person: its id with the version beside it.
    """

    commit: str = ""
    source: str = ""
    reason: str = ""
    detail: str = ""
    build: str = ""
    dirty: bool | None = None


def _applied_commit(client, app_id, project_id):
    """The commit the applied build was made from, or why it is not known.

    Returns an _AppliedCommit. The Console API does NOT hand out the contents of an
    assembly - there is no download method - so an archive-to-archive comparison is
    impossible. What the assembly card does carry is commit-id, which makes the sources of
    that commit the thing to compare against. A card without one - a build that created its
    project, or one uploaded before elemctl sent the commit - is looked up in the local
    registry of uploads: a build this machine uploaded is remembered with its commit. Every
    way of not having a commit is a reason of its own: a card that could not be read used to
    be reported as a build without a commit, and the report then explained a cause that was
    not there.
    """
    try:
        card = client.get_app(app_id) or {}
    except ServerStartingError:
        # Not a failure of the guard: the server refuses everything for now, and the deploy
        # waits it out or stops on it - swallowed here, it read as a build without a commit.
        raise
    except Exception as error:
        # The guard is auxiliary: no failure of it may get in the way of a deploy.
        return _AppliedCommit(reason="read-failed", detail=str(error))
    applied_id = str((card.get("source") or {}).get("project-version-id") or "")
    if not applied_id:
        return _AppliedCommit(reason="no-applied-build")
    try:
        assemblies = client.list_assemblies(project_id)
    except ServerStartingError:
        raise
    except Exception as error:
        return _AppliedCommit(reason="read-failed", detail=str(error))
    for assembly in assemblies:
        if not isinstance(assembly, dict):
            continue
        if applied_id not in {str(assembly.get(key) or "") for key in ASSEMBLY_ID_KEYS}:
            continue
        version = assembly.get("assembly-version") or assembly.get("project-version")
        build = assembly_label(applied_id, version)
        commit = str(assembly.get("commit-id") or "")
        if commit:
            return _AppliedCommit(commit=commit, source="platform", build=build)
        remembered = remembered_uploads([applied_id]).get(applied_id) or {}
        commit = str(remembered.get("commit") or "")
        if commit:
            dirty = remembered.get("dirty")
            return _AppliedCommit(
                commit=commit, source="registry", build=build,
                dirty=None if dirty is None else bool(dirty),
            )
        return _AppliedCommit(reason="no-commit-id", detail=build, build=build)
    return _AppliedCommit(reason="applied-build-not-listed", detail=applied_id)


def _git_show(project_dir, commit, relative_path):
    """The text of a file at a commit, or None when git cannot produce it."""
    try:
        # stdin=DEVNULL: a git that inherits the stdin of the MCP server cannot
        # reach its own exit on Windows - see git_dirty_files in build.py.
        completed = subprocess.run(
            ["git", "-C", str(project_dir), "show", f"{commit}:./{relative_path}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def _git_files(project_dir, commit):
    """The files of the project directory at a commit, relative to it; None when git cannot say.

    `ls-tree` run inside the directory lists what lies under it, with the paths relative to
    it - the same paths `_git_show` reads - and `-z` hands a Cyrillic name over as it is
    rather than quoted.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_dir), "ls-tree", "-r", "-z", "--name-only", commit],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return [name for name in completed.stdout.split("\0") if name]


def review_schema(client, app_id, project_id, project_dir):
    """The schema guard: the sources on disk against the commit of the applied build.

    Returns a SchemaVerdict. When there is nothing to compare against, skipped names
    why, and that must NOT block a deploy: the guard says it cannot judge and steps
    aside, because being unable to compare is not evidence of danger. The reasons:
    "no-project-dir" - no project directory to read; "read-failed" - the application
    card or the build list did not come; "no-applied-build" - the card names no build;
    "applied-build-not-listed" - the applied build is not among the project's builds;
    "no-commit-id" - neither the card of the applied build nor the local registry of
    uploads knows its commit; "commit-unavailable" - the local repository does not have
    that commit.

    The project directory is found the way the build finds it: a deploy without an
    explicit one used to skip the guard as "no-project-dir" and then build that very
    directory.
    """
    try:
        directory = find_project_dir(project_dir) if project_dir else find_project_dir()
    except ElemctlError:
        return SchemaVerdict(skipped="no-project-dir")
    applied = _applied_commit(client, app_id, project_id)
    if applied.reason:
        return SchemaVerdict(skipped=applied.reason, detail=applied.detail)
    commit = applied.commit
    if all(_git_show(directory, commit, name) is None for name in PROJECT_FILES):
        return SchemaVerdict(skipped="commit-unavailable", detail=commit)
    review = review_tree(
        directory,
        lambda relative: _git_show(directory, commit, relative),
        # The files of the applied commit: what the disk no longer has cannot be read off
        # the disk, and a catalog whose description is gone takes its table with it.
        lambda: _git_files(directory, commit),
    )
    return SchemaVerdict(
        changes=review.changes,
        removals=review.removals,
        commit=commit,
        commit_source=applied.source,
        commit_dirty=applied.dirty,
        build=applied.build,
    )


def _skip_message(verdict, project_id):
    """The progress line saying why the schema was not compared."""
    key = f"deploy.schema-skipped-{verdict.skipped}"
    message = i18n.t(key, detail=verdict.detail, project=project_id)
    if message == key:  # a reason without a wording of its own
        message = i18n.t("deploy.schema-check-skipped", reason=verdict.skipped)
    return message


def _add_server_log_hint(error):
    """Name the server log on an Error status whose text holds no compilation error.

    The apply that leaves the application in Error ends the deploy with an error rather
    than with a report, and the text may carry nothing but "Contact administrator for
    details". The hint goes into the error and into its text as well, the way the hint of
    a refused delete does: the MCP tool shows the text of an error alone.
    """
    body = getattr(error, "body", None)
    if error.hint or not (isinstance(body, dict) and body.get("status") == "Error"):
        return
    hint = server_log_hint([error.message])
    if hint:
        error.hint = hint
        error.message += " – " + hint
        error.args = (error.message,)


def uploaded_version(response):
    """The version the server gave an uploaded build, "" when its answer does not say.

    An upload into a project answers with the card of the build, and its assembly-version is
    the number the server handed out. An upload that creates or finds its project by the
    vendor and the name answers without one: that upload keeps the version of the archive.
    """
    answer = response if isinstance(response, dict) else {}
    return str(answer.get("assembly-version") or answer.get("project-version") or "")


def _stand(client):
    """The base address of the stand the client talks to ("" for a stand-in without one)."""
    return str(getattr(getattr(client, "config", None), "base_url", "") or "")


def _source_label(source):
    """The human label of where a target id came from ("" - it was not tracked)."""
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


def _verify(
    client, app_id, *, card, expected_version, since, expected_assembly_id="", uploaded_version=""
):
    """The verdict on an apply; uploaded_version - the version the server gave the build.

    expected_version is what the report calls the build by. The fallback comparison by the
    version string takes uploaded_version when it is known: the server numbers a build
    uploaded into a project itself, and the version of the archive may be on no card at all.
    """
    problems = []
    refusals = []

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
        refusals.append(str(message))
        problems.append(i18n.t(
            "deploy.task-failed", label=label, status=status, message=message
        ))

    # 2. Compare the build actually applied with the uploaded one. The reliable
    # signal is source.project-version-id being equal to the id of the uploaded
    # build: the version string will not do, because the server numbers a build
    # uploaded into a project itself (archive 1.0-1139 is listed as 1.0-3) and
    # comparing the strings used to report a false rollback. The version string
    # stays as a fallback check for when the build id is unknown, and it is the
    # server's version of the build whenever the upload said which.
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
    elif (uploaded_version or expected_version) and applied_version:
        applied = applied_version == (uploaded_version or expected_version)
        if not applied:
            problems.append(i18n.t(
                "deploy.version-mismatch",
                applied=applied_version,
                expected=uploaded_version or expected_version,
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
        # A refused task that names no file leaves the report with nothing to act on:
        # the cause is in the log of the server, and the hint says where.
        hint=server_log_hint(refusals),
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
        # The last lines are the ones read. A passed verification says the build is in
        # place, and on its own it read as if the schema had been checked as well.
        if report.schema_check.startswith("skipped:"):
            log(i18n.t(
                "deploy.schema-not-checked", reason=report.schema_check.split(":", 1)[1]
            ))
        if report.schema_warnings:
            log(i18n.t("deploy.schema-removed-summary", count=len(report.schema_warnings)))
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
        if report.hint:
            log(report.hint)
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
