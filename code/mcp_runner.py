"""Tool-use loop: eagv3 MCP + optional cua-driver MCP (dual stdio)."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from cua.tools import is_cua_tool, strip_cua_prefix
from gateway import LLM

MCP_SERVER = Path(__file__).parent / "mcp_server.py"
MAX_TOOL_HOPS = 6


def _cua_driver_command() -> list[str]:
    env_bin = os.environ.get("CUA_DRIVER_BIN")
    if env_bin:
        return [env_bin, "mcp"]
    found = shutil.which("cua-driver")
    if found:
        return [found, "mcp"]
    win = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Cua" / "cua-driver" / "bin" / "cua-driver.exe"
    if win.is_file():
        return [str(win), "mcp"]
    return ["cua-driver", "mcp"]


def _needs_cua(tools_payload: list[dict]) -> bool:
    return any(is_cua_tool(t.get("name", "")) for t in tools_payload)


async def _dispatch_tool(
    eagv3: ClientSession,
    cua: ClientSession | None,
    name: str,
    args: dict,
) -> str:
    session = cua if is_cua_tool(name) and cua is not None else eagv3
    wire_name = strip_cua_prefix(name) if is_cua_tool(name) else name
    try:
        result = await session.call_tool(wire_name, arguments=args)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
    parts: list[str] = []
    for c in (getattr(result, "content", None) or []):
        t = getattr(c, "text", None)
        parts.append(t if t is not None else str(c))
    return "\n".join(parts) if parts else ""


async def run_with_tools(*, prompt: str, tools_payload: list[dict],
                         agent: str, session_id: str,
                         provider_pin: str | None = None,
                         max_tokens: int = 2048,
                         temperature: float = 0.3) -> dict:
    messages: list[dict] = [{"role": "user", "content": prompt}]
    last_reply: dict = {}

    eagv3_params = StdioServerParameters(command=sys.executable, args=[str(MCP_SERVER)])
    use_cua = _needs_cua(tools_payload)

    async with stdio_client(eagv3_params) as (eread, ewrite):
        async with ClientSession(eread, ewrite) as eagv3:
            await eagv3.initialize()
            if use_cua:
                cua_cmd = _cua_driver_command()
                cua_params = StdioServerParameters(command=cua_cmd[0], args=cua_cmd[1:])
                async with stdio_client(cua_params) as (cread, cwrite):
                    async with ClientSession(cread, cwrite) as cua_sess:
                        await cua_sess.initialize()
                        last_reply = await _tool_loop(
                            messages, tools_payload, eagv3, cua_sess,
                            agent, session_id, provider_pin, max_tokens, temperature,
                        )
            else:
                last_reply = await _tool_loop(
                    messages, tools_payload, eagv3, None,
                    agent, session_id, provider_pin, max_tokens, temperature,
                )
    return last_reply


async def _tool_loop(
    messages, tools_payload, eagv3, cua_sess,
    agent, session_id, provider_pin, max_tokens, temperature,
) -> dict:
    last_reply: dict = {}
    for _ in range(MAX_TOOL_HOPS + 1):
        reply = await _chat(
            messages=messages, tools=tools_payload,
            agent=agent, session_id=session_id,
            provider_pin=provider_pin,
            max_tokens=max_tokens, temperature=temperature,
        )
        last_reply = reply
        tool_calls = reply.get("tool_calls") or []
        if not tool_calls:
            return reply
        messages.append({
            "role": "assistant",
            "content": reply.get("text", "") or "",
            "tool_calls": tool_calls,
        })
        for tc in tool_calls:
            result_text = await _dispatch_tool(
                eagv3, cua_sess, tc["name"], tc.get("arguments") or {},
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result_text[:8_000],
            })
    return last_reply


async def _chat(*, messages, tools, agent, session_id, provider_pin,
                max_tokens, temperature) -> dict:
    import asyncio as _a
    return await _a.to_thread(
        LLM().chat,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        agent=agent,
        session=session_id,
        provider=provider_pin,
        max_tokens=max_tokens,
        temperature=temperature,
    )
