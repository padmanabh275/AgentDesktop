"""UI server smoke tests (no full orchestrator run)."""
from __future__ import annotations

import base64
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import networkx as nx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import persistence
from persistence import SessionStore
from ui_server import (
    _annotate_windows,
    _decode_snapshot_png,
    _extract_computer_target,
    _frame_dimensions,
    _latest_frame_path,
    _live_payload,
    _load_presets,
    _probe_gateway,
    _resolve_target_from_windows,
    app,
)

client = TestClient(app)

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_presets_yaml():
    presets = _load_presets()
    ids = {p["id"] for p in presets}
    assert "calc_hotkey" in ids
    assert "canvas_vision" in ids
    assert "cursor_electron" in ids
    calc = next(p for p in presets if p["id"] == "calc_hotkey")
    assert "847" in calc["query"]
    assert calc.get("layer") == "hotkey"
    canvas = next(p for p in presets if p["id"] == "canvas_vision")
    assert canvas.get("layer") == "vision"


def test_app_routes_exist():
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/presets" in paths
    assert "/api/health" in paths
    assert "/api/run" in paths
    assert "/api/sessions/{sid}/live" in paths
    assert "/api/sessions/{sid}/frame" in paths
    assert "/api/desktop/windows" in paths
    assert "/api/desktop/click" in paths
    assert "/api/desktop/snapshot" in paths


def test_gateway_probe_shape():
    g = _probe_gateway()
    assert "ok" in g
    assert "url" in g


def test_latest_frame_path_picks_newest(tmp_path: Path):
    traj = tmp_path / "trajectory_1"
    turn1 = traj / "turn-00001"
    turn2 = traj / "turn-00002"
    artifacts = traj / "artifacts"
    turn1.mkdir(parents=True)
    turn2.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    old = turn1 / "click.png"
    old.write_bytes(b"old")
    new = artifacts / "vision_turn_01.png"
    new.write_bytes(b"new")
    time.sleep(0.02)
    new.touch()
    path, turn = _latest_frame_path(traj)
    assert path == new
    assert turn == "vision_turn_01"


def test_extract_computer_target_from_metadata():
    nodes = [
        {
            "skill": "computer",
            "metadata": {"app": "browser", "goal": "click red circle"},
            "computer": {"path": "vision", "turns": 1},
        },
    ]
    app_name, goal, comp = _extract_computer_target(nodes)
    assert app_name == "browser"
    assert goal == "click red circle"
    assert comp["path"] == "vision"


def test_annotate_windows_highlights_target():
    windows = [
        {"title": "Agent Desktop UI", "app_name": "msedge.exe", "pid": 1, "window_id": 10},
        {"title": "canvas_only - Comet", "app_name": "comet.exe", "pid": 2, "window_id": 20},
    ]
    out = _annotate_windows(windows, target_app="browser")
    assert out[0]["is_target"] is False
    assert out[1]["is_target"] is True


def test_session_frame_404_without_trajectory(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr("ui_server.SESSIONS_ROOT", tmp_path)
    sid = "ui-test-frame"
    store = SessionStore(sid)
    store.write_query("test")
    r = client.get(f"/api/sessions/{sid}/frame")
    assert r.status_code == 404


def test_session_live_404_without_session():
    sid = f"ui-{uuid.uuid4().hex}-missing"
    r = client.get(f"/api/sessions/{sid}/live")
    assert r.status_code == 404


def test_session_live_returns_target_app(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr("ui_server.SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr("ui_server._list_desktop_windows", lambda: [])
    sid = "ui-test-live"
    store = SessionStore(sid)
    graph = nx.DiGraph()
    graph.add_node(
        "n:2",
        skill="computer",
        status="running",
        metadata={"app": "browser", "goal": "click red circle"},
    )
    store.write_graph(graph)
    r = client.get(f"/api/sessions/{sid}/live")
    assert r.status_code == 200
    body = r.json()
    assert body["target_app"] == "browser"
    assert body["target_goal"] == "click red circle"


def test_health_includes_vision():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "vision" in body
    assert "gateway" in body


def test_decode_snapshot_png():
    b64 = base64.b64encode(_TINY_PNG).decode("ascii")
    assert _decode_snapshot_png({"screenshot_png_b64": b64}) == _TINY_PNG
    assert _decode_snapshot_png({}) is None


def test_resolve_target_from_windows():
    windows = [
        {"title": "Other", "pid": 1, "window_id": 10, "is_target": False},
        {"title": "Calc", "pid": 99, "window_id": 88, "is_target": True},
    ]
    assert _resolve_target_from_windows(windows) == (99, 88)


def test_frame_dimensions(tmp_path: Path):
    png = tmp_path / "frame.png"
    Image.new("RGB", (320, 240), color="red").save(png)
    w, h = _frame_dimensions(png)
    assert w == 320
    assert h == 240


def test_live_payload_includes_frame_dimensions(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr("ui_server.SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr("ui_server._list_desktop_windows", lambda: [])
    sid = "ui-test-dims"
    store = SessionStore(sid)
    store.write_query("test")
    comp = tmp_path / sid / "computer"
    traj = comp / "trajectory_1"
    turn = traj / "turn-00001"
    turn.mkdir(parents=True)
    frame = turn / "click.png"
    Image.new("RGB", (100, 80), color="blue").save(frame)
    action = turn / "action.json"
    action.write_text(
        '{"arguments": {"pid": 42, "window_id": 7}}',
        encoding="utf-8",
    )
    payload = _live_payload(sid)
    assert payload["frame_width"] == 100
    assert payload["frame_height"] == 80
    assert payload["target_pid"] == 42
    assert payload["target_window_id"] == 7


def test_desktop_click_400_invalid_body():
    r = client.post("/api/desktop/click", json={"pid": 0, "window_id": 1, "x": 0, "y": 0})
    assert r.status_code == 422


def test_desktop_click_success(monkeypatch):
    mock_client = MagicMock()
    mock_client.click.return_value = {"ok": True}
    monkeypatch.setattr("ui_server._cua_client_or_503", lambda: mock_client)
    r = client.post(
        "/api/desktop/click",
        json={"pid": 100, "window_id": 200, "x": 50, "y": 60},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    mock_client.click.assert_called_once_with(pid=100, window_id=200, x=50, y=60)


def test_desktop_snapshot_returns_png(monkeypatch):
    b64 = base64.b64encode(_TINY_PNG).decode("ascii")
    mock_client = MagicMock()
    mock_client.get_window_state.return_value = {"screenshot_png_b64": b64}
    monkeypatch.setattr("ui_server._cua_client_or_503", lambda: mock_client)
    r = client.get("/api/desktop/snapshot", params={"pid": 1, "window_id": 2})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == _TINY_PNG


def test_desktop_snapshot_404_without_image(monkeypatch):
    mock_client = MagicMock()
    mock_client.get_window_state.return_value = {}
    monkeypatch.setattr("ui_server._cua_client_or_503", lambda: mock_client)
    r = client.get("/api/desktop/snapshot", params={"pid": 1, "window_id": 2})
    assert r.status_code == 404


def test_desktop_snapshot_400_missing_params():
    r = client.get("/api/desktop/snapshot", params={"pid": 0, "window_id": 2})
    assert r.status_code == 400
