"""Unit tests for cua tool wiring (no daemon required)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cua.tools import cua_tool_payload, is_cua_tool, strip_cua_prefix
from skills import tool_payload


def test_cua_prefix_strip():
    assert strip_cua_prefix("cua_list_windows") == "list_windows"
    assert strip_cua_prefix("web_search") == "web_search"


def test_is_cua_tool():
    assert is_cua_tool("cua_get_window_state")
    assert not is_cua_tool("web_search")


def test_tool_payload_merges_cua():
    payload = tool_payload(["web_search", "cua_list_windows"])
    names = {p["name"] for p in payload}
    assert "web_search" in names
    assert "cua_list_windows" in names


def test_cua_tool_payload_read_only():
    tools = cua_tool_payload(["cua_list_windows", "cua_get_window_state"])
    assert len(tools) == 2
    assert tools[0]["name"] == "cua_list_windows"
