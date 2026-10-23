---
name: fusion2hermes
description: Connect Fusion 360 to Hermes and model parts live.
version: 1.0.0
author: Nilabh Yadav (Nilabh-code), Hermes Agent
license: MIT
platforms: [windows, macos]
metadata:
  hermes:
    tags: [fusion360, cad, mcp, 3d-modeling, autodesk]
    related_skills: [procedural-3d-print-model]
---

# Fusion2Hermes

Bridges Autodesk Fusion 360 to Hermes so you build real parametric parts inside
the user's live Fusion session — sketches, features, fillets, assemblies,
exports — instead of handing over a dumb mesh. Works on the **free personal-use
licence**: it does not use Autodesk's licensed MCP server, it exposes Fusion's
own Python API (free on personal use) as MCP tools.

93 tools over a loopback bridge. This skill covers install, verification, and
how to drive it. Two limits up front: it cannot do Form/T-Spline sculpting,
and it cannot convert meshes to B-Rep.

## When to Use

- "Connect Fusion 360", "set up Fusion2Hermes", "install this skill from <repo URL>".
- A part the user will reopen and edit: parameters, feature tree, assembly, CAM.
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
registers `fusion360` · copies this skill to `$HERMES_HOME/skills/creative/fusion2hermes`.

**Then restart Fusion once.** The add-in self-starts on every launch after that —
the user never opens Tools → Scripts and Add-Ins. Verify:

```bash
python ~/Fusion2Hermes/scripts/setup.py --check
```

Completion criterion: `--check` prints both `add-in socket listening on 127.0.0.1:9876`
and `live handshake OK`. A closed socket means Fusion isn't running or predates the install.

In Hermes, `mcp_fusion360_*` tools appear in the next session; `/reload-mcp` pulls
them into the current one.

## Driving it

Two interchangeable routes to the same 93 commands:

- **`mcp_fusion360_*` tools** — preferred once loaded (typed schemas, discovered at connect).
- **`scripts/fm_client.py`** — raw socket client, works immediately with no restart:
  ```bash
  python <skill-dir>/scripts/fm_client.py get_scene_info
  python <skill-dir>/scripts/fm_client.py create_box_parametric '{"length":40,"width":30,"height":10}'
  python <skill-dir>/scripts/fm_client.py render_view '{"view":"iso"}'
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

## Pitfalls

- **The socket has no authentication.** Any local process can drive Fusion while it's open, including `execute_code`. Say this out loud when installing for someone else; it is loopback-only and nothing phones home, but it is not zero-risk.
- **Never kill a running Fusion to "reload" it** — the user may have unsaved work. Ask, or tell them to restart.
- **One active document.** Every command acts on it. Confirm with `get_scene_info` before mutating, and open/activate the target document first.
- **30 s per command.** Long features time out and are cancelled, not applied late — split big builds into steps.
- **STEP export breaks on Fusion 2705** (`3 : invlid argument geometry`) because a `BRepBody` is rejected as STEP geometry. The installer patches it to pass `body.parentComponent`. If a re-clone of upstream overwrites the patch, re-run the installer.
- **Personal-use limits** (licence, not this bridge): 10 editable documents, no extensions, IGES/SAT export blocked. STEP/STL/F3D are fine.
- **Units.** Documents are unit-bound; state mm explicitly. Default to mm.
- **Not everything is scriptable.** Form/T-Spline bodies, mesh→BRep conversion, and drawing (2D) documents have little or no API. For organic shapes, generate geometry with code and import it.

## Verification

- `python scripts/setup.py --check` → add-in present, `fusion360` registered, socket open, handshake OK.
- Model something and prove it numerically: volume within ~1% of the hand-computed value, bounding box exact, `render_view` shows what you claim.
- Export and confirm the file exists with non-trivial size before reporting success.

Report the exported path, not "done".
