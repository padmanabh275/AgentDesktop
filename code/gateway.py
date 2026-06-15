"""Bridge to llm_gatewayV10.

V10 is the Session 10 gateway: V9 plus the V10 branding/port bump
(8110 default). Carries forward vision (`/v1/vision`), multimodal chat,
embeddings, agent/session tagging, batch chat, and per-agent USD cost.

Auto-starts the gateway if it is not already up, then re-exports the V10
`LLM` client and a module-level `embed()` helper.

Legacy env vars (`LLM_GATEWAY_V9_*`, `GATEWAY_V9_PORT`, `llm_gatewayV9/`)
are still honoured for migration.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

_code_dir = Path(__file__).resolve().parent
for _env in (_code_dir / ".env", _code_dir.parent / ".env"):
    if _env.exists():
        load_dotenv(_env)


def _resolve_gateway_dir() -> Path:
    for key in (
        "S10_GATEWAY_DIR",
        "S9_GATEWAY_DIR",
        "LLM_GATEWAY_V10_DIR",
        "LLM_GATEWAY_V9_DIR",
    ):
        raw = os.environ.get(key)
        if raw:
            return Path(raw).resolve()
    root = Path(__file__).resolve().parent.parent
    for name in ("llm_gatewayV10", "llm_gatewayV9"):
        candidate = root / name
        if candidate.exists():
            return candidate.resolve()
    return (root / "llm_gatewayV10").resolve()


def _resolve_gateway_url() -> str:
    for key in ("LLM_GATEWAY_V10_URL", "LLM_GATEWAY_V9_URL"):
        raw = os.environ.get(key)
        if raw:
            return raw.rstrip("/")
    port = (
        os.getenv("GATEWAY_V10_PORT")
        or os.getenv("GATEWAY_V9_PORT")
        or "8110"
    )
    return f"http://localhost:{port}"


GATEWAY_V10_DIR = _resolve_gateway_dir()
GATEWAY_V9_DIR = GATEWAY_V10_DIR  # back-compat alias
GATEWAY_URL = _resolve_gateway_url()


def _gateway_python() -> list[str]:
    """Prefer the gateway's own venv — avoids uv dev-deps sync on Windows/OneDrive."""
    for candidate in (
        GATEWAY_V10_DIR / ".venv" / "Scripts" / "python.exe",
        GATEWAY_V10_DIR / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return [str(candidate), "main.py"]
    return ["uv", "run", "--no-dev", "--no-sync", "python", "main.py"]


def _is_up() -> bool:
    try:
        httpx.get(f"{GATEWAY_URL}/v1/routers", timeout=2.0)
        return True
    except Exception:
        return False


def resolve_agent_provider(explicit: str | None = None) -> str | None:
    """Provider pin for gateway /v1/chat calls, or None for LLM_ORDER failover.

    Set AGENT_LLM_PROVIDER=auto (default) to try free-tier workers first.
    Set AGENT_LLM_PROVIDER=oai (or gemini, groq, …) to pin every agent call.
    """
    if explicit:
        return explicit
    env = os.getenv("AGENT_LLM_PROVIDER", "auto").strip().lower()
    if env in ("", "auto", "failover", "none"):
        return None
    return env


def ensure_gateway() -> None:
    """Start V10 if it is not already running. Idempotent."""
    if _is_up():
        return
    if not GATEWAY_V10_DIR.exists():
        raise RuntimeError(
            f"Gateway V10 directory not found at {GATEWAY_V10_DIR}. "
            "Build llm_gatewayV10 before running the agent code."
        )
    print(f"[gateway] launching llm_gatewayV10 from {GATEWAY_V10_DIR}")
    env = os.environ.copy()
    env.setdefault("UV_LINK_MODE", "copy")
    subprocess.Popen(
        _gateway_python(),
        cwd=str(GATEWAY_V10_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    for _ in range(45):
        time.sleep(1)
        if _is_up():
            print(f"[gateway] up on {GATEWAY_URL}")
            return
    raise RuntimeError(
        f"Gateway V10 failed to start within 45s. Check {GATEWAY_V10_DIR}"
    )


import importlib.util as _importlib_util

_client_path = GATEWAY_V10_DIR / "client.py"
if _client_path.exists():
    _spec = _importlib_util.spec_from_file_location("llm_gatewayV10_client", _client_path)
    _mod = _importlib_util.module_from_spec(_spec)
    assert _spec.loader is not None
    _spec.loader.exec_module(_mod)
    LLM = _mod.LLM
else:
    LLM = None


def embed(text: str, task_type: str = "retrieval_document") -> dict:
    """Compute an embedding for `text` via the gateway's embed endpoint."""
    ensure_gateway()
    if LLM is None:
        raise RuntimeError(
            f"Gateway V10 client unavailable. Expected client at {_client_path}."
        )
    return LLM(base_url=GATEWAY_URL).embed(text, task_type=task_type)


__all__ = [
    "ensure_gateway",
    "LLM",
    "GATEWAY_URL",
    "GATEWAY_V10_DIR",
    "GATEWAY_V9_DIR",
    "embed",
    "resolve_agent_provider",
]
