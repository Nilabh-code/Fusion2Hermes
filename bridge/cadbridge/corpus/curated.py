"""Curated knowledge base for the CAD bridge.

Each entry becomes one retrievable chunk. Written for a *model reading it before
writing code*: imperative rules, exact API names for build123d 0.13, real
dimension tables, and complete runnable patterns. Anything in here has been
executed on this machine (see `source: verified`) or is a standard published
dimension (see `source: datasheet`).

Do not add speculative API. If a symbol is not in build123d 0.13 the model will
emit code that fails to import, which the runner will reject.
"""

# fmt: off
CHUNKS: list[dict] = [

# ───────────────────────────────────────────── build123d: core model ────────
dict(id="bd-001", domain="build123d", kind="doc", source="verified",
     title="Two ways to write build123d: builder and algebra",
     tags=["buildpart", "buildsketch", "algebra", "basics", "style"],
     text="""build123d has two equivalent styles. Both are valid; pick one per script and stay in it.

BUILDER (context managers, sketch-then-extrude):
```python
from build123d import *

with BuildPart() as p:
    with BuildSketch() as sk:          # builds on Plane.XY by default
        RectangleRounded(40, 30, 4)
        with GridLocations(26, 17, 2, 2):
            Circle(1.7, mode=Mode.SUBTRACT)
    extrude(amount=10)

part = p.part
```

ALGEBRA (objects and operators, no context):
```python
from build123d import *

part = Box(40, 30, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
part = fillet(part.edges().filter_by(Axis.Z), radius=4)
part -= Cylinder(1.7, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((13, 8.5, 0)))
```

Rules:
- Inside a builder, `extrude()`, `fillet()`, `hole()` act on the builder's pending state automatically.
- Outside, everything returns a new object: `part = fillet(part.edges(), 2)`, never `fillet(...)` alone.
- `part` must be the final variable name. It must be ONE solid.
- The file must start with `from build123d import *` (not `import build123d as bd`) so the emitted code is short and matches this corpus."""),

dict(id="bd-002", domain="build123d", kind="doc", source="verified",
     title="Align and Location: where the origin goes",
     tags=["align", "location", "origin", "positioning", "move", "moved"],
     text="""Default alignment is CENTER on every axis, so primitives straddle the origin.

```python
Box(40, 30, 10)                                        # centered on origin
Box(40, 30, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))   # sits on Z=0
Box(40, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN))         # corner at origin
Cylinder(5, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))   # base at Z=0
```
House rule for parts that sit on a build plate: Z aligned MIN, X/Y aligned CENTER.
That makes the top face the last face in `part.faces().sort_by(Axis.Z)`.

To place something at a point use `.moved(Location((x, y, z)))`; it returns a new
object (it does not mutate). Rotate with `.rotate(Axis.X, 90)`.

```python
pin = Cylinder(2, 30)                       # centered, axis along Z
pin = pin.rotate(Axis.X, 90)                # now axis along Y, still centered
pin = pin.moved(Location((0, 0, 15)))
```
Rotate BEFORE moved, so the rotation happens about the origin and the translation
is not itself rotated.

Locations inside a builder multiply: `with Locations((0, 0, 5)): Cylinder(3, 10)`."""),

dict(id="bd-003", domain="build123d", kind="doc", source="verified",
     title="Mode: ADD, SUBTRACT, INTERSECT, PRIVATE",
     tags=["mode", "boolean", "subtract", "union", "cut"],
     text="""Every sketch and part object takes `mode`:

- `Mode.ADD` (default) — fuse into what is being built.
- `Mode.SUBTRACT` — cut away. `Hole` and `CounterBoreHole` default to this.
- `Mode.INTERSECT` — keep only the overlap.
- `Mode.PRIVATE` — keep it out of the result; use it to stash construction geometry.

In algebra mode the same thing is written with operators:

```python
part = base + boss        # ADD (fuse)
part -= hole_cylinder     # SUBTRACT (cut)
part = a & b              # INTERSECT
```

Coplanar boolean faces are the #1 source of invalid solids. Make cutters longer
than the material they pass through (add 1 mm each side) instead of exactly flush."""),

dict(id="bd-004", domain="build123d", kind="doc", source="verified",
     title="Selecting edges and faces: filter_by, sort_by, group_by",
     tags=["edges", "faces", "filter_by", "sort_by", "selection", "fillet", "chamfer"],
     text="""Fillets and chamfers apply to a selected set of edges. Never guess an index.

```python
part.edges()                                  # all edges
part.edges().filter_by(Axis.Z)                # edges parallel to Z (vertical)
part.edges().filter_by(GeomType.CIRCLE)       # circular edges only
part.edges().group_by(Axis.Z)[-1]             # top-most group of edges
part.faces().sort_by(Axis.Z)[-1]              # top face
part.faces().filter_by(Axis.Z)                # faces whose normal is along Z
part.solids()                                 # list of solids - must be length 1
```

Common selections:
- vertical corner fillets: `edges().filter_by(Axis.Z)` — but on a plate with holes this also catches hole walls. Exclude with `.filter_by(GeomType.LINE)`.
- top rim fillet: `edges().group_by(Axis.Z)[-1]`
- only outer wires: `faces().sort_by(Axis.Z)[-1].outer_wire().edges()`

Always cap the radius: `r <= min(L, W) / 4` for corner fillets, and less than the
wall thickness for internal fillets, or the operation raises."""),

dict(id="bd-005", domain="build123d", kind="doc", source="verified",
     title="Shelling an enclosure (open top)",
     tags=["shell", "enclosure", "hollow", "offset", "offset_3d", "box"],
     text="""Two reliable ways to make an open-top box. Use method A unless you need
constant wall thickness on a curved body.

METHOD A — subtract a smaller box (always works, easy to reason about):
```python
from build123d import *

L, W, H, t = 80.0, 60.0, 30.0, 2.0
outer = Box(L, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
inner = Box(L - 2*t, W - 2*t, H - t, align=(Align.CENTER, Align.CENTER, Align.MIN))
inner = inner.moved(Location((0, 0, t)))
part = outer - inner
```

METHOD B — true shell with an opening (build123d >= 0.13):
```python
with BuildPart() as p:
    Box(L, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
    top = p.faces().sort_by(Axis.Z)[-1]
    offset(amount=-t, openings=top, mode=Mode.SUBTRACT)
part = p.part
```
Algebra equivalent: `part = outer.offset_3d(openings=[top_face], thickness=-t)`.

The subtraction method and the shell differ only where there are internal corners;
for FDM printing method A gives a flat floor which is what you want. Add an
internal fillet at the wall/floor junction (r ~ t/2 to t) for strength, but only if
you also fillet the inner box's base edges first — filleting after subtraction on
the inner corner usually fails."""),

dict(id="bd-006", domain="build123d", kind="doc", source="verified",
     title="Holes: through, counterbore, countersink, tapped",
     tags=["hole", "counterbore", "countersink", "screw", "tap", "fastener"],
     text="""Inside a builder `Hole` cuts along -Z from the current workplane and is
through-all by default:

```python
with BuildPart() as p:
    Box(40, 30, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations((13, 8.5, 10)):          # note: z = top face
        Hole(1.7)                            # through hole, r=1.7 (M3 clearance)
    with Locations((-13, 8.5, 10)):
        CounterBoreHole(1.7, 3.1, 3.2)       # r, c'bore r, c'bore depth
    with Locations((0, -8.5, 10)):
        CounterSinkHole(1.7, 3.2, counter_sink_angle=90)   # 90 deg for metric
```

Algebra mode: cut a cylinder that is longer than the part.
```python
part -= Cylinder(1.7, 12, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((13, 8.5, -1)))
```

A tapped M3 hole is NOT modelled as a helix. Drill the tap drill size (2.5 mm) and
call it done; threads in FDM are cut by the screw. For heat-set inserts use the
insert's OD minus 0.1 mm."""),

dict(id="bd-007", domain="build123d", kind="doc", source="verified",
     title="Patterns: GridLocations, PolarLocations, Locations",
     tags=["grid", "polar", "pattern", "bolt circle", "array"],
     text="""```python
with GridLocations(26, 17, 2, 2):        # x_spacing, y_spacing, x_count, y_count
    Circle(1.7, mode=Mode.SUBTRACT)      # -> holes at (+-13, +-8.5)

with PolarLocations(radius=20, count=6):  # bolt circle
    Circle(1.7, mode=Mode.SUBTRACT)

with Locations((0, 0, 0), (15, 0, 0), (30, 0, 0)):   # explicit points
    Cylinder(2, 5)
```
`GridLocations` spacing is the distance between adjacent instances, NOT the overall
span. For a 2x2 grid on a plate of length L with edge margin m the spacing is L - 2m.
`PolarLocations(radius, count, start_angle=0, angular_range=360)`.

In algebra mode, loop instead:
```python
for i in range(4):
    x = (-1) ** i * 13
    y = (-1) ** (i // 2) * 8.5
    part -= Cylinder(1.7, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((x, y, 0)))
```"""),

dict(id="bd-008", domain="build123d", kind="doc", source="verified",
     title="Revolve, sweep, loft: exact call shapes",
     tags=["revolve", "sweep", "loft", "profile", "helix"],
     text="""```python
# revolve a profile about Axis.Z (profile must be on a plane containing the axis)
with BuildPart() as p:
    with BuildSketch(Plane.XZ) as sk:
        with BuildLine():
            Polyline((0, 0), (10, 0), (10, 4), (3, 6), (0, 6), close=True)
        make_face()
    revolve(axis=Axis.Z)

# sweep a circle along a helix -> coarse thread / spring
helix = Helix(pitch=2.0, height=20.0, radius=5.0)
part = sweep(sections=Circle(1.0).face(), path=helix)

# loft between two profiles at different heights
with BuildPart() as p:
    with BuildSketch(Plane.XY) as s1:
        Rectangle(20, 20)
    with BuildSketch(Plane.XY.offset(30)) as s2:
        Circle(6)
    loft()
```
`revolve` needs a planar face whose plane contains the axis or it fails.
`sweep` in algebra mode: `sweep(sections=sketch.face(), path=wire)`.
`loft(ruled=False)` gives a smooth blend, `ruled=True` gives straight sides."""),

dict(id="bd-009", domain="build123d", kind="doc", source="verified",
     title="Exporting: STL for printing, STEP for Fusion/slicers",
     tags=["export", "stl", "step", "brep", "file"],
     text="""```python
export_stl(part, "out/part.stl", tolerance=0.05, angular_tolerance=0.2)
export_step(part, "out/part.step")          # mm by default, unit=Unit.MM
export_brep(part, "out/part.brep")
```
- STL is a mesh: tolerance is in mm (0.05 is fine for printing, 0.01 for smooth curves).
- STEP keeps real B-rep faces — this is the format to import into Fusion 360.
- Both take a `Path`, and the parent directory must already exist.

Self-check before exporting (this is how the bridge verifies a model):
```python
bb = part.bounding_box()
assert len(part.solids()) == 1, f"expected one solid, got {len(part.solids())}"
assert part.is_valid, "invalid B-rep"
print(part.volume, bb.size.X, bb.size.Y, bb.size.Z)
```"""),

dict(id="bd-010", domain="build123d", kind="doc", source="verified",
     title="Failure modes that make build123d raise",
     tags=["error", "fillet", "radius", "invalid", "debug", "pitfall"],
     text="""Ranked by how often a generated script hits them:

1. `fillet()` radius larger than the material. Fix: `r <= min(L,W)/4`, and for internal
   fillets `r < wall_thickness`. Error: `StdFail_NotDone` or "radius is too big".
2. Filleting every edge including hole walls — the fillet self-intersects at the
   hole. Fix: `.filter_by(Axis.Z).filter_by(GeomType.LINE)` or fillet before cutting
   the holes.
3. Boolean between exactly coplanar faces leaves a sliver or a non-manifold body.
   Fix: make cutters 0.5-1 mm longer than the material.
4. Zero-thickness wall (two features exactly meeting). Check `part.volume` — if it is
   less than expected, the walls vanished.
5. `extrude()` with no pending sketch, or extruding a Sketch that is not closed
   (open wires) — use `make_face()` first.
6. Mixing builder and algebra in a way that updates `p.part` after you already read
   it: read `p.part` only after the `with` block exits.
7. Through-hole drilled from the wrong workplane placement so it starts below the
   part and misses: give `Locations` the z of the face you mean to drill from.
8. A part that comes out as 2+ solids (e.g. a slot that fully severs it). Check
   `len(part.solids()) == 1`.
9. `RuntimeError: Nothing to subtract from` — the first object inside a fresh
   `BuildSketch` or `BuildPart` was given `mode=Mode.SUBTRACT`. Add the outer face or
   the base solid first, then subtract from it.
10. Reading `p.part` before the `with BuildPart()` block has exited gives the state at
    that moment, not the finished part.

When something is wrong the runner returns the traceback and the volume/bbox it
actually got — compare that against your hand calculation before changing code."""),

# ───────────────────────────────────────────── orientation & house rules ────
dict(id="wf-001", domain="workflow", kind="rule", source="verified",
     title="House rules for every emitted script",
     tags=["convention", "orientation", "naming", "units", "part"],
     text="""Follow these or the bridge will reject the model:

1. `from build123d import *` on line 1.
2. All dimensions in millimetres, as plain floats. No unit conversion inside the script.
3. The finished solid is assigned to a variable named exactly `part`.
5. Primitives: `part` must be exactly one solid. No assemblies, no loose construction
   geometry, no `Compound`.
6. Imports: `from build123d import *` (line 1) and, if you need trigonometry,
   `import math`. Nothing else — the runner blocks every other import.
7. Sitting on the build plate: Z-aligned MIN, X and Y aligned CENTER. Origin at the
   centre of the footprint, Z=0 at the bottom face.
8. Name real features with real parameters at the top: `L, W, H, wall, hole_d, ...`
   then use them. Do not scatter magic numbers through the body — the numbers must
   match what the user asked for so they can be checked.
9. Add a short comment only where a dimension came from the drawing.
10. No `print`, no file writes. The runner does the exporting.

If a dimension is genuinely unknown, pick the standard value from the hardware table
and say so in a comment — never invent a dimension silently."""),

dict(id="wf-002", domain="workflow", kind="rule", source="verified",
     title="From a photo/drawing to a spec before any code",
     tags=["drawing", "image", "annotation", "spec", "measure", "calibration"],
     text="""Never write geometry straight off an image. Convert the image into a
dimension table first, then code from the table.

1. Look for a scale reference in the picture — a ruler, a coin, a known fastener, a
   printed dimension, or the calibration line the user drew. If the user calibrated
   the canvas, every drawn line already carries a millimetre value; trust those over
   pixel counting.
2. If there is no scale reference, assume the object is a standard part and use its
   published envelope, then say so: "using MG996R envelope 40 x 20 x 36 mm".
3. Extract, in this order: overall envelope (L x W x H), mounting interface (hole
   positions, screw size, boss diameter), functional openings (shaft bore, cable
   slot), and clearance class (slip/press/snap).
4. State the table back to the user before modelling when any dimension was
   inferred rather than measured.
5. Round to 0.5 mm unless the drawing is dimensioned. Do not emit 12.7371 because a
   pixel measurement said so.

The annotated canvas returns JSON shaped like:
```json
{"scale_mm_per_px": 0.1524, "calibration": {"line_px": 210.0, "real_mm": 32.0},
 "shapes": [{"tool": "line", "a": [10,40], "b": [120,40], "length_mm": 16.8, "label": "body length"},
            {"tool": "rect", "a": [10,40], "b": [120,180], "w_mm": 16.8, "h_mm": 21.3, "label": "servo body"},
            {"tool": "dim", "a": [0,0], "b": [181,0], "length_mm": 27.6, "label": "hole spacing"}],
 "notes": "two M2 holes on the flange",
 "prompt": "servo mount bracket, 3 mm walls, print upright"}
```
Read `length_mm`/`w_mm`/`h_mm` when present (already scaled), else multiply pixel
deltas by `scale_mm_per_px`. `label` and `notes` carry the intent."""),

# ───────────────────────────────────────────── hardware tables ──────────────
dict(id="hw-001", domain="hardware", kind="rule", source="ISO 273 / ISO 2306",
     title="Metric screw clearance, tap drill, insert and nut sizes",
     tags=["m3", "m4", "m5", "screw", "clearance", "tap", "insert", "nut", "table"],
     text="""Use these instead of guessing. Diameters in mm.

| thread | clearance hole | tap drill | heat-set insert OD | hex nut across-flats | nut pocket depth |
|--------|----------------|-----------|--------------------|----------------------|------------------|
| M2     | 2.4            | 1.6       | 3.2                | 4.0                  | 1.8              |
| M2.5   | 2.9            | 2.05      | 3.6                | 5.0                  | 2.2              |
| M3     | 3.4            | 2.5       | 4.0                | 5.5                  | 2.6              |
| M4     | 4.5            | 3.3       | 4.6                | 7.0                  | 3.4              |
| M5     | 5.5            | 4.2       | 5.6                | 8.0                  | 4.2              |
| M6     | 6.6            | 5.0       | 6.4                | 10.0                 | 5.2              |
| M8     | 9.0            | 6.8       | 8.0                | 13.0                 | 6.8              |

- Clearance hole for a screw that passes through = the table value (medium fit).
- For a screw that must self-tap into plastic: 0.8 x nominal (M3 -> 2.4).
- Heat-set insert hole: insert OD + 0.1, depth = insert length + 0.5.
- Nut trap: across-flats + 0.2, depth = nut thickness + 0.4 (drop-in from the side).
- Socket cap head diameters: M3 5.5, M4 7.0, M5 8.5, M6 10.0 (counterbore size).
- Add 0.2 mm clearance to any printed mating hole; FDM holes come out undersized."""),

dict(id="hw-002", domain="hardware", kind="rule", source="datasheet",
     title="Common bearing and shaft dimensions",
     tags=["bearing", "608", "6001", "shaft", "bore", "press fit"],
     text="""| bearing | ID x OD x width | typical use |
|---------|------------------|-------------|
| 623     | 3 x 10 x 4       | small pulley idler |
| 624     | 4 x 13 x 5       | idler |
| 625     | 5 x 16 x 5       | idler |
| 608     | 8 x 22 x 7       | skate wheel, filament spool |
| 6001    | 12 x 28 x 8      | roller, extruder |
| 6002    | 15 x 32 x 9      | larger roller |
| 6810    | 50 x 65 x 7      | thin-section |

Bearing pocket rules:
- Press fit (bearing stays put, you push it in with a vise): pocket = OD - 0.05 for
  a printed PLA/PETG part, - 0.02 for resin/ABS.
- Slip fit (bearing turns in the housing): pocket = OD + 0.1.
- Add a shoulder: pocket depth = width + 0.2, with a lip of 1-2 mm on one side.
- Chamfer the entry 0.5 x 45 deg so the bearing starts square.
- Shaft hole through a bearing: shaft diameter + 0.3 if the bearing carries load.""",),

dict(id="hw-003", domain="hardware", kind="rule", source="datasheet",
     title="Hobby servo and stepper envelopes",
     tags=["servo", "sg90", "mg996r", "nema17", "motor", "mount"],
     text="""Verify against the datasheet before a critical fit; these are the
dimensions to start from (mm).

SG90 / MG90S micro servo:
- body 22.8 x 12.2 x 22.5 (W x D x H) plus a 4 mm output boss
- mounting flange total length 32.2, two holes dia 2.1 on 27.6 centres
- shaft: 4.8 dia splined, 5.9 above the case

MG996R / MG995 standard servo:
- body 40.7 x 19.7 x 36.0
- mounting holes dia 4.0 on 49.5 centres, flange total 54.5
- shaft 5.9 dia, 15.4 tall

NEMA 17 stepper (42 mm frame):
- frame 42.3 x 42.3, length 40 (typical), 4 holes dia 3.2 on a 31 x 31 pattern
- pilot boss 22 dia x 2 tall, shaft 5 dia
- mount with M3 screws, counterbore 6.4 x 2 deep from the back if the screw head must
  clear the frame

Servo mount recipe: a pocket the body drops into with 0.3 mm clearance per side, a
through-slot for the output shaft, and two M3/M2 holes on the flange centres. Screw
into the flange from below, not through the body."""),

dict(id="hw-004", domain="hardware", kind="rule", source="standard practice",
     title="Fits and clearances for printed parts",
     tags=["tolerance", "fit", "press", "slip", "snap", "clearance", "shrink"],
     text="""FDM (0.4 mm nozzle, PLA/PETG), single value per mating pair:

| feature                        | clearance (mm, total on the pair) |
|--------------------------------|-----------------------------------|
| slip fit, easy to move         | 0.30                              |
| sliding fit, hand assembly     | 0.20                              |
| locating fit, light push       | 0.15                              |
| press fit, vise needed         | -0.05                             |
| snap-fit hook engagement       | 0.6 hook on 0.4 undercut          |
| threaded insert hole           | insert OD + 0.10                  |
| clearance for a screw          | use the ISO table, +0.1 for FDM   |

Other FDM design rules:
- Minimum printable wall: 1.2 mm (3 perimeters at 0.4). Structural: 2.0 mm. Enclosure
  wall: 2.0-2.4 mm.
- Minimum free-standing feature: 0.8 mm. Minimum feature gap: 0.4 mm.
- Overhang limit 45 deg; anything steeper needs a chamfer or a fillet.
- Holes print undersized by roughly 0.1-0.15 mm per side; add it to the CAD or drill out.
- Horizontal round holes under 8 mm print oval; model them 0.2 mm oversize or use a
  teardrop / diamond profile.
- A boss should be at least 1.5x the hole diameter in outer diameter, with a 0.5 mm
  chamfer at the top.
- Factor of safety for a 3D-printed bracket: printed plastic is ~40% weaker than the
  datasheet along layer lines. Thicken the loaded section.
- Plan the print orientation while modelling: a flat base, no need for support on
  the functional faces, layer lines perpendicular to the main load."""),

# ───────────────────────────────────────────── recipes (full code) ──────────
dict(id="rec-001", domain="recipe", kind="recipe", source="verified",
     title="Rounded mounting plate with a grid of clearance holes",
     tags=["plate", "bracket", "grid", "rounded", "holes", "recipe"],
     text="""Ask: "mounting plate 40 x 30 x 10, r4 corners, 4x M3 clearance holes".

```python
from build123d import *

L, W, H = 40.0, 30.0, 10.0
r = 4.0
hole_d = 3.4           # M3 clearance
nx, ny = 2, 2
margin = 8.0           # edge to hole centre
sx = L - 2 * margin
sy = W - 2 * margin

with BuildPart() as p:
    with BuildSketch(Plane.XY):
        RectangleRounded(L, W, r)
        with GridLocations(sx, sy, nx, ny):
            Circle(hole_d / 2, mode=Mode.SUBTRACT)
    extrude(amount=H)

part = p.part
```
Check: volume = (L*W - (4 - pi)*r^2 - n*pi*(d/2)^2) * H = 11499.5 mm^3 for these numbers."""),

dict(id="rec-002", domain="recipe", kind="recipe", source="verified",
     title="L-bracket with holes in both legs",
     tags=["l-bracket", "angle", "bracket", "two legs", "recipe"],
     text="""Ask: "L bracket, 60 base, 80 upright, 40 wide, 6 thick, 2 holes each leg, M5".

```python
from build123d import *

L, W, H, T = 60.0, 40.0, 80.0, 6.0     # base length, depth, upright height, thickness
d = 5.5                                 # M5 clearance

base = Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN))
wall = Box(T, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
wall = wall.moved(Location((L / 2 - T / 2, 0, 0)))
part = base + wall

# holes through the base, drilled in Z
for i in range(2):
    x = -L / 2 + L / 3 * (i + 1)
    part -= Cylinder(d / 2, T + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((x, 0, -1)))

# holes through the upright, drilled in Y -> rotate a centred cylinder about X
for i in range(2):
    z = H / 3 * (i + 1)
    part -= Cylinder(d / 2, W + 2).rotate(Axis.X, 90).moved(Location((L / 2 - T / 2, 0, z)))
```

Two traps: the upright hole cylinder must be CENTERED in all axes before rotating
(otherwise it only reaches half way through the width), and the base hole must start
at z = -1 so it is not coplanar with the bottom face."""),

dict(id="rec-003", domain="recipe", kind="recipe", source="verified",
     title="Tube / bushing / spacer",
     tags=["tube", "bushing", "spacer", "cylinder", "recipe"],
     text="""```python
from build123d import *

OD, ID, L = 16.0, 8.0, 20.0
part = Cylinder(OD / 2, L, align=(Align.CENTER, Align.CENTER, Align.MIN))
part -= Cylinder(ID / 2, L + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -1)))
```
Volume check: pi*(R^2 - r^2)*L.
For a printed spacer that must not crush, add a 0.5 mm chamfer on both ends:
`part = chamfer(part.edges().filter_by(GeomType.CIRCLE), 0.5)`."""),

dict(id="rec-004", domain="recipe", kind="recipe", source="verified",
     title="Hex standoff / spacer",
     tags=["hex", "standoff", "spacer", "pcb", "recipe"],
     text="""```python
from build123d import *
import math

across_flats = 5.5            # M3 hex standoff
h = 12.0
bore = 1.7                    # M3 clearance through
circumradius = across_flats / math.sqrt(3)

part = extrude(RegularPolygon(circumradius, 6, major_radius=True,
                              align=(Align.CENTER, Align.CENTER)), amount=h)
part -= Cylinder(bore, h + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -1)))
```
`RegularPolygon(radius, side_count, major_radius=True)` treats `radius` as the
circumscribed radius (to the vertices). Across-flats = 2 * r * cos(30) = sqrt(3) * r."""),

dict(id="rec-005", domain="recipe", kind="recipe", source="verified",
     title="Servo mount cradle (the photo-to-part demo)",
     tags=["servo", "sg90", "mount", "cradle", "pocket", "recipe", "demo"],
     text="""Ask: "servo mount for an SG90, 3 mm walls, two M2 flange screws, shaft slot
through, print flat".

```python
from build123d import *

# --- measured / datasheet envelope (mm)
body_l, body_w, body_h = 22.8, 12.2, 22.5      # servo body X, Y, Z
flange_l = 32.2                                 # flange overall length
hole_d = 2.2                                    # M2 clearance
hole_c = 27.6                                   # flange hole centres
clr = 0.3                                       # drop-in clearance per side

wall = 3.0
base_t = 3.0
pocket_h = body_h * 0.65                        # servo sits 65% into the cradle

# --- base plate
L = flange_l + 2 * wall + 8.0
W = body_w + 2 * clr + 2 * wall
part = Box(L, W, base_t, align=(Align.CENTER, Align.CENTER, Align.MIN))

# --- walls around the pocket (uprights on both long sides)
for sx in (-1, 1):
    uw = Box(pocket_h, wall, pocket_h + base_t,
             align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part += uw.moved(Location((0, sx * (W / 2 - wall / 2), base_t + pocket_h / 2)))
# --- and both ends
for sx in (-1, 1):
    ew = Box(wall, W, pocket_h + base_t, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part += ew.moved(Location((sx * (L / 2 - wall / 2), 0, base_t + pocket_h / 2)))

# --- shaft slot through the base (servo output is 4.8 dia, give it room)
part -= Cylinder(3.5, base_t + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -1)))

# --- two flange screw holes (through the base, on the flange centres)
for sx in (-1, 1):
    part -= Cylinder(hole_d / 2, base_t + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
        Location((sx * hole_c / 2, 0, -1)))

# --- cable relief notch in one end wall
part -= Box(6, 5, pocket_h, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
    Location((L / 2 - wall / 2, 0, base_t)))
```

Order matters: build the solid shell first, then cut. Every cutter is longer than the
material it crosses. This is the canonical "photo of a servo -> bracket" shape; adjust
`body_l/body_w/body_h` and `hole_c` from the canvas measurements and the geometry follows."""),

dict(id="rec-006", domain="recipe", kind="recipe", source="verified",
     title="Bearing housing / idler pulley",
     tags=["bearing", "housing", "pulley", "idler", "press fit", "recipe"],
     text="""```python
from build123d import *

od, bw = 22.0, 7.0            # 608 bearing
press = 0.05                  # printed press fit
flange_r = 15.0
flange_t = 2.0

part = Cylinder(flange_r, flange_t, align=(Align.CENTER, Align.CENTER, Align.MIN))
part += Cylinder(od / 2 + 2.5, bw + 1.0, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
    Location((0, 0, flange_t)))
pocket = Cylinder(od / 2 - press, bw + 0.2, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
    Location((0, 0, flange_t + 1.0)))
part -= pocket
part -= Cylinder(4.0, flange_t + bw + 3, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
    Location((0, 0, -1)))
# lead-in chamfer so the bearing starts square
part = chamfer(part.edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[-1], 0.5)
```"""),

dict(id="rec-007", domain="recipe", kind="recipe", source="verified",
     title="Open-top enclosure with lid lip and PCB standoffs",
     tags=["enclosure", "case", "lid", "standoff", "pcb", "recipe"],
     text="""```python
from build123d import *

L, W, H, t = 90.0, 60.0, 32.0, 2.4
lip = 1.2        # lid registers on this
pcb_x, pcb_y = 70.0, 46.0     # PCB hole pattern
stand_h = 5.0

body = Box(L, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
inner = Box(L - 2*t, W - 2*t, H - t, align=(Align.CENTER, Align.CENTER, Align.MIN))
body -= inner.moved(Location((0, 0, t)))

# inner lip at the top: a ring the lid sits on
ring_o = Box(L - 2*t, W - 2*t, lip, align=(Align.CENTER, Align.CENTER, Align.MIN))
ring_i = Box(L - 2*t - 2*lip, W - 2*t - 2*lip, lip, align=(Align.CENTER, Align.CENTER, Align.MIN))
body += (ring_o - ring_i).moved(Location((0, 0, H - lip)))

# four PCB standoffs with M3 pilot holes
for sx in (-1, 1):
    for sy in (-1, 1):
        x, y = sx * pcb_x / 2, sy * pcb_y / 2
        body += Cylinder(2.6, stand_h, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
            Location((x, y, t)))
        body -= Cylinder(1.25, stand_h + 1, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
            Location((x, y, t - 1)))

part = body
```
Lid is the same footprint, `Box(L, W, t)`, with a mating inner boss that drops into
the lip gap (L - 2*t - 0.3).""" ),

dict(id="rec-008", domain="recipe", kind="recipe", source="verified",
     title="Vent / grille slot pattern",
     tags=["vent", "grille", "slot", "pattern", "recipe"],
     text="""```python
from build123d import *

L, W, H, t = 80.0, 60.0, 20.0, 2.0
n = 5
slot_h = 4.0

with BuildPart() as p:
    Box(L, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with BuildSketch(Plane.XY.offset(H)):
        Rectangle(L, W)
        with GridLocations(0, 9.0, 1, n):
            SlotOverall(46.0, slot_h, mode=Mode.SUBTRACT)
    extrude(amount=-(t + 0.4), mode=Mode.SUBTRACT)

part = p.part
```
`SlotOverall(width, height)` — width is the OVERALL length including both end radii.
Keep the ligature between slots at least 1.5 mm or it will not print.

Two things to notice in the code. The sketch is placed on the TOP face and the extrude
goes DOWN (`amount=-`), which is how you cut a pocket from a face — a sketch on
`Plane.XY` extruded up would leave the slots floating above the part. And the
`Rectangle(L, W)` before the slots is not decoration: inside a fresh `BuildSketch` the
first object cannot be `Mode.SUBTRACT`, because there is nothing to subtract from yet."""),

dict(id="rec-009", domain="recipe", kind="recipe", source="verified",
     title="Snap-fit cantilever hook",
     tags=["snap", "clip", "cantilever", "latch", "recipe"],
     text="""```python
from build123d import *

arm_l, arm_w, arm_t = 18.0, 8.0, 1.6
hook_h = 0.8        # engagement depth
part = Box(arm_l, arm_w, arm_t, align=(Align.MIN, Align.CENTER, Align.CENTER))

# the hook must OVERLAP the arm, not sit on top of it, or you get two solids
hook = Box(3.4, arm_w, hook_h + 0.2, align=(Align.MIN, Align.CENTER, Align.MIN))
hook = hook.moved(Location((arm_l - 3.0, 0, arm_t / 2 - 0.2)))
part = part + hook
```
Rule of thumb: arm length >= 6x thickness so PETG/PLA can deflect 2-3% without
yielding, hook engagement 0.6-1.0 mm, and the hook face angled 30 deg on the entry
side so it cams in. Print the arm flat so layer lines run along it.
Check `len(part.solids()) == 1` before exporting — a hook placed exactly tangent to the
arm is the classic "two solids" mistake."""),

dict(id="rec-010", domain="recipe", kind="recipe", source="verified",
     title="Dovetail and keyed joints",
     tags=["dovetail", "joint", "key", "assembly", "recipe"],
     text="""A dovetail *slot* cut into a block (one solid). The male rail is the same
profile offset by the clearance.

```python
from build123d import *

block_x, block_y, block_h = 30.0, 40.0, 20.0
open_w = 14.0       # width at the surface
deep_w = 18.0       # width at the bottom of the slot -> the flare
depth = 8.0

with BuildPart() as p:
    Box(block_x, block_y, block_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with BuildSketch(Plane.XY):
        Rectangle(block_x, block_y)
        Polygon((-open_w / 2, -block_y / 2), (open_w / 2, -block_y / 2),
                (deep_w / 2, block_y / 2), (-deep_w / 2, block_y / 2),
                align=None, mode=Mode.SUBTRACT)
    extrude(amount=depth, mode=Mode.SUBTRACT)

part = p.part
```

To make the mating male rail, emit the same `Polygon` as `Mode.ADD` and extrude it
`-clearance` inward: `offset(sketch, amount=-0.15)`. Keep the taper under 20 deg per
side (here atan(2/40) ≈ 3 deg — safe and still self-retaining) or the joint will not
hold under load. The slot runs the full width so the rail slides in from the side."""),

dict(id="rec-011", domain="recipe", kind="recipe", source="verified",
     title="Text / logo emboss",
     tags=["text", "emboss", "label", "logo", "recipe"],
     text="""```python
from build123d import *

with BuildPart() as p:
    Box(60, 30, 4, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with BuildSketch(Plane.XY.offset(4)):
        Text("NILAB", font_size=8, font="Arial", align=(Align.CENTER, Align.CENTER))
    extrude(amount=-0.6, mode=Mode.SUBTRACT)     # engrave 0.6 mm deep

part = p.part
```
For raised text use `extrude(amount=0.6)` (mode ADD) instead — but then it is text on
top of the part, not in the part, so it stays one solid only because the sketch sits on
the face. Font size is cap height in mm; a 0.4 mm nozzle cannot resolve strokes under
~0.8 mm, so keep font_size above 6 mm. If the requested font is not installed the call
raises — fall back to `font="Arial"` or drop `font` entirely and use the default."""),

dict(id="rec-012", domain="recipe", kind="recipe", source="verified",
     title="Cable clamp / strain relief block",
     tags=["cable", "clamp", "strain relief", "slot", "recipe"],
     text="""```python
from build123d import *

L, W, H = 30.0, 22.0, 14.0
cable_d = 6.0
screw_d = 3.4        # M3
part = Box(L, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
# cable channel through the middle, open at the top
part -= Cylinder(cable_d / 2, L + 2).rotate(Axis.Y, 90).moved(Location((-1, 0, cable_d / 2 + 3)))
part -= Box(L + 2, cable_d, cable_d, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
    Location((0, 0, cable_d * 1.5 + 3)))
# two clamping screws
for sx in (-1, 1):
    part -= Cylinder(screw_d / 2, H + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
        Location((sx * (L / 2 - 5), 0, -1)))
```"""),

dict(id="rec-013", domain="recipe", kind="recipe", source="verified",
     title="Parametric V-slot / extrusion end cap",
     tags=["end cap", "2020", "extrusion", "v-slot", "recipe"],
     text="""```python
from build123d import *

s = 20.0          # 2020 extrusion
wall = 2.0
lip = 1.0
part = Box(s, s, 6.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
inner = Box(s - 2*wall, s - 2*wall, 6.0 - 1.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
part -= inner.moved(Location((0, 0, 1.0)))
# four corner relief slots so it clears the extrusion lips
for sx in (-1, 1):
    for sy in (-1, 1):
        part -= Box(3.2, 3.2, 8, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
            Location((sx * (s/2 - 1.6), sy * (s/2 - 1.6), -1)))
```"""),

# ───────────────────────────────────────────── fusion api ───────────────────
dict(id="fa-001", domain="fusion_api", kind="doc", source="verified",
     title="Fusion's Python API uses CENTIMETRES",
     tags=["fusion", "units", "cm", "api", "adsk", "execute_code"],
     text="""Every length in `adsk.core` / `adsk.fusion` is in centimetres, while the UI
shows millimetres. A 40 mm plate is `4.0` in the API.

```python
# inside the Fusion MCP execute_code tool
cw = adsk.core.ValueInput.createByReal(4.0)     # 40 mm
s = adsk.core.ValueInput.createByString("40 mm")  # explicit units, safer
```

Rules when driving Fusion:
- Convert `mm -> cm` by /10 at the boundary, and back when reading bounding boxes.
- Sketch geometry on the XY plane is `sketch.modelToSketchSpace()` — points are in cm too.
- Prefer `ValueInput.createByString("40 mm")` so the expression carries units and the
  document's unit setting cannot bite you.

The other MCP tools in this bridge (`fusion360` server) already return cm and say so
in their docstrings; double every number you read from them before using it in a
build123d script."""),

dict(id="fa-002", domain="fusion_api", kind="doc", source="verified",
     title="Import a STEP file into Fusion programmatically",
     tags=["fusion", "step", "import", "importmanager", "execute_code"],
     text="""The reliable path (via the fusion360 MCP `execute_code` tool), importing into
the active component:

```python
import adsk.core, adsk.fusion
path = r"C:/Users/you/out/part.step"          # forward slashes on Windows
mgr = app.importManager
opts = mgr.createSTEPImportOptions(path)
opts.isViewFit = True
des = app.activeProduct
root = des.rootComponent
new_occ = mgr.importToTarget(opts, root)      # returns an occurrence
print("imported:", new_occ.component.name)
```

Notes:
- `importToTarget` needs the component, not the design.
- The imported body keeps the STEP's own units; the build123d export is mm, so a 40 mm
  plate measures 4.0 in the API afterwards.
- Prefer importing the STEP from build123d over replaying 20 sketch/extrude MCP calls:
  one call, exact geometry, and the feature history is not needed for manufacturing.
- To keep documents small, delete the previous import first (`root.occurrences`)."""),

dict(id="fa-003", domain="fusion_api", kind="doc", source="verified",
     title="Choosing between build123d and live Fusion modelling",
     tags=["fusion", "build123d", "code", "tool choice", "strategy"],
     text="""Both produce the same STEP. Pick deliberately.

Use build123d (this bridge) when: the part is parametric, dimensions come from a
drawing, you need to iterate on numbers, the shape is a solid/prismatic/revolution, or
you want a verified volume/bbox before anything touches Fusion.

Use the live Fusion tools (`mcp_fusion360_*`) when: you need to *edit an existing
Fusion document*, keep a feature tree a human can edit, use Form/T-Spline (not
available via API anyway), run an interference check between components, or drive CAM.

Hybrid (recommended for this bridge): build123d generates and self-verifies the solid
-> export STEP -> `fusion_push_step` imports it into Fusion for the user to look at,
measure, and export.

Do not try to translate build123d fillet/loft trees into sketch+extrude calls; the
mapping is lossy and it will fail on any non-prismatic feature."""),

dict(id="fa-004", domain="fusion_api", kind="doc", source="verified",
     title="Reading a fusion360 MCP result: what the numbers mean",
     tags=["fusion", "mcp", "result", "bbox", "measure"],
     text="""The `fusion360` MCP server exposes ~93 commands over a local socket and returns
`{"status": "success", "result": {...}}`.

- `create_box(length, width, height)` and friends take **mm** in their arguments
  (the add-in converts for you) but return body bounding boxes in **cm**.
- `get_physical_properties` returns `volume` in cm^3 — multiply by 1000 for mm^3.
- `export_step(body_name, file_path)` needs a body name, not an index.
- `render_view` returns `image_base64` only; decode and save it yourself.
- There is no mouse picking: select by name, by index, or by bounding-box position.

Verify a build by `get_physical_properties` against the volume you calculated, the
same way the build123d runner does."""),

# ───────────────────────────────────────────── printing / manufacturing ────
dict(id="pr-001", domain="printing", kind="rule", source="verified",
     title="Design-for-print checklist applied to CAD decisions",
     tags=["print", "fdm", "orientation", "support", "strength"],
     text="""Decide these while modelling, not after:

1. Flat base of at least 20 x 20 mm for bed adhesion; add a 0.5 mm chamfer instead of
   a fillet on the first layer so there is no elephant-foot bulge.
2. No overhang steeper than 45 deg without a chamfer. A hole in a vertical wall needs
   a teardrop top beyond ~10 mm diameter.
3. Layer lines are the weak direction: align the longest dimension of a load-bearing
   part with X/Y, and put fillets where a bending moment peaks.
4. Wall = 3 perimeters (1.2 mm) minimum; bosses carrying a screw should be 2x the
   screw diameter across.
5. Anything under 0.8 mm will not print. Anything under 0.4 mm will not print at all.
6. Bridge spans under 15 mm print cleanly; longer needs a support or a rib.
7. Holes under 8 mm: model +0.2 mm. Slots wider than 8 mm: model +0.15 mm.
8. Model the part in the orientation you will print it, so the "bottom" face is the
   one on the bed and no rotation is needed in the slicer."""),

dict(id="pr-002", domain="printing", kind="rule", source="verified",
     title="Bambu A1 / P1 specifics that change the CAD",
     tags=["bambu", "a1", "printer", "bed", "build volume", "tolerance"],
     text="""Bambu Lab A1 build volume 256 x 256 x 256 mm; A1 mini 180 x 180 x 180.
- Bed is 256 mm; keep parts under 250 mm in X/Y to leave room for a brim.
- The textured PEI plate gives slightly different first-layer squish: holes print
  ~0.1 mm tighter than on smooth glass.
- Multi-colour (AMS lite) needs a filament purge tower, so keep the model's footprint
  under ~200 x 200 to leave room on the plate.
- Default profile is 0.4 mm nozzle / 0.2 mm layers; a 0.6 mm nozzle needs +0.1 mm on
  every clearance and allows a 1.8 mm minimum wall.
- Large flat parts warp: split into modules with dovetails above 180 mm, or add 3 mm
  ribs on the underside."""),

dict(id="pr-003", domain="printing", kind="rule", source="verified",
     title="Slicer-ready outputs and what to hand the user",
     tags=["export", "stl", "3mf", "step", "handoff"],
     text="""Deliverables per part:
- `part.step` — the editable/CAM/interop format. Always produce this.
- `part.stl` — direct slicer input, tolerance 0.05 mm.
- `part.png` — an isometric render so the user can see it before opening anything.
- A one-line summary: bounding box, volume, mass estimate at 1.24 g/cm^3 (PLA),
  and the print orientation.

Mass estimate: `volume_mm3 * 1.24e-3` grams for solid PLA; multiply by 0.4-0.6 for a
typical infill+perimeter part. Say which assumption you used."""),

# ───────────────────────────────────────────── workflow / agents ────────────
dict(id="wf-003", domain="workflow", kind="rule", source="verified",
     title="The image -> spec -> code -> verify -> Fusion loop",
     tags=["workflow", "loop", "agent", "verify", "mcp", "canvas"],
     text="""The bridge exists to make this loop cheap and closed:

1. `canvas_open(image_path)` — the user marks up a photo/drawing: outline, hole
   centres, a calibration line with its real length in mm, dimension lines, notes.
2. `canvas_wait()` — returns `{"shapes": [...], "scale_mm_per_px": k, "notes": ...}`
   plus the composite PNG path. Look at the PNG, read the numbers from the JSON.
3. `cad_knowledge_search(query)` — pull the API pattern and the hardware sizes you
   need (e.g. "m3 clearance counterbore", "servo flange holes", "press fit bearing").
4. Write ONE build123d script to the house rules. Write the dimension table to the user
   in the same message.
5. `cad_run_code(code)` — executes in a sandboxed venv, returns volume, bounding box,
   solid count, validity, and STL/STEP paths. It refuses anything that is not exactly
   one valid solid.
6. Compare the returned volume against your hand calculation. If it differs, fix the
   code — not the expectation.
7. `fusion_push_step(step_path)` — imports the STEP into the open Fusion document.

Never skip step 5. A script that "looks right" and has never been executed is the
normal failure mode of LLM CAD; the volume check catches the majority of real errors
(a feature that silently did nothing, a hole drilled in the wrong place, a boolean that
removed everything)."""),

dict(id="wf-004", domain="workflow", kind="rule", source="verified",
     title="What to ask the user when the image is ambiguous",
     tags=["ambiguity", "question", "spec", "assumption"],
     text="""One round of questions, maximum, and only about things a photo cannot tell you:

- Which face is the mounting face (what touches the other part)?
- How much clearance for the mating object (slip / press / snap)?
- Print orientation, if strength matters?
- Which dimensions are critical vs. cosmetic?

Do not ask: units (assume mm), origin convention (house rules), or file format
(STEP + STL always). If the answer does not arrive, proceed with the standard value
from the tables and label the assumption in the summary. A part with a stated
assumption is more useful than a question the user has to answer twice."""),

dict(id="wf-005", domain="workflow", kind="rule", source="verified",
     title="Self-check arithmetic for the common shapes",
     tags=["volume", "check", "math", "verify"],
     text="""Compute the expected volume before running code; the runner compares it.

- Box: L * W * H
- Cylinder: pi * r^2 * h
- Tube: pi * (R^2 - r^2) * h
- Box with 4 corner fillets radius r: (L*W - (4 - pi) * r^2) * H
- Box minus n through holes diameter d: ... - n * pi * (d/2)^2 * H
- Hexagon prism (circumradius s): (3 * sqrt(3) / 2) * s^2 * h
- Open-top box walls t: L*W*H - (L - 2t) * (W - 2t) * (H - t)
- Rectangular pocket pl x pw x pd: pl * pw * pd
- Union of two boxes overlapping by ov: V1 + V2 - ov
- Countersink removal: cone volume pi/3 * h * (R^2 + R*r + r^2) with h from the angle
- Sphere: 4/3 * pi * r^3   Torus: 2 * pi^2 * R * r^2

Tolerance: the runner accepts 0.5% volume error (fillet/boolean rounding), 0.05 mm on
each bounding-box dimension. Anything bigger is a real modelling error."""),
]
# fmt: on
