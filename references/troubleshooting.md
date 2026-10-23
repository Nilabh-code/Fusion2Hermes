# Troubleshooting

Every failure below has a specific signature. Work down this list instead of guessing.

## `--check` says the socket is closed

Fusion isn't running, or it was already running before you installed the add-in.

1. Start (or restart) Fusion. The add-in has `runOnStartup: true`, so it starts by itself.
   Give it ~20-60 s from a cold start — Fusion takes that long before it loads add-ins.
2. Confirm: `netstat -ano | grep 9876` (Windows) — you want a `LISTENING` line on `127.0.0.1:9876`.
3. Still closed? Read `~/fusion360mcp.log`. A successful start ends with:

   ```
   fusion360mcp.main: Fusion360MCP loaded - server on localhost:9876
   fusion360mcp.socket: Server listening on localhost:9876
   ```
4. Nothing in the log at all means Fusion never loaded the add-in. Check the folder is exactly
   `<APPDATA>/Autodesk/Autodesk Fusion 360/API/AddIns/Fusion360MCP/` containing
   `Fusion360MCP.py` and `Fusion360MCP.manifest`.

## Fusion shows a message box "Fusion360MCP failed to start"

That's the add-in's own error path — the traceback is in the box and in `~/fusion360mcp.log`.
Usual causes: the add-in folder was copied without its `server/` subfolder, or a port-collision
on 9876 from a previous run. Stop Fusion, check the folder tree, start again.

## `hermes mcp add` says "requires the 'mcp' Python SDK, but it is not installed"

Hermes runs from one install *environment* out of several under
`AppData/Local/hermes/installs/*/environments/*/`, and the one in use may lack the SDK. Don't
pip-install by hand; fix it from the Hermes side:

```bash
hermes pm install --extra mcp
```

The installer does this automatically when it sees that message.

## `hermes mcp add` just hangs

It prompts on stdin — `Does this server require authentication?`, `Enable all 93 tools?`,
`Save config anyway?`. Non-interactive callers must pipe answers (`printf 'y\n' | ...`). The
installer already does.

## Tools don't appear in my Hermes session

MCP tools load at session start. Either run `/reload-mcp`, or start a new session. Meanwhile
`scripts/fm_client.py` works immediately — it talks to the socket directly, no MCP involved.

## STEP export fails with `3 : invlid argument geometry`

The upstream add-in passes a `BRepBody` as STEP geometry, which Fusion 2705 rejects. The installer
patches it to pass the owning `Component` (`body.parentComponent`). If you re-cloned upstream by
hand, or the patch line was lost in an upgrade, re-run:

```bash
python scripts/setup.py
```

Hot-apply without restarting Fusion: send the `reload_handler` command
(`python scripts/fm_client.py reload_handler`) — but the *installed* copy is what gets reloaded,
so the patch must be on disk first.

## A command times out

The bridge cancels commands after 30 s and **does not** apply them late, so a timeout is safe to
retry. Split large builds into steps — one extrude, then the fillets, then the holes.

## Geometry looks wrong

Sequence to diagnose, cheapest first:

1. `get_scene_info` — is the document you think you're editing actually active?
2. `get_physical_properties` — compare volume against hand arithmetic. A 40×30×10 plate is
   12,000 mm³ before fillets and holes take material away.
3. `render_view` and look at the PNG. You cannot see the viewport otherwise; never assume.

## Units are off by 25.4

You parameterised something in inches while the document is in mm. Fusion documents are
unit-bound; pass mm values and set document units explicitly.

## macOS

The installer handles `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns`
and the macOS webdeploy layout, but the add-in's own docs only claim Windows and macOS support —
macOS has **not** been verified by this repo's author. Treat first-run failures there as
unvalidated rather than broken.

## Uninstall

1. Stop the add-in: Shift+S → Add-Ins → Fusion360MCP → Stop (or quit Fusion).
2. Delete `<APPDATA>/Autodesk/Autodesk Fusion 360/API/AddIns/Fusion360MCP`.
3. `hermes mcp remove fusion360`.
4. Delete the skill folder `$HERMES_HOME/skills/creative/fusion2hermes` and the clone.
