---
name: fusion2hermes
description: Connect Fusion 360 to Hermes and model parts live, including photo → verified part via the CAD bridge.
version: 1.1.0
author: Nilabh Yadav (Nilabh-code), Hermes Agent
license: MIT
platforms: [windows, macos]
metadata:
  hermes:
    tags: [fusion360, cad, mcp, 3d-modeling, autodesk, build123d, rag, canvas]
    related_skills: [procedural-3d-print-model]
---

# Fusion2Hermes

Bridges Autodesk Fusion 360 to Hermes so you build real parametric parts inside
the user's live Fusion session — sketches, features, fillets, assemblies,
exports — instead of handing over a dumb mesh. Works on the **free personal-use
licence**: it does not use Autodesk's licensed MCP server, it exposes Fusion's
own Python API (free on personal use) as MCP tools.

Two MCP servers get installed:

| server | what it is |
|--------|-----------|
| `fusion360` | 93 typed commands that drive the live Fusion session |
| `cadbridge` | knowledge base + sketch canvas + verified build123d runner + STEP hand-off |

Use `fusion360` to *operate* Fusion. Use `cadbridge` when the input is a **photo
and a description** and the output must be a part that has been measured before
anyone trusts it. Two limits up front: no Form/T-Spline sculpting, no mesh→B-Rep.

## When to Use

- "Connect Fusion 360", "set up Fusion2Hermes", "install this skill from <repo URL>".
- A part the user will reopen and edit: parameters, feature tree, assembly, CAM.
- **"Here's a photo of a servo/bracket/gearbox — make it in Fusion."** → the
  cadbridge loop below. This is the case models get wrong when left alone.
- Turning a code-generated STL into an editable solid.
- Don't use for a one-off printable mesh with no editing later — `procedural-3d-print-model` skips Fusion entirely and is faster.

## Prerequisites

- Fusion **desktop** installed and signed in once (not the web client). Windows or macOS.
- `git` and `uv` on PATH (the installer falls back to a tarball download and plain `venv` if either is missing).
- `hermes` on PATH, and the user's permission to run third-party code inside their CAD session — this installs the MIT add-in `faust-machines/fusion360-mcp-server`.

## Setup

Clone the repo somewhere durable, then run the installer from it:

```bash
git clone https://github.com/Nilabh-code/Fusion2Hermes ~/Fusion2Hermes
python ~/Fusion2Hermes/scripts/setup.py
```

`terminal(command="python ~/Fusion2Hermes/scripts/setup.py", timeout=900)`

The installer is idempotent — re-running repairs or upgrades in place. It:
finds the Fusion build · installs the add-in into Fusion's `API/AddIns` with
`runOnStartup: true` · patches its STEP exporter · creates a venv and installs
the MCP server · runs `hermes pm install --extra mcp` if Hermes lacks the SDK ·
registers `fusion360` · copies this skill to `$HERMES_HOME/skills/fusion2hermes`
· builds `bridge/.venv`, installs `cadbridge`, builds the knowledge index,
smoke-tests it (a search plus a measured 300 mm³ box), and registers `cadbridge`.

`--skip-bridge` skips that last group if the user only wants the raw Fusion tools.

**Then restart Fusion once.** The add-in self-starts on every launch after that —
the user never opens Tools → Scripts and Add-Ins. Verify:

```bash
python ~/Fusion2Hermes/scripts/setup.py --check
```

Completion criterion: `--check` prints `add-in socket listening on 127.0.0.1:9876`,
`live handshake OK`, and both `'fusion360'` and `'cadbridge'` registered. A closed
socket means Fusion isn't running or predates the install.

In Hermes, `mcp_fusion360_*` and `mcp_cadbridge_*` tools appear in the next
session; `/reload-mcp` pulls them into the current one.

## Driving Fusion directly

Two interchangeable routes to the same 93 commands:

- **`mcp_fusion360_*` tools** — preferred once loaded (typed schemas, discovered at connect).
- **`scripts/fm_client.py`** — raw socket client, works immediately with no restart. Use the copy
  in the clone (`~/Fusion2Hermes/scripts/fm_client.py`); after `setup.py` runs there is also one
  beside this skill file at `<skill-dir>/scripts/fm_client.py`.
  ```bash
  python ~/Fusion2Hermes/scripts/fm_client.py get_scene_info
  python ~/Fusion2Hermes/scripts/fm_client.py create_box_parametric '{"length":40,"width":30,"height":10}'
  python ~/Fusion2Hermes/scripts/fm_client.py render_view '{"view":"iso"}'
  ```

Wire protocol (for anything the client can't express): newline-delimited JSON to
`127.0.0.1:9876`, request `{"type": "<cmd>", "params": {...}}`, reply
`{"status": "success"|"error", "result": {...}}`. Look up signatures with
`search_files(pattern="def <cmd>", path="<upstream>/addon/server/command_handler.py")`
— arguments are keyword-style. `references/tools.md` lists every command by area.

Working order that avoids most failures:

1. `get_scene_info` — is a design open? `execute_code` with `app.documents.add(...)` if not.
2. Build with `create_box_parametric` / sketch + `extrude` / `revolve` per `references/tools.md`.
3. `render_view` after each visual step and actually look at the PNG — you cannot see the viewport otherwise.
4. `get_physical_properties` to check volume/bbox against hand-computed expectations.
5. `export_stl` / `export_step` with an absolute path, then confirm the file exists and its size is sane.

`execute_code` runs arbitrary Fusion Python API code in the live document — the
escape hatch for anything without a wrapper. Prefer wrapped commands when they
exist; they return structured deltas.

## Driving the CAD bridge (photo → part)

The rule this exists to enforce: **a model's CAD code is not to be believed until
it has been executed and measured.** Models produce scripts that run, look
plausible, and build the wrong thing. Every step below is checkable.

```
1  canvas_open(image=..., prompt=...)   ← user traces the part, calibrates one line
2  canvas_wait                          → shapes in millimetres + a composite PNG
3  cad_context(query)                   ← briefing: house rules, API, recipes, hardware
4  write ONE build123d script           ← name it `part`, mm, Z up, sits on Z=0
5  cad_run_code(code, expect_volume=…)  ← measured volume, bbox, solid count, validity
6  mismatch? feed the numbers back and fix; up to 3 rounds
7  fusion_push_step(step_path)          ← the STEP lands in the live document
```

Steps 5–6 are the point. `cad_run_code` returns what was *measured*, not what the
script meant:

```
{ok, volume_mm3, bbox_mm, solids, valid, faces, error, step, stl, svg, verdict}
```

`verdict.checks` compares against `expect_volume` / `expect_bbox`, and the call is
refused (`ok: false`) unless the result is exactly **one valid solid**.

### Tools

| tool | use |
|------|-----|
| `cad_knowledge_search(query, k, domain)` | build123d API, 13 executable recipes, hardware tables, FDM rules, Fusion API notes |
| `cad_knowledge_get(id)` | one chunk in full |
| `cad_knowledge_stats()` | corpus size, domains, whether dense retrieval is active |
| `cad_context(query)` | retrieve + format a ready-to-paste briefing (use when handing work to a model without tools) |
| `canvas_open(image?, prompt?)` | opens the canvas page, returns `session_id` + `url` |
| `canvas_wait(session_id, timeout)` | blocks until submit; returns annotation JSON incl. mm |
| `canvas_status` / `canvas_close` | poll / finish a session |
| `cad_run_code(code, out_dir?, expect_volume?, expect_bbox?)` | execute + measure + export STEP/STL/SVG |
| `fusion_push_step(step_path, clear?)` | import into the live Fusion document |
| `fusion_status()` | socket alive? which document? |

### Canvas input

`canvas_wait` returns measurements already in millimetres — never re-derive them,
never invent a dimension the user did not give:

```json
{"image": "servo.jpg", "image_size": [640, 480], "prompt": "servo mount",
 "calibration": {"line_px": 236.4, "real_mm": 22.8},
 "scale_mm_per_px": 0.09645,
 "shapes": [
  {"tool": "line",   "a": [120, 88], "b": [412, 88], "length_px": 292.0, "length_mm": 28.16},
  {"tool": "rect",   "a": [120, 88], "b": [412, 244], "w_mm": 28.16, "h_mm": 15.05},
  {"tool": "circle", "a": [176, 132], "b": [190, 132], "r_mm": 1.35, "d_mm": 2.70,
   "label": "flange hole"},
  {"tool": "dim",    "a": [120, 300], "b": [412, 300], "value_mm": 27.6,
   "length_mm": 27.6, "label": "hole centres"},
  {"tool": "text",   "a": [300, 400], "label": "M2 clearance x4, 2.4 dia"}],
 "composite_png": ".../sessions/<sid>/annotation.png"}
```

`a`/`b` are image-pixel points (y down); `a` is the centre for a circle and `b` a
point on its rim. A typed `value_mm` wins over the geometric measurement. If the
user never calibrated, `scale_mm_per_px` is null and no `*_mm` fields appear —
ask for a calibration line instead of inventing a scale.
Full schema and worked example: `references/canvas.md`. Corpus layout and how to
add knowledge: `references/knowledge.md`.

### Rules that produce parts that fit

- Millimetres, Z up, part sitting on Z=0, one solid named `part`.
- Every number must trace to the annotation, the prompt, or a hardware table —
  holes come from the ISO clearance table, not from measuring the photo.
- Model the *mating* part's envelope with clearance (servo body + 0.3 mm), never
  the photo's silhouette exactly.
- Fillet radius ≤ ¼ of the smallest adjacent face; cutters longer than the material.
- Check one number by hand before running: `L×W×H − voids ≈ expected`. If the
  runner's volume is off by more than ~2 %, the script is wrong, not the check.

### Pushing to Fusion

`fusion_push_step` imports into a **new child component** (`CADBridge_<HHMMSS>`)
and returns the measured bounding box — that box is the proof it landed.
`importToTarget` into the *root* component is rejected on Fusion 2705
(`2 : InternalValidationError : results`); the bridge works around it, don't
"fix" it back. `clear=true` deletes previous `CADBridge_*` components and root
bodies first. The component's `bRepBodies.count` reads 0 until Fusion recomputes,
so measure the occurrence bounding box instead of counting bodies.

### Model-agnostic

`cadbridge agent` (or `python -m cadbridge.agent`) drives any OpenAI-compatible
endpoint — llama.cpp, LM Studio, vLLM, Ollama `/v1`, or a cloud API — through
retrieve → generate → run → repair → export → push. A small local model fails on
spatial bookkeeping; the corpus plus the repair loop is what makes it usable. For
a weak model: `cad_context` first, one narrow recipe, and always pass
`expect_volume` so the loop can reject instead of ship.

## Pitfalls

- **The socket has no authentication.** Any local process can drive Fusion while it's open, including `execute_code`. Say this out loud when installing for someone else; it is loopback-only and nothing phones home, but it is not zero-risk.
- **Never kill a running Fusion to "reload" it** — the user may have unsaved work. Ask, or tell them to restart.
- **One active document.** Every command acts on it. Confirm with `get_scene_info` before mutating, and open/activate the target document first.
- **30 s per command.** Long features time out and are cancelled, not applied late — split big builds into steps.
- **STEP export breaks on Fusion 2705** (`3 : invlid argument geometry`) because a `BRepBody` is rejected as STEP geometry. The installer patches it to pass `body.parentComponent`. If a re-clone of upstream overwrites the patch, re-run the installer.
- **Personal-use limits** (licence, not this bridge): 10 editable documents, no extensions, IGES/SAT export blocked. STEP/STL/F3D are fine.
- **Units.** Documents are unit-bound; state mm explicitly. Default to mm.
- **Not everything is scriptable.** Form/T-Spline bodies, mesh→BRep conversion, and drawing (2D) documents have little or no API. For organic shapes, generate geometry with code and import it.
- **The runner is a guardrail, not a sandbox.** It blocks the obvious escapes (`subprocess`, `socket`, `open(`, `eval`, `exec`, `__import__`, …) and runs in a subprocess, but a determined script could still get out. Generated code must be reviewed or come from a model you would let run in your venv.
- **`part` must be one solid.** A snap hook placed tangent to its arm, or a sketch with no base face, silently yields two bodies — the runner rejects it, and that is correct.
- **Don't drive the canvas with the built-in browser tool on localhost** — it refuses `127.0.0.1`. Use Playwright (`bridge/test_canvas_e2e.py`) or a real browser.

## Verification

- `python scripts/setup.py --check` → add-in present, both servers registered, socket open, handshake OK, bridge venv + index present.
- Model something and prove it numerically: volume within ~1 % of the hand-computed value, bounding box exact, `render_view` shows what you claim.
- Bridge tests that must stay green:
  ```bash
  cd bridge && .venv/Scripts/python.exe test_corpus_code.py   # every recipe → one valid solid
  .venv/Scripts/python.exe test_mcp_server.py                 # stdio handshake + real tool calls
  .venv/Scripts/python.exe test_canvas_e2e.py                 # browser + mouse + mm round trip
  .venv/Scripts/python.exe test_agent_loop.py                 # broken script → repair → verified
  .venv/Scripts/python.exe test_pipeline.py                   # script → verify → STEP → inside Fusion
  ```
- Export and confirm the file exists with non-trivial size before reporting success.

Report the exported path and the measured volume, not "done".
