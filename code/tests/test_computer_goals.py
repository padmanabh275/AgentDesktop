"""Tests for computer goal routing helpers."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from computer.goal_utils import (
    enrich_computer_metadata,
    is_canvas_fixture_goal,
    is_calculator_goal,
    is_cursor_goal,
    is_launchable_app_name,
    normalize_app_for_goal,
)


def test_canvas_fixture_detection():
    assert is_canvas_fixture_goal("Open the canvas fixture and click the red circle")
    assert is_canvas_fixture_goal("click inside red circle on canvas")
    assert not is_canvas_fixture_goal("Open Calculator")


def test_launchable_app_names():
    assert is_launchable_app_name("Calculator")
    assert not is_launchable_app_name("CanvasFixtureApp")
    assert not is_launchable_app_name("canvas_fixture")


def test_normalize_canvas_app():
    assert normalize_app_for_goal("CanvasFixtureApp", "canvas fixture click") == "browser"


def test_cursor_goal_detection():
    assert is_cursor_goal("In Cursor, create notes/s10_evidence.txt")
    assert not is_cursor_goal("Open Calculator")


def test_calculator_goal_detection():
    assert is_calculator_goal("Open Calculator and compute 847 times 293")
    assert not is_calculator_goal("click red circle on canvas")


def test_enrich_computer_metadata_from_user_query():
    meta = enrich_computer_metadata({}, "In Cursor, create notes/s10_evidence.txt")
    assert meta["app"] == "Cursor"
    assert meta["electron_debugging_port"] == 9222
    assert "s10_evidence" in meta["goal"]

    calc = enrich_computer_metadata(
        {"question": "compute result"},
        "Open Calculator and compute 847 times 293",
    )
    assert calc["app"] == "Calculator"
    assert "847" in calc["goal"]
