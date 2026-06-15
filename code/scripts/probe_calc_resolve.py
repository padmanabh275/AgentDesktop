import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cua.client import CuaDriverClient
from computer.layer2a_hotkey import _resolve_target_window, _calc_button_index

c = CuaDriverClient()
launched = c.launch_app(name="Calculator")
pid, wid = _resolve_target_window(c, "Calculator", int(launched["pid"]), None)
print("resolved:", pid, wid)
snap = c.get_window_state(pid, wid, capture_mode="ax")
print("snap keys:", list(snap.keys()))
for k in ("markdown", "ax_tree", "elements", "ax_elements"):
    v = snap.get(k)
    if v:
        s = v if isinstance(v, str) else json.dumps(v)[:3000]
        print(f"--- {k} ---")
        print(s[:3000])
print("button 8:", _calc_button_index(snap, "8"))
print("button *:", _calc_button_index(snap, "*"))
