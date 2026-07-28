"""MCP server tests: the tool set matches section 8 of the specification."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("mcp", reason="extra elemctl[mcp] не установлен")

from elemctl.client import brief_app
from elemctl.mcp_server import INSTRUCTIONS, _brief_project, create_server

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
    properties = (find_tool.inputSchema or {}).get("properties") or {}
    assert "include_deleted" in properties


def test_every_platform_tool_accepts_env_file():
    """The environment is picked per call, not only when the server starts.

    Otherwise a single server serves a single stand only, and the second one (a local
    stand, say) is out of reach through MCP – one has to fall back to the CLI.
    """
    server = create_server()
    tools = asyncio.run(server.list_tools())
    local_only = {"build_assembly", "inspect_assembly", "debug_adapter"}
    for tool in tools:
        if tool.name in local_only:
            continue  # these never reach out to the platform
        properties = (tool.inputSchema or {}).get("properties") or {}
        assert "env_file" in properties, tool.name
    assert "env_file" in INSTRUCTIONS


def test_list_apps_is_brief_by_default():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    list_tool = next(tool for tool in tools if tool.name == "list_apps")
    properties = (list_tool.inputSchema or {}).get("properties") or {}
    assert properties.get("brief", {}).get("default") is True


def test_list_projects_is_brief_by_default():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    list_tool = next(tool for tool in tools if tool.name == "list_projects")
    properties = (list_tool.inputSchema or {}).get("properties") or {}
    assert properties.get("brief", {}).get("default") is True


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
    description says so – otherwise an agent never learns the option is there.
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

    Both answers of ensure carry it – the application already existed just as
    often as it is created.
    """

    class FakeClient:
        def find_app(self, name, *, include_deleted=False):
            return {"id": "app-7", "display-name": name, "uri": "https://host/apps/crm-dev"}

    server = _server_on(monkeypatch, FakeClient())

    payload = json.loads(asyncio.run(server.call_tool("ensure_app", {"name": "crm-dev"}))[0].text)

    assert payload["id"] == "app-7"
    assert payload["created"] is False
    assert payload["sign-in"]["url"] == "https://host/apps/crm-dev"
    assert payload["sign-in"]["account"] == "control-panel"
    assert "другие приложения" in payload["sign-in"]["note"]


def test_create_app_adds_the_way_in_to_the_card(monkeypatch):
    """create_app keeps answering with the platform card; the hint is an addition."""

    class FakeClient:
        def create_app(self, display_name, **kwargs):
            return {"id": "app-new", "display-name": display_name, "uri": "https://host/apps/new"}

    server = _server_on(monkeypatch, FakeClient())

    payload = json.loads(
        asyncio.run(
            server.call_tool("create_app", {"name": "crm-dev", "version_id": "asm-1"})
        )[0].text
    )

    assert payload["id"] == "app-new"
    assert payload["display-name"] == "crm-dev"
    assert payload["sign-in"]["url"] == "https://host/apps/new"


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

    monkeypatch.setattr(plugins, "plugin_commands", lambda: list(commands))
    return create_server()


def test_plugin_command_becomes_a_tool_with_a_schema(monkeypatch):
    """One declaration – and the tool has the types, the defaults and env_file.

    The signature of such a tool is only known at runtime, so it is assembled by
    hand; this is the check that FastMCP builds the schema out of it.
    """
    server = _server_with(monkeypatch, _plugin_command())
    tool = next(t for t in asyncio.run(server.list_tools()) if t.name == "warm_up")

    assert tool.description == "прогреть стенд"
    properties = (tool.inputSchema or {}).get("properties") or {}
    assert properties["stand"]["type"] == "string"
    assert properties["retries"] == {"default": 1, "title": "Retries", "type": "integer"}
    assert properties["force"]["type"] == "boolean"
    assert properties["force"]["default"] is False
    assert "env_file" in properties  # added by the core, like every platform tool has it


def test_plugin_tool_call_returns_the_result_and_the_log(monkeypatch):
    server = _server_with(monkeypatch, _plugin_command())

    result = asyncio.run(server.call_tool("warm_up", {"stand": "dev", "retries": 3}))

    payload = json.loads(result[0].text)
    assert payload == {"stand": "dev", "retries": 3, "force": False, "log": ["греем стенд"]}


def test_plugin_command_can_stay_out_of_mcp(monkeypatch):
    server = _server_with(monkeypatch, _plugin_command(mcp=False))
    assert "warm_up" not in {t.name for t in asyncio.run(server.list_tools())}


def test_plugin_cannot_take_over_a_core_tool(monkeypatch):
    from elemctl.errors import PluginError

    with pytest.raises(PluginError, match="deploy"):
        _server_with(monkeypatch, _plugin_command(name="deploy"))
