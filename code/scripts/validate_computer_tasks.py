"""Smoke tests for ComputerSkill validation tasks."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from computer.skill import ComputerSkill
from schemas import NodeSpec


async def task1_calculator() -> bool:
    skill = ComputerSkill(
        artifacts_root=str(Path("state/validation/computer")),
        session="validation-task1",
    )
    node = NodeSpec(
        skill="computer",
        inputs=["USER_QUERY"],
        metadata={
            "app": "Calculator",
            "goal": "Compute 847 times 293 and return the displayed result.",
            "force_path": "hotkey",
        },
    )
    result = await skill.run(node)
    out = result.output or {}
    ok = (
        result.success
        and out.get("path") == "hotkey"
        and str(out.get("result", "")).replace(",", "") == "248171"
    )
    print("task1:", "PASS" if ok else "FAIL", out)
    return ok


async def task3_canvas() -> bool:
    skill = ComputerSkill(
        artifacts_root=str(Path("state/validation/computer")),
        session="validation-task3",
    )
    node = NodeSpec(
        skill="computer",
        inputs=["USER_QUERY"],
        metadata={
            "app": "browser",
            "goal": "Open the canvas fixture and click inside the red circle on the canvas.",
            "force_path": "vision",
        },
    )
    result = await skill.run(node)
    out = result.output or {}
    ok = result.success and out.get("path") == "vision"
    print("task3:", "PASS" if ok else "FAIL", result.error, out.get("path"), out.get("trajectory_dir"))
    return ok


async def main() -> int:
    parser = argparse.ArgumentParser(description="Computer-use validation tasks")
    parser.add_argument("--task1", action="store_true", help="Calculator hotkey only")
    parser.add_argument("--task3", action="store_true", help="Canvas vision only")
    args = parser.parse_args()
    run_all = not args.task1 and not args.task3

    results: list[bool] = []
    if run_all or args.task1:
        results.append(await task1_calculator())
    if run_all or args.task3:
        results.append(await task3_canvas())
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
