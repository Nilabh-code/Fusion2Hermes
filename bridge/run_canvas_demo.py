"""Open a canvas session on the synthetic servo photo and wait for the submit."""
import json
import os
import sys
from pathlib import Path

os.environ["CADBRIDGE_NO_BROWSER"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cadbridge import canvas

srv = canvas.get_server(port=8477, open_browser=False)
sess = srv.open_session(
    "C:/Users/nilab/AppData/Local/hermes/cache/scratch/servo.png",
    prompt="servo mount bracket, 3 mm walls, shaft slot, M2 flange screws",
)
print("SESSION", sess.id, flush=True)
print("URL", srv.url(sess.id), flush=True)
print("IMAGE_SIZE", sess.image_size, flush=True)

got = srv.wait(sess.id, timeout=900)
print("TIMED_OUT", got.get("timed_out"), flush=True)
ann = got.get("annotation") or {}
Path("C:/Users/nilab/Fusion2Hermes/bridge/demo_annotation.json").write_text(
    json.dumps(ann, indent=2), encoding="utf-8")
print("SCALE", ann.get("scale_mm_per_px"), flush=True)
print("SHAPES", len(ann.get("shapes", [])), flush=True)
for s in ann.get("shapes", []):
    print("  ", json.dumps(s), flush=True)
print("NOTES", ann.get("notes"), flush=True)
print("PROMPT", ann.get("prompt"), flush=True)
print("PNG", ann.get("composite_png"), flush=True)
print("DONE", flush=True)
