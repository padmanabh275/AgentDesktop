"""Tests for the EAGV3 S9 MCP server.

Run from code/ (with deps installed):
  pip install -r requirements.txt
  pytest -v test_mcp_server.py

Offline-only:
  pytest -v test_mcp_server.py -m "not network"
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent
SERVER = HERE / "mcp_server.py"
SANDBOX = HERE / "sandbox"


def _result(res) -> object:
    """Extract a structured payload from a CallToolResult."""
    if getattr(res, "structuredContent", None) is not None:
        sc = res.structuredContent
        if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
            return sc["result"]
        return sc
    block = res.content[0]
    text = getattr(block, "text", None)
    if text is None:
        return block
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _list_dir_entries(data: object) -> list[dict]:
    """list_dir returns a dict {entries, names, count}; older tests used a list."""
    if isinstance(data, dict) and "entries" in data:
        return list(data["entries"])
    if isinstance(data, list):
        return data
    raise AssertionError(f"unexpected list_dir payload: {data!r}")


def _rm_tree(path: Path) -> None:
    def _onexc(func, p, exc):
        if isinstance(exc, PermissionError) and not os.access(p, os.W_OK):
            os.chmod(p, stat.S_IWUSR)
            func(p)
            return
        raise exc

    shutil.rmtree(path, onexc=_onexc)


def _clean_sandbox() -> None:
    """Reset sandbox test files. Keeps `papers/` (course fixture) if present."""
    SANDBOX.mkdir(parents=True, exist_ok=True)
    for child in list(SANDBOX.iterdir()):
        if child.name == "papers":
            continue
        if child.is_dir():
            _rm_tree(child)
        else:
            try:
                child.unlink()
            except PermissionError:
                os.chmod(child, stat.S_IWUSR)
                child.unlink()


@asynccontextmanager
async def _mcp_session():
    """One stdio MCP server subprocess. Uses asyncio.run() per test to avoid
    pytest-asyncio teardown issues with anyio TaskGroups on Windows."""
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as s:
                await s.initialize()
                yield s
    except Exception as e:
        raise RuntimeError(
            f"MCP server failed to start ({SERVER}). "
            f"Install deps: pip install -r requirements.txt. Root cause: {e!r}"
        ) from e


@pytest.mark.network
def test_web_search():
    async def _run():
        async with _mcp_session() as session:
            res = await session.call_tool("web_search", {"query": "python asyncio", "max_results": 3})
            data = _result(res)
            print("web_search:", data)
            assert isinstance(data, list)
            assert len(data) >= 1
            for hit in data:
                assert {"title", "url", "snippet"} <= set(hit)

    asyncio.run(_run())


@pytest.mark.network
def test_fetch_url():
    async def _run():
        async with _mcp_session() as session:
            res = await session.call_tool("fetch_url", {"url": "https://example.com"})
            data = _result(res)
            print("fetch_url status/len:", data["status"], data["length_bytes"])
            assert data["status"] == 200
            assert "Example Domain" in data["text"]
            assert data["length_bytes"] > 0
            assert "text" in data["content_type"].lower() or "html" in data["content_type"].lower()

    asyncio.run(_run())


def test_get_time():
    async def _run():
        async with _mcp_session() as session:
            res = await session.call_tool("get_time", {"timezone": "Asia/Kolkata"})
            data = _result(res)
            print("get_time:", data)
            assert data["timezone"] == "Asia/Kolkata"
            assert data["offset_hours"] == 5.5
            assert "T" in data["iso"]
            assert data["human"]

    asyncio.run(_run())


@pytest.mark.network
def test_currency_convert():
    async def _run():
        async with _mcp_session() as session:
            res = await session.call_tool(
                "currency_convert", {"amount": 100, "from_currency": "usd", "to_currency": "eur"}
            )
            data = _result(res)
            print("currency_convert:", data)
            assert data["from"] == "USD"
            assert data["to"] == "EUR"
            assert data["amount"] == 100
            assert data["source"] == "frankfurter.dev"
            assert data["converted"] > 0
            assert data["rate"] > 0

    asyncio.run(_run())


def test_read_file():
    async def _run():
        _clean_sandbox()
        (SANDBOX / "hello.txt").write_text("hello world", encoding="utf-8")
        async with _mcp_session() as session:
            res = await session.call_tool("read_file", {"path": "hello.txt"})
            data = _result(res)
            print("read_file:", data)
            assert data["content"] == "hello world"
            assert data["encoding"] == "utf-8"
            assert data["size_bytes"] == 11
            assert data["path"] == "hello.txt"

    asyncio.run(_run())


def test_list_dir():
    async def _run():
        _clean_sandbox()
        (SANDBOX / "a.txt").write_text("a", encoding="utf-8")
        (SANDBOX / "sub").mkdir()
        async with _mcp_session() as session:
            res = await session.call_tool("list_dir", {"path": "."})
            data = _result(res)
            print("list_dir:", data)
            entries = _list_dir_entries(data)
            names = {e["name"]: e for e in entries}
            assert names["a.txt"]["type"] == "file"
            assert names["a.txt"]["size_bytes"] == 1
            assert names["sub"]["type"] == "dir"
            assert names["sub"]["size_bytes"] == 0

    asyncio.run(_run())


def test_create_file():
    async def _run():
        _clean_sandbox()
        async with _mcp_session() as session:
            res = await session.call_tool("create_file", {"path": "new.txt", "content": "fresh"})
            data = _result(res)
            print("create_file:", data)
            assert data["ok"] is True
            assert data["size_bytes"] == 5
            assert (SANDBOX / "new.txt").read_text(encoding="utf-8") == "fresh"

            dup = await session.call_tool("create_file", {"path": "new.txt", "content": "x"})
            assert dup.isError, "second create on same path must error"
            print("create_file dup error:", dup.content[0].text if dup.content else "")

    asyncio.run(_run())


def test_update_file():
    async def _run():
        _clean_sandbox()
        (SANDBOX / "u.txt").write_text("old", encoding="utf-8")
        async with _mcp_session() as session:
            res = await session.call_tool("update_file", {"path": "u.txt", "content": "brand new body"})
            data = _result(res)
            print("update_file:", data)
            assert data["ok"] is True
            assert (SANDBOX / "u.txt").read_text(encoding="utf-8") == "brand new body"
            assert data["size_bytes"] == len("brand new body")

            missing = await session.call_tool("update_file", {"path": "nope.txt", "content": "x"})
            assert missing.isError
            print("update_file missing error:", missing.content[0].text if missing.content else "")

    asyncio.run(_run())


def test_edit_file():
    async def _run():
        _clean_sandbox()
        (SANDBOX / "e.txt").write_text("foo bar foo", encoding="utf-8")
        async with _mcp_session() as session:
            multi = await session.call_tool(
                "edit_file", {"path": "e.txt", "find": "foo", "replace": "FOO"}
            )
            assert multi.isError, "ambiguous find without replace_all must error"
            print("edit_file ambiguous error:", multi.content[0].text if multi.content else "")

            res_all = await session.call_tool(
                "edit_file",
                {"path": "e.txt", "find": "foo", "replace": "FOO", "replace_all": True},
            )
            data = _result(res_all)
            print("edit_file replace_all:", data)
            assert data["replacements"] == 2
            assert (SANDBOX / "e.txt").read_text(encoding="utf-8") == "FOO bar FOO"

            res_single = await session.call_tool(
                "edit_file", {"path": "e.txt", "find": "bar", "replace": "BAZ"}
            )
            data = _result(res_single)
            print("edit_file single:", data)
            assert data["replacements"] == 1
            assert (SANDBOX / "e.txt").read_text(encoding="utf-8") == "FOO BAZ FOO"

            missing = await session.call_tool(
                "edit_file", {"path": "e.txt", "find": "zzz", "replace": "x"}
            )
            assert missing.isError
            print("edit_file not-found error:", missing.content[0].text if missing.content else "")

    asyncio.run(_run())


def test_sandbox_escape():
    async def _run():
        async with _mcp_session() as session:
            res = await session.call_tool("read_file", {"path": "../foo"})
            assert res.isError, "sandbox escape must be rejected"
            msg = res.content[0].text if res.content else ""
            print("sandbox_escape error:", msg)
            assert "escape" in msg.lower() or "sandbox" in msg.lower()

    asyncio.run(_run())
