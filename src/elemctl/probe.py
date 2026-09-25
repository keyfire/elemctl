"""Probe: an isolated compilation check of the project sources.

A local build only packs an archive - the syntax, the types and the visibility
of the sources are checked by the SERVER compiler, and it runs when a build is
applied. That is why the only honest way to compile without touching the working
application is to create a throwaway one out of the build and read the errors of
its task.

What the probe is NOT allowed to do: touch the working application. The
`ELEMENT_APP_ID` and `ELEMENT_PROJECT_ID` of the environment are deliberately
ignored - the build goes to the platform without a project id at all, and the
platform routes it by the vendor and the name of the manifest (a project is
identified by that pair, see the platform page). So the sources land in the
project that owns them and nowhere else; a project that is not there yet is
created by the upload.

Cleanup is part of the operation: the throwaway application is deleted, then the
probe build, and - if the probe created it - the project. The order matters: the
platform rejects deleting a build while an application created from it still
exists.

A probe kept with `keep` (or one whose cleanup broke off) is finished by
`cleanup_probe`, which starts from the application alone: its card names the
project and the build, so nothing has to be remembered between the two runs, and
the build is looked for in the probe's own project rather than in the project of
the environment.
"""

from __future__ import annotations

import re
import tempfile
import uuid
from dataclasses import dataclass, field

from . import i18n
from .build import (
    build_assembly,
    descriptor_value,
    find_project_dir,
    parse_flat_yaml,
    read_project_meta,
)
from .client import (
    APP_NAME_KEYS,
    assembly_id_of,
    extract_assembly_id,
    extract_project_id,
)
from .errors import ApiError, ConfigError, ElemctlError
from .registry import remember_build

# The prefix of the throwaway application name; the same token goes into the
# build version, so that leftovers of an interrupted run can be matched up.
PROBE_PREFIX = "elemctl-probe-"
# What marks a probe build: its version is `{base}-probe-{token}`.
PROBE_VERSION_MARK = "-probe-"

# A compilation error line of an application task: the archive path of the file,
# the position in brackets and the text. The pattern is searched for rather than
# matched, because the first line carries the platform's own prefix - the label
# of the CreateApplication task and its "failed to create the application" text.
_ERROR_LINE = re.compile(
    r"(?P<entry>[^\s\[\]]+)\s+\[(?P<line>\d+):(?P<column>\d+)\]:\s*(?P<message>.*)$"
)

# The execution environment marker the compiler puts in front of the text: server
# or client, in angle brackets and spelled in the language of the platform.
_ENVIRONMENT = re.compile(r"^<(?P<environment>[^>]+)>\s*")

# The refusal that means the STAND is older than the project, not that the sources
# are broken. It comes first, and behind it follows an avalanche of derived errors:
# a platform that does not know the compatibility mode does not know the types and
# the properties of that mode either, so it complains about files the change never
# touched. Parsing that avalanche costs hundreds of lines and answers nothing -
# the probe stops at the refusal and says what it really is.
_COMPATIBILITY_REFUSED = re.compile(
    r"(?:Неизвестный режим совместимости|Unknown compatibility mode)\s*(?P<mode>[\d.]+)?",
    re.IGNORECASE,
)


@dataclass
class ProbeReport:
    """The result of a compilation probe.

    ok - the sources compiled. errors - the compilation errors parsed into
    fields; messages - the same texts verbatim, as the platform gave them
    (nothing is lost when the failure is not a compilation one). cleanup -
    what the probe managed to remove after itself.
    """

    ok: bool = False
    project_dir: str = ""
    vendor: str = ""
    name: str = ""
    file: str = ""
    version: str = ""
    project_id: str = ""
    # Whether this very upload created the project: True, False, or None when the list of
    # projects could not be read before the upload.
    project_created: bool | None = None
    assembly_id: str = ""
    app_id: str = ""
    app_name: str = ""
    status: str = ""
    errors: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    cleanup: dict = field(default_factory=dict)
    # The stand refused the compatibility mode of the project: the mode it refused
    # and how many further messages were dropped as derived from that refusal.
    # Filled in, these two say the verdict is about the STAND, not about the code.
    compatibility_refused: str = ""
    messages_dropped: int = 0
    # Where to look when the server refused without naming a compilation error
    # (server_log_hint); "" when the answer itself says what went wrong.
    hint: str = ""

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
            "project-created": self.project_created,
            "assembly-id": self.assembly_id,
            "app-id": self.app_id,
            "app-name": self.app_name,
            "status": self.status,
            "errors": list(self.errors),
            "messages": list(self.messages),
            "cleanup": dict(self.cleanup),
            "compatibility-refused": self.compatibility_refused or None,
            "messages-dropped": self.messages_dropped,
            "hint": self.hint or None,
        }


def parse_compilation_errors(messages, prefix=""):
    """Parse the error texts of an application task into fields.

    A message is one or more lines of the form
    `{vendor}/{name}/path/File.xbsl [line:column]: <environment> text`; the first
    one also carries the platform's prefix. prefix - the `{vendor}/{name}/` of the
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


def server_log_hint(messages):
    """Where the cause is when the server refused without naming a compilation error.

    The platform may answer a failed create or apply with "Contact administrator for
    details" and no file in the text, and then the answer holds nothing to act on. The
    cause is in the log of the server: the last "Caused by" line, with "SrcPath:" beside
    it naming the file the apply stopped at. "" when there is no refusal, or when the
    refusal names a file and a position itself.
    """
    if not any(str(message).strip() for message in messages or []):
        return ""
    if parse_compilation_errors(messages):
        return ""
    return i18n.t("probe.server-log-hint")


def compatibility_refusal(messages):
    """The compatibility mode the stand refused, or "" when the refusal is not there.

    The mode named in the text when the platform names one; otherwise the marker
    itself, so that a refusal without a version still reads as one.
    """
    for line in _all_lines(messages):
        found = _COMPATIBILITY_REFUSED.search(line)
        if found:
            return (found.group("mode") or "").strip() or line.strip()
    return ""


def manifest_problems(project_file):
    """What the manifest lacks for the server to take a probe; [] when nothing.

    A hand-written probe project tends to carry only the name, the vendor and the version,
    and the server answers each missing key in its own unhelpful way. Without
    `Представление` the console refuses the upload with a bare 500 and names the field only
    in its own event log. `ЯзыкРазработки` is a required property of the project
    descriptor: without it no application is created, so a probe can never come out ok. A
    `ЯзыкПоУмолчанию` without `ЯзыкиЛокализации` is refused with no word about the cause at
    all. Every key is read in both spellings, and the example of a fix is written in the
    spelling the manifest itself uses; the project's own name stands in for a presentation.
    """
    values = parse_flat_yaml(project_file.read_text(encoding="utf-8-sig"))
    english = "Name" in values and "Имя" not in values

    def spelled(russian, english_key):
        return english_key if english else russian

    language = spelled("Русский", "English")
    problems = []
    if not descriptor_value(values, "Представление", "Presentation"):
        name = descriptor_value(values, "Имя", "Name")
        problems.append(i18n.t(
            "probe.manifest-no-presentation",
            example=f"{spelled('Представление', 'Presentation')}: {name}",
        ))
    if not descriptor_value(values, "ЯзыкРазработки", "DevelopmentLanguage"):
        problems.append(i18n.t(
            "probe.manifest-no-development-language",
            example=f"{spelled('ЯзыкРазработки', 'DevelopmentLanguage')}: {language}",
        ))
    # The list may be written inline or as a nested block; a block leaves the value of the
    # key itself empty, so the key counts by its presence, and only an empty inline list
    # counts as no list.
    languages = [
        values[key] for key in ("ЯзыкиЛокализации", "LocalizationLanguages") if key in values
    ]
    no_list = all(value.replace(" ", "") == "[]" for value in languages)
    if descriptor_value(values, "ЯзыкПоУмолчанию", "DefaultLanguage") and no_list:
        problems.append(i18n.t(
            "probe.manifest-no-localization-languages",
            example=f"{spelled('ЯзыкиЛокализации', 'LocalizationLanguages')}: [{language}]",
        ))
    return problems


def _all_lines(messages):
    """Every non-empty line of the messages, in order."""
    return [
        line.strip()
        for message in messages or []
        for line in str(message).splitlines()
        if line.strip()
    ]


def probe_project(
    client,
    *,
    project_dir=None,
    output_dir=None,
    space_id=None,
    app_name="",
    version="",
    keep=False,
    env_file=None,
    log=None,
):
    """Run the project sources through the server compiler; return a ProbeReport.

    log - a callback for progress lines (print, for instance); the library itself
    prints nothing. keep - leave the throwaway application, the build and the
    project in place (for a hands-on investigation of a failure). env_file - the
    .env the caller reached the stand with; it is only written into the cleanup
    commands of a probe that left something behind, so that they reach the same stand.
    """
    log = log or (lambda message: None)
    # The token ends up as the version suffix after the last hyphen, and that suffix
    # picks the project's latest build when it parses as a number. Eight hex digits
    # come out all-numeric once in ~43 draws - often enough that CI caught it live.
    token = uuid.uuid4().hex[:8]
    while token.isdigit():
        token = uuid.uuid4().hex[:8]

    meta = read_project_meta(find_project_dir(project_dir) if project_dir else find_project_dir())
    # Checked before anything is built or uploaded: each of these ends the run on the
    # server anyway, and the server's own answer does not say which key was missing.
    problems = manifest_problems(meta.project_file)
    if problems:
        raise ElemctlError(i18n.t(
            "probe.manifest-incomplete", file=meta.project_file, problems=" ".join(problems)
        ))
    report = ProbeReport(
        project_dir=str(meta.project_dir),
        vendor=meta.vendor,
        name=meta.name,
        app_name=app_name or f"{PROBE_PREFIX}{token}",
    )

    # The version carries a non-numeric suffix on purpose: the platform refuses a
    # repeated upload of a version the project group already has (409
    # ALREADY_EXISTS), while the numeric counter of the version is what picks the
    # project's latest build - a probe build must never become that.
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
    report.project_created = created_project if known_projects is not None else None
    log(i18n.t(
        "probe.uploaded",
        assembly=report.assembly_id,
        project=report.project_id or i18n.t("probe.unknown"),
    ))
    # An upload like any other: kept with --keep, it is a build an application runs, and the
    # registry is what says which tree it came from - the creation of a project documents no
    # commit parameter, so the card carries none.
    warning = remember_build(
        result,
        response=response,
        project_id=report.project_id,
        stand=str(getattr(getattr(client, "config", None), "base_url", "") or ""),
        command="probe",
    )
    if warning:
        log(warning)

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
        refusals = client.failed_task_messages(report.app_id) if report.app_id else []
        report.messages = refusals or [str(error)]
        refused = compatibility_refusal(report.messages)
        if refused:
            # The verdict is about the stand, and the rest of the answer is its
            # consequence - the report keeps the refusal itself and counts what it
            # dropped, so nothing looks hidden.
            report.compatibility_refused = refused
            kept = [line for line in _all_lines(report.messages) if _COMPATIBILITY_REFUSED.search(line)]
            report.messages_dropped = len(_all_lines(report.messages)) - len(kept)
            report.messages = kept
            log(i18n.t(
                "probe.compatibility-refused",
                mode=refused,
                project=meta.compatibility or i18n.t("probe.unknown"),
                dropped=report.messages_dropped,
            ))
        else:
            report.errors = parse_compilation_errors(
                report.messages, prefix=f"{meta.vendor}/{meta.name}/"
            )
            # A refusal is a failed task or the Error status; a wait that simply ran out of
            # time carries no word from the server, and the hint would send the reader astray.
            if refusals or report.status == "Error":
                report.hint = server_log_hint(report.messages)
            log(i18n.t("probe.failed", count=len(report.errors) or len(report.messages)))
            if report.hint:
                log(report.hint)
    finally:
        report.cleanup = _cleanup(
            client, report, keep=keep, delete_project=created_project, env_file=env_file,
            log=log,
        )
    return report


# -- internals ----------------------------------------------------------------


def _project_ids(client):
    """The ids of the platform projects before the upload, or None when unknown.

    It is the only way to tell whether the project was created by this very
    upload - and therefore whether it has to be removed afterwards. A failure of
    the request is not a reason to abort the probe: None means "do not touch the
    project". Deleted projects are asked for on purpose: an upload may land in
    one of them, and an id the set does not know reads as "created here".
    """
    try:
        return {
            str(project.get("id"))
            for project in client.list_projects(include_deleted=True)
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


def _cleanup(client, report, *, keep, delete_project, env_file=None, log):
    """Remove what the probe created; return the report of that.

    The order is forced by the platform: a build that an application was created
    from cannot be deleted while that application exists, so the application goes
    first and the build only after it has really disappeared. None - nothing to
    do; a failure is a problem in the report rather than an exception: the
    compilation verdict has already been obtained and must reach the caller.

    Whatever is left behind - on purpose with keep, or by a step that failed - comes
    with the commands that remove it: `command` does it all, `steps` by hand.
    """
    outcome = {
        "kept": bool(keep),
        "app-deleted": None,
        "assembly-deleted": None,
        "project-deleted": None,
        "problems": [],
        "command": None,
        "steps": None,
    }
    if keep:
        outcome["command"], outcome["steps"] = cleanup_commands(
            report, project_created=delete_project, env_file=env_file
        )
        log(i18n.t("probe.kept", app=report.app_id or "-", version=report.version))
        _announce_commands(outcome, log)
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
    if outcome["problems"]:
        outcome["command"], outcome["steps"] = cleanup_commands(
            report, project_created=delete_project, env_file=env_file, done=outcome
        )
        _announce_commands(outcome, log)
    return outcome


def _quoted(value):
    """A value as it goes into a command line: in double quotes when it has blanks in it.

    Double quotes read the same in a POSIX shell, in PowerShell and in cmd, which is the
    one spelling a copied line needs.
    """
    text = str(value)
    return f'"{text}"' if any(char.isspace() for char in text) else text


def cleanup_commands(report, *, project_created, env_file=None, done=None):
    """The commands that remove what a probe left: (the one command, the steps by hand).

    The one command is `probe --cleanup` over the application, and None when there is no
    application to start from. The steps go in the order the platform demands: the
    application, then the build - addressed in the probe's own project, which is not the
    project of the environment - and the project only when this probe created it. A step
    the cleanup already made (done, its outcome) is left out. The .env the probe reached the
    stand with is named in every line, so that a copied line goes to the same stand.
    """
    done = done or {}
    suffix = f" --env-file {_quoted(env_file)}" if env_file else ""
    command = f"elemctl probe --cleanup {report.app_id}{suffix}" if report.app_id else None
    steps = []
    if report.app_id and not done.get("app-deleted"):
        steps.append(f"elemctl apps delete {report.app_id}{suffix}")
    if report.version and report.project_id and not done.get("assembly-deleted"):
        steps.append(
            f"elemctl builds delete {report.version} --project-id {report.project_id}{suffix}"
        )
    if project_created and report.project_id and not done.get("project-deleted"):
        steps.append(f"elemctl projects delete {report.project_id}{suffix}")
    return command, steps


def _announce_commands(outcome, log):
    """Say how to finish the cleanup: the one command first, then the steps by hand."""
    if outcome.get("command"):
        log(i18n.t("probe.cleanup-command", command=outcome["command"]))
    if outcome.get("steps"):
        log(i18n.t("probe.cleanup-steps", steps="; ".join(outcome["steps"])))


# -- finishing the cleanup of a kept probe -------------------------------------------------


def probe_token(name):
    """The token of an application named the way a probe names it; "" for any other name."""
    name = str(name or "")
    return name[len(PROBE_PREFIX):] if name.startswith(PROBE_PREFIX) else ""


def is_probe_build(version, token=""):
    """Whether a build version is a probe's: `{base}-probe-{token}`.

    With a token, the version has to carry that very token: the build of this probe and of no
    other. Without one, any probe version counts.
    """
    version = str(version or "")
    if token:
        return version.endswith(f"{PROBE_VERSION_MARK}{token}")
    return PROBE_VERSION_MARK in version


def _version_of(assembly):
    """The version of an assembly card, the address its card and its deletion take."""
    return str(assembly.get("assembly-version") or assembly.get("project-version") or "")


@dataclass
class CleanupReport:
    """What `cleanup_probe` removed and what it left, with the reasons.

    app_deleted - True once the application is gone (now or before this run), False when
    it did not disappear in time. builds - the probe builds found in the project, each with
    whether it was deleted. project_deleted - True when the project went (now or before),
    None when it was kept on purpose, and then project_kept says why; False when its
    deletion failed.
    """

    ok: bool = False
    app_id: str = ""
    app_name: str = ""
    project_id: str = ""
    app_deleted: bool | None = None
    builds: list = field(default_factory=list)
    project_deleted: bool | None = None
    project_kept: str = ""
    problems: list = field(default_factory=list)

    def to_dict(self):
        """Render the report as a dict with kebab-case keys (for JSON output)."""
        return {
            "ok": self.ok,
            "app-id": self.app_id,
            "app-name": self.app_name,
            "project-id": self.project_id,
            "app-deleted": self.app_deleted,
            "builds": list(self.builds),
            "project-deleted": self.project_deleted,
            "project-kept": self.project_kept or None,
            "problems": list(self.problems),
        }


def _is_deleted_card(card):
    return str(card.get("status") or "").strip().lower() == "deleted"


def _probe_card(client, app):
    """The card of the application out of the full list, deleted ones included.

    The list and not the card request: the card of a deleted application answers 404,
    while the list keeps it under the Deleted status with its source and project - and a
    second run after a cleanup that stopped halfway starts from exactly such an
    application. An id matches as it is; a name matches exactly, a live application first.
    """
    wanted = str(app or "").strip()
    if not wanted:
        raise ConfigError(i18n.t("client.app-not-found", name=app))
    cards = [card for card in client.list_apps(include_deleted=True) if isinstance(card, dict)]
    for card in cards:
        if str(card.get("id") or "") == wanted:
            return card
    target = wanted.lower()
    named = [
        card for card in cards
        if any(str(card.get(key) or "").strip().lower() == target for key in APP_NAME_KEYS)
    ]
    chosen = [card for card in named if not _is_deleted_card(card)] or named
    if not chosen:
        raise ConfigError(i18n.t("client.app-not-found", name=app))
    if len(chosen) > 1:
        ids = ", ".join(str(card.get("id")) for card in chosen)
        raise ConfigError(i18n.t("client.app-name-ambiguous", name=app, ids=ids))
    return chosen[0]


def _project_listing(client, project_id):
    """The builds of the project; an empty list when the project is gone already."""
    try:
        return [item for item in client.list_assemblies(project_id) if isinstance(item, dict)]
    except ApiError as error:
        if error.status == 404:
            return []
        raise


def _project_deleted_already(client, project_id):
    """Whether the platform lists the project as deleted (it keeps such projects in the list)."""
    for project in client.list_projects(include_deleted=True):
        if isinstance(project, dict) and str(project.get("id") or "") == project_id:
            return bool(project.get("deleted"))
    return False


def _users_of_project(client, project_id, app_id):
    """The names of the live applications other than this one that run the project."""
    names = []
    for card in client.list_apps():
        if not isinstance(card, dict) or str(card.get("id") or "") == app_id:
            continue
        source = card.get("source") if isinstance(card.get("source"), dict) else {}
        project = card.get("project") if isinstance(card.get("project"), dict) else {}
        if project_id in (str(project.get("id") or ""), str(source.get("image-id") or "")):
            names.append(str(card.get("name") or card.get("display-name") or card.get("id")))
    return names


def _project_kept_reason(client, project_id, app_id, working_project):
    """Why the project has to stay, or "" when it may go.

    A probe usually lands in the project that owns its sources - the working one - so the
    project goes only when nothing is left in it: no build at all after the probe's, and no
    live application that runs it. A real project keeps its first build for good, so an
    empty project is a throwaway one; the environment's own project is kept whatever it holds.
    """
    if working_project and project_id == working_project:
        return i18n.t("probe.cleanup-project-working")
    left = [_version_of(item) or assembly_id_of(item) for item in _project_listing(client, project_id)]
    if left:
        shown = ", ".join(left[:5]) + (", ..." if len(left) > 5 else "")
        return i18n.t("probe.cleanup-project-has-builds", builds=shown)
    users = _users_of_project(client, project_id, app_id)
    if users:
        return i18n.t("probe.cleanup-project-in-use", apps=", ".join(users))
    return ""


def cleanup_probe(client, app, *, log=None):
    """Remove what a probe left on the stand, starting from its application; a CleanupReport.

    This is how a probe kept with --keep is taken away, and a cleanup that broke off is
    finished: a second run picks up where the first one stopped. The application's card
    names the rest - the project the build landed in and the build it was created from -
    so the build is looked for in that project and not in the project of the environment.

    Only a probe's application is touched: one whose name carries the probe prefix, or one
    that runs a probe build (a probe named with --name). Anything else is refused with the
    reason, and so is the application the environment names as the working one. The order is
    the platform's: the application, a wait until it is really gone, the builds of the probe,
    and the project last - only when nothing is left in it (_project_kept_reason). The
    builds other runs uploaded into the probe's application are not the probe's; the
    platform deletes the builds nobody uses by itself.

    A failure is a problem in the report, not an exception: what was removed stays removed,
    and the next run finishes the rest.
    """
    log = log or (lambda message: None)
    config = getattr(client, "config", None)
    working_app = str(getattr(config, "app_id", "") or "")
    working_project = str(getattr(config, "project_id", "") or "")

    card = _probe_card(client, app)
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    project = card.get("project") if isinstance(card.get("project"), dict) else {}
    report = CleanupReport(
        app_id=str(card.get("id") or ""),
        app_name=str(card.get("name") or card.get("display-name") or ""),
        project_id=str(project.get("id") or source.get("image-id") or ""),
    )
    applied_id = str(source.get("project-version-id") or "")
    applied_version = str(source.get("project-version") or "")
    token = probe_token(report.app_name)

    if working_app and report.app_id == working_app:
        raise ElemctlError(i18n.t("probe.cleanup-working-app", app=report.app_id))
    if not token and not is_probe_build(applied_version):
        raise ElemctlError(i18n.t(
            "probe.cleanup-not-a-probe",
            name=report.app_name or report.app_id, app=report.app_id, prefix=PROBE_PREFIX,
            version=applied_version or i18n.t("probe.unknown"),
        ))

    # The application first: while it exists the platform refuses to delete its build.
    if _is_deleted_card(card):
        report.app_deleted = True
        log(i18n.t("probe.cleanup-app-already-deleted", app=report.app_id))
    else:
        try:
            log(i18n.t("probe.cleanup-deleting-app", app=report.app_id, name=report.app_name))
            client.delete_app(report.app_id)
            report.app_deleted = client.wait_app_deleted(report.app_id, log=log)
            if not report.app_deleted:
                report.problems.append(
                    i18n.t("probe.cleanup-app-still-there", app=report.app_id)
                )
        except (ApiError, ElemctlError) as error:
            report.app_deleted = False
            report.problems.append(
                i18n.t("probe.cleanup-app-not-deleted", app=report.app_id, error=error)
            )
        if not report.app_deleted:
            return _finish(report, log)

    if not report.project_id:
        report.problems.append(i18n.t("probe.cleanup-no-project", app=report.app_id))
        return _finish(report, log)

    try:
        listing = _project_listing(client, report.project_id)
    except (ApiError, ElemctlError) as error:
        report.problems.append(str(error))
        return _finish(report, log)
    ours = [
        item for item in listing
        if (token and is_probe_build(_version_of(item), token))
        or (assembly_id_of(item) == applied_id and is_probe_build(_version_of(item)))
    ]
    if not ours:
        log(i18n.t("probe.cleanup-no-build", project=report.project_id))
    for item in ours:
        entry = {"id": assembly_id_of(item), "version": _version_of(item), "deleted": False}
        try:
            client.delete_assembly(report.project_id, entry["version"] or entry["id"])
            entry["deleted"] = True
            log(i18n.t("probe.cleanup-build-deleted", version=entry["version"],
                       project=report.project_id))
        except (ApiError, ElemctlError) as error:
            entry["error"] = str(error)
            report.problems.append(str(error))
        report.builds.append(entry)

    try:
        if _project_deleted_already(client, report.project_id):
            report.project_deleted = True
            log(i18n.t("probe.cleanup-project-already", project=report.project_id))
            return _finish(report, log)
        reason = _project_kept_reason(client, report.project_id, report.app_id, working_project)
        if reason:
            report.project_kept = reason
            log(i18n.t("probe.cleanup-project-kept", project=report.project_id, reason=reason))
        else:
            client.delete_project(report.project_id)
            report.project_deleted = True
            log(i18n.t("probe.cleanup-project-deleted", project=report.project_id))
    except (ApiError, ElemctlError) as error:
        report.project_deleted = False
        report.problems.append(str(error))
    return _finish(report, log)


def _finish(report, log):
    """Settle the verdict: the cleanup went well when nothing went wrong on the way."""
    for problem in report.problems:
        log(i18n.t("probe.cleanup-problem", problem=problem))
    report.ok = not report.problems
    return report
