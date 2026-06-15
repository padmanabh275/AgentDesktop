"""V10 embed-endpoint tests. Run from llm_gatewayV10/:  uv run pytest -v tests/test_embed.py

Markers:
  - local:   requires `ollama` running locally with `nomic-embed-text` pulled
  - network: requires OPENAI_API_KEY in .env (or parent) and outbound HTTPS

The tests start an in-process httpx ASGI client against the V10 FastAPI app —
they do NOT require the gateway to be running on port 8110.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from dotenv import load_dotenv

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))
for _candidate in (HERE / ".env", HERE.parent / ".env"):
    if _candidate.exists():
        load_dotenv(_candidate)
        break

EXPECTED_OLLAMA_DIM = 768  # nomic-embed-text
EXPECTED_FALLBACK_DIM = 768  # text-embedding-3-small with dimensions=768


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client():
    """In-process ASGI client. Manually drives FastAPI's lifespan so
    app.state.embedders is wired before any test sends a request."""
    import main as M
    transport = httpx.ASGITransport(app=M.app)
    async with M.app.router.lifespan_context(M.app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            timeout=60,
        ) as c:
            yield c


@pytest.mark.local
@pytest.mark.asyncio
async def test_ollama_embed(client):
    """Hits the live Ollama endpoint; asserts shape and dim = 768."""
    r = await client.post("/v1/embed", json={
        "text": "the quick brown fox",
        "task_type": "retrieval_document",
        "provider": "ollama",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    print("ollama:", {k: v for k, v in d.items() if k != "embedding"}, "vec[0:3]:", d["embedding"][:3])
    assert d["provider"] == "ollama"
    assert d["model"]
    assert d["dim"] == EXPECTED_OLLAMA_DIM
    assert isinstance(d["embedding"], list) and len(d["embedding"]) == EXPECTED_OLLAMA_DIM
    assert all(isinstance(x, (int, float)) for x in d["embedding"][:5])


@pytest.mark.network
@pytest.mark.asyncio
async def test_fallback_embed(client):
    """Hits OpenAI text-embedding-3-small; asserts shape and dim = 768."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    r = await client.post("/v1/embed", json={
        "text": "the quick brown fox",
        "task_type": "retrieval_document",
        "provider": "openai",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    print("openai:", {k: v for k, v in d.items() if k != "embedding"}, "vec[0:3]:", d["embedding"][:3])
    assert d["provider"] == "openai"
    assert d["model"]
    assert d["dim"] == EXPECTED_FALLBACK_DIM
    assert isinstance(d["embedding"], list) and len(d["embedding"]) == EXPECTED_FALLBACK_DIM


@pytest.mark.network
@pytest.mark.asyncio
async def test_failover(client, monkeypatch):
    """Point Ollama at an unused port -> ring should fall over to OpenAI."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    import main as M
    import embedders as E
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:1")  # unbound
    broken_embedders, order = E.build_embedders()
    monkeypatch.setattr(M.app.state, "embedders", broken_embedders)
    monkeypatch.setattr(M.app.state, "embed_order", order)

    r = await client.post("/v1/embed", json={
        "text": "fall over please",
        "task_type": "retrieval_query",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    print("failover:", {k: v for k, v in d.items() if k != "embedding"})
    assert d["provider"] == "openai"
    assert len(d["attempted"]) >= 1 and d["attempted"][0]["provider"] == "ollama"


@pytest.mark.local
@pytest.mark.asyncio
async def test_provider_explicit(client):
    """Pinned provider should appear in the response provider field."""
    r = await client.post("/v1/embed", json={
        "text": "hello world",
        "provider": "ollama",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    print("explicit:", {k: v for k, v in d.items() if k != "embedding"})
    assert d["provider"] == "ollama"
