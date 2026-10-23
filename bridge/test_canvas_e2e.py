"""End-to-end test of the canvas: real browser, real mouse, real submit.

    python test_canvas_e2e.py [--headed]

Draws a servo markup on the synthetic photo, calibrates the ruler to 10 mm, submits,
and checks the millimetres that come back against the geometry the image was drawn
with (12 px/mm). Exits non-zero on any mismatch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE))

from cadbridge import canvas  # noqa: E402

IMG = Path("C:/Users/nilab/AppData/Local/hermes/cache/scratch/servo.png")
PX_PER_MM = 12.0
PORT = 8488

HEADED = "--headed" in sys.argv


def main() -> int:
    if not IMG.exists():
        print(f"test image missing: {IMG}\nrun: python make_test_image.py")
        return 2

    srv = canvas.CanvasServer(port=PORT, open_browser=False)
    srv.start()
    sess = srv.open_session(str(IMG), prompt="servo mount bracket, 3 mm walls")
    url = srv.url(sess.id)
    print(f"canvas up at {url}")

    from playwright.sync_api import sync_playwright

    failures: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not HEADED)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("console", lambda m: print(f"  [console.{m.type}] {m.text}")
                if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: failures.append(f"JS error: {e}"))
        page.goto(url, wait_until="load")
        page.wait_for_function("() => window.CB && CB.state.imgW > 0", timeout=15000)
        state = page.evaluate("() => ({imgW: CB.state.imgW, imgH: CB.state.imgH, "
                              "k: CB.state.view.k, ox: CB.state.view.ox, oy: CB.state.view.oy})")
        print(f"page loaded: image {state['imgW']}x{state['imgH']}  view k={state['k']:.3f}")
        if (state["imgW"], state["imgH"]) != (640, 480):
            failures.append(f"image not loaded: {state}")

        box = page.evaluate("""() => { const r = document.getElementById('cv').getBoundingClientRect();
            return {left: r.left, top: r.top, w: r.width, h: r.height}; }""")

        def client(pt):
            return (box["left"] + state["ox"] + pt[0] * state["k"],
                    box["top"] + state["oy"] + pt[1] * state["k"])

        def drag(a, b, steps=6):
            x0, y0 = client(a)
            x1, y1 = client(b)
            page.mouse.move(x0, y0)
            page.mouse.down()
            for i in range(1, steps + 1):
                page.mouse.move(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
            page.mouse.up()
            page.wait_for_timeout(60)

        def tool(name):
            page.click(f'#tools .tool[data-tool="{name}"]')
            page.wait_for_timeout(40)

        def label(text):
            page.fill("#labelInput", text)

        # 1. calibrate on the 10 mm ruler bar
        tool("cal")
        drag((30, 433), (150, 433))
        page.fill("#calInput", "10")
        page.click("#calApply")
        page.wait_for_timeout(120)
        scale = page.evaluate("() => CB.scale()")
        print(f"calibration: {scale:.6f} mm/px (expect {1/PX_PER_MM:.6f})")
        if abs(scale - 1 / PX_PER_MM) > 1e-3:
            failures.append(f"scale wrong: {scale}")

        # 2. the markup itself
        label("servo body")
        tool("rect")
        drag((183, 167), (457, 313))

        label("flange length")
        tool("dim")
        drag((127, 313), (513, 313))

        label("M2 mounting hole")
        tool("circle")
        drag((154.4, 337), (167.0, 337))

        label("hole spacing")
        tool("dim")
        drag((154.4, 337), (485.6, 337))

        label("body height")
        tool("line")
        drag((183, 167), (183, 313))

        page.fill("#notes", "3 mm walls, print flat, 7 mm shaft slot, M2 screws")
        page.fill("#prompt", "servo mount bracket for an SG90 micro servo")

        n = page.evaluate("() => CB.shapes.length")
        print(f"shapes drawn: {n}")
        if n != 6:
            failures.append(f"expected 6 shapes (cal + 5), got {n}")

        page.click("#sendBtn")
        page.wait_for_selector("#sentOverlay:not(.hidden)", timeout=15000)
        print("submit accepted by the server")
        browser.close()

    got = srv.wait(sess.id, timeout=5)
    ann = got.get("annotation") or {}
    shapes = ann.get("shapes", [])
    print(f"\nserver received {len(shapes)} shapes, scale={ann.get('scale_mm_per_px')}")

    expected = {
        "servo body": {"w_mm": 22.83, "h_mm": 12.17},
        "flange length": {"length_mm": 32.17},
        "M2 mounting hole": {"d_mm": 2.10},
        "hole spacing": {"length_mm": 27.60},
        "body height": {"length_mm": 12.17},
    }
    by_label = {s.get("label"): s for s in shapes}
    for lab, want in expected.items():
        s = by_label.get(lab)
        if not s:
            failures.append(f"shape missing: {lab}")
            continue
        for key, val in want.items():
            if key not in s:
                failures.append(f"{lab}: no {key}")
                continue
            if abs(s[key] - val) > 0.15:
                failures.append(f"{lab}: {key}={s[key]} expected {val}")
            print(f"  {lab:<18} {key:<10} {s[key]:>7.2f}  (expect {val})")

    if ann.get("notes", "").find("print flat") < 0:
        failures.append("notes not carried through")
    if "SG90" not in (ann.get("prompt") or ""):
        failures.append("prompt not carried through")
    png = ann.get("composite_png")
    if not png or not Path(png).exists():
        failures.append("composite png missing")
    else:
        print(f"\ncomposite png: {png} ({Path(png).stat().st_size} bytes)")
        if Path(png).stat().st_size < 4000:
            failures.append("composite png suspiciously small")

    srv.stop()
    print()
    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS — canvas round trip is correct")
    return 0


if __name__ == "__main__":
    sys.exit(main())
