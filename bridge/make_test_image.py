"""Draw a synthetic 'servo motor' PNG so the canvas can be tested with a real image.

640x480 white sheet, a servo body 22.8 x 12.2 mm drawn at 12 px/mm, a 32.2 mm flange
with two mounting holes, and a shaft. Known pixel geometry -> known millimetres.
"""
import struct
import zlib
from pathlib import Path

W, H = 640, 480
PX = 12.0        # pixels per mm in the drawing


class Img:
    def __init__(self, w, h, bg=(245, 246, 248)):
        self.w, self.h = w, h
        self.px = bytearray(bg * (w * h))

    def _set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = bytes(c)

    def rect(self, x0, y0, x1, y1, c, fill=True, t=2):
        x0, x1 = int(min(x0, x1)), int(max(x0, x1))
        y0, y1 = int(min(y0, y1)), int(max(y0, y1))
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                edge = (x - x0 < t or x1 - x < t or y - y0 < t or y1 - y < t)
                if fill or edge:
                    self._set(x, y, c)

    def circle(self, cx, cy, r, c, fill=False, t=2):
        for y in range(int(cy - r - 1), int(cy + r + 2)):
            for x in range(int(cx - r - 1), int(cx + r + 2)):
                d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                if (not fill and abs(d - r) <= t) or (fill and d <= r):
                    self._set(x, y, c)

    def save(self, path):
        raw = b"".join(b"\x00" + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3])
                       for y in range(self.h))

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data +
                    struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        png = (b"\x89PNG\r\n\x1a\n" +
               chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)) +
               chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(png)


im = Img(W, H)
dark, mid, hole = (38, 44, 52), (90, 100, 115), (12, 14, 18)

# servo body 22.8 x 12.2 mm, centred
bw, bh = 22.8 * PX, 12.2 * PX
cx, cy = 320, 240
im.rect(cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2, dark, fill=True)
im.rect(cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2, hole)

# flange 32.2 mm long x 4 mm tall on both sides, with M2 holes on 27.6 centres
fw, fh = 32.2 * PX, 4.0 * PX
for sy in (-1, 1):
    y0 = cy + sy * (bh / 2) - (fh if sy < 0 else 0)
    y1 = y0 + fh
    im.rect(cx - fw / 2, y0, cx + fw / 2, y1, mid, fill=True)
    im.rect(cx - fw / 2, y0, cx + fw / 2, y1, hole)
for sx in (-1, 1):
    for sy in (-1, 1):
        hx = cx + sx * (27.6 * PX / 2)
        hy = cy + sy * (bh / 2 + fh / 2)
        im.circle(hx, hy, 2.1 * PX / 2, (250, 250, 250), fill=True)
        im.circle(hx, hy, 2.1 * PX / 2, hole)

# output shaft (4.8 mm dia) on top of the body
im.circle(cx - bw / 2 + 4.5 * PX, cy, 4.8 * PX / 2, (200, 170, 60), fill=True)
im.circle(cx - bw / 2 + 4.5 * PX, cy, 4.8 * PX / 2, hole)

# a scale reference: 10 mm ruler bar at the bottom left
im.rect(30, 430, 30 + 10 * PX, 436, hole, fill=True)
for i in range(11):
    im.rect(30 + i * PX, 420, 30 + i * PX + 1, 436, hole, fill=True)

out = Path("C:/Users/nilab/AppData/Local/hermes/cache/scratch/servo.png")
im.save(out)
print(out, out.stat().st_size, "bytes", f"{W}x{H}")
print(f"body drawn {bw:.0f}x{bh:.0f}px = 22.8x12.2mm at {PX} px/mm")
print(f"flange {fw:.0f}px = 32.2mm, holes on {27.6*PX:.1f}px = 27.6mm")
