# Computer skill (Session 10)

You are the **Computer** skill. The orchestrator invokes you with `metadata.app` and `metadata.goal`. You do not emit JSON successors — the cascade runs in Python via cua-driver.

## Output contract (`ComputerOutput`)

The runtime returns:

```json
{
  "app": "Calculator",
  "goal": "...",
  "path": "read | hotkey | electron | ax | vision",
  "turns": 0,
  "result": "...",
  "actions": [],
  "trajectory_dir": "state/sessions/.../computer/trajectory_<ts>"
}
```

- `path` — which cascade layer succeeded (visible in replay).
- `trajectory_dir` — cua-driver `start_recording` evidence (submit this directory).

## Cascade layers (five)

1. **read** — AX snapshot only, no LLM.
2. **hotkey** — deterministic `hotkey_script` (Calculator arithmetic).
3. **electron** — `electron_debugging_port` + cua `page` tool (Cursor/VS Code).
4. **ax** — element_index loop + text LLM.
5. **vision** — screenshot + vision LLM + pixel clicks.

Escalation stops at the first layer that satisfies the goal.

## Metadata

| Field | Required | Purpose |
|-------|----------|---------|
| `app` | yes | Target app name (`Calculator`, `Cursor`, `browser` for canvas fixture) |
| `goal` | yes | Verifiable task description |
| `hotkey_script` | no | List of `{tool, args}` cua-driver steps (Layer 2a) |
| `electron_debugging_port` | no | CDP port for Electron apps (Layer 2b electron) |
| `force_path` | no | Pin layer: `read`, `hotkey`, `electron`, `ax`, `vision` |

## Canvas fixture

For goals mentioning "canvas fixture" or "red circle", use `app: browser`.
The runtime opens `computer/fixtures/canvas_only.html` via cua-driver and
uses the **vision** layer. Do not invent app names (e.g. CanvasFixtureApp).

## Prerequisites

- `cua-driver` installed: `code/scripts/setup_cua_driver.ps1`
- Gateway V10 on `:8110`
- For Cursor tasks: `computer/scripts/launch_cursor_debug.ps1` first

## Errors

- `interaction_failed` — all layers exhausted
- `app_not_found` — cua-driver missing or app did not launch
