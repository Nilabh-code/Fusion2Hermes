"""cadbridge MCP server — CAD knowledge, sketch canvas, code runner, Fusion push.

    python -m cadbridge.server            # stdio (what Hermes registers)

Register with Hermes:

    hermes mcp add cadbridge --command "<venv>/Scripts/python.exe" --args -m cadbridge.server

Tools
  cad_knowledge_search / cad_knowledge_get / cad_knowledge_stats
  cad_context                 retrieve + format knowledge for a model that has no tools
  canvas_open / canvas_wait / canvas_status / canvas_close
  cad_run_code                execute build123d, verify, export STEP/STL/SVG
  fusion_push_step / fusion_status
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import canvas as canvas_mod
from . import fusion_link, runner
from .rag import get_kb

OUTDIR = Path(os.environ.get("CADBRIDGE_OUT",
                             Path.home() / "cadbridge" / "out"))

srv = MCPServer(
    name="cadbridge",
    version="1.0.0",
    instructions=(
        "CAD bridge for text->3D. Workflow: canvas_open(image_path) to let the user "
        "mark up a photo, canvas_wait for the millimetre annotations, "
        "cad_knowledge_search for the build123d pattern and hardware sizes, write ONE "
        "build123d script (house rules: `part`, mm, one solid), cad_run_code to execute "
        "and verify it, then fusion_push_step to put the STEP into Fusion 360. Never "
        "report a model as working without a successful cad_run_code result."
    ),
)


# ─────────────────────────────────────────────────────────────── knowledge ──
@srv.tool(description="Search the CAD knowledge base (build123d API, recipes, "
                     "hardware tables, Fusion API, print rules). Start here.")
def cad_knowledge_search(query: str, k: int = 6, domain: str | None = None,
                         kind: str | None = None) -> dict:
    kb = get_kb()
    hits = kb.search(query, k=max(1, min(k, 20)), domain=domain, kind=kind)
    return {"query": query, "count": len(hits), "results": hits}


@srv.tool(description="Fetch one knowledge chunk in full by id (ids come from search).")
def cad_knowledge_get(doc_id: str) -> dict:
    kb = get_kb()
    got = kb.get(doc_id)
    if not got:
        return {"error": f"no chunk with id {doc_id!r}",
                "suggestions": [c["id"] for c in kb.listing()[:10]]}
    return got


@srv.tool(description="Corpus size, domains and whether dense retrieval is active.")
def cad_knowledge_stats() -> dict:
    return get_kb().stats()


@srv.tool(description="Retrieve knowledge for a task and format it as a ready-to-paste "
                     "briefing block, for a model that cannot call tools itself.")
def cad_context(query: str, k: int = 8) -> dict:
    kb = get_kb()
    hits = kb.search(query, k=max(1, min(k, 16)))
    lines = ["# CAD briefing (retrieved knowledge — follow it exactly)", ""]
    for h in hits:
        lines.append(f"## {h['title']}  [{h['id']} / {h['domain']}]")
        lines.append(h["text"].strip())
        lines.append("")
    lines.append("# House rules")
    for rule in kb.search("house rules emitted script", k=1, domain="workflow"):
        lines.append(rule["text"].strip())
    return {
        "query": query,
        "context": "\n".join(lines),
        "chunks": [{"id": h["id"], "title": h["title"]} for h in hits],
    }


# ────────────────────────────────────────────────────────────────── canvas ──
@srv.tool(description="Open the sketch canvas in the user's browser, optionally with an "
                     "image loaded. The user draws outlines, hole centres, dimension lines "
                     "and calibrates one line to a real mm length, then presses Send.")
def canvas_open(image_path: str | None = None, prompt: str = "", title: str = "",
                open_browser: bool = True) -> dict:
    srv_ = canvas_mod.get_server(open_browser=open_browser)
    sess = srv_.open_session(image_path, prompt=prompt, title=title)
    return {
        "session_id": sess.id,
        "url": srv_.url(sess.id),
        "has_image": bool(sess.image_path),
        "image_size": sess.image_size,
        "next": f"call canvas_wait(session_id='{sess.id}') after the user submits",
    }


@srv.tool(description="Block until the user submits the canvas annotation (or timeout). "
                     "Returns shapes with millimetres, notes, the prompt and a PNG path.")
def canvas_wait(session_id: str, timeout_s: float = 300.0) -> dict:
    out = canvas_mod.get_server().wait(session_id, timeout=timeout_s)
    if out.get("timed_out"):
        out["next"] = "the page is still open — ask the user to press Send, then wait again"
        return out
    ann = out.get("annotation") or {}
    shapes = ann.get("shapes", [])
    out["summary"] = {
        "shapes": len(shapes),
        "scale_mm_per_px": ann.get("scale_mm_per_px"),
        "measured": [s for s in shapes if any(k in s for k in ("length_mm", "w_mm", "d_mm"))],
        "unmeasured": [s for s in shapes if not any(k in s for k in ("length_mm", "w_mm", "d_mm"))],
        "notes": ann.get("notes", ""),
        "prompt": ann.get("prompt", ""),
    }
    out["next"] = ("look at composite_png if you need to see the markup; use the mm values "
                   "in annotation.shapes; unmeasured shapes are pixels only — ask or assume")
    return out


@srv.tool(description="Non-blocking canvas status: has the user submitted yet?")
def canvas_status(session_id: str) -> dict:
    sess = canvas_mod.get_server().get(session_id)
    out = sess.public()
    out["hint"] = ("submitted" if sess.submitted else
                   "still drawing — the user has not pressed Send")
    return out


@srv.tool(description="Close a canvas session (the page can stay open; state is dropped).")
def canvas_close(session_id: str) -> dict:
    s = canvas_mod.get_server()
    sess = s.sessions.pop(session_id, None)
    return {"closed": bool(sess), "session_id": session_id}


# ────────────────────────────────────────────────────────────────── runner ──
@srv.tool(description="Execute a build123d script in a separate process. Returns the real "
                     "volume, bounding box, solid count, validity, mass estimate, and "
                     "STEP/STL/SVG paths. Pass expect_volume / expect_bbox to get a verdict.")
def cad_run_code(code: str, out_dir: str | None = None, expect_volume: float | None = None,
                 expect_bbox: list[float] | None = None, timeout_s: int = 120) -> dict:
    target = Path(out_dir) if out_dir else OUTDIR
    res = runner.run_code(code, out_dir=target, timeout=timeout_s)
    if not res.get("ok"):
        return res
    summary = {
        "ok": True,
        "volume_mm3": round(res["volume"], 3),
        "area_mm2": round(res["area"], 2),
        "bbox_mm": [round(v, 3) for v in res["bbox"]],
        "bbox_min_mm": [round(v, 3) for v in res["bbox_min"]],
        "solids": res["solids"],
        "faces": res["faces"],
        "valid": res["valid"],
        "mass_g_pla": round(res["mass_g_pla"], 2),
        "files": res.get("files", {}),
        "seconds": res.get("seconds"),
    }
    if res.get("warnings"):
        summary["warnings"] = res["warnings"]
    if expect_volume is not None or expect_bbox:
        expect = {}
        if expect_volume is not None:
            expect["volume"] = expect_volume
        if expect_bbox:
            expect["bbox"] = expect_bbox
        summary["verdict"] = runner.compare(res, expect)
        summary["ok"] = summary["verdict"]["pass"]
    return summary


# ────────────────────────────────────────────────────────────────── fusion ──
@srv.tool(description="Import a STEP file into the running Fusion 360 document (needs the "
                     "Fusion360MCP add-in, installed by this repo's setup.py).")
def fusion_push_step(step_path: str) -> dict:
    try:
        out = fusion_link.push_step(step_path)
        out["next"] = "the body is in the active Fusion document; the user can now inspect or export"
        return out
    except fusion_link.FusionLinkError as exc:
        return {"ok": False, "error": str(exc),
                "help": "open Fusion 360, or run scripts/setup.py --check in the repo"}


@srv.tool(description="Is the Fusion 360 add-in reachable? Returns the active document and "
                     "body count.")
def fusion_status() -> dict:
    if not fusion_link.is_alive():
        return {"alive": False,
                "help": "start Fusion 360; the add-in auto-loads on startup"}
    try:
        info = fusion_link.document_info()
        return {"alive": True, "socket": "127.0.0.1:9876", **info}
    except Exception as exc:
        return {"alive": True, "error": str(exc)}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true",
                    help="serve streamable HTTP on 127.0.0.1:8477/mcp instead of stdio")
    ap.add_argument("--port", type=int, default=8478)
    args = ap.parse_args()
    if args.http:
        os.environ.setdefault("CADBRIDGE_PORT", "8477")
        srv.run(transport="streamable-http", port=args.port)
    else:
        srv.run(transport="stdio")


if __name__ == "__main__":
    main()
