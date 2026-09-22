"""Console API v2 client of the 1C:Enterprise.Element platform.

The client prints nothing by itself: the progress of long operations is handed
out through the log callback the caller passes in.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlencode

from . import i18n
from .auth import TokenManager
from .errors import ApiError, ConfigError, TransportError
from .transport import UrllibTransport
from .versions import missing_counters, newest_first, pick_latest

API_PREFIX = "/console/api/v2"

# Stable application statuses; everything else (an empty string included) is transitional.
STABLE_STATUSES = {"Running", "Stopped", "Error"}

# Wait timeouts (seconds) as per section 6 of the specification.
POLL_INTERVAL = 10.0
STOP_TIMEOUT = 180.0
START_TIMEOUT = 300.0
READY_TIMEOUT = 600.0
DELETE_TIMEOUT = 180.0

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


def brief_assembly(assembly):
    """A brief assembly card: what a build is recognized and picked by.

    The question a listing answers is "which commit is that build from": the
    versions, the date, the branch and the commit, plus the id an assembly is
    addressed by. The rest of the full card names the project over again or
    serves the platform itself.
    """
    return {
        "id": assembly.get("id"),
        "assembly-version": assembly.get("assembly-version"),
        "project-version": assembly.get("project-version"),
        "created": assembly.get("created"),
        "branch-name": assembly.get("branch-name"),
        "commit-id": assembly.get("commit-id"),
    }


def assembly_label(assembly_id, version=None):
    """An assembly the way a person reads it: the id, with the version beside it when known."""
    return f"{assembly_id} ({version})" if version else str(assembly_id)


def builds_summary(assemblies, shown):
    """The count line of a build listing: how many are shown, and is that all there is.

    Two different truths can hide behind the same listing. It may be every build the
    project has; it may be what the platform's housekeeping left of them - it deletes
    the builds nobody uses - and then "30 of 30" reads as the whole history while it is
    only what survived.

    Which of the two it is comes from the ANSWER, not from its length: the platform
    numbers the builds of a base version one after another, so a gap in those numbers is
    a build it has already taken away (`missing_counters`). Until 0.40.0 the line was
    picked by a threshold of thirty instead - a number measured on one installation, at a
    time when we believed the platform capped the store. It does not: there is no cap, a
    listing of any length can be what survived, and thirty said nothing about either.

    Only whether there are gaps is said, never how many numbers are missing: a live
    listing showed twenty thousand of them, because one build had once been numbered
    1.0.1-19001 by an auto-increment that read the counters of another base. The verdict
    survives that; a count of "deleted builds" would have been a fabrication.

    The CLI prints the line, the MCP tool carries it in the answer.
    """
    key = ("client.builds-summary-trimmed" if missing_counters(assemblies)
           else "client.builds-summary-full")
    return i18n.t(key, shown=shown, total=len(assemblies))


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
        )
        self._tokens = TokenManager(config, self._transport, cache_dir=token_cache_dir)
        # The override point for the tests: waits must not really sleep.
        self._sleep = time.sleep

    # -- low level -------------------------------------------------------

    def token(self):
        """Obtain a valid Bearer token."""
        return self._tokens.get_token()

    def _request(self, method, path, *, query=None, json_body=None, data=None, content_type=None):
        """Perform a request with the Bearer token; on a 401 refresh the token and retry once."""
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

        token = self._tokens.get_token()
        response = None
        for attempt in (1, 2):
            headers["Authorization"] = f"Bearer {token}"
            response = self._transport.request(
                method, url, headers=headers, data=body, timeout=config.timeout
            )
            if attempt == 1 and (response.status == 401 or _is_stale_token(response)):
                self._tokens.invalidate()
                token = self._tokens.get_token(force=True)
                continue
            break

        if 200 <= response.status < 300:
            if not response.body:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text()
        raise self._api_error(method, url, response)

    def _api(self, method, path, **kwargs):
        """A Console API v2 request (the shared /console/api/v2 prefix)."""
        return self._request(method, API_PREFIX + path, **kwargs)

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
    ):
        """Upload an assembly file (.xasm/.xlib) to the platform.

        With project_id the assembly is added to an existing project, without
        it a new project is created. The platform spells its query parameter
        names in PascalCase.

        No commit or branch parameters: the documented method does not take
        them, and the server ignores them when sent - proven by a direct POST
        with a real commit hash answered by `commit-id: null`. The commit on an
        assembly card comes from the project's link to its repository, not from
        the upload.
        """
        path = f"/projects/{project_id}/assemblies" if project_id else "/projects"
        return self._api(
            "POST",
            path,
            query={"SpaceId": space_id},
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
            # The version out of the build list: a fresh application numbers the versions on
            # its card from scratch, so the card would name another number for the same build.
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
        deadline = time.monotonic() + timeout
        while True:
            try:
                card = self.get_app(app_id) or {}
            except TransportError as error:
                if time.monotonic() >= deadline:
                    raise
                if log:
                    log(i18n.t("client.waiting-read-broken", error=error))
            else:
                yield card, time.monotonic() >= deadline
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
    ):
        """Wait for one of the target application statuses; return the card.

        Error is a terminal status: with error_is_fatal (and when it is not a
        target one) the wait stops right away, carrying the error texts of the
        tasks; running out of the timeout is an error as well. A read of the card
        that breaks off is a missed poll (_poll_app).
        """
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
            if time_is_up:
                expected = "/".join(sorted(target_statuses))
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

    def wait_app_ready(self, app_id, *, timeout=READY_TIMEOUT, poll=POLL_INTERVAL, log=None):
        """Wait until a new application is ready: a stable status and a uri.

        The Error status during the wait is an immediate error. A read of the card that
        breaks off is a missed poll (_poll_app): the application is being created all the
        same.
        """
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
        timeout. When the outcome is not Running - we stop the application (if
        needed), wait for Stopped, start it and wait for Running.
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
