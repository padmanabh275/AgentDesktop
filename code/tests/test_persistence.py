"""Persistence helpers (atomic write on Windows/OneDrive)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from persistence import _atomic_write


def test_atomic_write_success(tmp_path: Path):
    target = tmp_path / "graph.json"
    _atomic_write(target, '{"ok": true}')
    assert target.read_text(encoding="utf-8") == '{"ok": true}'


def test_atomic_write_falls_back_after_replace_denied(tmp_path: Path):
    target = tmp_path / "graph.json"
    calls = {"n": 0}
    real_replace = __import__("os").replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise PermissionError(13, "Access is denied")
        real_replace(src, dst)

    with patch("persistence.os.replace", side_effect=flaky_replace):
        _atomic_write(target, "recovered")
    assert target.read_text(encoding="utf-8") == "recovered"


def test_atomic_write_direct_fallback_when_replace_never_succeeds(tmp_path: Path):
    target = tmp_path / "graph.json"

    with patch("persistence.os.replace", side_effect=PermissionError(13, "denied")):
        _atomic_write(target, "direct")
    assert target.read_text(encoding="utf-8") == "direct"
