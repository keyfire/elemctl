"""Probe: an isolated compilation check of the project sources.

A local build only packs an archive – the syntax, the types and the visibility
of the sources are checked by the SERVER compiler, and it runs when a build is
applied. That is why the only honest way to compile without touching the working
application is to create a throwaway one out of the build and read the errors of
its task.

What the probe is NOT allowed to do: touch the working application. The
`ELEMENT_APP_ID` and `ELEMENT_PROJECT_ID` of the environment are deliberately
ignored – the build goes to the platform without a project id at all, and the
platform routes it by the vendor and the name of the manifest (a project is
identified by that pair, see the platform page). So the sources land in the
project that owns them and nowhere else; a project that is not there yet is
created by the upload.

Cleanup is part of the operation: the throwaway application is deleted, then the
probe build, and – if the probe created it – the project. The order matters: the
platform rejects deleting a build while an application created from it still
exists.
"""

from __future__ import annotations

import re
import tempfile
import uuid
from dataclasses import dataclass, field

from . import i18n
from .build import build_assembly, find_project_dir, read_project_meta
from .client import extract_assembly_id, extract_project_id
from .errors import ApiError, ElemctlError

# The prefix of the throwaway application name; the same token goes into the
# build version, so that leftovers of an interrupted run can be matched up.
PROBE_PREFIX = "elemctl-probe-"

# A compilation error line of an application task: the archive path of the file,
# the position in brackets and the text. The pattern is searched for rather than
# matched, because the first line carries the platform's own prefix – the label
# of the CreateApplication task and its "failed to create the application" text.
_ERROR_LINE = re.compile(
    r"(?P<entry>[^\s\[\]]+)\s+\[(?P<line>\d+):(?P<column>\d+)\]:\s*(?P<message>.*)$"
)

# The execution environment marker the compiler puts in front of the text: server
# or client, in angle brackets and spelled in the language of the platform.
_ENVIRONMENT = re.compile(r"^<(?P<environment>[^>]+)>\s*")


@dataclass
class ProbeReport:
    """The result of a compilation probe.

    ok – the sources compiled. errors – the compilation errors parsed into
    fields; messages – the same texts verbatim, as the platform gave them
    (nothing is lost when the failure is not a compilation one). cleanup –
    what the probe managed to remove after itself.
    """

    ok: bool = False
    project_dir: str = ""
    vendor: str = ""
    name: str = ""
    file: str = ""
    version: str = ""
    project_id: str = ""
    assembly_id: str = ""
    app_id: str = ""
    app_name: str = ""
    status: str = ""
    errors: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    cleanup: dict = field(default_factory=dict)

    def to_dict(self):
        """Render the report as a dict with kebab-case keys (for JSON output)."""
        return {
            "ok": self.ok,
            "project-dir": self.project_dir,
            "vendor": self.vendor,
            "name": self.name,
            "file": self.file,
            "version": self.version,
            "project-id": self.project_id,
            "assembly-id": self.assembly_id,
            "app-id": self.app_id,
            "app-name": self.app_name,
            "status": self.status,
            "errors": list(self.errors),
            "messages": list(self.messages),
            "cleanup": dict(self.cleanup),
        }


def parse_compilation_errors(messages, prefix=""):
    """Parse the error texts of an application task into fields.

    A message is one or more lines of the form
    `{vendor}/{name}/path/File.xbsl [line:column]: <environment> text`; the first
    one also carries the platform's prefix. prefix – the `{vendor}/{name}/` of the
    archive: it is stripped off, so that `file` is the path relative to the
    project directory, the one the editor opens.
    """
    errors = []
    for message in messages or []:
        for raw_line in str(message).splitlines():
            line = raw_line.strip()
            if not line:
                continue
            found = _ERROR_LINE.search(line)
            if not found:
                continue
            entry = found.group("entry")
            text = found.group("message").strip()
            environment = ""
            marker = _ENVIRONMENT.match(text)
            if marker:
                environment = marker.group("environment")
                text = text[marker.end():]
            errors.append(
                {
                    "file": entry[len(prefix):] if prefix and entry.startswith(prefix) else entry,
                    "entry": entry,
                    "line": int(found.group("line")),
                    "column": int(found.group("column")),
                    "environment": environment,
                    "message": text,
                }
            )
    return errors


def probe_project(
    client,
    *,
    project_dir=None,
    output_dir=None,
    space_id=None,
    app_name="",
    version="",
    keep=False,
    log=None,
):
    """Run the project sources through the server compiler; return a ProbeReport.

    log – a callback for progress lines (print, for instance); the library itself
    prints nothing. keep – leave the throwaway application, the build and the
    project in place (for a hands-on investigation of a failure).
    """
    log = log or (lambda message: None)
    # The token ends up as the version suffix after the last hyphen, and that suffix
    # picks the project's latest build when it parses as a number. Eight hex digits
    # come out all-numeric once in ~43 draws – often enough that CI caught it live.
    token = uuid.uuid4().hex[:8]
    while token.isdigit():
        token = uuid.uuid4().hex[:8]

    meta = read_project_meta(find_project_dir(project_dir) if project_dir else find_project_dir())
    report = ProbeReport(
        project_dir=str(meta.project_dir),
        vendor=meta.vendor,
        name=meta.name,
        app_name=app_name or f"{PROBE_PREFIX}{token}",
    )

    # The version carries a non-numeric suffix on purpose: the platform refuses a
    # repeated upload of a version the project group already has (409
    # ALREADY_EXISTS), while the numeric counter of the version is what picks the
    # project's latest build – a probe build must never become that.
    result = build_assembly(
        meta.project_dir,
        output_dir=output_dir or tempfile.mkdtemp(prefix="elemctl-probe-"),
        version=version or f"{meta.base_version}-probe-{token}",
    )
    report.file = str(result.file)
    report.version = result.version
    log(i18n.t("probe.built", file=result.file, version=result.version))

    known_projects = _project_ids(client)
    response = client.upload_assembly(
        result.file.read_bytes(), project_id=None, space_id=space_id or None
    )
    report.assembly_id = extract_assembly_id(response) or ""
    report.project_id = extract_project_id(response) or ""
    if not report.assembly_id:
        raise ElemctlError(i18n.t("probe.no-assembly-id"))
    created_project = bool(
        report.project_id and known_projects is not None
        and report.project_id not in known_projects
    )
    log(i18n.t(
        "probe.uploaded",
        assembly=report.assembly_id,
        project=report.project_id or i18n.t("probe.unknown"),
    ))

    try:
        log(i18n.t("probe.creating", name=report.app_name))
        card = client.create_app(
            report.app_name,
            project_version_id=report.assembly_id,
            development_mode=False,
            space_id=space_id or None,
        ) or {}
        report.app_id = str(card.get("id") or "")
        if not report.app_id:
            raise ElemctlError(i18n.t("probe.no-app-id"))
        card = client.wait_app_ready(report.app_id, log=log)
        report.status = str(card.get("status") or "")
        report.ok = True
        log(i18n.t("probe.compiled"))
    except ApiError as error:
        report.status = _status_of(error)
        report.messages = client.failed_task_messages(report.app_id) if report.app_id else []
        if not report.messages:
            report.messages = [str(error)]
        report.errors = parse_compilation_errors(
            report.messages, prefix=f"{meta.vendor}/{meta.name}/"
        )
        log(i18n.t("probe.failed", count=len(report.errors) or len(report.messages)))
    finally:
        report.cleanup = _cleanup(
            client, report, keep=keep, delete_project=created_project, log=log
        )
    return report


# -- internals ----------------------------------------------------------------


def _project_ids(client):
    """The ids of the platform projects before the upload, or None when unknown.

    It is the only way to tell whether the project was created by this very
    upload – and therefore whether it has to be removed afterwards. A failure of
    the request is not a reason to abort the probe: None means "do not touch the
    project".
    """
    try:
        return {
            str(project.get("id"))
            for project in client.list_projects()
            if isinstance(project, dict) and project.get("id")
        }
    except ApiError:
        return None


def _status_of(error):
    """The application status out of the body of an api error, when there is one."""
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        return str(body.get("status") or "")
    return ""


def _cleanup(client, report, *, keep, delete_project, log):
    """Remove what the probe created; return the report of that.

    The order is forced by the platform: a build that an application was created
    from cannot be deleted while that application exists, so the application goes
    first and the build only after it has really disappeared. None – nothing to
    do; a failure is a problem in the report rather than an exception: the
    compilation verdict has already been obtained and must reach the caller.
    """
    outcome = {
        "kept": bool(keep),
        "app-deleted": None,
        "assembly-deleted": None,
        "project-deleted": None,
        "problems": [],
    }
    if keep:
        log(i18n.t("probe.kept", app=report.app_id or "-", version=report.version))
        return outcome

    gone = False
    if report.app_id:
        try:
            client.delete_app(report.app_id)
            gone = client.wait_app_deleted(report.app_id, log=log)
            outcome["app-deleted"] = gone
            if not gone:
                outcome["problems"].append(i18n.t("probe.app-still-there", app=report.app_id))
        except (ApiError, ElemctlError) as error:
            outcome["app-deleted"] = False
            outcome["problems"].append(str(error))

    if report.assembly_id and report.project_id:
        if not report.app_id or gone:
            try:
                client.delete_assembly(report.project_id, report.assembly_id)
                outcome["assembly-deleted"] = True
            except (ApiError, ElemctlError) as error:
                outcome["assembly-deleted"] = False
                outcome["problems"].append(str(error))
        else:
            outcome["assembly-deleted"] = False
            outcome["problems"].append(
                i18n.t("probe.assembly-kept", version=report.version, project=report.project_id)
            )

    if delete_project and report.project_id and outcome["assembly-deleted"] is not False:
        try:
            client.delete_project(report.project_id)
            outcome["project-deleted"] = True
        except (ApiError, ElemctlError) as error:
            outcome["project-deleted"] = False
            outcome["problems"].append(str(error))

    for problem in outcome["problems"]:
        log(i18n.t("probe.cleanup-problem", problem=problem))
    return outcome
