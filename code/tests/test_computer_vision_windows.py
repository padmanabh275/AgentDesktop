"""Tests for vision layer window selection helpers."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from computer.layer3_vision import (
    _fallback_launch_browser_window,
    _pick_canvas_window,
    _vision_title_blocked,
)


def test_blocks_agent_desktop_ui():
    assert _vision_title_blocked("Agent Desktop UI")
    assert _vision_title_blocked("http://127.0.0.1:8120/")


def test_pick_canvas_by_title():
    listed = {
        "windows": [
            {"title": "Agent Desktop UI", "pid": 1, "window_id": 10},
            {"title": "canvas_only - Personal - Microsoft Edge", "pid": 2, "window_id": 20},
        ],
    }
    pid, wid = _pick_canvas_window(listed, hints=("canvas_only",))
    assert pid == 2 and wid == 20


def test_fallback_single_launched_browser():
    listed = {
        "windows": [
            {
                "title": "Some Tab",
                "pid": 99,
                "window_id": 42,
                "app_name": "msedge.exe",
            },
        ],
    }
    pid, wid = _fallback_launch_browser_window(listed)
    assert pid == 99 and wid == 42


def test_fallback_rejects_multiple_browser_windows():
    listed = {
        "windows": [
            {"title": "Tab A", "pid": 1, "window_id": 10, "app_name": "msedge.exe"},
            {"title": "Tab B", "pid": 1, "window_id": 11, "app_name": "msedge.exe"},
        ],
    }
    assert _fallback_launch_browser_window(listed) == (None, None)
