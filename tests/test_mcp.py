"""Тесты MCP-сервера: набор инструментов соответствует разделу 8 спецификации."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp", reason="extra elemctl[mcp] не установлен")

from elemctl.mcp_server import INSTRUCTIONS, create_server

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
