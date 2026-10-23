"""Push a STEP file into the running Fusion 360 document.

Talks to the community add-in's local socket (default 127.0.0.1:9876, installed by
this repo's setup.py) using its newline-delimited JSON protocol:

    -> {"type": "execute_code", "params": {"code": "..."}}
    <- {"status": "success", "result": ...}

Fusion's Python API is in centimetres; everything this module returns is in mm.
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

DEFAULT_HOST = os.environ.get("FUSION_MCP_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("FUSION_MCP_PORT", "9876"))

IMPORT_SNIPPET = '''
import os
import time
_path = r"{path}"
if not os.path.exists(_path):
    _r = {{"ok": False, "error": "file not found: " + _path}}
else:
    _root = app.activeProduct.rootComponent
    # NOTE: importToTarget() rejects the ROOT component on Fusion 2705
    # ("2 : InternalValidationError : results"). A fresh child component works.
    _occ = _root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    _occ.component.name = "CADBridge_" + time.strftime("%H%M%S")
    _opts = app.importManager.createSTEPImportOptions(_path)
    _opts.isViewFit = True
    app.importManager.importToTarget(_opts, _occ.component)
    # bRepBodies.count on the fresh component reads 0 until Fusion recomputes, but the
    # occurrence proxy bounding box is already correct - measure that instead.
    _bb = _occ.boundingBox
    _size = [(_bb.maxPoint.x - _bb.minPoint.x) * 10,
             (_bb.maxPoint.y - _bb.minPoint.y) * 10,
             (_bb.maxPoint.z - _bb.minPoint.z) * 10]
    _r = {{
        "ok": max(_size) > 0.01,
        "component": _occ.component.name,
        "bbox_mm": [round(_v, 3) for _v in _size],
        "min_mm": [round(_v * 10, 3) for _v in (_bb.minPoint.x, _bb.minPoint.y, _bb.minPoint.z)],
        "document": app.activeDocument.name if app.activeDocument else None,
    }}
_r
'''

CLEAR_SNIPPET = '''
_root = app.activeProduct.rootComponent
_dead = 0
for _i in range(_root.occurrences.count - 1, -1, -1):
    _o = _root.occurrences.item(_i)
    if _o.component.name.startswith("CADBridge_"):
        _o.deleteMe()
        _dead += 1
for _i in range(_root.bRepBodies.count - 1, -1, -1):
    _root.bRepBodies.item(_i).deleteMe()
    _dead += 1
{{"deleted": _dead}}
'''


class FusionLinkError(RuntimeError):
    pass


def send(command: str, params: dict | None = None, host: str = DEFAULT_HOST,
         port: int = DEFAULT_PORT, timeout: float = 60.0) -> dict:
    """Send one command to the add-in and return its parsed reply."""
    payload = json.dumps({"type": command, "params": params or {}}) + "\n"
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(payload.encode("utf-8"))
        sock.settimeout(timeout)
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    line = buf.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise FusionLinkError("empty reply from Fusion add-in")
    try:
        return json.loads(line[0])
    except json.JSONDecodeError:
        return {"status": "raw", "result": line[0]}


def is_alive(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


def execute(code: str, timeout: float = 90.0, **kw) -> dict:
    """Run python inside Fusion. Unwraps the add-in's {executed, result, deltas} envelope."""
    reply = send("execute_code", {"code": code}, timeout=timeout, **kw)
    if reply.get("status") != "success":
        raise FusionLinkError(f"Fusion error: {reply.get('error') or reply}")
    res = reply.get("result") or {}
    if isinstance(res, dict) and "executed" in res:
        inner = dict(res.get("result") or {})
        inner.setdefault("_deltas", res.get("deltas"))
        return inner
    return res


def push_step(step_path: str | Path, timeout: float = 120.0, clear: bool = False,
              **kw) -> dict:
    """Import a STEP into the active Fusion document. Returns mm bounding box.

    Uses a fresh child component: importToTarget() rejects the root component on
    Fusion 2705 with `2 : InternalValidationError : results`.
    """
    p = Path(step_path).expanduser().resolve()
    if not p.exists():
        raise FusionLinkError(f"STEP file not found: {p}")
    if p.suffix.lower() not in (".step", ".stp"):
        raise FusionLinkError(f"not a STEP file: {p.name}")
    if not is_alive(**{k: v for k, v in kw.items() if k in ("host", "port")}):
        raise FusionLinkError(
            "nothing is listening on the Fusion add-in socket - open Fusion 360 "
            "(the Fusion360MCP add-in starts itself) or run scripts/setup.py --check"
        )
    if clear:
        execute(CLEAR_SNIPPET, timeout=timeout, **kw)
    code = IMPORT_SNIPPET.format(path=str(p).replace("\\", "/"))
    result = execute(code, timeout=timeout, **kw)
    if isinstance(result, dict) and not result.get("ok", True):
        raise FusionLinkError(result.get("error", "import failed"))
    out = dict(result or {})
    out["step"] = str(p)
    out["size_kb"] = round(p.stat().st_size / 1024, 1)
    return out


def document_info(**kw) -> dict:
    """Active document name + body count, or raise if Fusion is not reachable."""
    out = execute(
        "{'name': app.activeDocument.name if app.activeDocument else None, "
        "'bodies': app.activeProduct.rootComponent.bRepBodies.count if app.activeProduct else 0, "
        "'components': app.activeProduct.rootComponent.occurrences.count if app.activeProduct else 0}",
        **kw,
    )
    out.pop("_deltas", None)
    return out


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="push a STEP into Fusion 360")
    ap.add_argument("step", nargs="?", help="path to a .step file")
    ap.add_argument("--status", action="store_true", help="just check the socket")
    args = ap.parse_args()
    try:
        if args.status or not args.step:
            print(json.dumps(document_info(), indent=2))
        else:
            print(json.dumps(push_step(args.step), indent=2))
    except FusionLinkError as exc:
        print(f"Fusion link error: {exc}")
        sys.exit(1)
