"""Servo mount bracket — built from a canvas annotation of an SG90 photo.

Every number below is traceable:
  body 22.8 x 12.2      measured on the canvas (22.83 x 12.17 at the 10 mm calibration)
  flange 32.2 long      measured on the canvas
  flange holes 27.6 c/c measured on the canvas, 4 holes at (+-13.8, +-8.1)
  body height 22.5      NOT measurable from a top view -> SG90 datasheet
  M2 clearance 2.4      ISO 273 table, not the 2.1 hole in the servo itself
  shaft slot 7.0        servo output boss is 4.8 dia, +2.2 clearance
"""
from build123d import *

# --- measured / datasheet
body_l, body_w = 22.8, 12.2
flange_l = 32.2
hole_c_x, hole_c_y = 27.6, 8.1
screw_d = 2.4                    # M2 clearance
shaft_x, shaft_d = -6.9, 7.0     # output boss sits 4.5 mm in from the body edge

# --- design decisions
wall = 6.7                       # ledge the servo flange rests on
plate_t = 3.0
pocket_clr = 0.3                 # drop-in clearance per side
pocket_depth = 2.0

L = flange_l + 2 * wall + 3.0    # 42.8
W = body_w + 2 * 8.1 + 0.0       # 26.4 ; flange centreline + wall
W = body_w + 2 * hole_c_y

part = Box(L, W, plate_t, align=(Align.CENTER, Align.CENTER, Align.MIN))

# body pocket, open to the top
pocket = Box(body_l + 2 * pocket_clr, body_w + 2 * pocket_clr, pocket_depth + 0.5,
             align=(Align.CENTER, Align.CENTER, Align.MIN))
part -= pocket.moved(Location((0, 0, plate_t - pocket_depth)))

# shaft clearance through the plate
part -= Cylinder(shaft_d / 2, plate_t + 2,
                 align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((shaft_x, 0, -1)))

# four flange screw holes
for sx in (-1, 1):
    for sy in (-1, 1):
        part -= Cylinder(screw_d / 2, plate_t + 2,
                         align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
            Location((sx * hole_c_x / 2, sy * hole_c_y, -1)))

# break the sharp corners the printer would otherwise elephant-foot
part = fillet(part.edges().filter_by(Axis.Z), radius=2.0)
