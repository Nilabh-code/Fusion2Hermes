"""A local sketch canvas: mark up a photo, hand the agent millimetres.

Serves one page on 127.0.0.1. The user drops in a photo (or a drawing), draws
outlines / hole centres / dimension lines on top of it, optionally calibrates one
line to a real millimetre length, and submits. The server then has:

  * the annotations in image pixels, plus every derived millimetre value
  * a composite PNG with the ink baked in, which the vision model can look at

No dependencies beyond the standard library; the browser does the drawing.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import struct
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

WEB = Path(__file__).resolve().parent / "web"
WORKSPACE = Path(os.environ.get("CADBRIDGE_WORKSPACE",
                                Path.home() / "AppData/Local/cadbridge/sessions"))


# ---------------------------------------------------------------- image probe
def image_size(path: Path) -> tuple[int, int] | None:
    """Read width/height straight out of the PNG or JPEG header (no Pillow)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
            if head[:2] == b"\xff\xd8":
                fh.seek(2)
                while True:
                    marker = fh.read(2)
                    if len(marker) < 2:
                        return None
                    if marker[0] != 0xFF:
                        return None
                    kind = marker[1]
                    if kind in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        _len = struct.unpack(">H", fh.read(2))[0]
                        _prec, h, w = struct.unpack(">BHH", fh.read(5))
                        return int(w), int(h)
                    seg = fh.read(2)
                    if len(seg) < 2:
                        return None
                    fh.seek(struct.unpack(">H", seg)[0] - 2, 1)
    except Exception:
        return None
    return None


# ------------------------------------------------------------------- session
@dataclass
class Session:
    id: str
    prompt: str = ""
    title: str = ""
    image_path: str | None = None
    image_size: list[int] | None = None
    created: float = field(default_factory=time.time)
    annotation: dict[str, Any] | None = None
    composite_png: str | None = None
    submitted: bool = False
    event: threading.Event = field(default_factory=threading.Event)

    @property
    def dir(self) -> Path:
        d = WORKSPACE / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "title": self.title,
            "has_image": bool(self.image_path),
            "image_size": self.image_size,
            "submitted": self.submitted,
            "created": self.created,
            "annotation": self.annotation,
            "composite_png": self.composite_png,
        }


# ------------------------------------------------------------------ geometry
def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def annotate_mm(annotation: dict[str, Any]) -> dict[str, Any]:
    """Add millimetre values to every shape, using the calibration if present."""
    cal = annotation.get("calibration") or {}
    scale = None
    line_px = float(cal.get("line_px") or 0)
    real_mm = float(cal.get("real_mm") or 0)
    if line_px > 0 and real_mm > 0:
        scale = real_mm / line_px
    annotation["scale_mm_per_px"] = round(scale, 6) if scale else None

    for s in annotation.get("shapes", []):
        tool = s.get("tool")
        a, b = s.get("a"), s.get("b")
        if s.get("value_mm"):        # user typed the real size: it wins over geometry
            s["length_mm"] = float(s["value_mm"])
        if not (a and b):
            continue
        d = _dist(a, b)
        s["length_px"] = round(d, 2)
        if scale:
            if tool in ("line", "dim", "arrow") and not s.get("value_mm"):
                s["length_mm"] = round(d * scale, 2)
            elif tool in ("rect", "ellipse"):
                s["w_mm"] = round(abs(b[0] - a[0]) * scale, 2)
                s["h_mm"] = round(abs(b[1] - a[1]) * scale, 2)
            elif tool == "circle":
                s["r_mm"] = round(d * scale, 2)
                s["d_mm"] = round(2 * d * scale, 2)
        if tool == "circle":
            s["r_px"] = round(d, 2)
    return annotation


# -------------------------------------------------------------------- server
class CanvasServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8477, open_browser: bool = True):
        self.host = host
        self.port = port
        self.open_browser = open_browser
        self.sessions: dict[str, Session] = {}
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ life
    def start(self) -> str:
        if self._httpd is not None:
            return f"http://{self.host}:{self.port}/"
        handler = _make_handler(self)
        port = self.port
        for attempt in range(12):
            try:
                self._httpd = ThreadingHTTPServer((self.host, port), handler)
                self.port = port
                break
            except OSError:
                port += 1
        if self._httpd is None:
            raise RuntimeError("could not bind a port for the canvas server")
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="cadbridge-canvas", daemon=True)
        self._thread.start()
        return self.url()

    def url(self, session: str | None = None) -> str:
        base = f"http://{self.host}:{self.port}/"
        return f"{base}?s={session}" if session else base

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    # --------------------------------------------------------------- session
    def open_session(self, image_path: str | None = None, prompt: str = "",
                     title: str = "") -> Session:
        self.start()
        sid = secrets.token_hex(8)
        sess = Session(id=sid, prompt=prompt, title=title)
        if image_path:
            src = Path(image_path).expanduser()
            if not src.exists():
                raise FileNotFoundError(f"image not found: {src}")
            dst = sess.dir / f"input{src.suffix.lower() or '.png'}"
            dst.write_bytes(src.read_bytes())
            sess.image_path = str(dst)
            size = image_size(dst)
            sess.image_size = list(size) if size else None
        with self._lock:
            self.sessions[sid] = sess
        if self.open_browser and os.environ.get("CADBRIDGE_NO_BROWSER") != "1":
            try:
                webbrowser.open(self.url(sid), new=2)
            except Exception:
                pass
        return sess

    def get(self, sid: str) -> Session:
        try:
            return self.sessions[sid]
        except KeyError:
            raise KeyError(f"unknown canvas session {sid!r} (open one with canvas_open)")

    def wait(self, sid: str, timeout: float = 600.0) -> dict[str, Any]:
        sess = self.get(sid)
        got = sess.event.wait(timeout)
        out = sess.public()
        out["timed_out"] = not got
        if not got:
            out["hint"] = ("nothing submitted yet - the page is still open; keep drawing "
                           "and press Send, or call canvas_status to poll")
        return out

    def submit(self, sid: str, payload: dict[str, Any]) -> dict[str, Any]:
        sess = self.get(sid)
        annotation = dict(payload.get("annotation") or {})
        annotation["notes"] = payload.get("notes", annotation.get("notes", ""))
        annotation["prompt"] = payload.get("prompt", sess.prompt or "")
        if sess.image_size and not annotation.get("image_size"):
            annotation["image_size"] = sess.image_size
        annotation = annotate_mm(annotation)

        png_b64 = payload.get("png_base64")
        if png_b64:
            if "," in png_b64:
                png_b64 = png_b64.split(",", 1)[1]
            path = sess.dir / "annotation.png"
            path.write_bytes(base64.b64decode(png_b64))
            sess.composite_png = str(path)
            annotation["composite_png"] = str(path)

        sess.annotation = annotation
        sess.prompt = annotation["prompt"]
        sess.submitted = True
        (sess.dir / "annotation.json").write_text(json.dumps(annotation, indent=2),
                                                  encoding="utf-8")
        sess.event.set()
        return sess.public()


# ------------------------------------------------------------------- handler
def _make_handler(server: CanvasServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):        # quiet
            if os.environ.get("CADBRIDGE_DEBUG"):
                print(f"[canvas] {fmt % args}")

        # ---------------------------------------------------------- helpers
        def _send(self, code: int, body: bytes, ctype: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict):
            self._send(code, json.dumps(obj).encode("utf-8"))

        def _file(self, path: Path, ctype: str):
            if not path.exists():
                return self._json(404, {"error": f"not found: {path.name}"})
            self._send(200, path.read_bytes(), ctype)

        # ------------------------------------------------------------- GET
        def do_GET(self):
            url = urlparse(self.path)
            p = unquote(url.path)
            if p in ("/", "/index.html"):
                return self._file(WEB / "index.html", "text/html; charset=utf-8")
            if p == "/app.js":
                return self._file(WEB / "app.js", "application/javascript; charset=utf-8")
            if p == "/style.css":
                return self._file(WEB / "style.css", "text/css; charset=utf-8")
            if p == "/health":
                return self._json(200, {"ok": True, "sessions": len(server.sessions)})
            if p.startswith("/image/"):
                sid = p.split("/")[-1]
                try:
                    sess = server.get(sid)
                except KeyError:
                    return self._json(404, {"error": "no session"})
                if not sess.image_path:
                    return self._json(404, {"error": "session has no image"})
                ext = Path(sess.image_path).suffix.lower()
                ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                         ".webp": "image/webp", ".gif": "image/gif",
                         ".bmp": "image/bmp"}.get(ext, "application/octet-stream")
                return self._file(Path(sess.image_path), ctype)
            if p.startswith("/api/session/"):
                sid = p.split("/")[-1]
                try:
                    return self._json(200, server.get(sid).public())
                except KeyError:
                    return self._json(404, {"error": "no session"})
            if p.startswith("/api/annotation/"):
                sid = p.split("/")[-1]
                try:
                    sess = server.get(sid)
                except KeyError:
                    return self._json(404, {"error": "no session"})
                return self._json(200, sess.annotation or {})
            return self._json(404, {"error": "no route", "path": p})

        # ------------------------------------------------------------ POST
        def do_POST(self):
            url = urlparse(self.path)
            p = unquote(url.path)
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception as exc:
                return self._json(400, {"error": f"bad json: {exc}"})
            if p.startswith("/api/submit/"):
                sid = p.split("/")[-1]
                try:
                    out = server.submit(sid, payload)
                except KeyError as exc:
                    return self._json(404, {"error": str(exc)})
                return self._json(200, {"ok": True, "session": out})
            if p.startswith("/api/draft/"):
                sid = p.split("/")[-1]
                try:
                    sess = server.get(sid)
                except KeyError:
                    return self._json(404, {"error": "no session"})
                sess.annotation = annotate_mm(dict(payload.get("annotation") or {}))
                return self._json(200, {"ok": True, "shapes": len(sess.annotation.get("shapes", []))})
            return self._json(404, {"error": "no route", "path": p})

    return Handler


_SERVER: CanvasServer | None = None


def get_server(port: int = 8477, open_browser: bool = True) -> CanvasServer:
    global _SERVER
    if _SERVER is None:
        _SERVER = CanvasServer(port=int(os.environ.get("CADBRIDGE_PORT", port)),
                               open_browser=open_browser)
        _SERVER.start()
    return _SERVER


def main() -> int:
    """Standalone: python -m cadbridge.canvas --image photo.jpg --prompt "servo mount" """
    import argparse
    ap = argparse.ArgumentParser(description="annotate an image, get millimetres back")
    ap.add_argument("--image", default=None)
    ap.add_argument("--prompt", default="")
    ap.add_argument("--port", type=int, default=8477)
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--out", default=None, help="write the annotation json here")
    args = ap.parse_args()

    srv = get_server(args.port)
    sess = srv.open_session(args.image, args.prompt)
    print(f"canvas open: {srv.url(sess.id)}")
    print("waiting for submit ...")
    out = srv.wait(sess.id, args.timeout)
    print(json.dumps(out, indent=2))
    if args.out and out.get("annotation"):
        Path(args.out).write_text(json.dumps(out["annotation"], indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
