"""Direct smoke test for ComputerSkill layers (requires cua-driver daemon)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from computer.skill import ComputerSkill
from schemas import NodeSpec


async def main() -> int:
    skill = ComputerSkill(
        artifacts_root=str(Path("state/validation/computer")),
        session="validation-smoke",
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
    print("success:", result.success)
    print("output:", result.output)
    print("error:", result.error)
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
