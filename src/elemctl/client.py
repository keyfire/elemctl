"""Console API v2 client of the 1C:Enterprise.Element platform.

The client prints nothing by itself: the progress of long operations is handed
out through the log callback the caller passes in.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import quote, urlencode

from . import i18n
from .auth import TokenManager
from .build import MANIFEST_FILE, parse_flat_yaml
from .config import BOOL_ENV_KEYS
from .errors import (
    ApiError,
    ConfigError,
    ElemctlError,
    ServerStartingError,
    TransportError,
    UnknownMethodError,
)
from .registry import ROUTE_NO_PROJECT_ID, remembered_uploads, upload_route
from .transport import UrllibTransport
from .versions import (
    newest_first,
    numbering_holes,
    pick_latest,
    version_base,
    version_counter,
)

API_PREFIX = "/console/api/v2"

#: The prefix of Console API 2.1. The newer console reference documents 2.1 as the main
#: version and keeps 2.0 beside it, working. The client stays on 2.0 (API_PREFIX) and
#: asks 2.1 only for what 2.0 has not got: the extensions applied to an application and the
#: export of their builds.
API_2_1_PREFIX = "/console/api/v2.1"

# A console that has no handler for a path answers 401, the status of a refused token, and
# names the path in the text: `Handler of HTTP request "[GET] /v2.1/..." in application
# "console" not found.` That is how a server older than a method refuses it, and only the text
# tells it from a refused token.
_NO_HANDLER = re.compile(r"handler\s+of\s+http\s+request", re.IGNORECASE)

# Stable application statuses; everything else (an empty string included) is transitional.
# The reference lists no values of the status, and two met live were in no list of ours:
# `Deleting`, while an application is being deleted, and `UNKNOWN`, on an application whose
# database files were gone. `UNKNOWN` is neither: the console gives it to a state of the server
# it has no name for, a lost database as much as a passing step, so it is not counted as stable
# and is not waited on for the whole timeout either - see UNKNOWN_TIMEOUT.
STABLE_STATUSES = {"Running", "Stopped", "Error"}

#: The status the console gives an application whose server state it cannot name.
UNKNOWN_STATUS = "UNKNOWN"

# Wait timeouts (seconds) as per section 6 of the specification.
POLL_INTERVAL = 10.0
STOP_TIMEOUT = 180.0
START_TIMEOUT = 300.0
READY_TIMEOUT = 600.0
DELETE_TIMEOUT = 180.0

# How long a wait for a status puts up with UNKNOWN in a row before it stops. An application
# without its database stays UNKNOWN for good, and a deploy on one used to wait the whole
# five minutes of START_TIMEOUT before naming the status. No evidence says UNKNOWN is always
# final, though, so it is given a minute of its own rather than being refused on sight: a
# status that moves on within it lets the wait go on as usual.
UNKNOWN_TIMEOUT = 60.0

# How long an apply waits out an application that is still finishing a previous
# operation, and how often it asks again. The wait is short on purpose: it covers
# a deploy that follows another one, not a stand that has hung.
APPLY_BUSY_TIMEOUT = 180.0
BUSY_POLL_INTERVAL = 10.0

# How many times a read is made when the connection keeps breaking off, and the pause
# between the attempts. Only a broken connection is repeated: an answer of the platform,
# an error status included, is final.
READ_ATTEMPTS = 3
READ_RETRY_PAUSE = 5.0

# The platform answers a request to a busy application with a 404 whose text says
# so - the same status a missing application gets. The text is what tells them
# apart, and retrying on the status alone would spend the whole timeout on an
# application that really is not there. Both spellings, like everywhere else.
BUSY_MARKERS = ("is busy", "занято", "занят")

# A server that is still starting answers every console request with a 404 whose text
# names the console application: `Application "console" not found`. The status is the one
# a missing object gets, so the text is again what tells the two apart. The quotes are
# spelled differently depending on whether the body is plain text or a JSON string, so the
# words are matched and the punctuation between them is not.
_CONSOLE_STARTING = re.compile(r"application\W+console\W+not\s+found", re.IGNORECASE)

# How long a deploy waits for a starting server, and how often it asks again. The console
# of a freshly updated server was seen answering that 404 for thirteen minutes in a row.
SERVER_START_TIMEOUT = 900.0
SERVER_START_POLL = 10.0

# Application task statuses that mean a failure (compared case-insensitively).
FAILED_TASK_STATUSES = {"error", "failed"}

# The type of the account service that authenticates by a login and a password:
# what the control panel calls "signing in with a login and a password" is this
# service being enabled in the user list.
LOCAL_SERVICE = "Local"
#: The account service that signs in through an external provider.
OIDC_SERVICE = "Oidc"
#: The key the platform accepts for the rules that build a user from the provider's
#: answer. The name differs from the one in the schema of the same catalog
#: (`calculation-rules`), and the platform rejects that one with 400.
CALCULATION_RULES_KEY = "userPropertiesCalculationRules"
#: The rules themselves: what kind of answer is parsed and how the fields are taken from it.
CALCULATION_RULE_FIELDS = ("response-kind", "presentation-rule", "phone-rule", "email-rule")


def extract_assembly_id(payload):
    """Extract the assembly id out of a platform response.

    The image-id, assembly-id and id fields are checked - in exactly that order.
    """
    if not isinstance(payload, dict):
        return None
    for key in ("image-id", "assembly-id", "id"):
        value = payload.get(key)
        if value:
            return value
    return None


def extract_project_id(payload):
    """Extract the project id out of a build upload response.

    On an upload without a project id the platform answers with the build id and
    an artifact - that artifact IS the project the build landed in (verified by a
    live call: the artifact-id opens as a project card). The plain id field is
    deliberately not looked at: at the top level it is the id of the build.
    """
    if not isinstance(payload, dict):
        return None
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        for key in ("artifact-id", "project-id", "id"):
            if artifact.get(key):
                return artifact[key]
    for key in ("project-id", "artifact-id"):
        if payload.get(key):
            return payload[key]
    return None


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _looks_like_uuid(value):
    return bool(_UUID_RE.match(str(value)))


# The words by which a 400 is recognized as "the token you hold is no good".
_STALE_TOKEN_MARKERS = ("jwt", "signature", "token", "expired")


def _is_stale_token(response):
    """Is this refusal about the token we hold rather than about the request?

    A rejected token does NOT come back as 401 from this server: it answers 400
    with error_code=invalid_request, and the reason sits in error_description
    ("JWT strings must contain exactly 2 period characters", "Unable to verify RSA
    signature ..."). Both are reproducible by planting a deliberately bad token
    into the cache. That is why the refresh-and-retry, which
    watched only for 401, never fired and the cure was written down as deleting the
    cache file by hand. The description is required to name the token, so an
    ordinary invalid request does not send us for a new token.
    """
    if response.status != 400:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    if str(body.get("error_code") or "").lower() != "invalid_request":
        return False
    description = str(body.get("error_description") or "").lower()
    return any(marker in description for marker in _STALE_TOKEN_MARKERS)


def server_starting(status, body):
    """Is this the answer of a server whose console is not up yet?

    The one place that recognizes a starting server: every request of the client and the
    token request behind it are judged here. body is what the answer carried - the parsed
    JSON or the text.
    """
    if status != 404 or body is None:
        return False
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    return bool(_CONSOLE_STARTING.search(text))


def missing_handler(status, body):
    """Is this the answer of a console that has no handler for the requested path at all?

    body is what the answer carried - the parsed JSON or the text.
    """
    if status != 401 or body is None:
        return False
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    return bool(_NO_HANDLER.search(text))


def _response_body(response):
    """The body of an answer: the parsed JSON, or the text when it is not JSON."""
    try:
        return response.json()
    except ValueError:
        return response.text()


def _is_busy(error):
    """Is this refusal about the application being busy rather than missing?

    The platform refuses a request to an application that is still finishing a
    previous operation with a 404 - the same status a missing application gets -
    and says which of the two it is only in the text. Everything the error carries
    is searched (the message and the body), because the wording travels in
    different fields depending on the method.
    """
    status = getattr(error, "status", None)
    if status not in (404, 409, 423):
        return False
    haystack = f"{getattr(error, 'message', '') or error} {getattr(error, 'body', '') or ''}".lower()
    return any(marker in haystack for marker in BUSY_MARKERS)


def _as_list(payload, *keys):
    """Normalize a list response to a list.

    The platform may return either an array or an object carrying the list in
    one of its fields (items or assemblies, for example).
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _collapse_reference(value):
    """Collapse a reference object down to {"id": ...} or {"name": ...}."""
    if not isinstance(value, dict):
        return None
    if value.get("id"):
        return {"id": value["id"]}
    if value.get("name"):
        return {"name": value["name"]}
    return None


# The status of a deleted application (compared case-insensitively).
DELETED_STATUS = "Deleted"

# The application card fields an application is recognized by name through.
APP_NAME_KEYS = ("name", "display-name", "publication-context")


def _is_deleted(app):
    """Whether the application is a deleted one.

    The platform does not drop deleted applications from the list, it marks
    them with the Deleted status keeping their former id. A later get or
    deploy on such an id answers 404, which is why the search skips them by
    default.
    """
    status = app.get("status")
    return isinstance(status, str) and status.strip().lower() == DELETED_STATUS.lower()


def _app_name_matches(app, target):
    """An exact, case-insensitive match of the application name."""
    for key in APP_NAME_KEYS:
        value = app.get(key)
        if isinstance(value, str) and value.strip().lower() == target:
            return True
    return False


def _app_name_contains(app, needle):
    """A case-insensitive substring occurrence in one of the application names."""
    for key in APP_NAME_KEYS:
        value = app.get(key)
        if isinstance(value, str) and needle in value.lower():
            return True
    return False


def _applied_assembly(app):
    """The id of the build the application runs, out of its card ("" when unknown)."""
    return str((app.get("source") or {}).get("project-version-id") or "")


def _is_running(app):
    return str(app.get("status") or "").strip().lower() == "running"


#: The fields an assembly card carries its id in.
ASSEMBLY_ID_KEYS = ("id", "image-id", "assembly-id")
#: Everything a caller may hold as the address of an assembly: its id or its version.
ASSEMBLY_ADDRESS_KEYS = ASSEMBLY_ID_KEYS + ("assembly-version", "project-version")


# The fields a project is named by: the manifest name and the presentation the console shows.
PROJECT_NAME_KEYS = ("name", "presentation")


def _is_deleted_project(project):
    """Whether the project is a deleted one.

    The platform does not drop deleted projects from the list either: they stay
    there with the `deleted` flag set, keeping their former id. Any true value
    of the flag counts.
    """
    return bool(project.get("deleted"))


def _project_name_contains(project, needle):
    """A case-insensitive substring occurrence in one of the project names."""
    for key in PROJECT_NAME_KEYS:
        value = project.get(key)
        if isinstance(value, str) and needle in value.lower():
            return True
    return False


def brief_app(app):
    """A brief application card: what an application is recognized and picked by.

    The full card carries user lists, development-environment flags and other
    things a listing does not need: a space of some fifty applications makes
    tens of thousands of characters of response. The version is taken from
    source - that is the build actually applied, the one a deploy is verified
    against.
    """
    source = app.get("source") or {}
    return {
        "id": app.get("id"),
        "name": app.get("name") or app.get("display-name"),
        "status": app.get("status"),
        "uri": app.get("uri"),
        "project-version": source.get("project-version"),
        "project-version-id": source.get("project-version-id"),
    }


def apps_summary(listing):
    """The count line of a listing: how many applications are alive out of how many.

    Deleted applications are hidden by default, and a cut nobody is told about is
    exactly the kind of help that misleads - so the answer of list_apps_counted is
    put into a line: how many cards the platform gave (`total`), how many of them
    are not deleted (`live`) and, when the answer holds something else than the
    live ones, how many are actually shown (`shown`). The CLI prints it, the MCP
    tool carries it in the answer.
    """
    total = listing.get("total") or 0
    live = listing.get("live") or 0
    shown = listing.get("shown") or 0
    key = "client.apps-summary" if shown == live else "client.apps-summary-shown"
    return i18n.t(key, live=live, total=total, shown=shown)


def app_users_summary(users):
    """The count line of the users connected to an application.

    Each entry of GET /applications/{id}/users says two things about its user besides who it
    is: whether they administer the application and whether they reach its HTTP services by a
    token. The line counts both, so that whether anyone can call a service with a token at
    all is read off one line rather than off every entry. The CLI prints it, the MCP tool
    carries it in the answer.
    """
    entries = [user for user in users or [] if isinstance(user, dict)]
    return i18n.t(
        "client.app-users-summary",
        total=len(entries),
        admins=sum(1 for user in entries if user.get("is-admin")),
        tokens=sum(1 for user in entries if user.get("token-access-enabled")),
    )


def brief_assembly(assembly, remembered=None):
    """A brief assembly card: what a build is recognized and picked by.

    The question a listing answers is "which commit is that build from": the
    versions, the date, the branch and the commit, plus the id an assembly is
    addressed by. The rest of the full card names the project over again or
    serves the platform itself.

    The branch and the commit come from the card when the platform filled them,
    otherwise from what this machine remembers of the upload - remembered is the
    build's entry of the local registry (registry.remembered_uploads). Which of the
    two answered is said beside each value: `branch-name-source` and
    `commit-id-source` are "platform", "registry", or null when neither knows. The
    registry alone knows `dirty` - whether the tree had uncommitted changes - and
    `project-dir`, the directory the build was made from.
    """
    remembered = remembered or {}
    brief = {
        "id": assembly.get("id"),
        "assembly-version": assembly.get("assembly-version"),
        "project-version": assembly.get("project-version"),
        "created": assembly.get("created"),
    }
    for card_field, registry_field in (("branch-name", "branch"), ("commit-id", "commit")):
        value, source = assembly.get(card_field), None
        if value:
            source = "platform"
        elif remembered.get(registry_field):
            value, source = remembered[registry_field], "registry"
        brief[card_field] = value
        brief[f"{card_field}-source"] = source
    brief["dirty"] = remembered.get("dirty")
    brief["project-dir"] = remembered.get("project-dir")
    return brief


def assembly_id_of(assembly):
    """The id of an assembly card, whichever of the id fields carries it ("" when none)."""
    if not isinstance(assembly, dict):
        return ""
    for key in ASSEMBLY_ID_KEYS:
        if assembly.get(key):
            return str(assembly[key])
    return ""


def brief_assemblies(assemblies):
    """Brief cards of a listing, each with what the local registry remembers of its upload."""
    remembered = remembered_uploads([assembly_id_of(item) for item in assemblies])
    return [
        brief_assembly(item, remembered.get(assembly_id_of(item)))
        for item in assemblies
        if isinstance(item, dict)
    ]


def applied_build(client, card):
    """The build an application runs, as a brief card with its origin; None when none is named.

    The branch and the commit of a build are on the build card, not on the card of the
    application, so the build is looked up in the list of its project; what the platform
    did not fill, the local registry of uploads may know. A list that cannot be read
    leaves the registry alone to answer: the card of the application was read, and this is
    an addition to it, not a reason to fail.
    """
    card = card if isinstance(card, dict) else {}
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    applied_id = str(source.get("project-version-id") or "")
    if not applied_id:
        return None
    project = card.get("project") if isinstance(card.get("project"), dict) else {}
    project_id = str(project.get("id") or source.get("image-id") or "")
    assembly = {"id": applied_id}
    if project_id:
        try:
            for item in client.list_assemblies(project_id):
                if isinstance(item, dict) and applied_id in {
                    str(item.get(key) or "") for key in ASSEMBLY_ID_KEYS
                }:
                    assembly = item
                    break
        except Exception:
            # Any failure of the list - the network, the rights, a stand-in without the
            # method - leaves the answer to the registry.
            pass
    return brief_assembly(assembly, remembered_uploads([applied_id]).get(applied_id))


def assembly_label(assembly_id, version=None):
    """An assembly the way a person reads it: the id, with the version beside it when known."""
    return f"{assembly_id} ({version})" if version else str(assembly_id)


def builds_summary(assemblies, shown, remembered=None):
    """The count line of a build listing: how many are shown, and is that all there is.

    Two different truths can hide behind the same listing. It may be every build the
    project has; it may be what the platform's housekeeping left of them - it deletes
    the builds nobody uses whenever an application of the project finishes applying a
    build - and then "30 of 30" reads as the whole history while it is only what survived.

    Which of the two it is comes from the ANSWER, not from its length: the platform
    numbers the builds of a base version one after another, so a hole in those numbers
    (`numbering_holes`) is a build it has already taken away. Until 0.40.0 the line was
    picked by a threshold of thirty instead - a number measured on one installation, at a
    time when we believed the platform capped the store. It does not: there is no cap, a
    listing of any length can be what survived, and thirty said nothing about either.

    A hole can also be a jump. An upload without a project id keeps the version of
    its archive, a number far above the project's count included, and the next upload into
    the project counts on from it: seen live, `1.0.0-3` was followed by `1.0.0-500` and then
    `1.0.0-501`, and the numbers between had never existed. The numbers cannot tell the two
    apart and neither can the created stamps, so the local registry of uploads does: a hole
    under a build this machine uploaded without a project id is a jump. It is named as
    one, and it is no evidence of the housekeeping. A build uploaded that way elsewhere is
    not in the registry, and its hole still reads as a deletion. remembered - the registry
    lines by build id, read here when not given.

    A hole can be a jump and a deletion at once, and the registry tells that too. Seen live:
    `1.0.0-8` was followed by `1.0.0-50`, uploaded without a project id, and by
    `1.0.0-51`, and after those two were deleted the listing went from `1.0.0-8` straight to
    `1.0.0-52`. The build above that hole was numbered by the server, so the hole read as a
    deletion alone, while most of it was a jump. And the other way round: a jump to
    `1.0.0-10` sat over `1.0.0-4`, a build this machine had uploaded into the project and
    the housekeeping had deleted, and the line called the whole hole a jump and no deletion.
    So a hole under a jump of this machine is a jump only while the registry knows no upload
    of the project inside it, and a hole with such an upload inside is named as both: the
    build that brought its number from the archive and the builds of this machine the
    listing no longer has. It counts as a loss, since a build that existed is gone.

    An empty listing and a listing without a single numbered build have no numbering to judge
    by, and the line says that instead of calling the numbering unbroken.

    Only whether there are gaps is said, never how many numbers are missing: a live
    listing showed twenty thousand of them, because one build had once been numbered
    1.0.1-19001 by an auto-increment that read the counters of another base. The verdict
    survives that; a count of "deleted builds" would have been a fabrication.

    The CLI prints the line, the MCP tool carries it in the answer.
    """
    cards = [item for item in assemblies or [] if isinstance(item, dict)]
    if not cards:
        return i18n.t("client.builds-summary-empty", shown=shown, total=len(assemblies or []))
    if not any(version_counter(item.get("assembly-version")) > 0 for item in cards):
        return i18n.t("client.builds-summary-unnumbered", shown=shown, total=len(assemblies))
    holes = numbering_holes(assemblies)
    if remembered is None:
        # The whole registry, not only the builds above the holes: the uploads inside a hole
        # are the builds the listing no longer has.
        remembered = remembered_uploads() if holes else {}
    projects = {str(card.get("project-id") or "") for card in cards} - {""}
    jumps, mixed = [], []
    for below, above in holes:
        inside = _uploads_inside(below, above, projects, remembered)
        if _kept_its_number(remembered.get(assembly_id_of(above))):
            top = _version_label(above)
        else:
            kept = [version for version, entry in inside if _kept_its_number(entry)]
            top = kept[0] if kept else ""
        if top and not inside:
            jumps.append((below, above))
        elif top:
            mixed.append((below, above, top, [version for version, _ in inside]))
    if len(jumps) < len(holes):
        key = "client.builds-summary-trimmed"
    else:
        key = "client.builds-summary-jumped" if jumps else "client.builds-summary-full"
    line = i18n.t(key, shown=shown, total=len(assemblies))
    if jumps:
        labels = ", ".join(
            f"{_version_label(below)} -> {_version_label(above)}" if below
            else _version_label(above)
            for below, above in jumps
        )
        line += i18n.t(
            "client.builds-summary-jump" if len(jumps) == 1 else "client.builds-summary-jumps",
            jumps=labels,
        )
    for below, above, top, gone in mixed:
        gap = (
            f"{_version_label(below)} -> {_version_label(above)}" if below
            else i18n.t("client.builds-summary-gap-first", above=_version_label(above))
        )
        line += i18n.t(
            "client.builds-summary-jump-and-loss", gap=gap, top=top, gone=_some(gone),
        )
    return line


#: How many versions a line names before it says how many more there are.
_NAMED_VERSIONS = 3


def _some(versions):
    """Versions for a line: the first few, and how many more there are."""
    named = ", ".join(versions[:_NAMED_VERSIONS])
    more = len(versions) - _NAMED_VERSIONS
    return i18n.t("client.builds-summary-and-more", names=named, more=more) if more > 0 else named


def _uploads_inside(below, above, projects, remembered):
    """The uploads of this machine into the project whose numbers lie inside a hole.

    [(version, registry line)], lowest number first. A number inside a hole is not in the
    listing, so each of them is a build this machine uploaded and the listing no longer has.
    """
    version = _version_label(above)
    base = version_base(version)
    low = version_counter(_version_label(below)) if below else 0
    high = version_counter(version)
    found = {}
    for entry in (remembered or {}).values():
        if not isinstance(entry, dict) or str(entry.get("project-id") or "") not in projects:
            continue
        given = str(entry.get("version") or "")
        if version_base(given) == base and low < version_counter(given) < high:
            found.setdefault(given, entry)
    return sorted(found.items(), key=lambda item: version_counter(item[0]))


def _kept_its_number(entry):
    """Whether a registry line is an upload that kept the number of its archive.

    A line written before the registry kept the route is judged by its command: a probe
    always uploads without a project id, a deploy always into a project by its id. A line
    written before the route got its present name carries the older value, and
    `upload_route` reads it as the same route.
    """
    if not isinstance(entry, dict):
        return False
    route = upload_route(entry)
    if route:
        return route == ROUTE_NO_PROJECT_ID
    return entry.get("command") == "probe"


def _version_label(assembly):
    return str(assembly.get("assembly-version") or assembly.get("project-version") or "")


#: The account a freshly created application can be signed in with. It is a code,
#: not a text: the human wording lives in the message catalog.
CONTROL_PANEL_ACCOUNT = "control-panel"


def sign_in_hint(app):
    """How to sign in to an application that has just been created.

    A new application gets its OWN, EMPTY user list, password sign-in off and
    no account service attached, so the accounts used to sign in to other
    applications do not work here - neither connecting another application's
    user list (`POST /applications/{id}/userlists`) nor enabling the local
    sign-in changes it. What does work is a CONTROL PANEL
    account: its users are connected to the application by the platform itself
    and sign in right away. Creating an application therefore ends with saying
    so out loud instead of leaving the caller to guess (section 6.11 of the
    specification).

    The card of an application that is still starting has no `uri` yet - then
    the address is missing rather than invented, and the hint says where to get
    it. Shared by the CLI and the MCP server.
    """
    card = app if isinstance(app, dict) else {}
    url = (card.get("uri") or "").strip() or None
    return {
        "url": url,
        "account": CONTROL_PANEL_ACCOUNT,
        "hint": (
            i18n.t("client.sign-in-hint", url=url) if url
            else i18n.t("client.sign-in-hint-no-uri")
        ),
        "note": i18n.t("client.sign-in-note"),
    }


#: The fields an extension applied to an application is recognized by: the id of the
#: extension, the id of its project, the name and the presentation of the project.
EXTENSION_NAME_KEYS = ("id", "project-id", "project-name", "project-presentation")

#: The kind of an extension project, as the `ProjectKind` of a manifest and the `project-kind`
#: of a project card spell it.
EXTENSION_KIND = "Extension"


def is_extension_kind(kind):
    """Whether a project kind names an extension, in either spelling a descriptor may use."""
    return str(kind or "").strip().lower() in {"extension", "расширение"}


def extension_entry(extensions, *, project_id="", vendor="", name=""):
    """The entry of `extension-projects` for the extension of a project, or None.

    The id of the project is the key. The console fills `project-id` by looking up the build of
    the version the application server runs, and a build it cannot find leaves the field empty,
    so the vendor and the name of the extension stand in for it then.
    """
    project_id = str(project_id or "")
    if project_id:
        for item in extensions:
            if str(item.get("project-id") or "") == project_id:
                return item
    pair = (str(vendor or "").strip().lower(), str(name or "").strip().lower())
    if all(pair):
        for item in extensions:
            names = (
                str(item.get("vendor-name") or "").strip().lower(),
                str(item.get("project-name") or "").strip().lower(),
            )
            if names == pair:
                return item
    return None


def _extension_names(extension):
    return {
        str(extension.get(key) or "").strip().lower() for key in EXTENSION_NAME_KEYS
    } - {""}


def extension_label(extension):
    """An extension the way a reader tells it apart: vendor/name, version and id."""
    name = extension.get("project-name") or extension.get("project-presentation") or "?"
    vendor = extension.get("vendor-name")
    label = f"{vendor}/{name}" if vendor else str(name)
    version = extension.get("assembly-version") or extension.get("project-version")
    if version:
        label += f" {version}"
    return f"{label} (id {extension.get('id') or '?'})"


def archive_manifest(data):
    """The manifest of a build archive held in memory, or None when the bytes are no archive."""
    try:
        with zipfile.ZipFile(io.BytesIO(bytes(data))) as archive:
            if MANIFEST_FILE not in archive.namelist():
                return None
            return parse_flat_yaml(archive.read(MANIFEST_FILE).decode("utf-8-sig"))
    except (zipfile.BadZipFile, ValueError):
        return None


# The characters no file name may carry on one system or another.
_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def export_file_name(manifest, card):
    """The name a build archive gets when the caller names no file: `{Name} {Version}.xasm`.

    That is the name a build of elemctl gets. The manifest of the archive is what the
    server sent, so it goes first, and the card of the extension or of the application
    covers what it lacks.
    """
    manifest = manifest or {}
    name = (
        manifest.get("Name") or card.get("project-name") or card.get("id") or "build"
    )
    version = (
        manifest.get("Version") or card.get("assembly-version")
        or card.get("project-version") or ""
    )
    stem = f"{name} {version}".strip()
    return _UNSAFE_NAME.sub("_", stem) + ".xasm"


def export_target(output, default_name):
    """Where an export goes: a file named by output, or default_name in a directory.

    An empty output is the current directory. An output that is an existing directory, or
    that ends with a separator, is a directory; anything else names the file itself.
    """
    text = str(output or "")
    if not text:
        return Path.cwd() / default_name
    path = Path(text)
    if path.is_dir() or text.endswith(("/", "\\")):
        return path / default_name
    return path


class _UnknownStreak:
    """How long a waited application has been UNKNOWN in a row (UNKNOWN_TIMEOUT).

    Every wait on the status of an application keeps the same rule, so it lives in one
    place: a status other than UNKNOWN starts the count afresh, and UNKNOWN held for limit
    seconds in a row ends the wait with an error naming the status and what it means.
    """

    def __init__(self, app_id, expected, limit, clock):
        self._app_id = app_id
        self._expected = expected
        self._limit = limit
        self._clock = clock
        self._since = None

    def check(self, card, status):
        """Count one read of the card; raise ApiError once UNKNOWN has lasted the limit."""
        if status != UNKNOWN_STATUS:
            self._since = None
            return
        now = self._clock()
        if self._since is None:
            self._since = now
        if now - self._since >= self._limit:
            raise ApiError(i18n.t(
                "client.wait-status-unknown",
                app=self._app_id,
                seconds=int(now - self._since),
                expected=self._expected,
            ), body=card)


class ElementClient:
    """A programmatic Console API v2 client."""

    def __init__(self, config, transport=None, token_cache_dir=None):
        self.config = config
        self._transport = transport or UrllibTransport(
            tls_verify=config.tls_verify,
            tls_strict=config.tls_strict,
            ca_file=config.ca_file,
            # config.no_proxy defaults to False on a Config built by hand (no from_env in
            # sight), indistinguishable from a from_env that read ELEMCTL_NO_PROXY and
            # resolved it to False - "or None" turns that default back into the transport's
            # own fallback (the process variable), the same as constructing it without the
            # argument at all. A resolved True still means True, unconditionally.
            no_proxy=config.no_proxy or None,
            # The configuration's own switch is the one to name: the check is off because
            # ELEMENT_TLS_VERIFY said so, in the environment or in the stand's .env.
            tls_off_reason=f"{BOOL_ENV_KEYS['tls_verify']}=false",
        )
        self._tokens = TokenManager(config, self._transport, cache_dir=token_cache_dir)
        # The override points for the tests: waits must not really sleep, and the time a
        # wait measures must be the time the test says has passed.
        self._sleep = time.sleep
        self._clock = time.monotonic
        # Set by waiting_for_server for the duration of its block: how long a starting
        # server is waited out, and when the current wait for it runs out.
        self._server_wait = None

    # -- low level -------------------------------------------------------

    def token(self):
        """Obtain a valid Bearer token."""
        return self._tokens.get_token()

    @contextlib.contextmanager
    def waiting_for_server(self, timeout=SERVER_START_TIMEOUT, *, poll=SERVER_START_POLL, log=None):
        """Inside the block a starting server is waited out instead of failing the request.

        Outside such a block a request to a server whose console is not up yet fails at once
        with ServerStartingError, which names the cause. Inside, the request is repeated
        every poll seconds until the console answers, for no longer than timeout seconds per
        outage; the start of the wait and its end are announced through log, as the wait for
        a busy application does. A console that refused a request never processed it, so
        repeating it is safe whatever the method. timeout=0 turns the wait off.
        """
        previous = self._server_wait
        self._server_wait = {
            "timeout": max(0.0, float(timeout or 0)),
            "poll": float(poll),
            "log": log,
            "deadline": None,
        }
        try:
            yield self
        finally:
            self._server_wait = previous

    def _request(
        self, method, path, *, query=None, json_body=None, data=None, content_type=None,
        raw=False,
    ):
        """Perform a request with the Bearer token; on a 401 refresh the token and retry once.

        A server whose console is still starting fails the request with ServerStartingError,
        unless the call runs inside waiting_for_server - then the request waits for it.
        raw=True hands a successful answer back as it came, the HttpResponse with its bytes
        and headers: a file the platform sends is neither JSON nor text.
        """
        config = self.config.require()
        url = config.base_url + path
        if query:
            filtered = {k: v for k, v in query.items() if v not in (None, "")}
            if filtered:
                url += "?" + urlencode(filtered)

        body = data
        headers = {}
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif content_type:
            headers["Content-Type"] = content_type

        while True:
            try:
                response = self._exchange(method, url, headers, body, config.timeout)
            except ServerStartingError as error:
                if self._wait_out_start(error):
                    continue
                raise
            self._server_answered()
            break

        if 200 <= response.status < 300:
            if raw:
                return response
            if not response.body:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text()
        raise self._api_error(method, url, response)

    def _exchange(self, method, url, headers, body, timeout):
        """One exchange under the Bearer token; a 401 or a stale token renews it once.

        The 401 of a console that has no handler for the path is not about the token, and it
        is recognized before a new token is asked for: a renewed token gets the same answer,
        so renewing it only costs a sign-in and a second request.
        """
        token = self._token_for(url)
        response = None
        for attempt in (1, 2):
            headers["Authorization"] = f"Bearer {token}"
            response = self._transport.request(
                method, url, headers=headers, data=body, timeout=timeout
            )
            if attempt == 1 and self._token_refused(response):
                self._tokens.invalidate()
                token = self._token_for(url, force=True)
                continue
            break
        answer = _response_body(response) if response.status == 404 else None
        if server_starting(response.status, answer):
            raise self._starting_error(method, url, response.status, answer)
        return response

    @staticmethod
    def _token_refused(response):
        """Is the answer a refusal of the token held, one that a new token may cure?"""
        if response.status == 401:
            return not missing_handler(response.status, _response_body(response))
        return _is_stale_token(response)

    def _token_for(self, url, force=False):
        """A token for the request; a token request refused by a starting server says so.

        Without a cached token the very first thing a starting server refuses is the token
        request, and its refusal used to read as a failed sign-in.
        """
        try:
            return self._tokens.get_token(force=force)
        except ServerStartingError:
            raise
        except ApiError as error:
            if server_starting(error.status, error.body):
                raise self._starting_error(
                    error.method or "POST", error.url or url, error.status, error.body
                ) from error
            raise

    def _starting_error(self, method, url, status, body):
        """The refusal of a starting server, naming the address that tells when it is up."""
        return ServerStartingError(
            i18n.t(
                "client.server-starting",
                method=method,
                url=url,
                console=self.config.base_url + "/console",
            ),
            status=status,
            method=method,
            url=url,
            body=body,
        )

    def _wait_out_start(self, error):
        """Whether the refused request is to be sent again: a wait is on and time is left.

        The clock of a wait starts at the first refusal of an outage, not at the start of
        the block: a long deploy must not spend its budget before the server goes down. When
        the time runs out, the refusal is raised with the time it was waited out for.
        """
        wait = self._server_wait
        if not wait or wait["timeout"] <= 0:
            return False
        now = self._clock()
        if wait["deadline"] is None:
            wait["deadline"] = now + wait["timeout"]
            if wait["log"]:
                wait["log"](i18n.t(
                    "client.server-starting-wait",
                    seconds=int(wait["timeout"]),
                    poll=int(wait["poll"]),
                ))
        elif now >= wait["deadline"]:
            error.message = i18n.t(
                "client.server-start-timeout",
                seconds=int(wait["timeout"]),
                method=error.method,
                url=error.url,
                console=self.config.base_url + "/console",
            )
            error.args = (error.message,)
            return False
        self._sleep(wait["poll"])
        return True

    def _server_answered(self):
        """A request got through: an outage being waited out is over, and that is said."""
        wait = self._server_wait
        if wait and wait["deadline"] is not None:
            wait["deadline"] = None
            if wait["log"]:
                wait["log"](i18n.t("client.server-started"))

    def _api(self, method, path, **kwargs):
        """A Console API v2 request (the shared /console/api/v2 prefix)."""
        return self._request(method, API_PREFIX + path, **kwargs)

    def _api_2_1(self, method, path, **kwargs):
        """A Console API 2.1 request; a server that does not know the method says so.

        Only the methods 2.0 lacks go here, the rest of the client stays on 2.0.
        """
        return self._known_method(API_2_1_PREFIX, "2.1", method, path, **kwargs)

    def _known_method(self, prefix, version, method, path, **kwargs):
        """A request to a method a server older than it has no handler for.

        A console without a handler for the path answers a 401 naming it. The exchange tells
        that answer from a refused token by its text and leaves the token alone, and here it
        is raised as UnknownMethodError, naming the method, the version of Console API it
        belongs to and the reason.
        """
        try:
            return self._request(method, prefix + path, **kwargs)
        except ApiError as error:
            if not missing_handler(error.status, error.body):
                raise
            raise UnknownMethodError(
                i18n.t("client.method-unknown", method=method, url=error.url, api=version),
                status=error.status,
                method=error.method,
                url=error.url,
                body=error.body,
            ) from error

    @staticmethod
    def _api_error(method, url, response):
        try:
            body = response.json()
        except ValueError:
            body = response.text()
        message = i18n.t("client.api-error", status=response.status, method=method, url=url)
        if isinstance(body, dict):
            for key in ("message", "error", "detail"):
                detail = body.get(key)
                if isinstance(detail, str) and detail.strip():
                    message += f": {detail.strip()}"
                    break
        return ApiError(message, status=response.status, method=method, url=url, body=body)

    def check_uri(self, uri, timeout=15.0):
        """A control GET on the application address; returns the HTTP status or None.

        The check is informational: 401/403 are normal for closed applications.
        """
        if not uri:
            return None
        try:
            response = self._transport.request("GET", uri, timeout=timeout)
            return response.status
        except Exception:
            return None

    # -- applications ------------------------------------------------------

    def list_apps(self, name="", status="", include_deleted=False):
        """The list of applications; name, status and include_deleted are filters.

        The plain list, for whoever only needs the applications; the counters
        behind the answer are what list_apps_counted adds.
        """
        return self.list_apps_counted(
            name=name, status=status, include_deleted=include_deleted
        )["items"]

    def list_apps_counted(self, name="", status="", include_deleted=False):
        """The same list plus the counters the answer has to be read against.

        Every filter runs on the client, case-insensitively: the platform ignores
        the name query parameter and returns the full list - verified by a live
        call. name matches a substring of the APP_NAME_KEYS fields; status matches
        the whole status word, and several of them may be given separated by
        commas ("running,stopped").

        Deleted applications stay in the platform list under the Deleted status
        keeping their former id, and a stand a few months old carries hundreds of
        them against a handful of live ones - so they are hidden unless
        include_deleted is True. Asking for the Deleted status by name counts as
        asking for them: a filter that answers with nothing is worse than no
        filter at all.

        Hiding cards without saying so is a trap of its own, hence the counters:
        `total` - how many the platform answered with, `live` - how many of those
        are not deleted, `shown` - how many are left in `items`. The callers that
        face a human report them (apps_summary); the library keeps the list.
        """
        payload = self._api("GET", "/applications")
        cards = _as_list(payload, "items", "applications")
        apps = [app for app in cards if isinstance(app, dict)]
        total = len(cards)
        live = sum(1 for app in apps if not _is_deleted(app))

        needle = (name or "").strip().lower()
        if needle:
            apps = [app for app in apps if _app_name_contains(app, needle)]
        wanted = {
            part.strip().lower()
            for part in str(status or "").split(",")
            if part.strip()
        }
        if wanted:
            apps = [
                app for app in apps
                if str(app.get("status") or "").lower() in wanted
            ]
        if not include_deleted and DELETED_STATUS.lower() not in wanted:
            apps = [app for app in apps if not _is_deleted(app)]
        return {"items": apps, "total": total, "live": live, "shown": len(apps)}

    def get_app(self, app_id):
        """The application card (status, uri, source.project-version and so on)."""
        return self._api("GET", f"/applications/{app_id}")

    def find_app(self, name, *, include_deleted=False):
        """Find an application by an exact, case-insensitive name match.

        The name is checked against the name, display-name and
        publication-context fields. Deleted applications (the Deleted status)
        are skipped by default: a later get or deploy on their former id
        answers 404. include_deleted=True brings the former behaviour back -
        the search covers all applications, deleted ones included. The card
        from the list is returned, or None.
        """
        target = (name or "").strip().lower()
        if not target:
            return None
        for app in self.list_apps(include_deleted=True):
            if not isinstance(app, dict):
                continue
            if not include_deleted and _is_deleted(app):
                continue
            if _app_name_matches(app, target):
                return app
        return None

    def resolve_app_id(self, name_or_id, *, include_deleted=False):
        """The application id by its name or by the id itself.

        A UUID is returned as is, without any requests. Any other value is
        looked up by an exact, case-insensitive name match (the APP_NAME_KEYS
        fields); deleted applications are skipped by default. Nothing found is
        an error; several matches is an error as well, listing the ids, because
        destructive operations (delete) must not guess.
        """
        if _looks_like_uuid(name_or_id):
            return str(name_or_id)
        target = str(name_or_id or "").strip().lower()
        if not target:
            raise ConfigError(i18n.t("client.app-not-found", name=name_or_id))
        matches = [
            app for app in self.list_apps(include_deleted=True)
            if isinstance(app, dict)
            and (include_deleted or not _is_deleted(app))
            and _app_name_matches(app, target)
        ]
        if not matches:
            raise ConfigError(i18n.t("client.app-not-found", name=name_or_id))
        if len(matches) > 1:
            ids = ", ".join(str(app.get("id")) for app in matches)
            raise ConfigError(
                i18n.t("client.app-name-ambiguous", name=name_or_id, ids=ids)
            )
        return matches[0].get("id")

    def create_app(
        self,
        display_name,
        *,
        publication_context=None,
        project_version_id=None,
        image_id=None,
        development_mode=True,
        space_id=None,
        technology_version=None,
    ):
        """Create an application.

        The source is exactly one of project_version_id (the assembly id, the
        reliable route) or image_id (the project id; on some platform
        configurations it gives an empty skeleton with no data).
        """
        if bool(project_version_id) == bool(image_id):
            raise ConfigError(i18n.t("client.app-source-exclusive"))
        source = {"type": "repository"}
        if project_version_id:
            source["project-version-id"] = project_version_id
        else:
            source["image-id"] = image_id
        body = {
            "source": source,
            "display-name": display_name,
            "publication-context": publication_context or display_name,
            "development-mode": bool(development_mode),
        }
        if space_id:
            body["space-id"] = space_id
        if technology_version:
            body["technology-version"] = technology_version
        return self._api("POST", "/applications", json_body=body)

    def delete_app(self, app_id):
        """Delete an application.

        Irreversible: a re-created application gets a different URL. If the
        development environment holds unpublished changes, the platform answers
        400 FAILED_PRECONDITION - in that case a hint is added to the error.
        """
        try:
            return self._api("DELETE", f"/applications/{app_id}")
        except ApiError as error:
            body_text = json.dumps(error.body, ensure_ascii=False) if error.body is not None else ""
            if error.status == 400 and "FAILED_PRECONDITION" in body_text:
                error.hint = i18n.t("client.delete-failed-precondition")
                error.message += " – " + error.hint
                error.args = (error.message,)
            raise

    def start_app(self, app_id):
        """Start the application."""
        return self._api("PUT", f"/applications/{app_id}/status/start")

    def stop_app(self, app_id):
        """Stop the application."""
        return self._api("PUT", f"/applications/{app_id}/status/stop")

    # -- users of an application and their access by a token -------------------

    def list_app_users(self, app_id):
        """The users connected to the application: GET /applications/{id}/users.

        An entry is {user-list-id, user-id, presentation, is-admin, token-access-enabled}.
        The users of the control panel are among them, connected by the platform itself.
        There is no login in an entry: the platform names a user of the panel by the login in
        `presentation` and any other user by its presentation, and the login itself is a field
        of the user in its list.
        """
        payload = self._api("GET", f"/applications/{app_id}/users")
        return [user for user in _as_list(payload, "items", "users") if isinstance(user, dict)]

    def current_user(self):
        """The user the credentials of this client belong to: GET /me."""
        return self._api("GET", "/me") or {}

    def _user_ids_by_login(self, connected, login):
        """The ids of the users with this login in the lists the connected users come from.

        The listing of an application names a user by a presentation only; the login is a
        field of the user in its list. Every list read here carries access tokens as well, so
        nothing but the ids leaves this method.
        """
        ids = set()
        for list_id in sorted({str(item.get("user-list-id")) for item in connected
                               if item.get("user-list-id")}):
            people = _as_list(self._api("GET", f"/user-lists/{list_id}/users"), "items", "users")
            for person in people:
                if (isinstance(person, dict)
                        and str(person.get("login") or "").strip().lower() == login):
                    ids.add(str(person.get("id") or ""))
        return ids - {""}

    def find_app_user(self, app_id, user=""):
        """The connection of one user to the application, out of list_app_users.

        user is a login, a presentation or a user id. An empty one means the user the
        credentials of this client belong to (current_user), the account elemctl itself signs
        in with. The listing names a control-panel user by the login, and a login that is not
        a presentation is looked up in the user lists of the connected users besides. No match
        is an error saying the user is not connected: the change of access for such a user is
        answered by the platform with a bare 500 "Can't change user token access". Several
        matches are an error listing the ids, as every resolution here is.
        """
        connected = self.list_app_users(app_id)
        wanted = str(user or "").strip()
        if not wanted:
            me = self.current_user()
            ids = {str(me.get("id") or "")} - {""}
            label = str(me.get("login") or me.get("presentation") or me.get("id") or "")
        elif _looks_like_uuid(wanted):
            ids, label = {wanted}, wanted
        else:
            target = wanted.lower()
            ids = {str(item.get("user-id")) for item in connected
                   if str(item.get("presentation") or "").strip().lower() == target}
            if not ids:
                ids = self._user_ids_by_login(connected, target)
            label = wanted
        matches = [item for item in connected if str(item.get("user-id") or "") in ids]
        if not matches:
            names = [str(item.get("presentation") or item.get("user-id")) for item in connected]
            shown = ", ".join(names[:10]) + (", ..." if len(names) > 10 else "")
            raise ConfigError(i18n.t(
                "client.app-user-not-connected", user=label, app=app_id,
                connected=shown or i18n.t("client.app-users-none"),
            ))
        if len(matches) > 1:
            raise ConfigError(i18n.t(
                "client.app-user-ambiguous", user=label, app=app_id,
                ids=", ".join(str(item.get("user-id")) for item in matches),
            ))
        return matches[0]

    def token_access(self, app_id, user="", enabled=None):
        """Whether a user reaches the HTTP services of the application by a token; switch it.

        The access is a flag of the user's connection to the application,
        `token-access-enabled`. Without it a call of the application's HTTP services with the
        user's token is refused with a 500 "Token access is denied", whatever the rights of the
        user. enabled=None reads the flag and changes nothing. True or False switches it
        through PUT /applications/{id}/users/change-token-access and reads the connection
        back: the answer carries the flag as the platform keeps it after the change, and a flag
        that did not move is an error rather than a report. Asking for the state that is
        already there sends no request, and `changed` says so.
        """
        entry = self.find_app_user(app_id, user)
        user_id, list_id = str(entry.get("user-id") or ""), str(entry.get("user-list-id") or "")
        report = {
            "app-id": app_id,
            "user": entry.get("presentation"),
            "user-id": user_id,
            "user-list-id": list_id,
            "token-access-enabled": bool(entry.get("token-access-enabled")),
            "changed": False,
        }
        if enabled is None or bool(enabled) == report["token-access-enabled"]:
            return report
        self._api(
            "PUT",
            f"/applications/{app_id}/users/change-token-access",
            json_body={"user-list-id": list_id, "user-id": user_id, "enable-access": bool(enabled)},
        )
        after = next(
            (item for item in self.list_app_users(app_id)
             if str(item.get("user-id") or "") == user_id
             and str(item.get("user-list-id") or "") == list_id),
            None,
        )
        label = report["user"] or user_id
        if after is None:
            raise ElemctlError(i18n.t("client.token-access-user-gone", user=label, app=app_id))
        now = bool(after.get("token-access-enabled"))
        if now is not bool(enabled):
            raise ElemctlError(i18n.t(
                "client.token-access-not-changed", user=label, app=app_id,
                wanted=str(bool(enabled)).lower(), now=str(now).lower(),
            ))
        report.update({"token-access-enabled": now, "changed": True})
        return report

    def get_debug_info(self, app_id):
        """The data for an application debug session: {debug-token, debug-address}.

        A wrapper over POST /applications/{app_id}/actions/debug (ApplicationDebugInfo).
        Requires debugging enabled on the server (config/debug.yml: enabled: true);
        the address points at the platform debug server (the WebSocket protocol),
        the token is a one-time session key. This is not application management -
        only reading the debugger connection parameters.
        """
        return self._api("POST", f"/applications/{app_id}/actions/debug")

    def apply_build(
        self,
        app_id,
        *,
        image_id=None,
        project_id=None,
        assembly_version=None,
        busy_timeout=APPLY_BUSY_TIMEOUT,
        poll=BUSY_POLL_INTERVAL,
        log=None,
    ):
        """Apply a build to the application (project/update).

        The source is either image_id (the assembly id) or project_id with an
        optional assembly_version.

        An application still finishing a previous operation refuses the call as
        busy; the apply waits it out instead of giving up, because by this point
        the build has already been uploaded and there is nothing to gain by
        throwing it away. busy_timeout=0 turns the wait off and makes the first
        refusal final.
        """
        if image_id:
            source = {"type": "repository", "image-id": image_id}
        elif project_id:
            source = {"type": "repository", "project-id": project_id}
            if assembly_version:
                source["assembly-version"] = assembly_version
        else:
            raise ConfigError(i18n.t("client.apply-source-required"))

        deadline = time.monotonic() + max(0.0, float(busy_timeout))
        waited = False
        while True:
            try:
                response = self._api(
                    "POST",
                    f"/applications/{app_id}/project/update",
                    json_body={"source": source},
                )
            except ApiError as error:
                if not _is_busy(error) or time.monotonic() >= deadline:
                    raise
                if not waited and log:
                    log(i18n.t("client.apply-busy", app=app_id, seconds=int(busy_timeout)))
                waited = True
                self._sleep(poll)
                continue
            if waited and log:
                log(i18n.t("client.apply-busy-gone"))
            return response

    def create_dump(self, app_id, *, include_users=True, include_binary_data=True, description=""):
        """Create an application dump."""
        body = {
            "include-users": bool(include_users),
            "include-binary-data": bool(include_binary_data),
            "description": description or "",
        }
        return self._api("POST", f"/applications/{app_id}/dumps", json_body=body)

    def get_dump(self, app_id, dump_id):
        """The status of an application dump."""
        return self._api("GET", f"/applications/{app_id}/dumps/{dump_id}")

    # -- the build an application runs --------------------------------------------

    def export_app_build(self, app_id):
        """The build the application runs, as the bytes of its archive.

        POST /applications/{id}/project/export of Console API 2.0; the reference documents the
        same method under 2.1. The request has no body, and the answer is the archive itself,
        `application/octet-stream` with no `Content-Disposition`: the files of the build,
        `Assembly.yaml` among them, packed anew. The manifest is the one the server keeps for
        the build, so a build uploaded into a project carries the number the server gave it.
        The console takes the archive from the application server, which gives the project it
        runs; while an update is under way, or after it has failed, the console answers with
        the build uploaded for it. The extensions applied to the application are not in the
        archive. A server without the method is refused as one that does not know it.
        """
        response = self._known_method(
            API_PREFIX, "2.0", "POST", f"/applications/{app_id}/project/export", raw=True
        )
        return response.body

    def export_app(self, app_id, output=""):
        """Save the build the application runs to a file.

        output is the file to write, or a directory for the default name `{Name}
        {Version}.xasm` taken from the manifest of the archive; empty means the current
        directory. An answer that is not a build archive is refused rather than saved under
        the name of one. Returns the report: the application, the file with its size, and the
        manifest of the archive.
        """
        data = self.export_app_build(app_id)
        manifest = archive_manifest(data)
        if manifest is None:
            raise ElemctlError(i18n.t(
                "client.app-export-not-archive",
                app=app_id,
                size=len(data),
                start=bytes(data[:80]).decode("utf-8", errors="replace"),
            ))
        path = export_target(output, export_file_name(manifest, {"id": app_id}))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {
            "app-id": app_id,
            "file": str(path.resolve()),
            "size": len(data),
            "manifest": manifest,
        }

    # -- extensions of an application (Console API 2.1) ----------------------------

    def list_app_extensions(self, app_id):
        """The extensions applied to the application: GET /applications/{id}/project of 2.1.

        The answer names the project of the application in `application-project` and the
        applied extensions in `extension-projects`. An extension carries `id`, the id the
        application server knows it by - the `Ид` of the extension's project descriptor, the
        `configuration-id` of its upload - then `project-id`, `assembly-id`, `enabled`,
        `order`, `vendor-name`, `project-name`, `project-presentation`, `project-version` and
        `assembly-version`. The console fills `assembly-id` of an extension with the id of its
        project, so the field names no build. The same path of 2.0 answers with the
        application project alone, which is why this call goes to 2.1.
        """
        payload = self._api_2_1("GET", f"/applications/{app_id}/project")
        items = payload.get("extension-projects") if isinstance(payload, dict) else None
        return [item for item in _as_list(items) if isinstance(item, dict)]

    def find_extension_build(self, assembly_id):
        """The extension project a build belongs to and the card of the build, or None.

        A build id leads to its project through the build lists alone, and the card of a
        project names its kind in `project-kind`. A stand keeps few extension projects, so the
        search is the listing of the projects and one build listing per extension project;
        deleted projects do not count. Returns `(project, assembly)`, None when no extension
        project lists the build - it is then the build of an application or of a library.
        """
        target = str(assembly_id or "")
        if not target:
            return None
        for project in self.list_projects():
            if not isinstance(project, dict) or not is_extension_kind(project.get("project-kind")):
                continue
            project_id = str(project.get("id") or "")
            if not project_id:
                continue
            for assembly in self.list_assemblies(project_id):
                if isinstance(assembly, dict) and target in {
                    str(assembly.get(key) or "") for key in ASSEMBLY_ID_KEYS
                }:
                    return project, assembly
        return None

    def find_app_extension(self, app_id, reference):
        """An extension applied to the application, by any name a caller may hold.

        The id of the extension, the id of its project, the name or the presentation of the
        project, compared exactly and without regard to case. The value is looked up in the
        list rather than sent as it is: the export answers a value the application has no
        extension for with a 500 that says nothing of the cause, so a miss is named here,
        together with the extensions the application does have. Several matches are an
        error listing them.
        """
        target = str(reference or "").strip().lower()
        extensions = self.list_app_extensions(app_id)
        matches = [item for item in extensions if target and target in _extension_names(item)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ConfigError(i18n.t(
                "client.extension-ambiguous",
                name=reference,
                app=app_id,
                extensions="; ".join(extension_label(item) for item in matches),
            ))
        raise ConfigError(i18n.t(
            "client.extension-not-found",
            name=reference,
            app=app_id,
            extensions="; ".join(extension_label(item) for item in extensions)
            or i18n.t("client.extensions-none"),
        ))

    def export_extension_build(self, app_id, extension_id):
        """The build of an extension applied to the application, as the bytes of its archive.

        POST /applications/{id}/project/{ExtensionId}/export of Console API 2.1, a method 2.0
        has not got. The request has no body, and the answer is the file itself, the archive
        the build was uploaded as, as `application/octet-stream`. The segment is the `id` of
        the extension in list_app_extensions, whatever the case of its letters: the console
        hands it on to the application server as the id of the extension there. The reference
        calls the parameter the id of the extension project, but the `project-id` of the
        listing is answered with the same bare 500 an unknown value gets.
        """
        segment = quote(str(extension_id), safe="")
        response = self._api_2_1(
            "POST", f"/applications/{app_id}/project/{segment}/export", raw=True
        )
        return response.body

    def export_extension(self, app_id, reference, output=""):
        """Save the build of an extension applied to the application to a file.

        reference names the extension the way find_app_extension takes it. output is the
        file to write, or a directory for the default name `{Name} {Version}.xasm` taken
        from the manifest of the archive; empty means the current directory. An answer that
        is not a build archive is refused rather than saved under the name of one. Returns
        the report: the application, the extension, the file with its size, and the
        manifest of the archive.
        """
        extension = self.find_app_extension(app_id, reference)
        extension_id = extension.get("id")
        if not extension_id:
            raise ElemctlError(i18n.t(
                "client.extension-without-id", extension=extension_label(extension), app=app_id
            ))
        data = self.export_extension_build(app_id, extension_id)
        manifest = archive_manifest(data)
        if manifest is None:
            raise ElemctlError(i18n.t(
                "client.extension-export-not-archive",
                extension=extension_label(extension),
                app=app_id,
                size=len(data),
                start=bytes(data[:80]).decode("utf-8", errors="replace"),
            ))
        path = export_target(output, export_file_name(manifest, extension))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {
            "app-id": app_id,
            "extension-id": extension_id,
            "project-id": extension.get("project-id"),
            "vendor-name": extension.get("vendor-name"),
            "project-name": extension.get("project-name"),
            "assembly-version": extension.get("assembly-version"),
            "enabled": extension.get("enabled"),
            "file": str(path.resolve()),
            "size": len(data),
            "manifest": manifest,
        }

    # -- technology version ------------------------------------------------

    def get_technology_version(self, app_id):
        """The technology version - out of the application card."""
        card = self.get_app(app_id) or {}
        return card.get("technology-version")

    def set_technology_version(self, version, app_ids):
        """Update the technology version of the applications; returns a group task."""
        body = {"technology-version": version, "applications": list(app_ids)}
        return self._api(
            "POST", "/tasks/group-tasks/update-applications-technology", json_body=body
        )

    def get_group_task(self, task_id):
        """The status of a group task."""
        return self._api("GET", f"/tasks/group-tasks/{task_id}")

    # -- user lists ----------------------------------------------------------

    def list_user_lists(self, name=""):
        """The list of user lists; name is an optional filter by a presentation substring.

        The filter runs on the client, case-insensitively: a user list is
        recognized by its presentation, and an application's own list is called
        after the application.
        """
        lists = _as_list(self._api("GET", "/user-lists"), "items", "user-lists")
        needle = (name or "").strip().lower()
        if not needle:
            return lists
        return [
            entry for entry in lists
            if isinstance(entry, dict) and needle in str(entry.get("presentation") or "").lower()
        ]

    def get_user_list(self, list_id):
        """The full user list card: settings of registration, passwords and account services."""
        return self._api("GET", f"/user-lists/{list_id}")

    def resolve_user_list_id(self, name_or_id):
        """The user list id by its presentation or by the id itself.

        A UUID passes through without any requests; any other value is looked up
        by an exact, case-insensitive presentation match. Nothing found is an
        error, several matches is an error listing the ids - the rules of
        resolve_app_id, for the same reason: a command that changes a setting
        must not guess which list it changes.
        """
        if _looks_like_uuid(name_or_id):
            return str(name_or_id)
        target = str(name_or_id or "").strip().lower()
        if not target:
            raise ConfigError(i18n.t("client.user-list-not-found", name=name_or_id))
        matches = [
            entry for entry in self.list_user_lists()
            if isinstance(entry, dict)
            and str(entry.get("presentation") or "").strip().lower() == target
        ]
        if not matches:
            raise ConfigError(i18n.t("client.user-list-not-found", name=name_or_id))
        if len(matches) > 1:
            ids = ", ".join(str(entry.get("id")) for entry in matches)
            raise ConfigError(
                i18n.t("client.user-list-ambiguous", name=name_or_id, ids=ids)
            )
        return matches[0].get("id")

    def app_user_list_id(self, app_id):
        """The id of the application's own (default) user list.

        The application card names it in default-user-list; that is the list the
        users of the application itself live in, as opposed to the control panel
        list also connected to the application.
        """
        card = self.get_app(self.resolve_app_id(app_id)) or {}
        list_id = card.get("default-user-list")
        if not list_id:
            raise ConfigError(i18n.t("client.app-has-no-user-list", app=app_id))
        return list_id

    def get_self_registration(self, list_id):
        """The self-registration settings of the list: enabled and what is required."""
        return self._api("GET", f"/user-lists/{list_id}/settings/self-registration")

    def set_self_registration(self, list_id, enabled):
        """Turn self-registration on or off; return the settings as they became.

        The platform expects the whole settings object, so the current one is
        read first and only the flag is replaced - the phone-required and
        email-required requirements stay as they were.
        """
        settings = dict(self.get_self_registration(list_id) or {})
        settings["enabled"] = bool(enabled)
        self._api(
            "PUT", f"/user-lists/{list_id}/settings/self-registration", json_body=settings
        )
        return self.get_self_registration(list_id)

    def list_account_services(self, list_id):
        """The account services of the list (Local, OIDC, Esia and the like)."""
        payload = self._api("GET", f"/user-lists/{list_id}/settings/account-services-settings")
        return _as_list(payload, "items", "account-services-settings")

    def update_account_service(self, list_id, service):
        """Update one account service of the list; the body is the whole entry.

        The entry is addressed by its account-service-id, and the platform wants
        it back in full - so the caller passes a card read from
        list_account_services with the fields it needs changed.
        """
        service_id = service.get("account-service-id")
        if not service_id:
            raise ConfigError(i18n.t("client.account-service-id-required"))
        return self._api(
            "PUT",
            f"/user-lists/{list_id}/settings/account-services-settings/{service_id}",
            json_body=service,
        )

    def find_account_service(self, list_id, *, service_id="", service_type=OIDC_SERVICE):
        """One account service of the list: by its id, otherwise the first of the type."""
        for service in self.list_account_services(list_id):
            if not isinstance(service, dict):
                continue
            if service_id:
                if str(service.get("account-service-id")) == str(service_id):
                    return service
                continue
            if str(service.get("account-service-type") or "").lower() == service_type.lower():
                return service
        return None

    def set_calculation_rules(self, list_id, rules, *, service_id="", service_type=OIDC_SERVICE):
        """Write the rules that build a user out of the provider's answer.

        The report is deliberately blunt about what was and was NOT confirmed. The
        platform does not return these rules in a GET of the service, so "the rules are
        in place" cannot be asserted through the API by anyone - this method included.
        What IS checked: the request was accepted, and re-reading the service shows the
        REST of its card unchanged. A PUT carries the whole entry, so a mistake here
        would quietly drop a neighbouring field - that is what the comparison catches.

        The rules are applied blind on purpose: recreating the sign-in service resets
        them, and the only way back is to write them again. Whether they took effect is
        answered by the control panel or by a live sign-in, and the report says so.
        """
        service = self.find_account_service(
            list_id, service_id=service_id, service_type=service_type
        )
        if service is None:
            return {"service": None, "sent": rules, "written": False, "rules-verified": False}
        before = dict(service)
        self.update_account_service(list_id, {**before, CALCULATION_RULES_KEY: dict(rules)})
        after = self.find_account_service(
            list_id, service_id=before.get("account-service-id"), service_type=service_type
        )
        untouched = None
        if isinstance(after, dict):
            keys = (set(before) | set(after)) - {CALCULATION_RULES_KEY}
            untouched = sorted(k for k in keys if before.get(k) != after.get(k))
        return {
            "service-id": before.get("account-service-id"),
            "service-type": before.get("account-service-type"),
            "sent": dict(rules),
            "written": True,
            # The platform answers a GET without this key - so nothing can confirm the
            # value itself, and saying "verified" here would be a lie.
            "rules-verified": False,
            "returned": (after or {}).get(CALCULATION_RULES_KEY),
            "other-fields-changed": untouched,
        }

    def set_password_login(self, list_id, enabled):
        """Allow or forbid signing in with a login and a password.

        Behind the wording of the control panel there is the account service of
        type Local: it is the one that authenticates by a password. A list
        without such a service (an application that only signs in through an
        external service) is not an error - there is simply nothing to change,
        and the answer says so.
        """
        for service in self.list_account_services(list_id):
            if not isinstance(service, dict):
                continue
            if str(service.get("account-service-type") or "").lower() != LOCAL_SERVICE.lower():
                continue
            if bool(service.get("enabled")) == bool(enabled):
                return {"service": service, "changed": False}
            updated = dict(service)
            updated["enabled"] = bool(enabled)
            self.update_account_service(list_id, updated)
            return {"service": updated, "changed": True}
        return {"service": None, "changed": False}

    # -- spaces and projects ------------------------------------------------

    def list_spaces(self):
        """The list of spaces."""
        return _as_list(self._api("GET", "/spaces"), "items", "spaces")

    def list_projects(self, name="", include_deleted=False):
        """The list of projects; name and include_deleted are optional filters.

        Both run on the client, the way list_apps does it: the platform answers
        the full list whatever the query. name is a case-insensitive substring
        of the PROJECT_NAME_KEYS fields. Deleted projects stay in the platform
        list under the `deleted` flag, and a stand a few months old carries
        hundreds of them against a handful of live ones - so they are hidden
        unless include_deleted is True, which brings the former, unfiltered
        list back.
        """
        projects = _as_list(self._api("GET", "/projects"), "items", "projects")
        needle = (name or "").strip().lower()
        if needle:
            projects = [
                project for project in projects
                if isinstance(project, dict) and _project_name_contains(project, needle)
            ]
        if not include_deleted:
            projects = [
                project for project in projects
                if not (isinstance(project, dict) and _is_deleted_project(project))
            ]
        return projects

    def get_project(self, project_id):
        """The project card."""
        return self._api("GET", f"/projects/{project_id}")

    def delete_project(self, project_id):
        """Delete a project."""
        return self._api("DELETE", f"/projects/{project_id}")

    # -- project assemblies --------------------------------------------------

    def upload_assembly(
        self,
        data,
        *,
        project_id=None,
        space_id=None,
        commit_id=None,
    ):
        """Upload an assembly file (.xasm/.xlib) to the platform.

        With project_id the assembly is added to an existing project, without
        it the platform finds the project by the Ид of the project descriptor
        and creates one when there is none. The vendor and the name of the
        manifest are no key there, only a constraint: a fresh Ид with a pair
        another project of the space holds is refused with a 409.

        The space of an upload into a project goes as the `space-id` query
        parameter, spelled the way the reference spells it: the server reads that
        one, refusing a malformed id with a 400 and an unknown space with a 404,
        and ignores the PascalCase `SpaceId` the client used to send. An upload
        without a project id documents no space parameter at all, and the server
        reads neither spelling there, so a space given for such an upload goes into
        the path instead: POST /spaces/{space-id}/projects is the method the
        reference documents for creating a project in a space. Without a space the
        upload goes to POST /projects.

        commit_id is the commit the build was made from, sent as the `commit-id`
        query parameter of an upload into an existing project: the reference
        documents it there, and the server puts it on the assembly card, which is
        what the schema guard of a deploy compares against. The same method also
        documents `branch-name`, `commit-message` and `modified`, and none of them
        is sent. The server takes them and shows none on the card: its
        `branch-name` is a branch of group development, not of git, and `modified=1`
        is refused with a 500. Creating a project documents no commit parameter
        at all, so a build that creates one carries no commit.
        """
        if project_id:
            path = f"/projects/{project_id}/assemblies"
            query = {"space-id": space_id, "commit-id": commit_id}
        elif space_id:
            path, query = f"/spaces/{space_id}/projects", {}
        else:
            path, query = "/projects", {}
        return self._api(
            "POST",
            path,
            query=query,
            data=bytes(data),
            content_type="application/octet-stream",
        )

    def list_assemblies(self, project_id):
        """The list of the project's assemblies (normalized to a list).

        The whole store, not a page of it: the method has no paging at all - limit, page,
        size, offset, skip, top and the rest are ignored, and neither the body nor the
        headers carry a total. What it leaves out is what the platform has deleted, and
        `builds_summary` says so out loud.
        """
        payload = self._api("GET", f"/projects/{project_id}/assemblies")
        return _as_list(payload, "items", "assemblies")

    def find_assembly(self, project_id, version_or_id):
        """The card of an assembly out of the project list, by its version or by its id.

        Both are addresses a caller may hold: the version is what a person reads, the id
        is what `builds list` prints and what an upload answers with. Neither is trusted
        blindly - the card is looked up in the list, so an assembly that is not there is
        named as missing instead of turning into a 404 from the depths of the platform.
        """
        for assembly in self.list_assemblies(project_id):
            if not isinstance(assembly, dict):
                continue
            if version_or_id in (
                assembly.get("assembly-version"),
                assembly.get("project-version"),
                assembly.get("id"),
            ):
                return assembly
        raise ConfigError(i18n.t(
            "client.assembly-not-found", version=version_or_id, project=project_id
        ))

    def resolve_assembly_id(self, project_id, version_or_id):
        """The assembly id by its version or by the id itself."""
        if _looks_like_uuid(version_or_id):
            return version_or_id
        return self.find_assembly(project_id, version_or_id).get("id")

    def assembly_path_segments(self, project_id, version_or_id):
        """The spellings of the last path segment of an assembly card, in the order to try.

        The method is `/projects/{id}/assemblies/{:Version}` and the segment is what its
        name says - the VERSION. Both installations we could reach answer a UUID there
        with a 404 "Assembly with version <uuid> not found": the id of a card is not an
        address. Our own pages used to claim the opposite (a UUID only, a version getting
        a 400 "Version is not a valid UUID"), and following them left `builds get` failing
        on every call, whichever form it was given.

        The version therefore comes first. The id is kept as the second candidate on
        purpose: the 400 the pages described had to come from somewhere, so an installation
        that really wants an id stays served instead of being declared impossible.
        """
        card = self.find_assembly(project_id, version_or_id)
        segments = []
        for value in (
            card.get("assembly-version"), card.get("project-version"), card.get("id")
        ):
            if value and value not in segments:
                segments.append(value)
        return segments or [version_or_id]

    def _assembly_request(self, method, project_id, version_or_id):
        """A request to the assembly card, trying every spelling of its address.

        Only a 400 and a 404 move on to the next spelling - those are the answers of a
        platform that did not understand the address. Anything else is the real answer and
        is raised as it is: a delete rejected with a 500 while the application created from
        the assembly is still alive (section 6.9) must not be retried away into a different
        error. When no spelling works, the first refusal is the one raised - it comes from
        the form the method is documented to take.
        """
        refusal = None
        for segment in self.assembly_path_segments(project_id, version_or_id):
            try:
                return self._api(method, f"/projects/{project_id}/assemblies/{segment}")
            except ApiError as error:
                if error.status not in (400, 404):
                    raise
                refusal = refusal or error
        raise refusal

    def get_assembly(self, project_id, version):
        """The assembly card by version or by id."""
        return self._assembly_request("GET", project_id, version)

    def delete_assembly(self, project_id, version):
        """Delete an assembly by version or by id."""
        return self._assembly_request("DELETE", project_id, version)

    def latest_assembly(self, project_id, base_version=None):
        """The project's latest assembly, or None.

        With base_version - the highest numeric counter among the assemblies of that
        base, the source of the auto-increment. Without it - the newest by the created
        stamp, which is what "the latest build" means when an application is created
        from it: after a base version bump the old base keeps the higher counters.
        """
        assemblies = self.list_assemblies(project_id)
        if base_version:
            return pick_latest(assemblies, base_version=base_version)
        ordered = newest_first(assemblies)
        return ordered[0] if ordered else None

    def missing_source(self, project_id, assembly_id):
        """None while the project lists the assembly; otherwise the build to take instead.

        The platform deletes the builds nobody uses, whatever their age, and it cannot create
        an application from a build it has deleted. The create is answered with a bare 400
        "Can't create application", which reads like a limit on the number of applications,
        not like a missing source. The build list says what happened before anything is
        created, so a caller looks there first.

        The build offered instead is one that an application of the project runs: the
        platform keeps such a build. A running application wins over a stopped one. Every
        field of the answer is None when no application runs a build of the project. The
        assembly counts as listed when it matches the id or the version of a card: a version
        is not an address the create takes, but it is not a deleted build either.
        """
        wanted = str(assembly_id or "").strip()
        if not wanted:
            return None
        versions = {}
        for assembly in self.list_assemblies(project_id):
            if not isinstance(assembly, dict):
                continue
            if wanted in {str(assembly.get(key) or "") for key in ASSEMBLY_ADDRESS_KEYS}:
                return None
            version = str(
                assembly.get("assembly-version") or assembly.get("project-version") or ""
            )
            for key in ASSEMBLY_ID_KEYS:
                if assembly.get(key):
                    versions[str(assembly[key])] = version
        chosen = None
        for app in self.list_apps():
            if not isinstance(app, dict) or _applied_assembly(app) not in versions:
                continue
            if chosen is None or (_is_running(app) and not _is_running(chosen)):
                chosen = app
        if chosen is None:
            return {"app": None, "app-id": None, "version-id": None, "version": None}
        applied = _applied_assembly(chosen)
        return {
            "app": chosen.get("name") or chosen.get("display-name"),
            "app-id": chosen.get("id"),
            "version-id": applied,
            # The version out of the build list, the one a build is addressed by: the server
            # numbers a build uploaded into a project itself, so it is the number to take.
            "version": versions.get(applied) or None,
        }

    # -- development-environment branches ------------------------------------

    def list_branches(self, project_id="", name=""):
        """The list of branches; the project-id and name filters are optional."""
        payload = self._api(
            "GET", "/branches", query={"project-id": project_id, "name": name}
        )
        return _as_list(payload, "items", "branches")

    def get_branch(self, branch_id):
        """The branch card."""
        return self._api("GET", f"/branches/{branch_id}")

    def create_branch(self, name, project_id, app_id=None):
        """Create a development-environment branch."""
        body = {"name": name, "kind": "development", "project": {"id": project_id}}
        if app_id:
            body["application"] = {"id": app_id}
        return self._api("POST", "/branches", json_body=body)

    def update_branch(self, branch_id, *, app_id=None, merge=False):
        """Change a branch, honouring the platform's optimistic locking.

        The card is read first, then a body made of the current values is sent
        (version-stamp must be returned exactly as it came); app_id rebinds the
        branch to an application, merge=True adds write-parameters and means
        accepting the branch's changes.
        """
        card = self.get_branch(branch_id) or {}
        body = {
            "name": card.get("name"),
            "kind": card.get("kind"),
            "deletion-mark": card.get("deletion-mark", False),
            "version-stamp": card.get("version-stamp"),
        }
        for key in ("source-branch", "application"):
            collapsed = _collapse_reference(card.get(key))
            if collapsed is not None:
                body[key] = collapsed
        if app_id:
            body["application"] = {"id": app_id}
        if merge:
            body["write-parameters"] = {"merge": True}
        return self._api("PUT", f"/branches/{branch_id}", json_body=body)

    def merge_branch(self, branch_id):
        """Accept the branch's changes (merge)."""
        return self.update_branch(branch_id, merge=True)

    def delete_branch(self, branch_id):
        """Delete a branch."""
        return self._api("DELETE", f"/branches/{branch_id}")

    # -- application tasks ----------------------------------------------------

    def _get_through_breaks(self, path):
        """A GET made again when the connection breaks off, READ_ATTEMPTS times in all."""
        for attempt in range(1, READ_ATTEMPTS + 1):
            try:
                return self._api("GET", path)
            except TransportError:
                if attempt >= READ_ATTEMPTS:
                    raise
                self._sleep(READ_RETRY_PAUSE)

    def list_app_tasks(self, app_id=""):
        """Application tasks; there is no server-side filter - we filter on the client.

        The platform hands over the tasks of every application at once, so the answer grows
        with the stand, and this is the read that breaks off. A wait for a new application
        used to end on it with a bare network error while the application went on being
        created. A broken read is made again (_get_through_breaks).
        """
        payload = self._get_through_breaks("/tasks/application-tasks")
        tasks = _as_list(payload, "items", "tasks")
        if not app_id:
            return tasks
        return [
            task
            for task in tasks
            if isinstance(task, dict) and task.get("application-id") == app_id
        ]

    def failed_task_messages(self, app_id):
        """The error texts of the application's failed tasks, the freshest first.

        The platform puts a generic "unknown error" into the application card,
        while the details (for a build - the file, the line and the column of
        every compilation error) it gives away in the task's error-message
        field. That is exactly what this method is for: without it the cause
        has to be looked for in the server logs.
        """
        messages = []
        try:
            tasks = self.list_app_tasks(app_id)
        except (ApiError, TransportError):
            return messages  # diagnostics must not replace the original error
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if str(task.get("status") or "").lower() not in FAILED_TASK_STATUSES:
                continue
            text = (task.get("error-message") or "").strip()
            if not text:
                continue
            label = task.get("operation-type") or task.get("id") or ""
            messages.append(f"{label}: {text}" if label else text)
        messages.reverse()
        return messages

    # -- waiting for states -----------------------------------------------------

    def _status_error_text(self, app_id, card):
        """The application error text, extended with the errors of its tasks.

        The card carries the platform's generic message, the details (the file,
        the line and the column of every compilation error) are in the
        application's tasks.
        """
        text = card.get("error") or i18n.t("client.no-error-text")
        details = self.failed_task_messages(app_id)
        if details:
            text += "\n" + "\n".join(details)
        return text

    def _poll_app(self, app_id, *, timeout, poll, log):
        """Read the card of the application every poll seconds; yield (card, time_is_up).

        Every wait for an application reads its card through here. A read that breaks off on
        the network is a missed poll, not the end of the wait: the platform goes on with the
        application all the same. The failure becomes the answer only when the time is up.
        The polls never end by themselves: the wait returns or raises once a card settles it
        or time_is_up comes true.
        """
        deadline = self._clock() + timeout
        while True:
            try:
                card = self.get_app(app_id) or {}
            except TransportError as error:
                if self._clock() >= deadline:
                    raise
                if log:
                    log(i18n.t("client.waiting-read-broken", error=error))
            else:
                yield card, self._clock() >= deadline
            self._sleep(poll)

    def wait_app_status(
        self,
        app_id,
        target_statuses,
        *,
        timeout,
        poll=POLL_INTERVAL,
        log=None,
        error_is_fatal=True,
        unknown_timeout=UNKNOWN_TIMEOUT,
    ):
        """Wait for one of the target application statuses; return the card.

        Error is a terminal status: with error_is_fatal (and when it is not a
        target one) the wait stops right away, carrying the error texts of the
        tasks; running out of the timeout is an error as well. UNKNOWN that lasts
        unknown_timeout seconds in a row ends the wait too, with an error of its
        own: an application without its database never leaves it, and the whole
        timeout used to be spent before the status was named. 0 refuses it on the
        first read. A read of the card that breaks off is a missed poll (_poll_app).
        """
        expected = "/".join(sorted(target_statuses))
        unknown = _UnknownStreak(app_id, expected, unknown_timeout, self._clock)
        for card, time_is_up in self._poll_app(app_id, timeout=timeout, poll=poll, log=log):
            status = (card.get("status") or "").strip()
            if status in target_statuses:
                return card
            if error_is_fatal and status == "Error":
                raise ApiError(
                    i18n.t(
                        "client.app-error-status",
                        app=app_id,
                        error=self._status_error_text(app_id, card),
                    ),
                    body=card,
                )
            unknown.check(card, status)
            if time_is_up:
                raise ApiError(i18n.t(
                    "client.wait-status-timeout",
                    expected=expected,
                    app=app_id,
                    timeout=int(timeout),
                    status=status or i18n.t("client.transitional-status"),
                ))
            if log:
                log(i18n.t("client.waiting-status", status=status or i18n.t("client.transitional")))

    def wait_app_stable(self, app_id, *, timeout=START_TIMEOUT, poll=POLL_INTERVAL, log=None):
        """Wait until the application leaves the transitional statuses."""
        return self.wait_app_status(
            app_id, STABLE_STATUSES, timeout=timeout, poll=poll, log=log, error_is_fatal=False
        )

    def wait_app_ready(
        self,
        app_id,
        *,
        timeout=READY_TIMEOUT,
        poll=POLL_INTERVAL,
        log=None,
        unknown_timeout=UNKNOWN_TIMEOUT,
    ):
        """Wait until a new application is ready: a stable status and a uri.

        The Error status during the wait is an immediate error. A read of the card that
        breaks off is a missed poll (_poll_app): the application is being created all the
        same. UNKNOWN that lasts unknown_timeout seconds in a row ends the wait with the
        error wait_app_status gives it. While the task that creates the application runs,
        the console reports Initializing whatever the server says, so UNKNOWN comes only
        after that task, and the ten minutes of READY_TIMEOUT used to be spent on it
        before the status was named.
        """
        unknown = _UnknownStreak(app_id, "Running/Stopped", unknown_timeout, self._clock)
        for card, time_is_up in self._poll_app(app_id, timeout=timeout, poll=poll, log=log):
            status = (card.get("status") or "").strip()
            if status == "Error":
                raise ApiError(
                    i18n.t(
                        "client.app-created-with-error",
                        app=app_id,
                        error=self._status_error_text(app_id, card),
                    ),
                    body=card,
                )
            if status in ("Running", "Stopped") and card.get("uri"):
                return card
            unknown.check(card, status)
            if time_is_up:
                raise ApiError(i18n.t(
                    "client.wait-ready-timeout",
                    app=app_id,
                    timeout=int(timeout),
                    status=status or i18n.t("client.transitional-status"),
                    uri=card.get("uri") or i18n.t("client.no-uri"),
                ))
            if log:
                log(i18n.t("client.waiting-ready", status=status or i18n.t("client.transitional")))

    def wait_app_deleted(self, app_id, *, timeout=DELETE_TIMEOUT, poll=POLL_INTERVAL, log=None):
        """Wait until a deleted application really disappears; True when it has.

        Deletion is asynchronous: the call returns right away, and the
        application lives on for a while with a DeleteApplication task. The
        distinction matters to whoever deletes the build afterwards - while the
        application exists, the platform rejects that with a 500. A gone
        application is a 404 to the card request or the Deleted status. Running
        out of the timeout is an answer (False), not an exception: the caller is
        cleaning up and has to report rather than fall over. A read of the card that
        breaks off is a missed poll (_poll_app). When the time runs out on such a read,
        its failure is raised: after a broken read, whether the application is still there
        is unknown.
        """
        try:
            for card, time_is_up in self._poll_app(app_id, timeout=timeout, poll=poll, log=log):
                if _is_deleted(card):
                    return True
                if time_is_up:
                    return False
                if log:
                    log(i18n.t(
                        "client.waiting-deleted",
                        status=card.get("status") or i18n.t("client.transitional"),
                    ))
        except ApiError as error:
            # The read of the card raises ApiError, and its 404 means the application is gone.
            if error.status == 404:
                return True
            raise

    def ensure_running(self, app_id, *, log=None):
        """Bring the application to the Running status after a build has been applied.

        Applying may restart the application on its own: we wait for it to
        stabilize. A stable Error is an immediate error carrying the error
        texts of the tasks: the apply has failed, a restart does not cure that,
        while waiting for Stopped out of Error used to simply eat the whole
        timeout. UNKNOWN held for UNKNOWN_TIMEOUT in a row ends every wait here
        (wait_app_status) instead of the whole timeout. When the outcome is not
        Running - we stop the application (if needed), wait for Stopped, start it
        and wait for Running.
        """
        card = self.wait_app_stable(app_id, timeout=START_TIMEOUT, log=log)
        status = card.get("status")
        if status == "Running":
            return card
        if status == "Error":
            raise ApiError(
                i18n.t(
                    "client.app-error-status",
                    app=app_id,
                    error=self._status_error_text(app_id, card),
                ),
                body=card,
            )
        if status != "Stopped":
            if log:
                log(i18n.t("client.stopping", status=status))
            self.stop_app(app_id)
            # Error is terminal here as well (error_is_fatal is on by default):
            # an application that fell over while stopping will never reach Stopped.
            self.wait_app_status(app_id, {"Stopped"}, timeout=STOP_TIMEOUT, log=log)
        if log:
            log(i18n.t("client.starting"))
        self.start_app(app_id)
        return self.wait_app_status(app_id, {"Running"}, timeout=START_TIMEOUT, log=log)
