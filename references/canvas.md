# The canvas

A local page for turning a photo into millimetres. It exists because the hardest
part of photo → CAD is not modelling, it is **the user's intent**: which edge is
the datum, which circle is an M3 hole and which is a shaft, whether that line
means 40 mm or "about this big".

The canvas answers that as data. The user traces, marks, and calibrates one line;
everything comes back with a millimetre value attached.

## Opening a session

```python
canvas_open(image="C:/photos/sg90.jpg", prompt="servo mount, 3 mm walls")
# -> {"session_id": "...", "url": "http://127.0.0.1:8477/s/<sid>", ...}
canvas_wait(session_id, timeout=600)
# -> the annotation dict below, once the user presses "Send to agent"
```

CLI equivalent: `cadbridge canvas --image sg90.jpg --prompt "servo mount" --out ann.json`.
The page opens itself unless `CADBRIDGE_NO_BROWSER=1`.

## What the user has

| tool | key | what it means |
|------|-----|---------------|
| Line | `L` | an edge or a centreline |
| Dimension | `D` | a measurement the user is asserting; can carry a typed value |
| Rectangle | `R` | a body outline or a pocket |
| Circle | `C` | a hole, a boss, a shaft |
| Ellipse | `E` | an oval cut-out |
| Polyline | `P` | free outline, closed on Enter |
| Text | `T` | a note ("M3 clearance ×4", "R3 fillet") |
| Calibrate | `K` | one line the user declares to be a known length |

Plus: import an image, paste from clipboard (`Ctrl+V`), wheel zoom, middle-drag
pan, `Ctrl+Z` / `Ctrl+Shift+Z`, **Send to agent**.

Geometry is stored in **image pixel space**, never screen space, so zooming and
panning cannot corrupt a measurement. Calibration is one scale factor for the
whole image — a photo taken at an angle is an approximation, and a typed
`value_mm` is how the user corrects it.

## The annotation payload

```json
{
  "image": "C:/photos/sg90.jpg",
  "image_size": [640, 480],
  "prompt": "servo mount, 3 mm walls",
  "calibration": {"line_px": 236.4, "real_mm": 22.8, "label": "servo body width"},
  "scale_mm_per_px": 0.09645,
  "shapes": [
    {"tool": "rect",   "a": [120, 88], "b": [412, 244],
     "length_px": 301.9, "w_mm": 28.16, "h_mm": 15.05},
    {"tool": "circle", "a": [176, 132], "b": [190, 132],
     "length_px": 14.0, "r_px": 14.0, "r_mm": 1.35, "d_mm": 2.70,
     "label": "flange hole"},
    {"tool": "dim",    "a": [120, 300], "b": [412, 300],
     "value_mm": 27.6, "length_px": 292.0, "length_mm": 27.6,
     "label": "hole centres"},
    {"tool": "text",   "a": [300, 400], "label": "M2 clearance x4, 2.4 dia"},
    {"tool": "cal",    "a": [120, 60], "b": [356, 60],
     "label": "calibrate", "length_px": 236.0, "length_mm": 22.76}
  ],
  "composite_png": "C:/Users/<you>/AppData/Local/cadbridge/sessions/<sid>/annotation.png"
}
```

Field rules, straight from `annotate_mm()` in `canvas.py`:

- `a`/`b` are `[x, y]` in **image pixels** (y down, origin top-left).
- `scale_mm_per_px = calibration.real_mm / calibration.line_px`. If the user never
  calibrated, it is `null` and no `*_mm` fields are produced — ask for a
  calibration line rather than guessing a scale.
- A typed `value_mm` **wins**: `length_mm` is set from it and the geometric
  measurement is not overwritten.
- `rect`/`ellipse` → `w_mm`, `h_mm` (absolute extents, not the diagonal).
- `circle` → `r_mm` = radius, `d_mm` = diameter; `a` is the centre, `b` a point on
  the rim, so `r_px = |b − a|`.
- `length_mm` on `dim`/`line` is the distance between `a` and `b` unless the user
  typed a value.
- `composite_png` is the photo with all the ink baked in — **show this to a vision
  model**, not the original. The ink is the intent.

## How to use it in the loop

1. `canvas_wait` → annotation.
2. Read the mm values as constraints, not suggestions. `w_mm 28.16` from a photo is
   ±0.5 mm of the truth; if the user typed `value_mm`, that is exact.
3. Convert to the part's real structure: pick datums (usually the flange/bottom
   face), then derive the rest. `examples/servo_mount.py` is the worked case — every
   number in it traces to a canvas measurement or a datasheet.
4. Holes: take the *nominal* size from the hardware table, not the photo. A 2.70 mm
   drawn hole is an M2 clearance hole (2.4 mm nominal) plus ink width.
5. Model the mating part's envelope with clearance (servo body + 0.3 mm), so the
   servo actually drops in.
6. `cad_run_code(code, expect_volume=<your hand calculation>)` and compare.

## Gotchas

- **A photo is not orthographic.** Scale is only valid on the plane the object sits
  in; a tilted face measures short. Say so instead of silently compensating.
- **The ink has width.** A circle drawn on a 3 mm hole comes out ~1 px larger in
  radius; that is why hole diameters come from tables.
- **No calibration → no millimetres.** Don't invent a scale from the image DPI.
- **One session = one part.** New part, new `canvas_open`.
- Sessions live in `%LOCALAPPDATA%/cadbridge/sessions/<sid>/` (override with
  `CADBRIDGE_WORKSPACE`); `annotation.json` and `annotation.png` persist there.

## Test it without a human

`bridge/test_canvas_e2e.py` drives the real page with Playwright — real mouse
events, a real calibration, a real submit — and asserts the returned millimetres
against the drawing. Run it after touching `web/app.js` or `canvas.py`:

```bash
cd bridge && .venv/Scripts/python.exe test_canvas_e2e.py
```

The built-in browser tool refuses `127.0.0.1`; Playwright does not.
