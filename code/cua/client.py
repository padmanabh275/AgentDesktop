"""Thin wrapper around the cua-driver CLI (daemon-backed).

ComputerSkill and CuaDriverClient share this module. Tool-using skills
reach cua-driver via mcp_runner's MCP stdio session instead.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any


class CuaDriverError(RuntimeError):
    pass


def _find_cua_driver() -> str:
    env = os.environ.get("CUA_DRIVER_BIN")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("cua-driver")
    if found:
        return found
    win_default = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Programs", "Cua", "cua-driver", "bin", "cua-driver.exe",
    )
    if win_default and os.path.isfile(win_default):
        return win_default
    raise CuaDriverError(
        "cua-driver not found on PATH. Run code/scripts/setup_cua_driver.ps1"
    )


class CuaDriverClient:
    """Call cua-driver tools through `cua-driver call <tool> <json>`."""

    def __init__(self, binary: str | None = None):
        self.binary = binary or _find_cua_driver()

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> Any:
        args = arguments or {}
        payload = json.dumps(args, ensure_ascii=True)
        proc = subprocess.run(
            [self.binary, "call", tool, payload],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise CuaDriverError(f"cua-driver {tool} failed ({proc.returncode}): {err[:500]}")
        out = (proc.stdout or "").strip()
        if not out:
            return {}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"raw": out}

    def launch_app(self, **kwargs: Any) -> dict:
        return self.call("launch_app", kwargs)

    def list_windows(self, pid: int | None = None) -> dict:
        body: dict[str, Any] = {}
        if pid is not None:
            body["pid"] = pid
        return self.call("list_windows", body)

    def get_window_state(
        self,
        pid: int,
        window_id: int,
        *,
        capture_mode: str = "ax",
        query: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "pid": pid,
            "window_id": window_id,
            "capture_mode": capture_mode,
        }
        if query:
            body["query"] = query
        return self.call("get_window_state", body)

    def click(self, pid: int, window_id: int, **kwargs: Any) -> dict:
        body: dict[str, Any] = {"pid": pid, "window_id": window_id, **kwargs}
        return self.call("click", body)

    def type_text(self, pid: int, text: str, **kwargs: Any) -> dict:
        body: dict[str, Any] = {"pid": pid, "text": text, **kwargs}
        return self.call("type_text", body)

    def hotkey(self, keys: list[str], **kwargs: Any) -> dict:
        return self.call("hotkey", {"keys": keys, **kwargs})

    def press_key(self, key: str, **kwargs: Any) -> dict:
        return self.call("press_key", {"key": key, **kwargs})

    def page(
        self,
        pid: int,
        action: str,
        *,
        window_id: int | None = None,
        **kwargs: Any,
    ) -> dict:
        body: dict[str, Any] = {"pid": pid, "action": action, **kwargs}
        if window_id is not None:
            body["window_id"] = window_id
        return self.call("page", body)

    def start_recording(self, output_dir: str, *, record_video: bool = False) -> dict:
        return self.call(
            "start_recording",
            {"output_dir": output_dir, "record_video": record_video},
        )

    def stop_recording(self) -> dict:
        return self.call("stop_recording", {})

    def get_recording_state(self) -> dict:
        return self.call("get_recording_state", {})
