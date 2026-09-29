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
    EXTENSION_KIND,
    FAILED_TASK_STATUSES,
    SERVER_START_TIMEOUT,
    assembly_label,
    extension_entry,
    extension_label,
    extract_assembly_id,
    is_extension_kind,
)
from .errors import (
    ApiError,
    ElemctlError,
    ServerStartingError,
    TransportError,
    UnknownMethodError,
)
from .probe import server_log_hint
from .registry import ROUTE_PROJECT, remember_build, remembered_uploads, remembered_versions
from .schema import review_tree
from .versions import highest_version, server_may_keep, version_counter

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
    # is numbered by the server: the Версия of the project descriptor and the highest number it
    # has ever given in that base plus one, deleted builds included, whatever the archive said -
    # `1.0.0-i1` lands as `1.0.0-6`.
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
    # The build of an extension: the card of the application names the build of the
    # application alone and keeps naming it after an extension is applied, so the verdict rests
    # on the extensions of the application (Console API 2.1). extension_project_id is the
    # project of the verified build when that project is an extension ("" otherwise), and
    # extension is the entry of `extension-projects` the verdict rests on (None - the
    # application has no such extension, or the server could not list them). applied_version and
    # applied_version_id then name the build the extension runs.
    extension_project_id: str = ""
    extension: dict | None = None

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
            "extension-project-id": self.extension_project_id or None,
            "extension": dict(self.extension) if self.extension is not None else None,
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

    # The build version: either explicit or counted on from the project's last build OF THE
    # SAME BASE VERSION - a bumped project starts counting from 1 again. The server numbers
    # the upload itself, so an explicit version it cannot keep is said now, before anything
    # is built, rather than discovered on the card afterwards. A counted version is a guess
    # at the server's number, and the server counts on from the highest number it has ever
    # given in the base: a deleted build keeps its number, and the list no longer shows it.
    # The local registry of uploads remembers the numbers the uploads of this machine got,
    # so the guess takes the higher of the two. A build uploaded from elsewhere and deleted
    # since is out of sight of both.
    base_version = read_project_meta(
        find_project_dir(project_dir) if project_dir else find_project_dir()
    ).base_version
    explicit = bool(version and version.strip())
    last_version = ""
    if explicit:
        if not server_may_keep(version, base_version):
            log(i18n.t("deploy.version-not-kept", version=version.strip(), base=base_version))
    else:
        latest = client.latest_assembly(project_id, base_version=base_version)
        if latest:
            last_version = str(latest.get("assembly-version") or "")
        remembered = highest_version(remembered_versions(project_id), base_version)
        if version_counter(remembered) > version_counter(last_version):
            log(i18n.t("deploy.count-from-registry", version=remembered))
            last_version = remembered

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
        # An explicit version is the caller's, and the server not keeping it is a warning. A
        # counted one was elemctl's own guess, and the line says what the guess cannot see.
        log(i18n.t(
            "deploy.renumbered" if explicit else "deploy.renumbered-count",
            built=result.version, given=assembly_version,
        ))
    warning = remember_build(
        result, response=response, project_id=project_id, stand=_stand(client),
        command="deploy", app_id=app_id, route=ROUTE_PROJECT,
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

    # The kind of the build goes along: an extension is applied beside the build of the
    # application, and the card goes on naming that one.
    report = _verify(
        client,
        app_id,
        card=card,
        expected_version=result.version,
        expected_assembly_id=assembly_id,
        since=started_at,
        uploaded_version=assembly_version,
        build=_BuiltBuild(
            kind=result.kind, project_id=str(project_id or ""),
            vendor=result.vendor, name=result.name,
        ),
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
    named without stopping it; skipped - why nothing was compared ("" when it was), with
    detail naming what could not be read or found. commit - what the sources were compared
    against, commit_source - where it came from ("platform" or "registry"), commit_dirty -
    the registry's word on whether that build was made from a tree with uncommitted changes
    (None when it does not know), build - the applied build as a person reads it.
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


def _applied_commit(client, app_id, project_id, extension=None):
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

    extension - the (vendor, name) of an extension project, None for any other kind. The card
    of the application names the build of the application alone, so the build an extension
    runs is read off the extensions of the application (Console API 2.1) and found in the
    build list of the project by its version.
    """
    try:
        if extension is None:
            card = client.get_app(app_id) or {}
            applied_id = str((card.get("source") or {}).get("project-version-id") or "")
            applied_version = ""
        else:
            entry = extension_entry(
                client.list_app_extensions(app_id), project_id=project_id,
                vendor=extension[0], name=extension[1],
            )
            if entry is None:
                return _AppliedCommit(reason="no-applied-extension", detail=str(project_id))
            applied_id = ""
            applied_version = str(entry.get("assembly-version") or "")
    except ServerStartingError:
        # Not a failure of the guard: the server refuses everything for now, and the deploy
        # waits it out or stops on it - swallowed here, it read as a build without a commit.
        raise
    except Exception as error:
        # The guard is auxiliary: no failure of it may get in the way of a deploy.
        return _AppliedCommit(reason="read-failed", detail=str(error))
    if not (applied_id or applied_version):
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
        if applied_id:
            if applied_id not in {str(assembly.get(key) or "") for key in ASSEMBLY_ID_KEYS}:
                continue
        elif applied_version not in (
            assembly.get("assembly-version"), assembly.get("project-version")
        ):
            continue
        else:
            applied_id = str(extract_assembly_id(assembly) or "")
            if not applied_id:
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
    return _AppliedCommit(
        reason="applied-build-not-listed", detail=applied_id or applied_version
    )


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
    card, the extensions of the application or the build list did not come;
    "no-applied-build" - the card names no build; "no-applied-extension" - the sources are
    an extension the application does not have yet; "applied-build-not-listed" - the
    applied build is not among the project's builds; "no-commit-id" - neither the card of
    the applied build nor the local registry of uploads knows its commit;
    "commit-unavailable" - the local repository does not have that commit.

    The project directory is found the way the build finds it: a deploy without an
    explicit one used to skip the guard as "no-project-dir" and then build that very
    directory. An extension is compared with the build the extension runs rather than with
    the build on the card of the application.
    """
    try:
        directory = find_project_dir(project_dir) if project_dir else find_project_dir()
    except ElemctlError:
        return SchemaVerdict(skipped="no-project-dir")
    try:
        meta = read_project_meta(directory)
    except ElemctlError:
        meta = None
    extension = (meta.vendor, meta.name) if meta and is_extension_kind(meta.kind) else None
    applied = _applied_commit(client, app_id, project_id, extension)
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
    the number the server handed out. An upload without a project id, which finds its
    project by the Ид of the descriptor or creates one, answers without one: that upload
    keeps the version of the archive.
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


@dataclass
class _BuiltBuild:
    """What the caller knows about the verified build: its kind, project, vendor and name.

    A deploy knows all of it from the archive it built. A standalone check knows the id of the
    build alone, and then the kind is looked up only when the card of the application names
    another build: an extension is applied beside the build of the application.
    """

    kind: str = ""
    project_id: str = ""
    vendor: str = ""
    name: str = ""
    # The version the server gave the build, "" when not known.
    version: str = ""

    def label(self):
        """The extension the way a reader tells it apart: vendor/name, or its project."""
        if self.vendor and self.name:
            return f"{self.vendor}/{self.name}"
        return self.name or self.project_id


@dataclass
class _ExtensionVerdict:
    """What the extensions of the application say about an extension build.

    applied - True: the extension runs the build, False: it runs another one or the
    application has no such extension, None: the server could not list the extensions.
    version and version_id name the build the extension runs, entry is its row of
    `extension-projects`.
    """

    applied: bool | None = None
    version: str = ""
    version_id: str = ""
    entry: dict | None = None
    problems: list = field(default_factory=list)


def _extension_build(client, assembly_id):
    """The build as an extension build, when an extension project lists it; None otherwise."""
    found = client.find_extension_build(assembly_id)
    if found is None:
        return None
    project, assembly = found
    return _BuiltBuild(
        kind=EXTENSION_KIND,
        project_id=str(project.get("id") or ""),
        vendor=str(assembly.get("project-developer") or ""),
        name=str(assembly.get("project-name") or ""),
        version=str(assembly.get("assembly-version") or assembly.get("project-version") or ""),
    )


def _extension_verdict(client, app_id, build, assembly_id):
    """Whether the extension runs the build: `extension-projects` of Console API 2.1.

    The card of the application names the build of the application alone, before an extension
    is applied and after. What the application server runs is listed by
    GET /v2.1/applications/{id}/project, so the extension of the project is found there and its
    `assembly-version` is compared with the version of the build - by the id of the build of
    that version when the build list of the project has it. A disabled extension is applied and
    does not run, and that is a problem of its own. A server without 2.1 cannot say, and the
    apply is named unverifiable: the card alone would read as a rollback.
    """
    uploaded = assembly_label(assembly_id, build.version) if assembly_id else build.version
    try:
        extensions = client.list_app_extensions(app_id)
    except UnknownMethodError as error:
        return _ExtensionVerdict(problems=[i18n.t(
            "deploy.extension-unverifiable",
            build=uploaded, extension=build.label(), project=build.project_id or "?",
            reason=str(error),
        )])
    entry = extension_entry(
        extensions, project_id=build.project_id, vendor=build.vendor, name=build.name
    )
    if entry is None:
        return _ExtensionVerdict(applied=False, problems=[i18n.t(
            "deploy.extension-missing",
            build=uploaded, extension=build.label(), project=build.project_id or "?",
            extensions="; ".join(extension_label(item) for item in extensions)
            or i18n.t("client.extensions-none"),
        )])
    running = str(entry.get("assembly-version") or "")
    running_id = ""
    if running and build.project_id:
        for assembly in client.list_assemblies(build.project_id):
            if isinstance(assembly, dict) and running in (
                assembly.get("assembly-version"), assembly.get("project-version")
            ):
                running_id = str(extract_assembly_id(assembly) or "")
                break
    if assembly_id and running_id:
        applied = running_id == assembly_id
    elif build.version and running:
        applied = running == build.version
    else:
        applied = None
    problems = []
    if applied is False:
        problems.append(i18n.t(
            "deploy.extension-mismatch",
            extension=extension_label(entry),
            applied=assembly_label(running_id, running) if running_id else running,
            expected=uploaded,
        ))
    if applied and entry.get("enabled") is False:
        problems.append(i18n.t("deploy.extension-disabled", extension=extension_label(entry)))
    return _ExtensionVerdict(
        applied=applied, version=running, version_id=running_id, entry=entry, problems=problems
    )


@dataclass
class RunningBuild:
    """Whether an application runs a build, told without applying or waiting for anything.

    applied - True: the build runs, False: another one does, None: the server cannot tell (an
    extension build on a server without Console API 2.1). version_id and version name the build
    that runs: the build on the card, or the build the extension runs when the requested build
    belongs to an extension. extension_project_id is the project of such a build ("" for any
    other), extension its row of `extension-projects` (None - the application has no such
    extension, or the server could not list them), extension_name its vendor/name, disabled
    whether that extension is switched off. lookup_error says why the kind of the build was not
    found out; the card then gives the verdict alone.
    """

    applied: bool | None = None
    version_id: str = ""
    version: str = ""
    extension_project_id: str = ""
    extension: dict | None = None
    extension_name: str = ""
    disabled: bool = False
    lookup_error: str = ""

    def fields(self):
        """The fields an answer carries: applied, applied-version-id and the extension ones."""
        answer = {"applied": self.applied, "applied-version-id": self.version_id}
        if self.extension_project_id:
            answer["extension-project-id"] = self.extension_project_id
            answer["extension"] = dict(self.extension) if self.extension is not None else None
        return answer


def running_build(client, app_id, assembly_id, *, card=None):
    """Whether the application runs the build, by the same evidence `verify-deploy` rests on.

    The card names the build of the application, and when it names the build asked about no
    request is made. Any other id is looked up among the builds of the extension projects: an
    extension is applied beside the build of the application, the card goes on naming the
    latter, and comparing with the card called an applied extension a build that was not
    there. The build an extension runs is read off the extensions of the application (Console
    API 2.1). Returns a RunningBuild; card - the card when the caller has it already.
    """
    requested = str(assembly_id or "")
    if card is None:
        card = client.get_app(app_id) or {}
    source = card.get("source") or {}
    on_card = str(source.get("project-version-id") or "")
    state = RunningBuild(
        applied=bool(requested) and on_card == requested,
        version_id=on_card,
        version=str(source.get("project-version") or ""),
    )
    if not requested or state.applied:
        return state
    try:
        build = _extension_build(client, requested)
    except ServerStartingError:
        raise
    except (ApiError, TransportError) as error:
        # The lookup only explains a mismatch; the card keeps its verdict, and the caller says
        # that the kind of the build was not found out.
        state.lookup_error = str(error)
        return state
    if build is None:
        return state
    verdict = _extension_verdict(client, app_id, build, requested)
    entry = verdict.entry
    return RunningBuild(
        applied=verdict.applied,
        version_id=verdict.version_id,
        version=verdict.version,
        extension_project_id=build.project_id,
        extension=entry,
        extension_name=extension_label(entry) if entry is not None else build.label(),
        disabled=bool(verdict.applied) and entry is not None and entry.get("enabled") is False,
    )


def _verify(
    client, app_id, *, card, expected_version, since, expected_assembly_id="", uploaded_version="",
    build=None,
):
    """The verdict on an apply; uploaded_version - the version the server gave the build.

    expected_version is what the report calls the build by. The fallback comparison by the
    version string takes uploaded_version when it is known: the server numbers a build
    uploaded into a project itself, and the version of the archive may be on no card at all.

    build - what the caller knows about the build (_BuiltBuild). An extension build is judged
    by the extensions of the application, since the card goes on naming the build of the
    application. Without a kind, an id the card does not name is looked up among the builds
    of the extension projects, which is how a standalone check tells an applied extension
    from a rollback.
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
    # server's version of the build whenever the upload said which. An extension
    # leaves the card naming the build of the application, so an extension build
    # is judged by the extensions of the application instead (_extension_verdict).
    if card is None:
        card = client.get_app(app_id) or {}
    source = card.get("source") or {}
    applied_version = str(source.get("project-version") or "")
    applied_version_id = str(source.get("project-version-id") or "")
    applied = None
    extension_build = None
    lookup_failed = ""
    if build is not None and is_extension_kind(build.kind):
        extension_build = _BuiltBuild(
            kind=build.kind, project_id=build.project_id, vendor=build.vendor, name=build.name,
            version=uploaded_version or expected_version,
        )
    elif (
        not (build and build.kind)
        and expected_assembly_id
        and applied_version_id != expected_assembly_id
    ):
        try:
            extension_build = _extension_build(client, expected_assembly_id)
        except ServerStartingError:
            raise
        except (ApiError, TransportError) as error:
            # The lookup only explains a mismatch; the card still gives its verdict, and the
            # report says that the kind of the build was not found out.
            lookup_failed = str(error)
    extension = None
    if extension_build is not None:
        verdict = _extension_verdict(client, app_id, extension_build, expected_assembly_id)
        applied = verdict.applied
        applied_version = verdict.version
        applied_version_id = verdict.version_id
        extension = verdict.entry
        problems.extend(verdict.problems)
    elif expected_assembly_id and applied_version_id:
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
    if lookup_failed:
        problems.append(i18n.t(
            "deploy.extension-lookup-failed", build=expected_assembly_id, error=lookup_failed
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
        extension_project_id=extension_build.project_id if extension_build else "",
        extension=extension,
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
    if report.extension_project_id:
        # Said first: the verdict of an extension build rests on another list than the card,
        # and a reader who compares the card with the build would take the result for a mistake.
        log(i18n.t("deploy.extension-evidence", project=report.extension_project_id))
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
