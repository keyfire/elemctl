"""MCP server tests: the tool set matches section 8 of the specification."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
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
    stand, say) is out of reach through MCP – one has to fall back to the CLI.
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

    result = asyncio.run(server.call_tool("ensure_app", {"name": "crm-dev"}))
    payload = json.loads(call_result_content(result)[0].text)

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

    result = asyncio.run(
        server.call_tool("create_app", {"name": "crm-dev", "version_id": "asm-1"})
    )
    payload = json.loads(call_result_content(result)[0].text)

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


def test_plugin_tool_call_returns_the_result_and_the_log(monkeypatch):
    server = _server_with(monkeypatch, _plugin_command())

    result = asyncio.run(server.call_tool("warm_up", {"stand": "dev", "retries": 3}))

    payload = json.loads(call_result_content(result)[0].text)
    assert payload == {"stand": "dev", "retries": 3, "force": False, "log": ["греем стенд"]}


def test_plugin_command_can_stay_out_of_mcp(monkeypatch):
    server = _server_with(monkeypatch, _plugin_command(mcp=False))
    assert "warm_up" not in {t.name for t in asyncio.run(server.list_tools())}


def test_plugin_cannot_take_over_a_core_tool(monkeypatch):
    from elemctl.errors import PluginError

    with pytest.raises(PluginError, match="deploy"):
        _server_with(monkeypatch, _plugin_command(name="deploy"))


# --- Both majors of the mcp package ------------------------------------------------

# tool -> (every parameter, the required ones), sorted and space separated. The
# server class builds these schemas out of the function signatures, so a listing
# that still matches this table is the proof that supporting the other major
# changed no declaration.
EXPECTED_TOOL_PARAMETERS = {
    "apply_build": ("app_id env_file version_id", "app_id version_id"),
    "build_assembly": ("output_dir project_dir version", ""),
    "configure_user_list": ("app_id env_file list_id password_login self_registration", ""),
    "create_app": ("development_mode env_file name project_id space_id version_id", "name"),
    "debug_adapter": ("", ""),
    "debug_info": ("app_id env_file", "app_id"),
    "delete_app": ("app_id env_file", "app_id"),
    "deploy": (
        "app_id branch env_file project_dir project_id version",
        "app_id project_id",
    ),
    "ensure_app": ("development_mode env_file name project_id space_id version_id", "name"),
    "find_app": ("env_file include_deleted name", "name"),
    "get_app": ("app_id env_file", "app_id"),
    "inspect_assembly": ("file", "file"),
    "list_app_tasks": ("app_id env_file", ""),
    "list_apps": ("brief env_file name", ""),
    "list_branches": ("env_file name project_id", ""),
    "list_builds": ("brief env_file limit project_id", "project_id"),
    "list_projects": ("brief env_file", ""),
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
    unimportable – the import machinery raises on it. The real
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
    """Neither of the two – the extra is not installed, and the message says so."""
    with pytest.raises(ImportError, match=r"elemctl\[mcp\]"):
        _load_mcp_server(monkeypatch, mcpserver=None, fastmcp=None)


class _ServerTakingVersion:
    """A stand-in server class of the mcp 2.x shape: it records the construction.

    The positional order is the one 2.x has – title and description sit between
    the name and the instructions – so a call that passed instructions
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
    """mcp 1.x has no such parameter – handing it one would be a TypeError."""
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
