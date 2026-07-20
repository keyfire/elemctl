"""Тесты MCP-сервера: набор инструментов соответствует разделу 8 спецификации."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp", reason="extra elemctl[mcp] не установлен")

from elemctl.mcp_server import INSTRUCTIONS, _brief_app, create_server

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
    "apply_build",
    "verify_deploy",
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
    assert "пересозда" in description  # существующее приложение НЕ пересоздаётся
    assert "created" in description


def test_find_app_exposes_include_deleted():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    find_tool = next(tool for tool in tools if tool.name == "find_app")
    properties = (find_tool.inputSchema or {}).get("properties") or {}
    assert "include_deleted" in properties


def test_every_platform_tool_accepts_env_file():
    """Окружение задаётся на вызов, а не только при запуске сервера.

    Иначе один сервер обслуживает лишь один стенд, и до второго (например,
    локального) через MCP не добраться - приходится уходить в CLI.
    """
    server = create_server()
    tools = asyncio.run(server.list_tools())
    local_only = {"build_assembly", "inspect_assembly", "debug_adapter"}
    for tool in tools:
        if tool.name in local_only:
            continue  # к платформе не обращаются
        properties = (tool.inputSchema or {}).get("properties") or {}
        assert "env_file" in properties, tool.name
    assert "env_file" in INSTRUCTIONS


def test_list_apps_is_brief_by_default():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    list_tool = next(tool for tool in tools if tool.name == "list_apps")
    properties = (list_tool.inputSchema or {}).get("properties") or {}
    assert properties.get("brief", {}).get("default") is True


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
    brief = _brief_app(card)
    assert brief == {
        "id": "app-1",
        "name": "site",
        "status": "Running",
        "uri": "https://host/applications/site",
        "project-version": "1.0.0-3",
        "project-version-id": "asm-1",
    }
