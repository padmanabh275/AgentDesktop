"""Session 10: Computer-Use skill — five-layer cascade via cua-driver.

    Layer 1  — read-only AX snapshot (no LLM)
    Layer 2a — deterministic hotkey_script (no LLM)
    Layer 2b — electron page/CDP OR AX element_index (text LLM)
    Layer 3  — vision capture_mode + pixel clicks (vision LLM)
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from browser.client import V10Client
from cua.client import CuaDriverClient, CuaDriverError
from cua.recording import start_recording
from gateway import resolve_agent_provider
from schemas import AgentResult, ComputerOutput, NodeSpec

from .layer1_read import try_read
from .goal_utils import (
    is_canvas_fixture_goal,
    is_calculator_goal,
    is_cursor_goal,
    normalize_app_for_goal,
)
from .layer2a_hotkey import run_hotkey_script, script_for_metadata
from .layer2b_ax import run_ax
from .layer2b_electron import run_electron
from .layer3_vision import run_vision

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


class ComputerSkill:
    NAME = "computer"

    def __init__(
        self,
        *,
        gateway_url: str = "http://localhost:8110",
        agent_tag: str = "computer",
        a11y_provider_pin: str | None = None,
        vision_provider_pin: str | None = None,
        artifacts_root: str | None = None,
        wall_clock_s: float = 120.0,
        session: str | None = None,
    ):
        self.gateway_url = gateway_url
        self.agent_tag = agent_tag
        self.a11y_provider_pin = resolve_agent_provider(a11y_provider_pin)
        self.vision_provider_pin = resolve_agent_provider(vision_provider_pin)
        self.artifacts_root = Path(artifacts_root) if artifacts_root else None
        self.wall_clock_s = wall_clock_s
        self.session = session

    async def run(self, node: NodeSpec) -> AgentResult:
        meta = dict(node.metadata or {})
        goal = str(meta.get("goal") or meta.get("question") or "")
        app = normalize_app_for_goal(
            str(meta.get("app") or "desktop"),
            goal,
        )
        force_path = meta.get("force_path")
        electron_port = meta.get("electron_debugging_port")
        if electron_port is not None:
            electron_port = int(electron_port)
        elif app.lower() in ("cursor", "code", "vscode", "visual studio code"):
            electron_port = int(os.getenv("CURSOR_ELECTRON_DEBUG_PORT", "9222"))

        if not goal:
            return self._pack_error(app, goal, "interaction_failed", "no goal in metadata")

        t0 = time.time()
        trajectory_base = (
            self.artifacts_root
            if self.artifacts_root
            else Path("state/sessions/computer")
        )
        trajectory_base.mkdir(parents=True, exist_ok=True)

        try:
            cua = CuaDriverClient()
        except CuaDriverError as e:
            return self._pack_error(app, goal, "interaction_failed", str(e), elapsed=time.time() - t0)

        recording = start_recording(
            trajectory_base,
            session_id=self.session or "",
            goal=goal,
            app=app,
        )
        trajectory_dir = str(recording.output_dir.resolve())

        gateway = V10Client(
            base_url=self.gateway_url,
            agent=self.agent_tag,
            session=self.session,
        )
        artifacts_dir = recording.output_dir / "artifacts"

        try:
            result = await self._cascade(
                cua, gateway, app=app, goal=goal, force_path=force_path,
                electron_port=electron_port, metadata=meta,
                artifacts_dir=artifacts_dir, trajectory_dir=trajectory_dir,
                a11y_provider=self.a11y_provider_pin,
                vision_provider=self.vision_provider_pin,
            )
            recording.stop()
            result.elapsed_s = time.time() - t0
            out = result.output or {}
            out["trajectory_dir"] = trajectory_dir
            result.output = out
            return result
        except Exception as e:
            recording.stop()
            return self._pack_error(
                app, goal, "interaction_failed",
                f"{type(e).__name__}: {e}",
                path=getattr(self, "_last_cascade_path", "read"),
                elapsed=time.time() - t0,
                trajectory_dir=trajectory_dir,
            )

    async def _cascade(
        self,
        cua: CuaDriverClient,
        gateway: V10Client,
        *,
        app: str,
        goal: str,
        force_path: str | None,
        electron_port: int | None,
        metadata: dict,
        artifacts_dir: Path,
        trajectory_dir: str,
        a11y_provider: str | None = None,
        vision_provider: str | None = None,
    ) -> AgentResult:
        pin = vision_provider or self.vision_provider_pin
        self._last_cascade_path = "read"
        last_path = "read"
        # Layer 1 — read (skip interactive/canvas goals)
        if force_path not in ("hotkey", "electron", "ax", "vision"):
            if not is_canvas_fixture_goal(goal):
                read_out = await try_read(cua, app=app, goal=goal)
                if read_out and (force_path == "read" or force_path is None):
                    return self._pack(
                        app, goal, "read", result=read_out["result"],
                        actions=[], trajectory_dir=trajectory_dir,
                    )

        # Layer 2a — hotkey
        last_path = "hotkey"
        self._last_cascade_path = last_path
        script = script_for_metadata(metadata, app)
        if script and force_path in (None, "hotkey", "read"):
            hot = await run_hotkey_script(cua, script, app=app)
            if hot.get("success") or force_path == "hotkey":
                if hot.get("success"):
                    return self._pack(
                        app, goal, "hotkey",
                        result=str(hot.get("result") or ""),
                        actions=hot.get("actions") or [],
                        trajectory_dir=trajectory_dir,
                    )
                if force_path == "hotkey" or is_calculator_goal(goal):
                    return self._pack_error(
                        app, goal, "interaction_failed",
                        str(hot.get("result") or "hotkey script failed"),
                        path=last_path,
                        trajectory_dir=trajectory_dir,
                    )

        # Layer 2b electron
        last_path = "electron"
        self._last_cascade_path = last_path
        electron_task = bool(
            electron_port
            or is_cursor_goal(goal)
            or app.lower() in ("cursor", "code", "vscode", "visual studio code")
        )
        electron_port_eff = int(electron_port or 0) or (
            9222 if electron_task else None
        )
        if electron_port_eff and force_path != "ax" and force_path != "vision":
            try:
                elec = await run_electron(
                    cua, gateway, app=app, goal=goal,
                    electron_port=electron_port_eff,
                    provider=a11y_provider,
                )
            except Exception as e:
                return self._pack_error(
                    app, goal, "interaction_failed",
                    f"{type(e).__name__}: {e}",
                    path=last_path,
                    trajectory_dir=trajectory_dir,
                )
            if elec.success or force_path == "electron":
                if elec.success:
                    return self._pack(
                        app, goal, "electron",
                        result=elec.result,
                        actions=elec.actions,
                        turns=elec.turns,
                        trajectory_dir=trajectory_dir,
                    )
                if force_path == "electron" or electron_task:
                    return self._pack_error(
                        app, goal, "interaction_failed",
                        elec.note or "electron layer failed",
                        path=last_path,
                        trajectory_dir=trajectory_dir,
                    )

        # Layer 2b AX (canvas fixture escalates to vision)
        last_path = "ax"
        self._last_cascade_path = last_path
        if force_path not in ("vision",) and not is_canvas_fixture_goal(goal):
            if electron_task and force_path is None:
                return self._pack_error(
                    app, goal, "interaction_failed",
                    "Cursor/electron task could not attach — run "
                    "computer/scripts/launch_cursor_debug.ps1 (port 9222)",
                    path="electron",
                    trajectory_dir=trajectory_dir,
                )
            ax = await run_ax(
                cua, gateway, app=app, goal=goal, provider=a11y_provider,
            )
            if ax.success or force_path == "ax":
                if ax.success:
                    return self._pack(
                        app, goal, "ax",
                        result=ax.result,
                        actions=ax.actions,
                        turns=ax.turns,
                        trajectory_dir=trajectory_dir,
                    )
                if force_path == "ax":
                    return self._pack_error(
                        app, goal, "interaction_failed", ax.note,
                        path=last_path,
                        trajectory_dir=trajectory_dir,
                    )

        if is_calculator_goal(goal) and force_path is None:
            return self._pack_error(
                app, goal, "interaction_failed",
                "Calculator hotkey path did not complete",
                path="hotkey",
                trajectory_dir=trajectory_dir,
            )

        last_path = "vision"
        self._last_cascade_path = last_path
        try:
            vis = await run_vision(
                cua, gateway, app=app, goal=goal,
                artifacts_dir=artifacts_dir,
                provider=pin,
            )
        except Exception as e:
            return self._pack_error(
                app, goal, "interaction_failed",
                f"{type(e).__name__}: {e}",
                path=last_path,
                trajectory_dir=trajectory_dir,
            )
        if vis.success:
            return self._pack(
                app, goal, "vision",
                result=vis.result or vis.note,
                actions=vis.actions,
                turns=vis.turns,
                trajectory_dir=trajectory_dir,
            )
        return self._pack_error(
            app, goal, "interaction_failed",
            vis.note or "all layers exhausted",
            path=last_path,
            trajectory_dir=trajectory_dir,
        )

    def _pack(
        self,
        app: str,
        goal: str,
        path: str,
        *,
        result: str = "",
        actions: list | None = None,
        turns: int = 0,
        trajectory_dir: str = "",
        elapsed: float = 0.0,
    ) -> AgentResult:
        body = ComputerOutput(
            app=app,
            goal=goal,
            path=path,
            turns=turns,
            result=result or None,
            actions=actions or [],
            trajectory_dir=trajectory_dir,
        )
        return AgentResult(
            success=True,
            agent_name=self.NAME,
            output=body.model_dump(),
            elapsed_s=elapsed,
        )

    def _pack_error(
        self,
        app: str,
        goal: str,
        error_code: str,
        error: str,
        *,
        path: str = "read",
        elapsed: float = 0.0,
        trajectory_dir: str = "",
    ) -> AgentResult:
        return AgentResult(
            success=False,
            agent_name=self.NAME,
            output=ComputerOutput(
                app=app, goal=goal, path=path,
                result=None, trajectory_dir=trajectory_dir,
            ).model_dump(),
            error=error,
            error_code=error_code,
            elapsed_s=elapsed,
        )
