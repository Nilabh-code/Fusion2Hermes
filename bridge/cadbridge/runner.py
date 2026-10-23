"""Execute generated build123d code in an isolated process and report the truth.

The whole point: a model's script is not trusted, it is *run*. The runner returns
the solid's measured volume, bounding box, face count and validity, exports
STEP/STL/SVG, and refuses anything that is not exactly one valid solid.

    from cadbridge.runner import run_code
    r = run_code(code)
    r["ok"], r["volume"], r["bbox"], r["step"]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Static guardrail. This is NOT a sandbox — it blocks the obvious footguns so a
# hallucinated script cannot silently rewrite files or reach the network.
DENY = (
    "subprocess", "os.system", "os.popen", "shutil", "socket", "requests",
    "urllib", "http.client", "ctypes", "pickle", "eval(", "exec(",
    "__import__", "importlib", "builtins", "open(",
)
ALLOWED_IMPORTS = ("build123d", "from build123d import", "import math", "from math import")

WRAPPER = r'''
import json, math, os, sys, traceback
import build123d
from build123d import *

OUT = {"ok": False, "error": None}
src = SRC
try:
    ns = {"__name__": "__cad__"}
    exec(compile(src, "<cad>", "exec"), ns)
    names = [k for k in ("part", "solid", "body", "model", "result", "shape") if k in ns]
    if not names:
        raise RuntimeError("no `part` variable in the script")
    part = ns[names[0]]
    if not hasattr(part, "volume"):
        raise RuntimeError(f"`{names[0]}` is a {type(part).__name__}, not a solid")

    solids = list(part.solids())
    bb = part.bounding_box()
    size = [bb.size.X, bb.size.Y, bb.size.Z]
    OUT.update(
        ok=True, var=names[0], volume=part.volume, area=part.area,
        bbox=size,
        bbox_min=[bb.min.X, bb.min.Y, bb.min.Z],
        bbox_max=[bb.max.X, bb.max.Y, bb.max.Z],
        solids=len(solids), faces=len(part.faces()), edges=len(part.edges()),
        valid=bool(part.is_valid), manifold=bool(part.is_manifold),
        mass_g_pla=part.volume * 1.24e-3,
    )

    files = {}
    if OUT["solids"] >= 1 and OUT["valid"]:
        if OUT_DIR:
            os.makedirs(OUT_DIR, exist_ok=True)
            stl = os.path.join(OUT_DIR, "part.stl")
            step = os.path.join(OUT_DIR, "part.step")
            try:
                export_stl(part, stl, tolerance=0.05, angular_tolerance=0.2, ascii_format=False)
                files["stl"] = stl
            except Exception as exc:
                OUT.setdefault("warnings", []).append(f"stl: {exc}")
            try:
                export_step(part, step)
                files["step"] = step
            except Exception as exc:
                OUT.setdefault("warnings", []).append(f"step: {exc}")
            try:
                import build123d as _bd
                vis, hid = part.project_to_viewport((120, -120, 90), (0, 0, 0))
                svg = _bd.ExportSVG(scale=4)
                svg.add_layer("visible", line_weight=0.9)
                svg.add_layer("hidden", line_weight=0.35)
                svg.add_shape(vis, layer="visible")
                if hid:
                    svg.add_shape(hid, layer="hidden")
                path = os.path.join(OUT_DIR, "part.svg")
                svg.write(path)
                files["svg"] = path
            except Exception as exc:
                OUT.setdefault("warnings", []).append(f"svg: {exc}")
    OUT["files"] = files
except Exception:
    OUT["error"] = traceback.format_exc(limit=6)
print("@@CAD@@" + json.dumps(OUT))
'''


def check_code(code: str) -> list[str]:
    """Return a list of policy violations (empty == allowed)."""
    problems = []
    for bad in DENY:
        if bad in code:
            problems.append(f"blocked token: {bad!r}")
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("import ") or s.startswith("from "):
            if not any(s.startswith(a) for a in ALLOWED_IMPORTS):
                problems.append(f"blocked import: {s}")
    return problems


def extract_code(text: str) -> str:
    """Pull the python script out of a model reply (fenced or bare)."""
    fences = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    if fences:
        return max(fences, key=len).strip()
    if "from build123d import" in text:
        start = text.index("from build123d import")
        return text[start:].strip()
    return text.strip()


def run_code(code: str, out_dir: str | Path | None = None, timeout: int = 120,
             python: str | None = None) -> dict:
    t0 = time.time()
    problems = check_code(code)
    if problems:
        return {"ok": False, "error": "policy: " + "; ".join(problems), "blocked": problems}

    out = str(Path(out_dir).resolve()) if out_dir else ""
    payload = f"SRC = {code!r}\nOUT_DIR = {out!r}\n" + WRAPPER
    exe = python or sys.executable
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
        fh.write(payload)
        script = fh.name
    try:
        cp = subprocess.run([exe, script], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    finally:
        try:
            os.unlink(script)
        except OSError:
            pass

    lines = [l for l in (cp.stdout or "").splitlines() if l.startswith("@@CAD@@")]
    if not lines:
        tail = (cp.stderr or cp.stdout or "no output").strip().splitlines()
        return {"ok": False, "error": "crash: " + ("\n".join(tail[-12:]) or "no output")}
    res = json.loads(lines[-1][len("@@CAD@@"):])
    res["seconds"] = round(time.time() - t0, 2)
    res["code"] = code
    if cp.stderr and cp.stderr.strip():
        res["stderr"] = cp.stderr.strip()[-1500:]
    return res


def compare(res: dict, expect: dict, vol_tol: float = 0.005, bb_tol: float = 0.05) -> dict:
    """Check a run against a hand-computed expectation (volume mm^3, bbox [L,W,H])."""
    checks: list[dict] = []
    ok = bool(res.get("ok"))
    if not ok:
        return {"pass": False, "checks": [{"what": "execution", "pass": False,
                                           "detail": res.get("error", "failed")}]}

    checks.append({"what": "single solid", "pass": res["solids"] == 1,
                   "detail": f"{res['solids']} solid(s)"})
    checks.append({"what": "valid B-rep", "pass": bool(res["valid"]), "detail": str(res["valid"])})

    if "volume" in expect:
        exp = float(expect["volume"])
        got = float(res["volume"])
        err = abs(got - exp) / exp if exp else abs(got)
        checks.append({"what": "volume", "pass": err <= vol_tol,
                       "detail": f"got {got:.2f} expect {exp:.2f} ({err*100:.3f}% off)"})
    if "bbox" in expect and expect["bbox"]:
        bad = []
        for axis, (a, b) in zip("XYZ", zip(expect["bbox"], res["bbox"])):
            if abs(a - b) > bb_tol:
                bad.append(f"{axis}: {b:.3f} vs {a:.3f}")
        checks.append({"what": "bounding box", "pass": not bad,
                       "detail": ", ".join(bad) or "matches"})
    return {"pass": all(c["pass"] for c in checks), "checks": checks}


def main() -> int:
    """CLI: python -m cadbridge.runner script.py [--out DIR]"""
    import argparse
    ap = argparse.ArgumentParser(description="run a build123d script and report measurements")
    ap.add_argument("script")
    ap.add_argument("--out", default="out")
    ap.add_argument("--expect-volume", type=float)
    args = ap.parse_args()
    code = Path(args.script).read_text(encoding="utf-8")
    res = run_code(code, out_dir=args.out)
    if not res["ok"]:
        print(res["error"])
        return 1
    print(json.dumps({k: v for k, v in res.items() if k != "code"}, indent=2))
    if args.expect_volume is not None:
        cmp = compare(res, {"volume": args.expect_volume})
        print("VERDICT:", "PASS" if cmp["pass"] else "FAIL", cmp["checks"])
        return 0 if cmp["pass"] else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
