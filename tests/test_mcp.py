"""MCP server tests: the tool set matches section 8 of the specification."""

from __future__ import annotations

import asyncio
import importlib.util
import itertools
import json
import sys
import threading
import time
import types

import pytest

# Either major version of the mcp package carries the server class, under a
# different name; the extra is what may be missing.
pytest.importorskip("mcp.server", reason="extra elemctl[mcp] не установлен")

from elemctl.client import brief_app, brief_assembly
from elemctl.mcp_server import (
    INSTRUCTIONS,
    _brief_project,
    call_result_content,
    create_server,
    tool_input_schema,
)

EXPECTED_TOOLS = {
    "list_apps",
    "get_app",
    "find_app",
    "create_app",
    "ensure_app",
    "start_app",
    "stop_app",
    "debug_info",
    "debug_adapter",
    "delete_app",
    "list_spaces",
    "list_projects",
    "list_builds",
    "get_build",
    "build_assembly",
    "inspect_assembly",
    "deploy",
    "probe",
    "apply_build",
    "verify_deploy",
    "list_user_lists",
    "configure_user_list",
    "list_app_tasks",
    "list_branches",
    "merge_branch",
}


def test_tool_set_matches_spec():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


def test_server_name_and_rollback_warning():
    server = create_server()
    assert server.name == "elemctl"
    assert "откатывает" in INSTRUCTIONS
    assert "Running" in INSTRUCTIONS


def test_delete_app_docstring_warns():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    delete_tool = next(tool for tool in tools if tool.name == "delete_app")
    assert "URL" in (delete_tool.description or "")


def test_ensure_app_docstring_states_no_recreate():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    ensure_tool = next(tool for tool in tools if tool.name == "ensure_app")
    description = ensure_tool.description or ""
    assert "пересозда" in description  # an existing application is NOT re-created
    assert "created" in description


def test_find_app_exposes_include_deleted():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    find_tool = next(tool for tool in tools if tool.name == "find_app")
    properties = tool_input_schema(find_tool).get("properties") or {}
    assert "include_deleted" in properties


def test_every_platform_tool_accepts_env_file():
    """The environment is picked per call, not only when the server starts.

    Otherwise a single server serves a single stand only, and the second one (a local
    stand, say) is out of reach through MCP - one has to fall back to the CLI.
    """
    server = create_server()
    tools = asyncio.run(server.list_tools())
    local_only = {"build_assembly", "inspect_assembly", "debug_adapter"}
    for tool in tools:
        if tool.name in local_only:
            continue  # these never reach out to the platform
        properties = tool_input_schema(tool).get("properties") or {}
        assert "env_file" in properties, tool.name
    assert "env_file" in INSTRUCTIONS


def test_list_apps_is_brief_by_default():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    list_tool = next(tool for tool in tools if tool.name == "list_apps")
    properties = tool_input_schema(list_tool).get("properties") or {}
    assert properties.get("brief", {}).get("default") is True


def test_list_apps_docstring_states_that_the_deleted_ones_are_hidden():
    """An agent reads the docstring and nothing else: a cut it is not told about
    would read as "the stand holds seven applications"."""
    server = create_server()
    tools = asyncio.run(server.list_tools())
    list_tool = next(tool for tool in tools if tool.name == "list_apps")
    description = list_tool.description or ""
    assert "Deleted" in description
    assert "СКРЫТЫ" in description
    assert "include_deleted" in description


def test_list_projects_is_brief_by_default():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    list_tool = next(tool for tool in tools if tool.name == "list_projects")
    properties = tool_input_schema(list_tool).get("properties") or {}
    assert properties.get("brief", {}).get("default") is True


def test_list_builds_is_brief_and_limited_by_default():
    """A project holds assemblies by the thousand: the full list floods the response."""
    server = create_server()
    tools = asyncio.run(server.list_tools())
    list_tool = next(tool for tool in tools if tool.name == "list_builds")
    properties = tool_input_schema(list_tool).get("properties") or {}
    assert properties.get("brief", {}).get("default") is True
    assert properties.get("limit", {}).get("default") == 10


def test_list_builds_says_whether_the_listing_is_all_there_is(monkeypatch):
    """An agent sees the JSON alone, so the answer carries the counters and the verdict.

    The platform deletes the builds nobody uses, whatever their age; a bare array of cards
    let a listing read as "the project has these builds". The verdict is read off the
    numbering of the WHOLE answer, not of the cards that survived the limit - here the
    missing number is far below the ten that come back.
    """
    cards = [
        {
            "id": f"asm-{number}",
            "assembly-version": f"1.0-{number}",
            "project-version": f"1.0-{number}",
            "created": f"2026-01-01T10:00:{number:02d}.000Z",
            "branch-name": None,
            "commit-id": f"c{number}",
            "project-name": "crm",
        }
        for number in range(1, 21)
        if number != 3
    ]

    class FakeClient:
        def list_assemblies(self, project_id):
            assert project_id == "proj-1"
            return cards

    server = _server_on(monkeypatch, FakeClient())

    result = asyncio.run(server.call_tool("list_builds", {"project_id": "proj-1"}))
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["total"] == 19
    assert payload["shown"] == 10
    assert "НЕ вся история" in payload["summary"]
    assert len(payload["builds"]) == 10
    assert set(payload["builds"][0]) == {
        "id", "assembly-version", "project-version", "created", "branch-name", "commit-id",
    }


def test_list_builds_calls_a_short_listing_complete(monkeypatch):
    class FakeClient:
        def list_assemblies(self, project_id):
            return [{"id": "asm-1", "assembly-version": "1.0-1", "created": "2026-01-01"}]

    server = _server_on(monkeypatch, FakeClient())

    result = asyncio.run(server.call_tool("list_builds", {"project_id": "proj-1"}))
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["total"] == payload["shown"] == 1
    assert "все сборки проекта" in payload["summary"]


def test_get_build_asks_the_client_for_the_card_by_version(monkeypatch):
    """The card of one build, whole - the listing only ever carried the brief cards.

    The address is the VERSION: the value goes to the client as it came, and the client is
    the one that looks it up in the listing (an id is an address a caller holds too).
    """
    asked = []

    class FakeClient:
        def get_assembly(self, project_id, version):
            asked.append((project_id, version))
            return {"id": "asm-42", "assembly-version": "1.0-42", "project-developer": "acme"}

    server = _server_on(monkeypatch, FakeClient())

    result = asyncio.run(
        server.call_tool("get_build", {"project_id": "proj-1", "version": "1.0-42"}))
    payload = json.loads(call_result_content(result)[0].text)

    assert asked == [("proj-1", "1.0-42")]
    assert payload["project-developer"] == "acme"


def test_get_build_says_the_address_is_the_version(monkeypatch):
    """An agent reads the hint and nothing else, and this is where the wrong form cost a day."""
    server = create_server()
    tools = asyncio.run(server.list_tools())
    tool = next(tool for tool in tools if tool.name == "get_build")
    description = tool.description or ""

    assert "ВЕРСИЯ" in description
    assert "404" in description
    properties = tool_input_schema(tool).get("properties") or {}
    assert set(properties) >= {"project_id", "version", "env_file"}


def test_brief_assembly_keeps_only_the_identifying_fields():
    card = {
        "id": "asm-1",
        "assembly-version": "1.0-3",
        "project-version": "1.0-3",
        "created": "2026-01-01T10:00:00.000Z",
        "branch-name": "main",
        "commit-id": "abc123",
        "project-name": "crm",
        "project-developer": "acme",
        "project-id": "proj-1",
        "modified": False,
        "comment": "",
    }
    assert brief_assembly(card) == {
        "id": "asm-1",
        "assembly-version": "1.0-3",
        "project-version": "1.0-3",
        "created": "2026-01-01T10:00:00.000Z",
        "branch-name": "main",
        "commit-id": "abc123",
    }


def test_brief_project_keeps_only_the_identifying_fields():
    card = {
        "id": "proj-1",
        "name": "crm",
        "project-kind": "Application",
        "space-id": "space-1",
        "application-count": 2,
        "deleted": False,
        "code": "ART00000000000000000001",
        "group-id": "grp-1",
        "presentation": "crm",
        "default-image": {"id": "img-1", "version": "1.0-1"},
        "date-created": "2026-01-01T00:00:00Z",
        "description": "",
        "parent-id": None,
    }
    brief = _brief_project(card)
    assert brief == {
        "id": "proj-1",
        "name": "crm",
        "project-kind": "Application",
        "space-id": "space-1",
        "application-count": 2,
        "deleted": False,
    }


def test_brief_app_keeps_only_the_identifying_fields():
    card = {
        "id": "app-1",
        "name": "site",
        "display-name": "site",
        "status": "Running",
        "uri": "https://host/applications/site",
        "user-lists": ["u1", "u2"],
        "description": "",
        "source": {"project-version": "1.0.0-3", "project-version-id": "asm-1", "type": "image"},
    }
    brief = brief_app(card)
    assert brief == {
        "id": "app-1",
        "name": "site",
        "status": "Running",
        "uri": "https://host/applications/site",
        "project-version": "1.0.0-3",
        "project-version-id": "asm-1",
    }


def test_app_tools_accept_name_in_docstring():
    """Tools that take an app_id parameter also accept the exact application name.

    client.resolve_app_id does the resolving; what is pinned here is that the tool
    description says so - otherwise an agent never learns the option is there.
    """
    server = create_server()
    tools = asyncio.run(server.list_tools())
    by_name = {tool.name: tool for tool in tools}
    for name in ("get_app", "delete_app", "start_app", "stop_app", "debug_info"):
        description = by_name[name].description or ""
        assert "имя" in description, name


def _server_on(monkeypatch, fake_client):
    """A server whose every environment answers with the given stand-in client."""
    from elemctl import mcp_server
    from elemctl.config import Config

    monkeypatch.setattr(mcp_server, "ElementClient", lambda config: fake_client)
    return create_server(
        Config(base_url="https://api.test", client_id="cid", client_secret="secret")
    )


def test_ensure_app_returns_the_way_in(monkeypatch):
    """An agent sees only the JSON, so the way into the stand has to be inside it.

    Both answers of ensure carry it - the application already existed just as
    often as it is created.
    """

    class FakeClient:
        def find_app(self, name, *, include_deleted=False):
            return {"id": "app-7", "display-name": name, "uri": "https://host/apps/crm-dev"}

    server = _server_on(monkeypatch, FakeClient())

    result = asyncio.run(server.call_tool("ensure_app", {"name": "crm-dev"}))
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["id"] == "app-7"
    assert payload["created"] is False
    assert payload["sign-in"]["url"] == "https://host/apps/crm-dev"
    assert payload["sign-in"]["account"] == "control-panel"
    assert "другие приложения" in payload["sign-in"]["note"]


def test_list_apps_hides_the_deleted_ones_and_says_how_many(monkeypatch):
    """Hiding cards silently is a trap of its own: the answer of the tool carries the
    counters and the ready line next to the applications themselves."""

    class FakeClient:
        def list_apps_counted(self, name="", status="", include_deleted=False):
            assert (name, status, include_deleted) == ("", "", False)
            return {
                "items": [{"id": "1", "name": "crm-dev", "status": "Running", "users": ["a"]}],
                "total": 324,
                "live": 1,
                "shown": 1,
            }

    server = _server_on(monkeypatch, FakeClient())

    result = asyncio.run(server.call_tool("list_apps", {}))
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["total"] == 324
    assert payload["live"] == 1
    assert payload["shown"] == 1
    assert payload["summary"] == "живых 1 из 324"
    assert payload["applications"] == [
        {
            "id": "1",
            "name": "crm-dev",
            "status": "Running",
            "uri": None,
            "project-version": None,
            "project-version-id": None,
        }
    ]


def test_list_apps_passes_include_deleted_and_keeps_the_full_cards_on_demand(monkeypatch):
    class FakeClient:
        def list_apps_counted(self, name="", status="", include_deleted=False):
            assert (name, include_deleted) == ("crm", True)
            items = [{"id": "2", "name": "crm-old", "status": "Deleted", "users": ["a"]}]
            return {"items": items, "total": 4, "live": 1, "shown": 1}

    server = _server_on(monkeypatch, FakeClient())

    result = asyncio.run(
        server.call_tool(
            "list_apps", {"name": "crm", "include_deleted": True, "brief": False}
        )
    )
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["summary"] == "живых 1 из 4"
    assert payload["applications"][0]["users"] == ["a"]


def test_list_projects_passes_the_filters_and_keeps_the_cards_brief(monkeypatch):
    """The listing of a long-lived stand is hundreds of cards, most of them deleted:
    the filters go to the client, and the answer stays brief by default."""

    class FakeClient:
        def list_projects(self, name="", include_deleted=False):
            assert name == "crm"
            assert include_deleted is True
            return [{"id": "p1", "name": "crm", "deleted": True, "code": "ART1", "group-id": "g"}]

    server = _server_on(monkeypatch, FakeClient())

    result = asyncio.run(
        server.call_tool("list_projects", {"name": "crm", "include_deleted": True})
    )
    payload = json.loads(call_result_content(result)[0].text)

    assert payload == {
        "id": "p1",
        "name": "crm",
        "project-kind": None,
        "space-id": None,
        "application-count": None,
        "deleted": True,
    }


def test_create_app_adds_the_way_in_to_the_card(monkeypatch):
    """create_app keeps answering with the platform card; the hint is an addition."""

    class FakeClient:
        def create_app(self, display_name, **kwargs):
            return {"id": "app-new", "display-name": display_name, "uri": "https://host/apps/new"}

    server = _server_on(monkeypatch, FakeClient())

    result = asyncio.run(
        server.call_tool("create_app", {"name": "crm-dev", "version_id": "asm-1"})
    )
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["id"] == "app-new"
    assert payload["display-name"] == "crm-dev"
    assert payload["sign-in"]["url"] == "https://host/apps/new"


def _stub_mcp_verify(monkeypatch, ok=True):
    """Stub the verification of the server and keep what it was called with."""
    from elemctl import mcp_server

    calls = []

    class Report:
        def __init__(self):
            self.ok = ok

        def to_dict(self):
            return {"ok": ok, "applied": ok}

    def fake(client, app_id, **kwargs):
        calls.append((app_id, kwargs))
        return Report()

    monkeypatch.setattr(mcp_server, "_verify_deploy", fake)
    return calls


class FakeCreatingClient:
    """Creates an application and reports what it was asked to wait for."""

    def __init__(self, exists=None):
        self.exists = exists
        self.waited = []

    def find_app(self, name, *, include_deleted=False):
        return self.exists

    def create_app(self, display_name, **kwargs):
        return {"id": "app-new", "display-name": display_name, "status": "Creating"}

    def wait_app_ready(self, app_id, log=None):
        self.waited.append(app_id)
        return {"id": app_id, "status": "Running", "uri": "https://host/apps/new"}


def test_create_app_verify_proves_the_build_really_landed(monkeypatch):
    """A card is not proof: a failed apply is rolled back and the status still says Running."""
    fake = FakeCreatingClient()
    server = _server_on(monkeypatch, fake)
    calls = _stub_mcp_verify(monkeypatch, ok=False)

    result = asyncio.run(
        server.call_tool(
            "create_app", {"name": "crm-dev", "version_id": "asm-1", "verify": True}
        )
    )
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["verify"]["ok"] is False
    assert fake.waited == ["app-new"]
    assert calls[0][1]["expected_assembly_id"] == "asm-1"


def test_create_app_without_verify_neither_waits_nor_checks(monkeypatch):
    fake = FakeCreatingClient()
    server = _server_on(monkeypatch, fake)

    result = asyncio.run(
        server.call_tool("create_app", {"name": "crm-dev", "version_id": "asm-1"})
    )
    payload = json.loads(call_result_content(result)[0].text)

    assert "verify" not in payload
    assert fake.waited == []


def test_ensure_app_created_application_no_longer_claims_applied_on_trust(monkeypatch):
    fake = FakeCreatingClient()
    server = _server_on(monkeypatch, fake)
    _stub_mcp_verify(monkeypatch, ok=False)

    result = asyncio.run(
        server.call_tool(
            "ensure_app", {"name": "crm-dev", "version_id": "asm-1", "verify": True}
        )
    )
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["created"] is True
    assert payload["applied"] is False
    assert payload["verify"]["ok"] is False


def test_ensure_app_verify_checks_the_application_it_found(monkeypatch):
    """The card of an existing application matches - --verify asks whether it is alive."""
    existing = {
        "id": "app-7",
        "display-name": "crm-dev",
        "uri": "https://host/apps/crm-dev",
        "source": {"project-version-id": "asm-1"},
    }
    fake = FakeCreatingClient(exists=existing)
    server = _server_on(monkeypatch, fake)
    calls = _stub_mcp_verify(monkeypatch, ok=False)

    result = asyncio.run(
        server.call_tool(
            "ensure_app", {"name": "crm-dev", "version_id": "asm-1", "verify": True}
        )
    )
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["created"] is False
    assert payload["applied"] is False
    assert payload["verify"]["ok"] is False
    assert calls[0][0] == "app-7"


def test_ensure_app_keeps_the_id_when_the_wait_breaks_off(monkeypatch):
    """The tool twin of the CLI answer: the created application is not lost with the wait."""
    from elemctl.errors import TransportError

    class BrokenWait(FakeCreatingClient):
        def wait_app_ready(self, app_id, log=None):
            raise TransportError("сетевая ошибка: обрыв")

    server = _server_on(monkeypatch, BrokenWait())

    result = asyncio.run(
        server.call_tool(
            "ensure_app", {"name": "crm-dev", "version_id": "asm-1", "verify": True}
        )
    )
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["id"] == "app-new"
    assert payload["created"] is True
    assert payload["applied"] is None
    assert "обрыв" in payload["wait-error"]["error"]


def _root_elemctl_error_message(exc):
    """The text of our own error inside a tool-call exception, whichever major wrapped it."""
    from elemctl.errors import ElemctlError

    seen = exc
    while seen is not None:
        if isinstance(seen, ElemctlError):
            return str(seen)
        seen = seen.__cause__ or seen.__context__
    return str(exc)


def test_ensure_app_names_a_source_assembly_the_platform_has_deleted(monkeypatch):
    """The tool twin of the CLI refusal: nothing is created from a build the project lost."""

    class FakeClient:
        def __init__(self):
            self.created = []

        def find_app(self, name, *, include_deleted=False):
            return None

        def missing_source(self, project_id, assembly_id):
            assert (project_id, assembly_id) == ("proj-1", "asm-3")
            return {"app": "crm-main", "app-id": "app-2", "version-id": "asm-7",
                    "version": "1.0-7"}

        def create_app(self, display_name, **kwargs):
            self.created.append(display_name)
            return {"id": "app-new"}

    fake = FakeClient()
    server = _server_on(monkeypatch, fake)

    with pytest.raises(Exception) as excinfo:
        asyncio.run(server.call_tool(
            "ensure_app", {"name": "crm-dev", "project_id": "proj-1", "version_id": "asm-3"}
        ))

    message = _root_elemctl_error_message(excinfo.value)
    assert "asm-3" in message and "никто не пользуется" in message
    assert "crm-main" in message and "asm-7" in message and "version_id" in message
    assert fake.created == []


# --- Tools brought by a plugin -----------------------------------------------------

def _plugin_command(**overrides):
    """A stand-in command of a plugin: it reports what it was given."""
    from elemctl import plugins

    def handler(context, stand="", retries=1, force=False):
        context.log("греем стенд")
        return {"stand": stand, "retries": retries, "force": force}

    fields = {
        "name": "warm-up",
        "help": "прогреть стенд",
        "handler": handler,
        "arguments": [
            plugins.Argument("--stand", help="имя стенда", default=""),
            plugins.Argument("--retries", type=int, default=1),
            plugins.Argument("--force", type=bool),
        ],
    }
    fields.update(overrides)
    return plugins.Command(**fields)


def _server_with(monkeypatch, *commands):
    from elemctl import plugins

    monkeypatch.setattr(plugins, "discover_commands", lambda: (list(commands), []))
    return create_server()


def test_plugin_command_becomes_a_tool_with_a_schema(monkeypatch):
    """One declaration - and the tool has the types, the defaults and env_file.

    The signature of such a tool is only known at runtime, so it is assembled by
    hand; this is the check that the server builds the schema out of it.
    """
    server = _server_with(monkeypatch, _plugin_command())
    tool = next(t for t in asyncio.run(server.list_tools()) if t.name == "warm_up")

    assert tool.description == "прогреть стенд"
    properties = tool_input_schema(tool).get("properties") or {}
    assert properties["stand"]["type"] == "string"
    assert properties["retries"] == {"default": 1, "title": "Retries", "type": "integer"}
    assert properties["force"]["type"] == "boolean"
    assert properties["force"]["default"] is False
    assert "env_file" in properties  # added by the core, like every platform tool has it


def test_plugin_command_with_a_cli_alias_keeps_one_mcp_parameter(monkeypatch):
    """cli_alias is a CLI-only convenience (see test_plugins.py) - the schema here is
    exactly what a plugin without one would get: one parameter per declared argument."""
    from elemctl import plugins

    server = _server_with(monkeypatch, _plugin_command(
        name="wiki-get",
        arguments=[plugins.Argument("page", required=True, cli_alias="--page")],
        handler=lambda context, page=None: {"page": page},
    ))
    tool = next(t for t in asyncio.run(server.list_tools()) if t.name == "wiki_get")

    properties = tool_input_schema(tool).get("properties") or {}
    assert set(properties) == {"page", "env_file"}  # no second, alias-shaped parameter

    result = asyncio.run(server.call_tool("wiki_get", {"page": "123"}))
    payload = json.loads(call_result_content(result)[0].text)
    assert payload == {"page": "123", "log": []}


def test_plugin_tool_call_returns_the_result_and_the_log(monkeypatch):
    server = _server_with(monkeypatch, _plugin_command())

    result = asyncio.run(server.call_tool("warm_up", {"stand": "dev", "retries": 3}))

    payload = json.loads(call_result_content(result)[0].text)
    assert payload == {"stand": "dev", "retries": 3, "force": False, "log": ["греем стенд"]}


def test_plugin_tool_hands_the_exit_code_field_over(monkeypatch):
    """The CLI turns the field into the exit code of its process; the tool just returns it."""
    report = {"ok": False, "verdict": "step-failed", "exit-code": 2}
    server = _server_with(
        monkeypatch, _plugin_command(arguments=[], handler=lambda context: report)
    )

    result = asyncio.run(server.call_tool("warm_up", {}))

    payload = json.loads(call_result_content(result)[0].text)
    assert payload == {**report, "log": []}


def test_plugin_command_can_stay_out_of_mcp(monkeypatch):
    server = _server_with(monkeypatch, _plugin_command(mcp=False))
    assert "warm_up" not in {t.name for t in asyncio.run(server.list_tools())}


def test_plugin_cannot_take_over_a_core_tool(monkeypatch, capsys):
    """The core keeps its tool, and the clash is named on stderr, the log of a server."""
    server = _server_with(monkeypatch, _plugin_command(name="deploy"), _plugin_command())

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert "warm_up" in tools
    assert tools["deploy"].description != "прогреть стенд"  # still the tool of the core
    assert "deploy" in capsys.readouterr().err


def test_a_broken_plugin_leaves_the_server_serving(monkeypatch, capsys):
    """One plugin that could not load used to stop the server, and every tool went with it."""
    from elemctl import plugins

    def newer_core():
        raise TypeError("Argument.__init__() got an unexpected keyword argument 'cli_alias'")

    points = [
        types.SimpleNamespace(
            name="а-исправный", group=plugins.COMMANDS_GROUP, value="stub",
            load=lambda: [_plugin_command()],
        ),
        types.SimpleNamespace(
            name="б-новее-ядра", group=plugins.COMMANDS_GROUP, value="stub",
            load=lambda: newer_core,
        ),
    ]
    monkeypatch.delenv(plugins.ENV_DISABLE, raising=False)
    monkeypatch.setattr(
        plugins, "entry_points", lambda group: [p for p in points if p.group == group]
    )

    server = create_server()

    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert "warm_up" in names and "deploy" in names
    stderr = capsys.readouterr().err
    assert "б-новее-ядра" in stderr and "cli_alias" in stderr


# --- Both majors of the mcp package ------------------------------------------------

# tool -> (every parameter, the required ones), sorted and space separated. The
# server class builds these schemas out of the function signatures, so a listing
# that still matches this table is the proof that supporting the other major
# changed no declaration.
EXPECTED_TOOL_PARAMETERS = {
    "apply_build": ("app_id env_file version_id", "app_id version_id"),
    "build_assembly": ("output_dir project_dir version", ""),
    "configure_user_list": ("app_id env_file list_id password_login self_registration", ""),
    "create_app": (
        "development_mode env_file name project_id space_id verify version_id", "name"
    ),
    "debug_adapter": ("", ""),
    "debug_info": ("app_id env_file", "app_id"),
    "delete_app": ("app_id env_file", "app_id"),
    "deploy": (
        "app_id branch env_file project_dir project_id version",
        "app_id project_id",
    ),
    "ensure_app": (
        "development_mode env_file name project_id space_id verify version_id", "name"
    ),
    "find_app": ("env_file include_deleted name", "name"),
    "get_app": ("app_id env_file", "app_id"),
    "get_build": ("env_file project_id version", "project_id version"),
    "inspect_assembly": ("file", "file"),
    "list_app_tasks": ("app_id env_file", ""),
    "list_apps": ("brief env_file include_deleted name status", ""),
    "list_branches": ("env_file name project_id", ""),
    "list_builds": ("brief env_file limit project_id", "project_id"),
    "list_projects": ("brief env_file include_deleted name", ""),
    "list_spaces": ("env_file", ""),
    "list_user_lists": ("env_file name", ""),
    "merge_branch": ("branch_id env_file", "branch_id"),
    "probe": ("env_file keep project_dir space_id", ""),
    "start_app": ("app_id env_file", "app_id"),
    "stop_app": ("app_id env_file", "app_id"),
    "verify_deploy": (
        "app_id env_file expected_assembly_id expected_version since_minutes",
        "app_id",
    ),
}


def test_tool_declarations_are_frozen():
    server = create_server()
    declared = {}
    for tool in asyncio.run(server.list_tools()):
        schema = tool_input_schema(tool)
        declared[tool.name] = (
            " ".join(sorted(schema.get("properties") or {})),
            " ".join(sorted(schema.get("required") or [])),
        )
    assert declared == EXPECTED_TOOL_PARAMETERS


def test_the_server_class_is_the_one_the_installed_major_offers():
    """Whichever major is installed, the compatibility import took its class."""
    from elemctl import mcp_server

    if importlib.util.find_spec("mcp.server.mcpserver") is not None:  # mcp 2.x
        assert mcp_server.McpServer.__name__ == "MCPServer"
        assert mcp_server.McpServer.__module__.startswith("mcp.server.mcpserver")
    else:  # mcp 1.x
        assert mcp_server.McpServer.__name__ == "FastMCP"
        assert mcp_server.McpServer.__module__.startswith("mcp.server.fastmcp")


def _stub_home(class_name):
    """A stand-in for a module the compatibility import reaches for."""
    home = types.ModuleType("stub")
    setattr(home, class_name, type(class_name, (), {}))
    return home


def _load_mcp_server(monkeypatch, *, mcpserver, fastmcp):
    """A private copy of elemctl.mcp_server loaded with the mcp package stubbed.

    The two majors cannot be installed side by side, so the branch that is not
    the installed one is proven by substitution: the modules the compatibility
    import reaches for are put into sys.modules and the file is executed again
    under a name of its own. None as the value is how a module is made
    unimportable - the import machinery raises on it. The real
    elemctl.mcp_server, which the rest of the tests hold, is left alone.
    """
    from elemctl import mcp_server

    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", mcpserver)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp)
    spec = importlib.util.spec_from_file_location(
        "elemctl._mcp_server_under_test", mcp_server.__file__
    )
    copy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy)
    return copy


def test_the_new_home_of_the_server_class_wins(monkeypatch):
    """mcp 2.x renamed FastMCP to MCPServer and moved it; that one is preferred."""
    copy = _load_mcp_server(
        monkeypatch, mcpserver=_stub_home("MCPServer"), fastmcp=_stub_home("FastMCP")
    )
    assert copy.McpServer.__name__ == "MCPServer"


def test_the_old_home_is_the_fallback(monkeypatch):
    """No mcp.server.mcpserver means mcp 1.x, and FastMCP is where the class is."""
    copy = _load_mcp_server(monkeypatch, mcpserver=None, fastmcp=_stub_home("FastMCP"))
    assert copy.McpServer.__name__ == "FastMCP"


def test_without_either_home_the_error_names_the_extra(monkeypatch):
    """Neither of the two - the extra is not installed, and the message says so."""
    with pytest.raises(ImportError, match=r"elemctl\[mcp\]"):
        _load_mcp_server(monkeypatch, mcpserver=None, fastmcp=None)


class _ServerTakingVersion:
    """A stand-in server class of the mcp 2.x shape: it records the construction.

    The positional order is the one 2.x has - title and description sit between
    the name and the instructions - so a call that passed instructions
    positionally would land in the wrong parameter and be caught here.
    """

    def __init__(self, name, title=None, description=None, instructions=None, version=""):
        self.constructed = {"name": name, "instructions": instructions, "version": version}

    def tool(self, name=None, **rest):
        return lambda function: function

    def add_tool(self, function, name=None, description=None, **rest):
        pass


class _ServerWithoutVersion(_ServerTakingVersion):
    """The mcp 1.x shape: no version parameter, so passing one is a TypeError."""

    def __init__(self, name, instructions=None):
        self.constructed = {"name": name, "instructions": instructions}


def test_the_server_is_told_its_own_version_where_the_class_takes_one(monkeypatch):
    """Without it mcp 2.x stamps an empty version into serverInfo."""
    from elemctl import __version__, mcp_server

    monkeypatch.setattr(mcp_server, "McpServer", _ServerTakingVersion)
    server = create_server()

    assert server.constructed["name"] == "elemctl"
    assert server.constructed["instructions"] == INSTRUCTIONS
    assert server.constructed["version"] == __version__


def test_a_class_without_a_version_parameter_is_not_given_one(monkeypatch):
    """mcp 1.x has no such parameter - handing it one would be a TypeError."""
    from elemctl import mcp_server

    monkeypatch.setattr(mcp_server, "McpServer", _ServerWithoutVersion)
    server = create_server()

    assert server.constructed == {"name": "elemctl", "instructions": INSTRUCTIONS}


def test_reading_helpers_understand_both_shapes():
    """The two places where the majors answer differently, pinned on both shapes.

    mcp 1.x spells the schema field inputSchema and hands the content blocks back
    as they are; mcp 2.x spells it input_schema and wraps the blocks into a
    CallToolResult.
    """

    class OldTool:
        inputSchema = {"properties": {"app_id": {}}}

    class NewTool:
        input_schema = {"properties": {"app_id": {}}}

    class NoSchema:
        input_schema = None

    assert tool_input_schema(OldTool()) == {"properties": {"app_id": {}}}
    assert tool_input_schema(NewTool()) == {"properties": {"app_id": {}}}
    assert tool_input_schema(NoSchema()) == {}

    class NewResult:
        content = ["block"]

    assert call_result_content(["block"]) == ["block"]
    assert call_result_content(NewResult()) == ["block"]


# --- The client cache reacts to the .env file on disk -------------------------------

@pytest.fixture(autouse=True)
def _no_stray_element_env(monkeypatch):
    """Neutralize every ELEMENT_*/ELEMCTL_NO_PROXY variable before each test below.

    The tests in this section build real clients through Config.from_env, which reads the
    actual process environment whenever nothing overrides it. A developer's own
    ELEMENT_BASE_URL, set in their shell for convenience and never touched by the test
    itself, would then outrank the file content or override every assertion here is about -
    the failure would depend on who happened to run the suite, and where.
    """
    from elemctl.config import BOOL_ENV_KEYS, ENV_KEYS
    from elemctl.transport import NO_PROXY_ENV

    for var in (*ENV_KEYS.values(), *BOOL_ENV_KEYS.values(), NO_PROXY_ENV):
        monkeypatch.delenv(var, raising=False)


def _recording_client_factory():
    """A stand-in for ElementClient that remembers which config built it and whether it was
    later closed - exactly the facts the cache behaviour under test turns on, with no real
    client or network involved.
    """
    counter = itertools.count(1)
    created = []

    class RecordingClient:
        def __init__(self, config):
            self.id = next(counter)
            self.config = config
            self.closed = False
            created.append(self)

        def close(self):
            self.closed = True

        def list_spaces(self):
            return [{
                "instance-id": self.id,
                "base-url": self.config.base_url,
                "client-secret": self.config.client_secret,
            }]

    return RecordingClient, created


def _call_list_spaces(server, env_file=None):
    """Call list_spaces (optionally for one stand) and return its single answer row.

    list_spaces is declared -> list, and a one-item list comes back from call_tool as a single
    content block holding that one item's JSON, not an array wrapping it - the same shape
    test_list_projects_passes_the_filters_and_keeps_the_cards_brief relies on above.
    """
    arguments = {"env_file": env_file} if env_file is not None else {}
    result = asyncio.run(server.call_tool("list_spaces", arguments))
    return json.loads(call_result_content(result)[0].text)


def _server_via_cli_mcp(monkeypatch, argv, elementclient):
    """Build the server exactly the way `elemctl mcp` builds it: cli.main's own dispatch to
    cmd_mcp, which calls the real mcp_server.main (itself calling the real create_server) -
    only McpServer.run is replaced, handing the built server back instead of starting it. The
    real .run() blocks on stdio forever waiting for a client that never connects, and that is
    exactly the entry point that hid the startup bug this file guards against; replacing
    main() itself instead of just .run() would hide a mismatch between what main() is told
    and what create_server() actually receives, which is the one thing this helper exists to
    exercise for real.
    """
    from elemctl import cli, mcp_server

    monkeypatch.setattr(mcp_server, "ElementClient", elementclient)
    captured = {}

    def fake_run(self):
        captured["server"] = self

    monkeypatch.setattr(mcp_server.McpServer, "run", fake_run)
    exit_code = cli.main(argv)
    assert exit_code == 0
    return captured["server"]


def test_two_stands_served_by_one_process_do_not_mix(monkeypatch, tmp_path):
    """Two env files, two clients - and asking for the first one again is a cache hit,
    not a third client."""
    from elemctl import mcp_server

    RecordingClient, _created = _recording_client_factory()
    monkeypatch.setattr(mcp_server, "ElementClient", RecordingClient)

    env_a = tmp_path / "stand-a.env"
    env_a.write_text("ELEMENT_BASE_URL=https://stand-a.test\n", encoding="utf-8")
    env_b = tmp_path / "stand-b.env"
    env_b.write_text("ELEMENT_BASE_URL=https://stand-b.test\n", encoding="utf-8")

    server = create_server()

    first_a = _call_list_spaces(server, str(env_a))
    first_b = _call_list_spaces(server, str(env_b))
    again_a = _call_list_spaces(server, str(env_a))

    assert first_a["base-url"] == "https://stand-a.test"
    assert first_b["base-url"] == "https://stand-b.test"
    assert first_a["instance-id"] != first_b["instance-id"]
    assert again_a["instance-id"] == first_a["instance-id"]


def test_editing_one_stands_file_replaces_only_its_own_client(monkeypatch, tmp_path):
    """The proxy hint's own example - adding ELEMCTL_NO_PROXY=1 to a stand's .env - must take
    effect on the very next call, and a neighbour stand served by the same process must not
    notice anything happened."""
    from elemctl import mcp_server

    RecordingClient, created = _recording_client_factory()
    monkeypatch.setattr(mcp_server, "ElementClient", RecordingClient)

    env_a = tmp_path / "stand-a.env"
    env_a.write_text("ELEMENT_BASE_URL=https://stand-a.test\n", encoding="utf-8")
    env_b = tmp_path / "stand-b.env"
    env_b.write_text("ELEMENT_BASE_URL=https://stand-b.test\n", encoding="utf-8")

    server = create_server()
    before_a = _call_list_spaces(server, str(env_a))
    before_b = _call_list_spaces(server, str(env_b))

    env_a.write_text(
        "ELEMENT_BASE_URL=https://stand-a.test\nELEMCTL_NO_PROXY=1\n", encoding="utf-8"
    )

    after_a = _call_list_spaces(server, str(env_a))
    after_b = _call_list_spaces(server, str(env_b))

    assert after_a["instance-id"] != before_a["instance-id"]  # the edit is picked up
    assert after_b["instance-id"] == before_b["instance-id"]  # the other stand is untouched

    outgoing = next(c for c in created if c.id == before_a["instance-id"])
    assert outgoing.closed is True  # the replaced client released what it could


def test_a_client_with_nothing_to_close_is_simply_replaced(monkeypatch, tmp_path):
    """Not every client has a close() - ElementClient itself does not today - and the cache
    must not choke on the one it is holding when a file changes underneath it."""
    from elemctl import mcp_server

    counter = itertools.count(1)

    class BareClient:
        def __init__(self, config):
            self.id = next(counter)
            self.config = config

        def list_spaces(self):
            return [{"instance-id": self.id, "base-url": self.config.base_url}]

    monkeypatch.setattr(mcp_server, "ElementClient", BareClient)

    env_file = tmp_path / "stand.env"
    env_file.write_text("ELEMENT_BASE_URL=https://stand.test\n", encoding="utf-8")
    server = create_server()

    before = _call_list_spaces(server, str(env_file))
    env_file.write_text(
        "ELEMENT_BASE_URL=https://stand.test\nELEMCTL_NO_PROXY=1\n", encoding="utf-8"
    )
    after = _call_list_spaces(server, str(env_file))

    assert after["instance-id"] != before["instance-id"]


def test_default_env_file_is_watched_the_same_way_as_an_explicit_one(monkeypatch, tmp_path):
    """The exact shape `elemctl mcp` runs in: no --env-file, no other flag. A tool call
    without env_file must re-read the .env of the working directory on every miss - built
    through the CLI's own construction (cli.main -> cmd_mcp -> mcp_server.main), not through
    calling create_server() with nothing at all: that shortcut and what the CLI actually does
    used to differ in exactly the way that mattered here (cmd_mcp handed the server a
    pre-resolved Config, which pinned the default stand forever).
    """
    RecordingClient, _created = _recording_client_factory()
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ELEMENT_BASE_URL=https://default.test\n", encoding="utf-8")

    server = _server_via_cli_mcp(monkeypatch, ["mcp"], RecordingClient)

    before = _call_list_spaces(server)
    (tmp_path / ".env").write_text(
        "ELEMENT_BASE_URL=https://default.test\nELEMCTL_NO_PROXY=1\n", encoding="utf-8"
    )
    after = _call_list_spaces(server)

    assert before["base-url"] == "https://default.test"
    assert after["instance-id"] != before["instance-id"]


def test_a_cli_startup_override_wins_over_the_file_even_after_it_is_rebuilt(monkeypatch, tmp_path):
    """--base-url on the elemctl mcp command line is the most explicit source there is -
    Config.from_env's own precedence, explicit arguments over the file. A file edit that
    forces the default stand's client to be rebuilt must not lose that override along the way.
    """
    RecordingClient, _created = _recording_client_factory()
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ELEMENT_BASE_URL=https://from-file.test\n", encoding="utf-8")

    server = _server_via_cli_mcp(
        monkeypatch, ["mcp", "--base-url", "https://override.test"], RecordingClient
    )

    before = _call_list_spaces(server)
    (tmp_path / ".env").write_text(
        "ELEMENT_BASE_URL=https://from-file.test\nELEMCTL_NO_PROXY=1\n", encoding="utf-8"
    )
    after = _call_list_spaces(server)

    assert before["base-url"] == "https://override.test"
    assert after["base-url"] == "https://override.test"
    assert after["instance-id"] != before["instance-id"]  # the edit still rebuilt the client


def test_env_file_paths_naming_the_same_file_share_one_cache_entry(monkeypatch, tmp_path):
    """a.env and ./a.env are the same file by any path resolution; they must not each get
    their own client just because the two spellings differ."""
    from elemctl import mcp_server

    RecordingClient, _created = _recording_client_factory()
    monkeypatch.setattr(mcp_server, "ElementClient", RecordingClient)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.env").write_text("ELEMENT_BASE_URL=https://a.test\n", encoding="utf-8")

    server = create_server()

    plain = _call_list_spaces(server, "a.env")
    dotted = _call_list_spaces(server, "./a.env")

    assert dotted["instance-id"] == plain["instance-id"]


def test_explicit_env_file_equal_to_the_default_path_shares_the_entry_with_the_no_env_file_call(
    monkeypatch, tmp_path
):
    """A call that happens to name the working directory's own .env explicitly must land on
    the very same cache entry as a call that left env_file out - they are the same stand."""
    RecordingClient, _created = _recording_client_factory()
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ELEMENT_BASE_URL=https://default.test\n", encoding="utf-8")

    server = _server_via_cli_mcp(monkeypatch, ["mcp"], RecordingClient)

    without_env_file = _call_list_spaces(server)
    named_explicitly = _call_list_spaces(server, str(tmp_path / ".env"))

    assert named_explicitly["instance-id"] == without_env_file["instance-id"]


def test_a_config_passed_to_create_server_directly_stays_pinned_unlike_the_cli_path(
    monkeypatch, tmp_path
):
    """create_server(config=...) is the library-embedding entry point - cmd_mcp does not use
    it any more (see test_default_env_file_is_watched_the_same_way_as_an_explicit_one, which
    goes through the CLI's own construction and DOES re-read a file). A Config object handed
    in this way has no file behind it for the cache to watch, so it stays pinned for the life
    of the process, and a stray .env of the working directory (an agent started from an
    unexpected place, say) must not shadow it.
    """
    from elemctl import mcp_server
    from elemctl.config import Config

    RecordingClient, _created = _recording_client_factory()
    monkeypatch.setattr(mcp_server, "ElementClient", RecordingClient)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ELEMENT_BASE_URL=https://from-file.test\n", encoding="utf-8")

    server = create_server(
        Config(base_url="https://startup.test", client_id="cid", client_secret="secret")
    )

    first = _call_list_spaces(server)
    second = _call_list_spaces(server)

    assert first["base-url"] == second["base-url"] == "https://startup.test"
    assert first["instance-id"] == second["instance-id"]


def _root_config_error_message(exc):
    """The message of our own ConfigError inside a tool-call exception, however either major
    of the mcp package happens to wrap it.

    mcp 1.x folds the original text into its own message (`Error executing tool X:
    <original>`), so a plain regex on str(exc) used to work by accident; mcp 2.x's own
    message is bare (`Error executing tool X`, no colon and no original text) and keeps the
    ConfigError only as __cause__ - matching against str(exc) then finds nothing, on a
    genuine failure exactly as much as on this one. The chain is walked instead, so the
    assertion is about OUR error and not about which major happened to run it; a ConfigError
    not wrapped at all (a future major, or a direct call outside any tool machinery) is
    caught on the very first step.
    """
    from elemctl.errors import ConfigError

    seen = exc
    while seen is not None:
        if isinstance(seen, ConfigError):
            return str(seen)
        seen = seen.__cause__ or seen.__context__
    return str(exc)


def test_a_missing_env_file_gives_a_clear_error_through_the_tool(tmp_path):
    """An env_file named by a tool call that does not exist is refused through the same
    ConfigError Config.from_env always raised for one - the cache adds no path of its own
    that could swallow it."""
    server = create_server()
    missing = tmp_path / "nope.env"

    with pytest.raises(Exception) as excinfo:
        asyncio.run(server.call_tool("list_spaces", {"env_file": str(missing)}))

    assert "не найден" in _root_config_error_message(excinfo.value)


def test_an_env_file_deleted_after_being_cached_is_noticed_on_the_next_call(monkeypatch, tmp_path):
    """A first, successful call must not leave the server trusting a client whose file is gone
    by the time of the second call - silently carrying on with stale credentials is worse than
    an error that says so."""
    from elemctl import mcp_server

    RecordingClient, _created = _recording_client_factory()
    monkeypatch.setattr(mcp_server, "ElementClient", RecordingClient)

    env_file = tmp_path / "stand.env"
    env_file.write_text("ELEMENT_BASE_URL=https://stand.test\n", encoding="utf-8")
    server = create_server()

    first = _call_list_spaces(server, str(env_file))
    assert first["base-url"] == "https://stand.test"

    env_file.unlink()

    with pytest.raises(Exception) as excinfo:
        asyncio.run(server.call_tool("list_spaces", {"env_file": str(env_file)}))

    assert "не найден" in _root_config_error_message(excinfo.value)


def test_startup_identity_overrides_apply_only_without_an_explicit_env_file(monkeypatch, tmp_path):
    """--base-url/--client-id/--client-secret at elemctl mcp startup name the stand at the
    startup address - the default stand, a call without its own env_file. A call naming a
    DIFFERENT stand explicitly must be built from that stand's own file untouched, exactly as
    it was on 4813d0a, before these flags reached the cache at all: a call to another stand
    landing on the startup host with a mixed set of credentials is the regression this pins
    down (the probe that first found it: `elemctl --env-file cloud.env --base-url
    https://cloud.test --client-secret cloud-secret mcp`, then a call naming local.env -
    which came back https://cloud.test with the cloud secret, instead of local.env's own).
    """
    RecordingClient, _created = _recording_client_factory()
    monkeypatch.chdir(tmp_path)
    cloud_env = tmp_path / "cloud.env"
    cloud_env.write_text(
        "ELEMENT_BASE_URL=https://cloud-file.test\nELEMENT_CLIENT_SECRET=cloud-file-secret\n",
        encoding="utf-8",
    )
    local_env = tmp_path / "local.env"
    local_env.write_text(
        "ELEMENT_BASE_URL=https://local.test\nELEMENT_CLIENT_SECRET=local-secret\n",
        encoding="utf-8",
    )

    server = _server_via_cli_mcp(
        monkeypatch,
        [
            "mcp",
            "--env-file", str(cloud_env),
            "--base-url", "https://cloud.test",
            "--client-secret", "cloud-secret",
        ],
        RecordingClient,
    )

    default_stand = _call_list_spaces(server)
    other_stand = _call_list_spaces(server, str(local_env))

    assert default_stand["base-url"] == "https://cloud.test"  # the startup override wins
    assert default_stand["client-secret"] == "cloud-secret"
    assert other_stand["base-url"] == "https://local.test"  # untouched by the startup flags
    assert other_stand["client-secret"] == "local-secret"


def test_a_missing_explicit_env_file_fails_at_cli_startup_before_the_server_runs(
    monkeypatch, tmp_path
):
    """A bad --env-file must not slip past startup quietly, the way it did once main() stopped
    resolving a Config there - it is checked at the same place and with the same clear error
    as on 4813d0a, before create_server ever runs, so McpServer.run must never be reached."""
    from elemctl import cli, mcp_server

    started = []
    monkeypatch.setattr(mcp_server.McpServer, "run", lambda self: started.append(self))

    missing = tmp_path / "nope.env"
    exit_code = cli.main(["--env-file", str(missing), "mcp"])

    assert exit_code == 1
    assert started == []


# --- Four small things about the client cache ---------------------------------------------


def _counting_env_file_signature(monkeypatch):
    """Replace _env_file_signature with a version that keeps behaving exactly the same way but
    also remembers how many times it was asked - the number of times client() actually went
    through its cache-lookup logic for one tool call, the thing create_app and ensure_app used
    to do several times over."""
    from elemctl import mcp_server

    calls = []
    original = mcp_server._env_file_signature

    def counting(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(mcp_server, "_env_file_signature", counting)
    return calls


class _FakeCreatingClient:
    """Creates an application, the way FakeCreatingClient in the tests above does, but also
    answers latest_assembly - the one call _create_app makes that FakeCreatingClient has no
    need for, since every test up there always names version_id explicitly."""

    def __init__(self, config):
        self.config = config

    def find_app(self, name, *, include_deleted=False):
        return None

    def latest_assembly(self, project_id):
        return {"id": "asm-latest"}

    def create_app(self, display_name, **kwargs):
        return {"id": "app-new", "display-name": display_name, "status": "Creating"}

    def wait_app_ready(self, app_id, log=None):
        return {"id": app_id, "status": "Running", "uri": "https://host/apps/new"}


def test_create_app_resolves_the_client_once_per_call(monkeypatch, tmp_path):
    """create_app used to look client(env_file) up separately for the source assembly
    (latest_assembly), for the creation itself, for the readiness wait and for the
    verification - four lookups where one was meant, each re-reading the .env file's
    modification time and size on every one of them. Worse, a file edited mid-call could in
    principle hand the four steps four different clients. One resolution per tool call closes
    both gaps; project_id (rather than version_id) is what exercises all four sites at once."""
    from elemctl import mcp_server

    monkeypatch.setattr(mcp_server, "ElementClient", _FakeCreatingClient)
    _stub_mcp_verify(monkeypatch, ok=True)

    env_file = tmp_path / "stand.env"
    env_file.write_text("ELEMENT_BASE_URL=https://stand.test\n", encoding="utf-8")
    signature_calls = _counting_env_file_signature(monkeypatch)

    server = create_server()
    result = asyncio.run(
        server.call_tool(
            "create_app",
            {
                "name": "crm-dev",
                "project_id": "proj-1",
                "verify": True,
                "env_file": str(env_file),
            },
        )
    )
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["id"] == "app-new"
    assert payload["verify"]["ok"] is True
    assert len(signature_calls) == 1


def test_ensure_app_resolves_the_client_once_per_call(monkeypatch, tmp_path):
    """ensure_app's own lookup (does the application already exist) used to be a separate
    client(env_file) call on top of whatever _create_app made once the answer turned out to
    be no - three more of them here, since version_id is given and project_id is not. One
    resolution, shared with _create_app, means every step of one ensure_app call sees the
    same client instead of possibly several built from different moments of the same file."""
    from elemctl import mcp_server

    monkeypatch.setattr(mcp_server, "ElementClient", _FakeCreatingClient)
    _stub_mcp_verify(monkeypatch, ok=True)

    env_file = tmp_path / "stand.env"
    env_file.write_text("ELEMENT_BASE_URL=https://stand.test\n", encoding="utf-8")
    signature_calls = _counting_env_file_signature(monkeypatch)

    server = create_server()
    result = asyncio.run(
        server.call_tool(
            "ensure_app",
            {
                "name": "crm-dev",
                "version_id": "asm-1",
                "verify": True,
                "env_file": str(env_file),
            },
        )
    )
    payload = json.loads(call_result_content(result)[0].text)

    assert payload["created"] is True
    assert payload["verify"]["ok"] is True
    assert len(signature_calls) == 1


def test_a_close_failure_does_not_orphan_the_new_client(monkeypatch, tmp_path):
    """The client an edit is replacing used to be released BEFORE the new one was stored - an
    exception from its close() then left the cache pointing at the entry that was there
    before: the very client whose close() just failed, instead of the new, working one that
    had already been built. Storing first means a close() failure loses at most the close,
    never the cache's ability to move on to the client it just built."""
    from elemctl import mcp_server

    close_attempts = []

    class FailsToClose:
        def __init__(self, config):
            self.config = config

        def close(self):
            close_attempts.append(self)
            raise RuntimeError("boom")

        def list_spaces(self):
            return [{"base-url": self.config.base_url}]

    monkeypatch.setattr(mcp_server, "ElementClient", FailsToClose)

    env_file = tmp_path / "stand.env"
    env_file.write_text("ELEMENT_BASE_URL=https://stand.test\n", encoding="utf-8")
    server = create_server()

    first = _call_list_spaces(server, str(env_file))
    assert first["base-url"] == "https://stand.test"

    env_file.write_text(
        "ELEMENT_BASE_URL=https://stand.test\nELEMCTL_NO_PROXY=1\n", encoding="utf-8"
    )

    with pytest.raises(Exception):
        _call_list_spaces(server, str(env_file))
    assert len(close_attempts) == 1

    # Despite the failed close(), the cache must already hold the new, working client - a
    # second call must succeed outright, not try (and fail) to close the same old client again.
    second = _call_list_spaces(server, str(env_file))
    assert second["base-url"] == "https://stand.test"
    assert len(close_attempts) == 1


def test_concurrent_calls_for_the_same_stand_build_one_client(monkeypatch, tmp_path):
    """Every tool runs to completion before the next one starts today - the mcp package drives
    calls one at a time over stdio - so nothing exercises this race yet; the point of a lock
    around the cache dictionary is to hold the guarantee regardless of how calls end up being
    dispatched later. This drives the race directly with real threads instead of waiting for
    a future dispatcher to create it: without a lock, several callers can each see the same
    stale (or missing) cache entry before any of them stores a replacement, and each ends up
    building its own client - correct by accident today only because nothing calls in
    concurrently, and silently leaking every client but the last one the dictionary keeps."""
    from elemctl import mcp_server

    threads_total = 8
    counter = itertools.count(1)
    created = []
    created_lock = threading.Lock()  # guards the TEST's own bookkeeping, not the code under test
    build_gate = threading.Event()

    class SlowClient:
        def __init__(self, config):
            # Held here to widen the window between the cache-miss check and the cache being
            # written to - exactly the window a lock around that whole sequence has to close.
            build_gate.wait(timeout=5)
            self.config = config
            with created_lock:
                self.id = next(counter)
                created.append(self)

        def list_spaces(self):
            return [{"instance-id": self.id}]

    monkeypatch.setattr(mcp_server, "ElementClient", SlowClient)
    env_file = tmp_path / "stand.env"
    env_file.write_text("ELEMENT_BASE_URL=https://stand.test\n", encoding="utf-8")
    server = create_server()

    results = []
    results_lock = threading.Lock()

    def call():
        answer = _call_list_spaces(server, str(env_file))
        with results_lock:
            results.append(answer)

    threads = [threading.Thread(target=call) for _ in range(threads_total)]
    for thread in threads:
        thread.start()
    time.sleep(0.3)  # let every thread reach as far as it can get before any client finishes
    build_gate.set()
    for thread in threads:
        thread.join(timeout=5)

    assert len(created) == 1
    assert {row["instance-id"] for row in results} == {created[0].id}
