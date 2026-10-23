"""Full pipeline test: build123d script -> verify against hand maths -> Fusion 360.

    python test_pipeline.py            # skips the Fusion step if Fusion is closed

1. runs examples/servo_mount.py through the runner
2. checks the measured volume/bbox against an independently computed expectation
3. imports the STEP into the live Fusion document and compares the bbox Fusion reports
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cadbridge import fusion_link, runner  # noqa: E402

SCRIPT = HERE.parent / "examples" / "servo_mount.py"
OUT = HERE / "out_pipeline"


def expected() -> dict:
    """Recompute the part's volume from first principles (independent of the script)."""
    body_l, body_w = 22.8, 12.2
    flange_l, hole_c_y = 32.2, 8.1
    wall, plate_t, clr, depth = 6.7, 3.0, 0.3, 2.0
    screw_d, shaft_d = 2.4, 7.0

    L = flange_l + 2 * wall + 3.0
    W = body_w + 2 * hole_c_y
    plate = L * W * plate_t

    pocket = (body_l + 2 * clr) * (body_w + 2 * clr) * depth
    # the shaft and the screw holes only remove what the pocket did not already take:
    shaft = math.pi * (shaft_d / 2) ** 2 * (plate_t - depth)
    screws = 4 * math.pi * (screw_d / 2) ** 2 * plate_t

    # corner fillets r2 on 4 vertical edges of a 42.8 x 26.4 footprint
    r = 2.0
    fillet_gain = -(4 - math.pi) * r * r * plate_t

    # the pocket keeps its own corners square, so the fillet only acts on the outer wall
    vol = plate + fillet_gain - pocket - shaft - screws
    return {"volume": vol, "bbox": [L, W, plate_t]}


def main() -> int:
    exp = expected()
    print(f"expected: volume={exp['volume']:.2f} mm3 bbox={[round(v,2) for v in exp['bbox']]}")
    code = SCRIPT.read_text(encoding="utf-8")
    res = runner.run_code(code, out_dir=OUT)
    if not res.get("ok"):
        print("RUN FAILED:\n" + (res.get("error") or "")[-1500:])
        return 1
    print(f"measured: volume={res['volume']:.2f} mm3 bbox={[round(v,2) for v in res['bbox']]} "
          f"solids={res['solids']} faces={res['faces']}")
    verdict = runner.compare(res, exp)
    for c in verdict["checks"]:
        print(f"  [{'ok' if c['pass'] else 'XX'}] {c['what']}: {c['detail']}")

    ok = verdict["pass"]
    step = res["files"].get("step")
    print(f"files: {res['files']}")

    if step and fusion_link.is_alive():
        print("\npushing STEP into Fusion 360 ...")
        try:
            out = fusion_link.push_step(step)
            print(json.dumps(out, indent=2))
            fb = out.get("bbox_mm") or []
            if len(fb) != 3:
                print(f"  XX Fusion did not report a bounding box: {out}")
                ok = False
            else:
                bad = [f"{axis}: {b:.2f} vs {a:.2f}" for axis, a, b
                       in zip("XYZ", exp["bbox"], fb) if abs(a - b) > 0.15]
                if bad:
                    print("  XX Fusion bbox mismatch:", bad)
                    ok = False
                else:
                    print(f"  ok Fusion has the part at {fb} mm in "
                          f"component {out.get('component')}")
        except Exception as exc:
            print(f"  XX Fusion push failed: {exc}")
            ok = False
    else:
        print("\nFusion not running - skipped the import step")

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
