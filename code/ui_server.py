"""Agent Desktop UI — FastAPI wrapper around flow.Executor.

Serves static/index.html and exposes REST endpoints for presets, health,
and session polling while runs execute in the background.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from cua.client import CuaDriverClient, CuaDriverError
from flow import Executor
from gateway import GATEWAY_URL
from persistence import SESSIONS_ROOT, SessionStore, list_sessions
from schemas import AgentResult

ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
PRESETS_PATH = ROOT / "ui" / "presets.yaml"

_FRAME_GLOBS = (
    "turn-*/click.png",
    "turn-*/screenshot.png",
    "artifacts/vision_turn_*.png",
)

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

RunState = Literal["running", "complete", "failed"]

# In-memory lifecycle for active UI runs (session dir persists on disk).
_run_registry: dict[str, dict[str, Any]] = {}
_registry_lock = asyncio.Lock()


class RunRequest(BaseModel):
    query: str = Field(min_length=1)


class RunResponse(BaseModel):
    session_id: str


class DesktopClickRequest(BaseModel):
    pid: int = Field(ge=1)
    window_id: int = Field(ge=1)
    x: int = Field(ge=0)
    y: int = Field(ge=0)


app = FastAPI(title="Agent Desktop UI", version="1.0.0")

_click_timestamps: dict[str, list[float]] = {}


def _load_presets() -> list[dict]:
    if not PRESETS_PATH.is_file():
        return []
    data = yaml.safe_load(PRESETS_PATH.read_text(encoding="utf-8")) or {}
    return list(data.get("presets") or [])


def _probe_gateway() -> dict[str, Any]:
    try:
        r = httpx.get(f"{GATEWAY_URL}/v1/routers", timeout=3.0)
        return {"ok": r.status_code < 400, "url": GATEWAY_URL, "status": r.status_code}
    except Exception as e:
        return {"ok": False, "url": GATEWAY_URL, "error": str(e)[:200]}


def _probe_cua_driver() -> dict[str, Any]:
    binary = shutil.which("cua-driver")
    if not binary:
        win = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Programs", "Cua", "cua-driver", "bin", "cua-driver.exe",
        )
        if os.path.isfile(win):
            binary = win
    if not binary:
        return {"ok": False, "error": "cua-driver not on PATH"}
    try:
        proc = subprocess.run(
            [binary, "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        out = (proc.stdout or proc.stderr or "").strip()
        ok = proc.returncode == 0 and "running" in out.lower()
        return {"ok": ok, "detail": out[:300]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _probe_vision() -> dict[str, Any]:
    """Quick /v1/vision check (canvas preset needs this)."""
    pixel = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    provider = os.getenv("AGENT_LLM_PROVIDER", "auto").strip().lower()
    if provider in ("", "auto", "failover", "none"):
        provider = None
    body: dict[str, Any] = {
        "image": pixel,
        "prompt": "Reply with one word: ok",
        "max_tokens": 8,
        "agent": "ui_health",
    }
    if provider:
        body["provider"] = provider
    try:
        r = httpx.post(f"{GATEWAY_URL}/v1/vision", json=body, timeout=30.0)
        ok = r.status_code < 400
        detail = ""
        if not ok:
            detail = (r.text or "")[:200]
        return {"ok": ok, "status": r.status_code, "detail": detail}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _cua_driver_binary() -> str | None:
    binary = shutil.which("cua-driver")
    if binary:
        return binary
    win = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Programs", "Cua", "cua-driver", "bin", "cua-driver.exe",
    )
    if os.path.isfile(win):
        return win
    return None


def _list_desktop_windows() -> list[dict[str, Any]]:
    binary = _cua_driver_binary()
    if not binary:
        return []
    try:
        proc = subprocess.run(
            [binary, "call", "list_windows", "{}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            return []
        data = json.loads(proc.stdout or "{}")
        wins = data.get("windows") or []
        out: list[dict[str, Any]] = []
        for w in wins:
            if not isinstance(w, dict):
                continue
            out.append({
                "title": str(w.get("title") or ""),
                "app_name": str(w.get("app_name") or ""),
                "pid": int(w.get("pid") or 0),
                "window_id": int(w.get("window_id") or w.get("id") or 0),
            })
        return out
    except Exception:
        return []


def _session_exists(sid: str) -> bool:
    """True when the session is in the run registry or has persisted data."""
    if sid in _run_registry:
        return True
    d = SESSIONS_ROOT / sid
    if not d.is_dir():
        return False
    return (
        (d / "graph.json").is_file()
        or (d / "graph.pkl").is_file()
        or (d / "query.txt").is_file()
    )


def _session_computer_root(sid: str) -> Path:
    return (SESSIONS_ROOT / sid / "computer").resolve()


def _safe_session_trajectory(sid: str, path: Path) -> Path:
    root = _session_computer_root(sid)
    resolved = path.resolve()
    if root not in resolved.parents and resolved != root:
        raise HTTPException(403, "path outside session computer dir")
    return resolved


def _latest_trajectory_dir(sid: str) -> Path | None:
    comp = _session_computer_root(sid)
    if not comp.is_dir():
        return None
    dirs = sorted(
        (p for p in comp.glob("trajectory_*") if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return dirs[0] if dirs else None


def _latest_frame_path(trajectory_dir: Path) -> tuple[Path | None, str | None]:
    """Return (path, turn_label) for newest frame PNG under a trajectory."""
    if not trajectory_dir.is_dir():
        return None, None
    best: Path | None = None
    best_mtime = 0.0
    best_turn: str | None = None
    for pattern in _FRAME_GLOBS:
        for p in trajectory_dir.glob(pattern):
            if not p.is_file():
                continue
            mtime = p.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best = p
                if p.parent.name.startswith("turn-"):
                    best_turn = p.parent.name
                elif p.name.startswith("vision_turn_"):
                    best_turn = p.stem
    return best, best_turn


def _extract_computer_target(nodes: list[dict]) -> tuple[str | None, str | None, dict | None]:
    """Return (target_app, target_goal, computer dict) from node summaries."""
    computer: dict | None = None
    target_app: str | None = None
    target_goal: str | None = None
    for n in nodes:
        if n.get("skill") != "computer":
            continue
        meta = n.get("metadata") or {}
        if meta.get("app"):
            target_app = str(meta["app"])
        if meta.get("goal"):
            target_goal = str(meta["goal"])
        comp = n.get("computer")
        if comp:
            computer = comp
            out = n.get("output") or {}
            if isinstance(out, dict) and out.get("app"):
                target_app = str(out["app"])
            if isinstance(out, dict) and out.get("goal"):
                target_goal = str(out["goal"])
    return target_app, target_goal, computer


_UI_WINDOW_HINTS = ("agent desktop", ":8120")


def _is_agent_ui_window(title: str) -> bool:
    low = title.lower()
    return any(h in low for h in _UI_WINDOW_HINTS)


def _annotate_windows(
    windows: list[dict[str, Any]],
    *,
    target_app: str | None,
    target_pid: int | None = None,
    target_window_id: int | None = None,
) -> list[dict[str, Any]]:
    hint = (target_app or "").lower()
    out: list[dict[str, Any]] = []
    for w in windows:
        title = str(w.get("title") or "")
        app_name = str(w.get("app_name") or "")
        pid = int(w.get("pid") or 0)
        wid = int(w.get("window_id") or 0)
        is_target = False
        if target_pid and target_window_id and pid == target_pid and wid == target_window_id:
            is_target = True
        elif hint:
            low_title = title.lower()
            low_app = app_name.lower()
            if hint in low_title or hint in low_app:
                is_target = True
            elif hint == "browser" and not _is_agent_ui_window(title) and any(
                b in low_app for b in ("msedge", "chrome", "firefox", "brave", "comet")
            ):
                is_target = True
            elif hint == "calculator" and "calc" in low_title:
                is_target = True
            elif hint == "cursor" and "cursor" in low_title:
                is_target = True
        row = dict(w)
        row["is_target"] = is_target
        out.append(row)
    return out


def _decode_snapshot_png(snap: dict[str, Any]) -> bytes | None:
    """Extract raw PNG bytes from a cua-driver get_window_state response."""
    for key in ("screenshot_png_b64", "screenshot_base64", "image_base64", "screenshot"):
        val = snap.get(key)
        if not isinstance(val, str):
            continue
        raw = val.split(",", 1)[-1] if val.startswith("data:") else val
        if len(raw) < 16:
            continue
        try:
            return base64.b64decode(raw)
        except Exception:
            continue
    for key in ("image", "png"):
        val = snap.get(key)
        if isinstance(val, str) and len(val) > 100:
            try:
                return base64.b64decode(val)
            except Exception:
                continue
    return None


def _frame_dimensions(frame_path: Path | None) -> tuple[int | None, int | None]:
    if not frame_path or not frame_path.is_file():
        return None, None
    try:
        with Image.open(frame_path) as im:
            w, h = im.size
            return w, h
    except Exception:
        return None, None


def _resolve_target_from_windows(
    windows: list[dict[str, Any]],
) -> tuple[int | None, int | None]:
    for w in windows:
        if not w.get("is_target"):
            continue
        pid = int(w.get("pid") or 0)
        wid = int(w.get("window_id") or 0)
        if pid and wid:
            return pid, wid
    return None, None


def _cua_client_or_503() -> CuaDriverClient:
    try:
        return CuaDriverClient()
    except CuaDriverError as e:
        raise HTTPException(503, str(e)) from e


def _check_click_rate_limit(client_host: str) -> None:
    now = time.time()
    times = [t for t in _click_timestamps.get(client_host, []) if now - t < 10.0]
    if len(times) >= 5:
        raise HTTPException(429, "click rate limit exceeded (5 per 10s)")
    times.append(now)
    _click_timestamps[client_host] = times


def _live_payload(sid: str) -> dict[str, Any]:
    payload = _session_payload(sid)
    nodes = payload.get("nodes") or []
    target_app, target_goal, computer = _extract_computer_target(nodes)
    traj = _latest_trajectory_dir(sid)
    frame_path: Path | None = None
    frame_turn: str | None = None
    if traj:
        frame_path, frame_turn = _latest_frame_path(traj)
    windows = _list_desktop_windows()
    target_pid: int | None = None
    target_window_id: int | None = None
    if frame_path and frame_path.parent.name.startswith("turn-"):
        action_file = frame_path.parent / "action.json"
        if action_file.is_file():
            try:
                act = json.loads(action_file.read_text(encoding="utf-8"))
                args = act.get("arguments") or {}
                target_pid = int(args.get("pid") or 0) or None
                target_window_id = int(args.get("window_id") or 0) or None
            except Exception:
                pass
    annotated = _annotate_windows(
        windows,
        target_app=target_app,
        target_pid=target_pid,
        target_window_id=target_window_id,
    )
    if not (target_pid and target_window_id):
        target_pid, target_window_id = _resolve_target_from_windows(annotated)
    frame_width, frame_height = _frame_dimensions(frame_path)
    return {
        "session_id": sid,
        "status": payload.get("status"),
        "target_app": target_app,
        "target_goal": target_goal,
        "target_pid": target_pid,
        "target_window_id": target_window_id,
        "path": (computer or {}).get("path"),
        "turns": (computer or {}).get("turns"),
        "frame_available": frame_path is not None,
        "frame_turn": frame_turn,
        "frame_mtime": int(frame_path.stat().st_mtime) if frame_path else None,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "windows": annotated,
    }


def _node_summary(nid: str, data: dict) -> dict[str, Any]:
    skill = data.get("skill") or ""
    status = data.get("status") or "pending"
    meta = data.get("metadata") or {}
    out: dict[str, Any] = {
        "id": nid,
        "skill": skill,
        "status": status,
        "metadata": meta,
    }
    result = data.get("result")
    if isinstance(result, AgentResult):
        out["success"] = result.success
        out["error"] = result.error
        out["elapsed_s"] = result.elapsed_s
        if isinstance(result.output, dict):
            out["output"] = result.output
            if skill == "computer":
                out["computer"] = {
                    "path": result.output.get("path"),
                    "result": result.output.get("result"),
                    "turns": result.output.get("turns"),
                    "trajectory_dir": result.output.get("trajectory_dir"),
                    "app": result.output.get("app"),
                }
            if skill == "formatter" and result.output.get("final_answer"):
                out["final_answer"] = result.output.get("final_answer")
    return out


def _session_payload(sid: str) -> dict[str, Any]:
    store = SessionStore(sid)
    reg = _run_registry.get(sid, {})
    run_state: RunState = reg.get("state", "complete")
    error = reg.get("error")

    graph = store.read_graph()
    nodes: list[dict] = []
    answer: str | None = reg.get("answer")
    computer: dict | None = None

    if graph is not None:
        for nid in graph.nodes:
            summary = _node_summary(nid, dict(graph.nodes[nid]))
            nodes.append(summary)
            if summary.get("skill") == "formatter" and summary.get("final_answer"):
                answer = summary["final_answer"]
            comp = summary.get("computer")
            if comp and comp.get("trajectory_dir"):
                computer = comp

    if run_state == "complete" and answer is None:
        answer = reg.get("answer")

    target_app, target_goal, computer = _extract_computer_target(nodes)

    return {
        "session_id": sid,
        "query": store.read_query(),
        "status": run_state,
        "error": error,
        "nodes": nodes,
        "answer": answer,
        "computer": computer,
        "target_app": target_app,
        "target_goal": target_goal,
    }


async def _execute_run(sid: str, query: str) -> None:
    async with _registry_lock:
        _run_registry[sid] = {"state": "running", "query": query}
    try:
        result = await Executor().run(query, session_id=sid, quiet=True)
        async with _registry_lock:
            _run_registry[sid] = {
                "state": "complete",
                "query": query,
                "answer": result.answer,
            }
    except Exception as e:
        async with _registry_lock:
            _run_registry[sid] = {
                "state": "failed",
                "query": query,
                "error": f"{type(e).__name__}: {e}",
            }


@app.get("/")
async def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(404, "static/index.html missing")
    return FileResponse(index_path)


@app.get("/api/presets")
async def api_presets():
    return {"presets": _load_presets()}


@app.get("/api/health")
async def api_health():
    return {
        "gateway": _probe_gateway(),
        "vision": _probe_vision(),
        "cua_driver": _probe_cua_driver(),
        "ui_port": int(os.getenv("AGENT_UI_PORT", "8120")),
    }


@app.post("/api/run", response_model=RunResponse)
async def api_run(body: RunRequest):
    import uuid

    sid = f"ui-{uuid.uuid4().hex[:8]}"
    asyncio.create_task(_execute_run(sid, body.query.strip()))
    return RunResponse(session_id=sid)


@app.get("/api/sessions")
async def api_sessions():
    sessions = list_sessions()
    return {"sessions": sessions[-20:]}


@app.get("/api/sessions/{sid}")
async def api_session(sid: str):
    if not _session_exists(sid):
        raise HTTPException(404, f"session not found: {sid}")
    return _session_payload(sid)


@app.get("/api/sessions/{sid}/live")
async def api_session_live(sid: str):
    if not _session_exists(sid):
        raise HTTPException(404, f"session not found: {sid}")
    return _live_payload(sid)


@app.get("/api/sessions/{sid}/frame")
async def api_session_frame(sid: str):
    if not _session_exists(sid):
        raise HTTPException(404, f"session not found: {sid}")
    traj = _latest_trajectory_dir(sid)
    if not traj:
        raise HTTPException(404, "no trajectory yet")
    frame_path, _ = _latest_frame_path(traj)
    if not frame_path:
        raise HTTPException(404, "no frame yet")
    safe = _safe_session_trajectory(sid, frame_path)
    return FileResponse(safe, media_type="image/png")


@app.get("/api/desktop/windows")
async def api_desktop_windows():
    return {"windows": _list_desktop_windows()}


@app.post("/api/desktop/click")
async def api_desktop_click(body: DesktopClickRequest, request: Request):
    _check_click_rate_limit(request.client.host if request.client else "unknown")
    client = _cua_client_or_503()
    try:
        result = client.click(
            pid=body.pid,
            window_id=body.window_id,
            x=body.x,
            y=body.y,
        )
    except CuaDriverError as e:
        raise HTTPException(502, str(e)[:300]) from e
    return {"ok": True, "result": result}


@app.get("/api/desktop/snapshot")
async def api_desktop_snapshot(pid: int, window_id: int):
    if pid < 1 or window_id < 1:
        raise HTTPException(400, "pid and window_id required")
    client = _cua_client_or_503()
    try:
        snap = client.get_window_state(pid, window_id, capture_mode="som")
    except CuaDriverError as e:
        raise HTTPException(502, str(e)[:300]) from e
    png = _decode_snapshot_png(snap)
    if not png:
        try:
            snap = client.get_window_state(pid, window_id, capture_mode="vision")
            png = _decode_snapshot_png(snap)
        except CuaDriverError as e:
            raise HTTPException(502, str(e)[:300]) from e
    if not png:
        raise HTTPException(404, "no screenshot in window state")
    return Response(content=png, media_type="image/png")


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
