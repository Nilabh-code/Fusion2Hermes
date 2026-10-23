"""Prove the agent's repair loop with a stub OpenAI-compatible server.

Attempt 1 gets a deliberately broken script (undefined name), attempt 2 gets the
corrected one. The agent must detect the failure from the runner's real output,
feed it back, and end with a verified solid.

    python test_agent_loop.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8099

BROKEN = '''```python
from build123d import *

part = Box(L, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
```'''

GOOD = '''```python
from build123d import *

L, W, H = 40.0, 30.0, 10.0
r, hole_d = 4.0, 3.4

part = Box(L, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
part = fillet(part.edges().filter_by(Axis.Z), radius=r)
for sx in (-1, 1):
    for sy in (-1, 1):
        part -= Cylinder(hole_d / 2, H + 2,
                         align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
            Location((sx * 13.0, sy * 8.5, -1)))
```'''

state = {"calls": 0, "saw_feedback": False}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        state["calls"] += 1
        text = json.dumps(body.get("messages", []))
        retry = "previous attempt FAILED" in text
        state["saw_feedback"] = state["saw_feedback"] or retry
        content = GOOD if retry else BROKEN
        out = {"id": "stub", "object": "chat.completion",
               "choices": [{"index": 0, "finish_reason": "stop",
                            "message": {"role": "assistant", "content": content}}]}
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out_dir = HERE / "out_agent_test"
    cmd = [sys.executable, "-m", "cadbridge.agent",
           "--prompt", "40 x 30 x 10 plate, 4 mm rounded corners, four M3 clearance holes",
           "--base-url", f"http://127.0.0.1:{PORT}/v1", "--model", "stub",
           "--attempts", "3", "--out", str(out_dir), "--quiet"]
    cp = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=300)
    srv.shutdown()
    print(cp.stdout[-2500:])
    if cp.stderr.strip():
        print("stderr:", cp.stderr[-800:])

    ok = cp.returncode == 0 and state["calls"] == 2 and state["saw_feedback"]
    try:
        result = json.loads(cp.stdout[cp.stdout.index("{"):])
        ok = ok and result.get("attempts") == 2 and abs(result.get("volume_mm3", 0) - 11499.5) < 60
        files = result.get("files", {})
        ok = ok and Path(files.get("step", "")).exists() and Path(files.get("stl", "")).exists()
        print(f"volume={result.get('volume_mm3')} attempts={result.get('attempts')} "
              f"files={list(files)}")
    except Exception as exc:
        print("could not parse agent output:", exc)
        ok = False

    print(f"model calls: {state['calls']} (expect 2), feedback seen: {state['saw_feedback']}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
