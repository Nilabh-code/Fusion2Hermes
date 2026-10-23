"""Connect any OpenAI-compatible model to the bridge, with a repair loop.

    # 1. mark up a photo (opens a browser canvas), then build from it
    python -m cadbridge.agent --annotate photo.png --prompt "servo mount, 3 mm walls" \
        --base-url http://127.0.0.1:8080/v1 --model qwen3-coder

    # 2. from an existing annotation json
    python -m cadbridge.agent --annotation ann.json --prompt "same but 5 mm walls"

    # 3. from text only
    python -m cadbridge.agent --prompt "M3 hex standoff, 12 mm tall, 5.5 across flats"

The loop: retrieve knowledge -> ask the model for one build123d script -> execute it
-> if it fails or the measured volume/bbox disagrees, feed the real numbers back and
retry (default 3 attempts) -> export STEP/STL -> optionally push into Fusion.

Works with llama.cpp, LM Studio, vLLM, Ollama (/v1), EXL, or a cloud API — anything
that speaks POST {base_url}/chat/completions.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import canvas as canvas_mod
from . import fusion_link, runner
from .rag import get_kb

SYSTEM = """You are a mechanical CAD engineer. You write build123d scripts that build one
solid part, exactly as specified by the drawing annotation and the request.

Hard rules:
- Start with `from build123d import *`. `import math` is allowed. Nothing else.
- All dimensions in millimetres.
- Assign the finished single solid to a variable named `part`.
- Z is up, the part sits on Z=0, centred on X/Y. Exactly one solid.
- Every dimension must come from the annotation, the request, or the hardware
  tables in the briefing. Do not invent dimensions; if something is unknown, choose
  the standard value and note it in a comment.
- Return ONLY a fenced ```python block with the script. No prose.

Common failure to avoid: a fillet radius larger than the material, cutting with a
cutter that is exactly flush with the surface, subtracting from an empty builder, or
leaving a feature that splits the part into two solids."""


def chat(base_url: str, model: str, messages: list[dict], api_key: str | None,
         temperature: float = 0.2, max_tokens: int = 2000, timeout: float = 300.0) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps({"model": model, "messages": messages, "temperature": temperature,
                       "max_tokens": max_tokens, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    if isinstance(content, list):                      # some servers return parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content


def annotation_text(ann: dict) -> str:
    """Compact, model-friendly rendering of the canvas annotation."""
    lines = []
    if ann.get("image_size"):
        lines.append(f"image: {ann['image_size'][0]} x {ann['image_size'][1]} px")
    if ann.get("scale_mm_per_px"):
        lines.append(f"scale: {ann['scale_mm_per_px']} mm per pixel (calibrated)")
    else:
        lines.append("scale: NOT calibrated - only labelled mm values are trustworthy")
    cal = ann.get("calibration") or {}
    if cal.get("real_mm"):
        lines.append(f"calibration line: {cal['line_px']} px = {cal['real_mm']} mm")
    lines.append("shapes (drawing order):")
    for i, s in enumerate(ann.get("shapes", []), 1):
        bits = [f"{i}. {s.get('tool')}"]
        if s.get("label"):
            bits.append(f'label="{s["label"]}"')
        for k in ("length_mm", "w_mm", "h_mm", "r_mm", "d_mm", "length_px"):
            if s.get(k) is not None:
                bits.append(f"{k}={s[k]}")
        if s.get("text"):
            bits.append(f'text="{s["text"]}"')
        if s.get("pts"):
            bits.append(f"pts={s['pts']}")
        lines.append("   " + "  ".join(bits))
    if ann.get("notes"):
        lines.append(f"notes: {ann['notes']}")
    return "\n".join(lines)


def build_messages(briefing: str, request: str, ann_text: str, feedback: str = "") -> list[dict]:
    user = f"""# Briefing (retrieved knowledge - follow it)
{briefing}

# Drawing annotation
{ann_text or "(none - text request only)"}

# What to build
{request}
"""
    if feedback:
        user += f"\n# Your previous attempt FAILED - fix these measured facts\n{feedback}\n"
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": user}]


def generate(base_url: str, model: str, api_key: str | None, request: str,
             ann: dict | None, out_dir: Path, attempts: int = 3,
             push: bool = False, verbose: bool = True) -> dict:
    kb = get_kb()
    query = " ".join(filter(None, [request, (ann or {}).get("notes", ""),
                                   " ".join(s.get("label", "") for s in (ann or {}).get("shapes", []))]))
    briefing = "\n\n".join(
        f"## {h['title']} [{h['id']}]\n{h['text']}" for h in kb.search(query, k=8))
    ann_text = annotation_text(ann or {})

    history = build_messages(briefing, request, ann_text)
    feedback = ""
    last = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            history = build_messages(briefing, request, ann_text, feedback)
        reply = chat(base_url, model, history, api_key)
        code = runner.extract_code(reply)
        if verbose:
            print(f"[attempt {attempt}] {len(code)} chars of code from {model}")
        res = runner.run_code(code, out_dir=out_dir)
        last = {"attempt": attempt, "code": code, "result": res, "reply": reply}
        if res.get("ok") and res.get("solids") == 1 and res.get("valid"):
            runs = res["files"]
            out = {
                "ok": True, "attempts": attempt, "code": code,
                "volume_mm3": round(res["volume"], 3),
                "bbox_mm": [round(v, 3) for v in res["bbox"]],
                "mass_g_pla": round(res["mass_g_pla"], 2),
                "files": runs, "model": model,
            }
            if push and runs.get("step"):
                try:
                    out["fusion"] = fusion_link.push_step(runs["step"])
                except Exception as exc:
                    out["fusion_error"] = str(exc)
            return out
        feedback = (
            f"script did not produce one valid solid.\n"
            f"error: {(res.get('error') or '').strip()[-900:]}\n"
            f"measured: solids={res.get('solids')} valid={res.get('valid')} "
            f"volume={res.get('volume')} bbox={res.get('bbox')}\n"
            f"previous code:\n```python\n{code}\n```"
        )
        if verbose:
            print(f"[attempt {attempt}] FAILED: {(res.get('error') or 'invalid solid').strip().splitlines()[-1][:160]}")
    return {"ok": False, "attempts": attempts, "last": last,
            "error": "no valid solid after retries"}


def main() -> int:
    ap = argparse.ArgumentParser(description="text/image -> verified build123d -> Fusion")
    ap.add_argument("--prompt", required=True, help="what to build")
    ap.add_argument("--annotate", help="image to mark up first in the canvas")
    ap.add_argument("--annotation", help="existing annotation .json")
    ap.add_argument("--base-url", default=os.environ.get("CADBRIDGE_BASE_URL",
                                                         "http://127.0.0.1:8080/v1"))
    ap.add_argument("--model", default=os.environ.get("CADBRIDGE_MODEL", "local-model"))
    ap.add_argument("--api-key", default=os.environ.get("CADBRIDGE_API_KEY"))
    ap.add_argument("--out", default=str(Path.home() / "cadbridge" / "out"))
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--push", action="store_true", help="import the STEP into Fusion")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out)
    ann = None
    if args.annotate:
        srv = canvas_mod.get_server()
        sess = srv.open_session(args.annotate, prompt=args.prompt)
        print(f"canvas: {srv.url(sess.id)}\nwaiting for you to draw and press Send ...")
        got = srv.wait(sess.id, timeout=1800)
        ann = got.get("annotation") or {}
    elif args.annotation:
        ann = json.loads(Path(args.annotation).read_text(encoding="utf-8"))

    out = generate(args.base_url, args.model, args.api_key, args.prompt, ann,
                   out_dir, attempts=args.attempts, push=args.push,
                   verbose=not args.quiet)
    print(json.dumps({k: v for k, v in out.items() if k != "code"}, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
