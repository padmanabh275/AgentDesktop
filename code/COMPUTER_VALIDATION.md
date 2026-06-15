# Session 10 — Computer-Use validation

Desktop automation via **cua-driver** (MCP + CLI) and a new **computer** skill with a five-layer cascade. Trajectory evidence comes from cua-driver `start_recording`.

## Retest results (2026-06-15)

| Task | Result | Evidence |
|------|--------|----------|
| **1 Calculator hotkey** | **PASS** | `path=hotkey`, `result=248171`, trajectory `state/validation/computer/trajectory_1781512941/` (9 turns) |
| **2 Cursor electron** | Manual | Requires `computer/scripts/launch_cursor_debug.ps1` + gateway |
| **3 Canvas vision** | Partial | Screenshot capture works (`screenshot_png_b64`); gateway `/v1/vision` returned 502 (provider config) |

```powershell
# Task 1 direct smoke (passed)
uv run python scripts/smoke_computer_hotkey.py

# Unit tests (passed)
uv run pytest tests/test_computer_tools.py -q
```

**Win11 Calculator note:** UWP apps resolve via `ApplicationFrameHost` title match, not `launch_app` pid. Layer 2a clicks AX buttons parsed from `tree_markdown`.

## Agent Desktop UI

Browser frontend for submitting `USER_QUERY` and watching orchestrator progress.

```powershell
# Prerequisites: gateway + cua-driver (for computer presets)
cd llm_gatewayV10; .\run.ps1
cd ..\code; .\scripts\setup_cua_driver.ps1   # once

# Start UI (default http://localhost:8120)
.\run_ui.ps1
```

| Feature | Detail |
|---------|--------|
| Presets | Calculator, Canvas vision, Cursor electron — each fills `USER_QUERY` |
| Run path | Full flow: Planner → computer (etc.) → Formatter |
| Progress | Poll `GET /api/sessions/{id}` for node status + `trajectory_dir` |
| CLI equivalent | `uv run python flow.py "<same query>"` |

```powershell
uv run pytest tests/test_ui_server.py -q
```


```powershell
# 1. cua-driver (Windows)
cd code
.\scripts\setup_cua_driver.ps1

# 2. LLM Gateway V10
cd ..\llm_gatewayV10
.\run.ps1

# 3. Cursor CDP (Task 2 only)
cd ..\code
.\computer\scripts\launch_cursor_debug.ps1
```

Requires: `cua-driver` on PATH, UI Automation permissions, gateway on `http://localhost:8110`.

## Architecture checklist

| item | status |
|------|--------|
| `code/cua/` shared client + recording | implemented |
| Dual MCP in `mcp_runner.py` (eagv3 + cua-driver) | implemented |
| Researcher opt-in: `cua_list_windows`, `cua_get_window_state` | agent_config.yaml |
| `computer` skill cascade (5 layers) | `code/computer/` |
| `ComputerOutput` + `skills.py` dispatch | implemented |
| `start_recording` on every computer run | `cua/recording.py` |

## Five layers (code map)

| Layer | Path value | Module |
|-------|------------|--------|
| 1 read | `read` | `computer/layer1_read.py` |
| 2a hotkey | `hotkey` | `computer/layer2a_hotkey.py` |
| 2b electron | `electron` | `computer/layer2b_electron.py` |
| 2b ax | `ax` | `computer/layer2b_ax.py` |
| 3 vision | `vision` | `computer/layer3_vision.py` |

Orchestrator: `computer/skill.py`

## Three validation tasks

### Task 1 — Calculator (Layer 2a, zero vision)

```
query : "Open Calculator and compute 847 times 293. Return the displayed result."
expect: path=hotkey, vision calls=0
```

Planner should emit `computer` with `app: Calculator` and arithmetic goal.

### Task 2 — Cursor Electron (Layer 2b electron, zero vision)

```
query : "In Cursor, create notes/s10_evidence.txt containing: Computer-Use Layer2b OK"
metadata: electron_debugging_port=9222
expect: path=electron, vision calls=0
```

Prerequisite: Cursor running with `--remote-debugging-port=9222`.

### Task 3 — Canvas vision (Layer 3, vision required)

```
query : "Open the canvas fixture and click inside the red circle on the canvas."
expect: path=vision, trajectory turn-*/screenshot.png present
```

Fixture: `code/computer/fixtures/canvas_only.html`

## Constraint matrix

| Constraint | Task |
|------------|------|
| At least one vision | Task 3 |
| At least one Electron page path | Task 2 |
| At least one zero-vision completion | Task 1 (and Task 2) |

## Run commands

```powershell
cd code
uv run python flow.py "Open Calculator and compute 847 times 293"
uv run python flow.py "In Cursor create notes/s10_evidence.txt with line Computer-Use Layer2b OK"
uv run python flow.py "Open the canvas fixture and click inside the red circle"
```

## Evidence to submit

Per run, zip or point reviewers to:

```
state/sessions/<session_id>/computer/trajectory_<ts>/
  manifest.json
  turn-00001/
    action.json
    screenshot.png
    app_state.json
```

`ComputerOutput.trajectory_dir` in replay output lists the path.

## Gateway cost checks

```powershell
curl "http://localhost:8110/v1/cost/by_agent?session=<session_id>"
```

- Task 1: `computer` row should show **chat=0, vision=0**
- Task 2: **vision=0**
- Task 3: **vision>=1**

## Unit tests

```powershell
cd code
uv run pytest tests/test_computer_tools.py -q
```

Integration desktop tests require cua-driver daemon (`@pytest.mark.desktop`).
