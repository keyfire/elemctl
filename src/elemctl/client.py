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
from .errors import ApiError, ConfigError
from .transport import UrllibTransport
from .versions import pick_latest

API_PREFIX = "/console/api/v2"

# Stable application statuses; everything else (an empty string included) is transitional.
STABLE_STATUSES = {"Running", "Stopped", "Error"}

# Wait timeouts (seconds) as per section 6 of the specification.
POLL_INTERVAL = 10.0
STOP_TIMEOUT = 180.0
START_TIMEOUT = 300.0
READY_TIMEOUT = 600.0
DELETE_TIMEOUT = 180.0

# Application task statuses that mean a failure (compared case-insensitively).
FAILED_TASK_STATUSES = {"error", "failed"}

# The type of the account service that authenticates by a login and a password:
# what the control panel calls "signing in with a login and a password" is this
# service being enabled in the user list.
LOCAL_SERVICE = "Local"


def extract_assembly_id(payload):
    """Extract the assembly id out of a platform response.

    The image-id, assembly-id and id fields are checked – in exactly that order.
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
    an artifact – that artifact IS the project the build landed in (verified by a
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


def brief_app(app):
    """A brief application card: what an application is recognized and picked by.

    The full card carries user lists, development-environment flags and other
    things a listing does not need: a space of some fifty applications makes
    tens of thousands of characters of response. The version is taken from
    source – that is the build actually applied, the one a deploy is verified
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


class ElementClient:
    """A programmatic Console API v2 client."""

    def __init__(self, config, transport=None, token_cache_dir=None):
        self.config = config
        self._transport = transport or UrllibTransport()
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
            if response.status == 401 and attempt == 1:
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

    def list_apps(self, name=""):
        """The list of applications; name is an optional filter by a name substring.

        The filter runs on the client, case-insensitively (over the
        APP_NAME_KEYS fields): the platform ignores the name query parameter
        and returns the full list – verified by a live call.
        """
        payload = self._api("GET", "/applications")
        apps = _as_list(payload, "items", "applications")
        needle = (name or "").strip().lower()
        if not needle:
            return apps
        return [
            app for app in apps
            if isinstance(app, dict) and _app_name_contains(app, needle)
        ]

    def get_app(self, app_id):
        """The application card (status, uri, source.project-version and so on)."""
        return self._api("GET", f"/applications/{app_id}")

    def find_app(self, name, *, include_deleted=False):
        """Find an application by an exact, case-insensitive name match.

        The name is checked against the name, display-name and
        publication-context fields. Deleted applications (the Deleted status)
        are skipped by default: a later get or deploy on their former id
        answers 404. include_deleted=True brings the former behaviour back –
        the search covers all applications, deleted ones included. The card
        from the list is returned, or None.
        """
        target = (name or "").strip().lower()
        if not target:
            return None
        for app in self.list_apps():
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
            app for app in self.list_apps()
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
        400 FAILED_PRECONDITION – in that case a hint is added to the error.
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
        the token is a one-time session key. This is not application management –
        only reading the debugger connection parameters.
        """
        return self._api("POST", f"/applications/{app_id}/actions/debug")

    def apply_build(self, app_id, *, image_id=None, project_id=None, assembly_version=None):
        """Apply a build to the application (project/update).

        The source is either image_id (the assembly id) or project_id with an
        optional assembly_version.
        """
        if image_id:
            source = {"type": "repository", "image-id": image_id}
        elif project_id:
            source = {"type": "repository", "project-id": project_id}
            if assembly_version:
                source["assembly-version"] = assembly_version
        else:
            raise ConfigError(i18n.t("client.apply-source-required"))
        return self._api(
            "POST", f"/applications/{app_id}/project/update", json_body={"source": source}
        )

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
        """The technology version – out of the application card."""
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
        error, several matches is an error listing the ids – the rules of
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
        read first and only the flag is replaced – the phone-required and
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
        it back in full – so the caller passes a card read from
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

    def set_password_login(self, list_id, enabled):
        """Allow or forbid signing in with a login and a password.

        Behind the wording of the control panel there is the account service of
        type Local: it is the one that authenticates by a password. A list
        without such a service (an application that only signs in through an
        external service) is not an error – there is simply nothing to change,
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

    def list_projects(self):
        """The list of projects."""
        return _as_list(self._api("GET", "/projects"), "items", "projects")

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
        branch_name=None,
        commit_id=None,
        commit_message=None,
    ):
        """Upload an assembly file (.xasm/.xlib) to the platform.

        With project_id the assembly is added to an existing project, without
        it a new project is created. The platform spells its query parameter
        names in PascalCase.
        """
        path = f"/projects/{project_id}/assemblies" if project_id else "/projects"
        query = {
            "SpaceId": space_id,
            "BranchName": branch_name,
            "CommitId": commit_id,
            "CommitMessage": commit_message,
        }
        return self._api(
            "POST",
            path,
            query=query,
            data=bytes(data),
            content_type="application/octet-stream",
        )

    def list_assemblies(self, project_id):
        """The list of the project's assemblies (normalized to a list)."""
        payload = self._api("GET", f"/projects/{project_id}/assemblies")
        return _as_list(payload, "items", "assemblies")

    def resolve_assembly_id(self, project_id, version_or_id):
        """The assembly id by its version or by the id itself.

        The API addresses an assembly by UUID only (to a version it answers 400 "Version
        is not a valid UUID"); the version, on top of that, is renumbered the platform's
        own way on upload. A non-UUID argument is looked up in the list of assemblies by
        assembly-version / project-version.
        """
        if _looks_like_uuid(version_or_id):
            return version_or_id
        for assembly in self.list_assemblies(project_id):
            if version_or_id in (
                assembly.get("assembly-version"), assembly.get("project-version")
            ):
                return assembly.get("id")
        raise ConfigError(i18n.t(
            "client.assembly-not-found", version=version_or_id, project=project_id
        ))

    def get_assembly(self, project_id, version):
        """The assembly card by version or by id."""
        assembly_id = self.resolve_assembly_id(project_id, version)
        return self._api("GET", f"/projects/{project_id}/assemblies/{assembly_id}")

    def delete_assembly(self, project_id, version):
        """Delete an assembly by version or by id."""
        assembly_id = self.resolve_assembly_id(project_id, version)
        return self._api("DELETE", f"/projects/{project_id}/assemblies/{assembly_id}")

    def latest_assembly(self, project_id):
        """The project's latest assembly by the numeric version counter, or None."""
        return pick_latest(self.list_assemblies(project_id))

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

    def list_app_tasks(self, app_id=""):
        """Application tasks; there is no server-side filter – we filter on the client."""
        payload = self._api("GET", "/tasks/application-tasks")
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
        while the details (for a build – the file, the line and the column of
        every compilation error) it gives away in the task's error-message
        field. That is exactly what this method is for: without it the cause
        has to be looked for in the server logs.
        """
        messages = []
        try:
            tasks = self.list_app_tasks(app_id)
        except ApiError:
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
        tasks; running out of the timeout is an error as well.
        """
        deadline = time.monotonic() + timeout
        while True:
            card = self.get_app(app_id) or {}
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
            if time.monotonic() >= deadline:
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
            self._sleep(poll)

    def wait_app_stable(self, app_id, *, timeout=START_TIMEOUT, poll=POLL_INTERVAL, log=None):
        """Wait until the application leaves the transitional statuses."""
        return self.wait_app_status(
            app_id, STABLE_STATUSES, timeout=timeout, poll=poll, log=log, error_is_fatal=False
        )

    def wait_app_ready(self, app_id, *, timeout=READY_TIMEOUT, poll=POLL_INTERVAL, log=None):
        """Wait until a new application is ready: a stable status and a uri.

        The Error status during the wait is an immediate error.
        """
        deadline = time.monotonic() + timeout
        while True:
            card = self.get_app(app_id) or {}
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
            if time.monotonic() >= deadline:
                raise ApiError(i18n.t(
                    "client.wait-ready-timeout",
                    app=app_id,
                    timeout=int(timeout),
                    status=status or i18n.t("client.transitional-status"),
                    uri=card.get("uri") or i18n.t("client.no-uri"),
                ))
            if log:
                log(i18n.t("client.waiting-ready", status=status or i18n.t("client.transitional")))
            self._sleep(poll)

    def wait_app_deleted(self, app_id, *, timeout=DELETE_TIMEOUT, poll=POLL_INTERVAL, log=None):
        """Wait until a deleted application really disappears; True when it has.

        Deletion is asynchronous: the call returns right away, and the
        application lives on for a while with a DeleteApplication task. The
        distinction matters to whoever deletes the build afterwards – while the
        application exists, the platform rejects that with a 500. A gone
        application is a 404 to the card request or the Deleted status. Running
        out of the timeout is an answer (False), not an exception: the caller is
        cleaning up and has to report rather than fall over.
        """
        deadline = time.monotonic() + timeout
        while True:
            try:
                card = self.get_app(app_id) or {}
            except ApiError as error:
                if error.status == 404:
                    return True
                raise
            if _is_deleted(card):
                return True
            if time.monotonic() >= deadline:
                return False
            if log:
                log(i18n.t(
                    "client.waiting-deleted",
                    status=card.get("status") or i18n.t("client.transitional"),
                ))
            self._sleep(poll)

    def ensure_running(self, app_id, *, log=None):
        """Bring the application to the Running status after a build has been applied.

        Applying may restart the application on its own: we wait for it to
        stabilize. A stable Error is an immediate error carrying the error
        texts of the tasks: the apply has failed, a restart does not cure that,
        while waiting for Stopped out of Error used to simply eat the whole
        timeout. When the outcome is not Running – we stop the application (if
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
