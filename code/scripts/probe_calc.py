import json
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cua.client import CuaDriverClient

c = CuaDriverClient()
launched = c.launch_app(name="Calculator")
print("launch:", json.dumps(launched, indent=2)[:800])
pid = launched["pid"]
time.sleep(1.5)
wid = launched["windows"][0]["window_id"]
print("launch window_id:", wid)
try:
    snap = c.get_window_state(pid, wid, capture_mode="ax")
except Exception as e:
    print("launch wid failed:", e)
    listed = c.list_windows()
    print("all windows count:", len(listed.get("windows") or []))
    for w in (listed.get("windows") or []):
        if "calc" in str(w.get("title", "")).lower():
            print("match:", w)
            wid = w["window_id"]
    snap = c.get_window_state(pid, wid, capture_mode="ax")
print("keys:", list(snap.keys()))
print(json.dumps(snap, indent=2)[:4000])
