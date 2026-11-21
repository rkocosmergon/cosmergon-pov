#!/usr/bin/env python3
"""The drawn surfaces of the themes: palette layout, a small canvas, and the faces, floors and tops.

Standard library only, deterministic (every variant has its own seeded generator, nothing depends on
the theme: the pictures are made of palette INDICES, a theme only says which colour an index has).
Used by tools/make_theme.py; `tools/theme_samples.py --sheet` shows them.

Geometry: every picture is 256 x 256 texels over 128 units (a cell edge, a cell): two texels to the
unit (the engine's `pov_tex_dshift` / `pov_flat_dshift`, COSMERGON.md "Themes"). Row 0 of a wall
texture is its top. Row 0 of a floor flat is its NORTH edge, column 0 its WEST edge (the span drawer
runs on world x and on -y).

Colour discipline: a role has at most three stages (surface, shade, fleck) plus the navy of the line.
A face has two of them: the surface and its "fleck" stage (the shade for the lit sides and the tops,
the darker stage for the shaded sides). The ground has three: surface, a darker stain, a lighter scrap.
A fleck is drawn in the SAME class as its surface (no outline around it, make_theme.theme_lump).

Lines ("ink") are twin indices of the colour they lie on. Three kinds, each folds into the surface at
its own distance (make_theme.colormap):
  core  1 texel (half a unit); it is the line near the viewer and, with its halo, the coarse structure
        far away: it stays visible to the "coarse" distance;
  halo  a second texel beside a core texel; navy only between the "halo" and the "coarse" distance:
        the line is two texels (one unit) there, so it keeps about the weight of the outline;
  fine  1 texel, folds at the "fine" distance: small things (rivets, scraps, cracks) vanish first.
"""

from __future__ import annotations

import math
import random

N = 256                    # texels a side

# ---- palette layout (the same in every theme)
I_OUTLINE = 0
I_GROUND, I_GROUND_SHADE, I_BORDER, I_GROUND_LIGHT = 1, 2, 3, 4
ROLES = ("cell", "own", "wall", "tower")
FACE_KEYS = ("t0", "t1", "x0", "x1", "y0", "y1")      # top (surface, fleck), side x, side y
I_ROLE = {role: {key: 8 + 6 * r + i for i, key in enumerate(FACE_KEYS)} for r, role in enumerate(ROLES)}
I_BAND = {"x": 32, "y": 33}
TWIN_FIRST = 40
I_SHAPES = (5, 6)           # sky shapes: sun disc, cloud
I_SKY = {"sun": 5, "cloud": 6, "shade": 7, "star": 34, "moon": 35}     # the sky's own indices (POVSKY)
SKY_FIRST = 156

# every index that can carry a line, with the orientation of its surface (decides when its lines fold)
BASES: list[tuple[int, str]] = [(I_GROUND, "floor"), (I_GROUND_SHADE, "floor"), (I_GROUND_LIGHT, "floor")]
for _role in ROLES:
    for _key in FACE_KEYS:
        BASES.append((I_ROLE[_role][_key], {"t": "floor", "x": "x", "y": "y"}[_key[0]]))
BASES += [(I_BAND["x"], "x"), (I_BAND["y"], "y")]
# base -> (core, halo, fine) twin indices
TW: dict[int, tuple[int, int, int]] = {b: (TWIN_FIRST + 3 * i, TWIN_FIRST + 3 * i + 1, TWIN_FIRST + 3 * i + 2)
                                       for i, (b, _o) in enumerate(BASES)}
TWIN_SET = {t for trio in TW.values() for t in trio}
assert max(TWIN_SET) < 127
KIND = {"c": 0, "h": 1, "f": 2}

# "Small flecks": a stain or a scrap that is only a few points across at a distance would shimmer when the
# camera moves (one picture it is there, the next it is not). Small fills use a second index of the fleck colour
# that the COLORMAP maps to the colour of the surface from a distance on (make_theme.colormap), the way the
# lines fold. A small fleck can carry fine lines (one twin each).
SMALL_FIRST = 127
SMALL_PAIRS: list[tuple[int, int]] = [(I_GROUND_SHADE, I_GROUND), (I_GROUND_LIGHT, I_GROUND)]     # (fleck, surface)
for _role in ROLES:
    _ids = I_ROLE[_role]
    SMALL_PAIRS += [(_ids["t1"], _ids["t0"]), (_ids["x1"], _ids["x0"]), (_ids["y1"], _ids["y0"])]
SMALL_OF = {fleck: SMALL_FIRST + i for i, (fleck, _s) in enumerate(SMALL_PAIRS)}          # fleck -> small index
SURFACE_OF_SMALL = {SMALL_FIRST + i: surface for i, (_f, surface) in enumerate(SMALL_PAIRS)}
FLECK_OF_SMALL = {v: k for k, v in SMALL_OF.items()}
SMALL_TWIN = {sm: SMALL_FIRST + len(SMALL_PAIRS) + i for i, sm in enumerate(SURFACE_OF_SMALL)}
ORIENT_OF = dict(BASES)
assert max(SMALL_TWIN.values()) < SKY_FIRST and min(SMALL_TWIN.values()) > max(SMALL_OF.values())


class Canvas:
    """A grid of palette indices. `base` is the surface, `alt` its fleck stage, `alt2` an optional third."""

    def __init__(self, base: int, alt: int, alt2: int | None = None, rows: int = N, small_r: int = 12):
        self.base, self.alt, self.alt2 = base, alt, alt2
        self.alt_s, self.alt2_s = SMALL_OF.get(alt), SMALL_OF.get(alt2)
        self.small_r = small_r          # a fleck of a smaller radius uses the small index
        self.g = [bytearray([base]) * N for _ in range(rows)]
        self.rows = rows

    # ---- single pixels
    def get(self, x: int, y: int) -> int:
        return self.g[y][x] if 0 <= x < N and 0 <= y < self.rows else -1

    def put(self, x: int, y: int, idx: int, only_on: int | None = None) -> None:
        if 0 <= x < N and 0 <= y < self.rows and (only_on is None or self.g[y][x] == only_on):
            self.g[y][x] = idx

    def ink(self, x: int, y: int, kind: str) -> None:
        """A pixel of line in the colour class of the pixel it lies on (nothing on an existing line)."""
        cur = self.get(x, y)
        trio = TW.get(cur)
        if trio is not None:
            self.g[y][x] = trio[KIND[kind]]
        elif cur in SMALL_TWIN:
            self.g[y][x] = SMALL_TWIN[cur]

    # ---- fills (a fleck replaces the surface only: it never paints over a line or another fleck)
    def fill(self, x0, y0, x1, y1, idx=None):
        idx = self.alt if idx is None else idx
        for y in range(max(0, y0), min(self.rows - 1, y1) + 1):
            row = self.g[y]
            for x in range(max(0, x0), min(N - 1, x1) + 1):
                if row[x] == self.base:
                    row[x] = idx

    def clear(self, x0, y0, x1, y1):
        """Back to the bare surface (details underneath are gone)."""
        for y in range(max(0, y0), min(self.rows - 1, y1) + 1):
            for x in range(max(0, x0), min(N - 1, x1) + 1):
                self.g[y][x] = self.base

    def poly(self, pts, idx=None):
        idx = self.alt if idx is None else idx
        ys = [p[1] for p in pts]
        for y in range(max(0, int(min(ys))), min(self.rows - 1, int(max(ys))) + 1):
            xs = []
            for i in range(len(pts)):
                (xa, ya), (xb, yb) = pts[i], pts[(i + 1) % len(pts)]
                if (ya <= y + 0.5 < yb) or (yb <= y + 0.5 < ya):
                    xs.append(xa + (y + 0.5 - ya) * (xb - xa) / (yb - ya))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                for x in range(math.ceil(xs[k] - 0.5), math.floor(xs[k + 1] - 0.5) + 1):
                    self.put(x, y, idx, self.base)

    def ellipse(self, cx, cy, rx, ry, idx=None):
        idx = self.alt if idx is None else idx
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                if ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1.0:
                    self.put(x, y, idx, self.base)

    def blob(self, rng, cx, cy, r, squash=1.0, idx=None):
        """An irregular patch: a polygon with a wobbling radius."""
        n = rng.randint(7, 10)
        pts = []
        for i in range(n):
            a = 2 * math.pi * i / n
            rr = r * rng.uniform(0.62, 1.15)
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a) * squash))
        self.poly(pts, idx)

    # ---- ink
    def hline(self, x0, x1, y, kind="c"):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            self.ink(x, y, "f" if kind == "f" else "c")
            if kind == "c":
                self.ink(x, y + 1, "h")

    def vline(self, x, y0, y1, kind="c"):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            self.ink(x, y, "f" if kind == "f" else "c")
            if kind == "c":
                self.ink(x + 1, y, "h")

    def line(self, x0, y0, x1, y1, kind="f"):
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx, sy = (1 if x1 > x0 else -1), (1 if y1 > y0 else -1)
        err, x, y = dx - dy, x0, y0
        while True:
            self.ink(x, y, "f" if kind == "f" else "c")
            if kind == "c":
                if dx >= dy:
                    self.ink(x, y + 1, "h")
                else:
                    self.ink(x + 1, y, "h")
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    def polyline(self, pts, kind="f"):
        for a, b in zip(pts, pts[1:]):
            self.line(a[0], a[1], b[0], b[1], kind)

    def rect(self, x0, y0, x1, y1, kind="c"):
        """Outline; the halo texel lies inside."""
        for x in range(x0, x1 + 1):
            self.ink(x, y0, "f" if kind == "f" else "c")
            self.ink(x, y1, "f" if kind == "f" else "c")
        for y in range(y0, y1 + 1):
            self.ink(x0, y, "f" if kind == "f" else "c")
            self.ink(x1, y, "f" if kind == "f" else "c")
        if kind == "c":
            for x in range(x0 + 1, x1):
                self.ink(x, y0 + 1, "h")
                self.ink(x, y1 - 1, "h")
            for y in range(y0 + 1, y1):
                self.ink(x0 + 1, y, "h")
                self.ink(x1 - 1, y, "h")

    def ring(self, cx, cy, r, kind="c"):
        for y in range(int(cy - r) - 2, int(cy + r) + 3):
            for x in range(int(cx - r) - 2, int(cx + r) + 3):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                if r - 0.5 <= d < r + 0.5:
                    self.ink(x, y, "f" if kind == "f" else "c")
                elif kind == "c" and r - 1.5 <= d < r - 0.5:
                    self.ink(x, y, "h")

    def disc(self, cx, cy, r, idx=None):
        self.ellipse(cx, cy, r, r, idx)

    def paint_disc(self, cx, cy, r, idx):
        """A disc of `idx` over whatever is there (lines excepted: they are drawn afterwards)."""
        for y in range(int(cy - r) - 1, int(cy + r) + 2):
            for x in range(int(cx - r) - 1, int(cx + r) + 2):
                if math.hypot(x + 0.5 - cx, y + 0.5 - cy) <= r and 0 <= x < N and 0 <= y < self.rows:
                    self.g[y][x] = idx

    def diamond(self, cx, cy, rx, ry, kind="c", fill=True):
        pts = [(cx, cy - ry), (cx + rx, cy), (cx, cy + ry), (cx - rx, cy)]
        if fill:
            self.poly(pts)
        for i in range(4):
            a, b = pts[i], pts[(i + 1) % 4]
            self.line(int(a[0]), int(a[1]), int(b[0]), int(b[1]), kind)

    def dot(self, x, y, size=2):
        for dy in range(size):
            for dx in range(size):
                self.ink(x + dx, y + dy, "f")


# =======================================================================================
# parts of a face (all in texels; rng decides placement)
# =======================================================================================

def scribbles(c, rng, x, y, w=44, h=26):
    """Short dashes like writing: a few lines of unequal strokes."""
    for line in range(rng.randint(2, 4)):
        px = x + rng.randint(0, 6)
        py = y + line * (h // 3)
        while px < x + w - 8:
            n = rng.randint(4, 12)
            c.hline(px, min(x + w, px + n), py, "f")
            px += n + rng.randint(3, 7)


def rivets(c, y, x0, x1, step=24, off=0):
    for x in range(x0 + off, x1, step):
        c.dot(x, y, 2)


def vents(c, rng, x, y, slots=5, w=46):
    for i in range(slots):
        yy = y + i * 9
        c.fill(x + 1, yy + 1, x + w - 1, yy + 6)
        c.rect(x, yy, x + w, yy + 7, "f")


def window(c, x, y, w, h, mullion=False):
    c.fill(x + 1, y + 1, x + w - 1, y + h - 1)
    c.rect(x, y, x + w, y + h, "c")
    if mullion:
        c.vline(x + w // 2, y + 2, y + h - 2, "f")


def window_row(c, rng, y, n=None):
    n = n or rng.randint(3, 4)
    w = rng.choice((24, 28, 32))
    h = rng.choice((30, 36, 42))
    gap = (N - n * w) // (n + 1)
    for i in range(n):
        window(c, gap + i * (w + gap), y, w, h, mullion=rng.random() < 0.4)
    if rng.random() < 0.6:
        c.hline(max(0, gap - 4), min(N - 1, N - gap + 4), y + h + 5, "f")    # a sill


def hatch(c, rng, x, y, w=44, h=62):
    c.fill(x + 1, y + 1, x + w - 1, y + h - 1)
    c.rect(x, y, x + w, y + h, "c")
    c.ring(x + w - 10, y + h // 2, 3, "f")                                  # handle
    c.rect(x - 3, y + 8, x, y + 14, "f")                                    # hinges
    c.rect(x - 3, y + h - 14, x, y + h - 8, "f")


def porthole(c, rng, cx, cy, r=20):
    c.disc(cx, cy, r - 1)
    c.ring(cx, cy, r, "c")
    c.ring(cx, cy, r - 7, "f")
    c.hline(cx - r + 6, cx + r - 6, cy, "f")
    c.vline(cx, cy - r + 6, cy + r - 6, "f")


def pipe(c, rng, x, y0, y1, w=14):
    c.fill(x + 1, y0, x + w - 1, y1)
    c.vline(x, y0, y1, "c")
    c.vline(x + w, y0, y1, "c")
    yy = y0 + rng.randint(10, 24)
    while yy < y1 - 6:
        c.hline(x - 3, x + w + 3, yy, "f")
        c.hline(x - 3, x + w + 3, yy + 2, "f")
        yy += rng.randint(34, 62)
    if rng.random() < 0.6:                                                  # an elbow into a seam
        c.hline(x + w, min(N - 1, x + w + rng.randint(18, 50)), y0, "c")


def chip(c, rng, x, y, r=18):
    """A spalled place: an irregular patch of the fleck stage with a few short cracks."""
    c.blob(rng, x, y, r, rng.uniform(0.6, 1.0), c.alt_s if r < c.small_r else None)
    for _ in range(rng.randint(1, 3)):
        a = rng.uniform(0, 2 * math.pi)
        l = rng.randint(8, 20)
        c.line(int(x), int(y), int(x + l * math.cos(a)), int(y + l * math.sin(a)), "f")


def stain(c, rng, x, y, r):
    c.blob(rng, x, y, r, rng.uniform(0.5, 1.0), c.alt_s if r < c.small_r else None)


def drip(c, rng, x, y0, length):
    c.ellipse(x, y0 + length * 0.5, rng.randint(6, 12), length * 0.5)


def crack(c, rng, x, y, length, kind="f"):
    pts = [(x, y)]
    ang = rng.uniform(0, 2 * math.pi)
    for _ in range(rng.randint(3, 5)):
        ang += rng.uniform(-0.7, 0.7)
        step = length / 4
        x, y = x + step * math.cos(ang), y + step * math.sin(ang)
        pts.append((int(x), int(y)))
    c.polyline([(int(a), int(b)) for a, b in pts], kind)


def emblem(c, rng, cx, cy, size=48, clear=True):
    """The mark of an own cell: a framed plate with a diamond, readable without colour."""
    h = size
    if clear:
        c.clear(cx - h - 6, cy - h - 6, cx + h + 6, cy + h + 6)
    c.rect(cx - h, cy - h, cx + h, cy + h, "c")
    c.diamond(cx, cy, h - 12, h - 8, "c", fill=True)
    c.diamond(cx, cy, h // 3, h // 3 + 2, "f", fill=False)
    c.dot(cx - 1, cy - 1, 2)
    for sx in (-1, 1):
        for sy in (-1, 1):
            c.dot(cx + sx * (h - 7) - 1, cy + sy * (h - 7) - 1, 2)


# more parts: small things that make a surface busy

def label(c, rng, x, y, w=36, h=16):
    c.fill(x + 1, y + 1, x + w - 1, y + h - 1)
    c.rect(x, y, x + w, y + h, "c")
    c.hline(x + 5, x + w - 6, y + h // 2 - 2, "f")
    c.hline(x + 5, x + rng.randint(w // 2, w - 8), y + h // 2 + 3, "f")


def hazard(c, rng, x, y, w=50, h=22):
    c.rect(x, y, x + w, y + h, "c")
    for k in range(6, w + h, 9):
        a = (x + min(k, w), y + max(0, k - w))
        b = (x + max(0, k - h), y + min(k, h))
        c.line(a[0], a[1], b[0], b[1], "f")


def duct(c, rng, y, x0=0, x1=N - 1, h=16):
    c.fill(x0, y + 1, x1, y + h - 1)
    c.hline(x0, x1, y, "c")
    c.hline(x0, x1, y + h, "c")
    for x in range(x0 + rng.randint(10, 40), x1 - 6, rng.randint(46, 72)):
        c.vline(x, y + 2, y + h - 2, "f")
        c.vline(x + 3, y + 2, y + h - 2, "f")


def bolts(c, x, y, n=3, step=9):
    for i in range(n):
        for j in range(2):
            c.dot(x + i * step, y + j * step, 2)


def lamp(c, rng, x, y, r=6):
    c.disc(x, y, r)
    c.ring(x, y, r, "f")
    c.line(x, y - r - 1, x, y - r - 8, "f")


def ladder(c, rng, x, y0, y1, w=18):
    c.vline(x, y0, y1, "f")
    c.vline(x + w, y0, y1, "f")
    for y in range(y0 + 6, y1 - 3, 11):
        c.hline(x, x + w, y, "f")


def dial(c, rng, x, y, r=10):
    c.disc(x, y, r - 1)
    c.ring(x, y, r, "c")
    a = rng.uniform(-2.5, -0.6)
    c.line(x, y, int(x + (r - 3) * math.cos(a)), int(y + (r - 3) * math.sin(a)), "f")
    for k in range(5):
        t = -2.8 + k * 0.55
        c.dot(int(x + (r - 3) * math.cos(t)), int(y + (r - 3) * math.sin(t)), 1)


def conduit(c, rng, x, y, n=3):
    pts = [(x, y)]
    for _ in range(n):
        if len(pts) % 2:
            x = max(4, min(N - 5, x + rng.choice((-1, 1)) * rng.randint(20, 60)))
        else:
            y = max(4, min(N - 5, y + rng.choice((-1, 1)) * rng.randint(20, 60)))
        pts.append((x, y))
    c.polyline(pts, "f")
    c.dot(pts[0][0] - 1, pts[0][1] - 1, 3)


def free_box(rng, taken, w, h, x_lo=6, x_hi=None, y_lo=16, y_hi=None, tries=14):
    """A place of w x h texels clear of everything taken so far (None when there is none)."""
    x_hi = (N - w - 6) if x_hi is None else x_hi
    y_hi = (N - h - 6) if y_hi is None else y_hi
    for _ in range(tries):
        x, y = rng.randint(x_lo, max(x_lo, x_hi)), rng.randint(y_lo, max(y_lo, y_hi))
        if all(x + w + 6 < a or a + aw + 6 < x or y + h + 6 < b or b + bh + 6 < y for a, b, aw, bh in taken):
            taken.append((x, y, w, h))
            return x, y
    return None


# =======================================================================================
# faces
# =======================================================================================

BLOCK_FEATURES = ("windows", "vents", "hatch", "porthole", "pipe", "scribble", "label", "hazard", "duct",
                  "bolts", "lamp", "ladder", "dial", "conduit")


def block_feature(c, rng, taken, feat):
    sizes = {"windows": (N, 46), "vents": (48, 54), "hatch": (52, 64), "porthole": (44, 44), "pipe": (22, 200),
             "scribble": (46, 26), "label": (38, 18), "hazard": (52, 24), "duct": (N, 18), "bolts": (30, 12),
             "lamp": (16, 24), "ladder": (20, 96), "dial": (22, 22), "conduit": (60, 40)}
    w, h = sizes[feat]
    full = feat in ("windows", "duct")
    pos = free_box(rng, taken, w, h, 0 if full else 6, 0 if full else None, 20)
    if pos is None:
        return
    x, y = pos
    if feat == "windows":
        window_row(c, rng, y)
    elif feat == "vents":
        vents(c, rng, x, y, rng.randint(4, 6))
    elif feat == "hatch":
        hatch(c, rng, x + 3, y)
    elif feat == "porthole":
        porthole(c, rng, x + 22, y + 22, rng.choice((16, 20, 22)))
    elif feat == "pipe":
        pipe(c, rng, x, rng.randint(0, 24), rng.randint(150, 250))
    elif feat == "scribble":
        scribbles(c, rng, x, y)
    elif feat == "label":
        label(c, rng, x, y)
    elif feat == "hazard":
        hazard(c, rng, x, y)
    elif feat == "duct":
        duct(c, rng, y)
    elif feat == "bolts":
        bolts(c, x, y)
    elif feat == "lamp":
        lamp(c, rng, x + 8, y + 14)
    elif feat == "ladder":
        ladder(c, rng, x, y, y + 90)
    elif feat == "dial":
        dial(c, rng, x + 11, y + 11)
    else:
        conduit(c, rng, x, y + 20)


def block_face(c: Canvas, rng: random.Random, dens: int) -> None:
    """A machine / building block of 128 units: plate joints and tinted plates, rivets, vents, hatch,
    windows, pipes, ducts, ladders, labels, hazard marks, lamps."""
    # roof edge
    if rng.random() < (0.4, 0.55, 0.7)[dens]:
        c.fill(0, 0, N - 1, 11)
        c.hline(0, N - 1, 12, "c")
    # horizontal plate joints, not always across the whole face; plates between them may be tinted
    ys = sorted(rng.sample(range(50, 210), (2, 3, 4)[dens]))
    ys = [y for i, y in enumerate(ys) if i == 0 or y - ys[i - 1] > 34]
    seams = []
    for i, y in enumerate(ys):
        x0 = 0 if rng.random() < 0.7 else rng.randint(20, 80)
        x1 = N - 1 if rng.random() < 0.7 else rng.randint(170, 235)
        y_next = ys[i + 1] if i + 1 < len(ys) else min(N - 1, y + rng.randint(60, 110))
        splits = sorted(rng.sample(range(26, 230), rng.randint(0, (1, 2, 3)[dens])))
        plates = list(zip([0] + splits, splits + [N]))
        for a, b in plates:
            if rng.random() < (0.22, 0.3, 0.38)[dens]:
                c.fill(a + 2, y + 2, b - 1, y_next - 1)
        seams.append((y, x0, x1, splits, y_next))
    for y, x0, x1, splits, y_next in seams:
        c.hline(x0, x1, y, "c")
        if rng.random() < (0.4, 0.6, 0.8)[dens]:
            rivets(c, y + 6, x0 + 8, x1 - 4, rng.choice((20, 24, 28)), rng.randint(0, 8))
        for sx in splits:
            c.vline(sx, y + 1, y_next - 1, "c")
    if rng.random() < 0.5:
        c.vline(0, 0, N - 1, "c")
    taken: list = []
    n_feat = (4, 6, 9)[dens] + rng.choice((0, 0, 1))
    pool = list(BLOCK_FEATURES)
    for _ in range(n_feat):
        block_feature(c, rng, taken, rng.choice(pool))
    # weathering
    for _ in range(rng.choice((1, 1, 2)) + dens):
        if rng.random() < 0.5:
            stain(c, rng, rng.randint(20, 236), rng.randint(30, 230), rng.randint(12, 34))
        else:
            drip(c, rng, rng.randint(12, 244), rng.randint(0, 20), rng.randint(40, 120))
    if rng.random() < (0.4, 0.7, 0.9)[dens]:
        chip(c, rng, rng.choice((rng.randint(10, 40), rng.randint(216, 246))), rng.randint(150, 240))
    for _ in range((0, 1, 3)[dens]):
        crack(c, rng, rng.randint(30, 226), rng.randint(40, 220), rng.randint(26, 54))


WALL_FEATURES = ("slit", "grate", "plaque", "stain", "crack", "scribble", "lamp", "bolts", "vent")


def wall_face(c: Canvas, rng: random.Random, dens: int, kind: str) -> None:
    """A wall of 64 units (rows 0..127 show): a coping band and large ashlar blocks."""
    cap = rng.choice((14, 16, 20))
    c.fill(0, 0, N - 1, cap - 1)
    c.hline(0, N - 1, cap, "c")
    if rng.random() < 0.6:
        for x in range(rng.randint(30, 80), N - 20, rng.randint(70, 110)):
            c.vline(x, 0, cap - 1, "c")
    courses = [cap, cap + rng.randint(50, 58), 127]
    if dens == 2 or (dens == 1 and rng.random() < 0.3):
        courses = [cap, cap + 28, cap + 58, 127]
    for i in range(len(courses) - 1):
        y0, y1 = courses[i], courses[i + 1]
        if i > 0:
            c.hline(0, N - 1, y0, "c")
        x = rng.randint(30, 110) if i % 2 else rng.randint(50, 140)
        blocks = [0]
        while x < N - 24:
            blocks.append(x)
            x += rng.randint(60, 130)
        for bx in blocks[1:]:
            c.vline(bx, y0 + 1, y1 - 1, "c")
        for a, b in zip(blocks, blocks[1:] + [N]):
            if rng.random() < (0.2, 0.28, 0.35)[dens]:
                c.fill(a + 2, y0 + 2, b - 1, y1 - 2)
            if rng.random() < (0.2, 0.35, 0.5)[dens] and b - a > 40:
                rivets(c, y0 + 6, a + 8, b - 6, 24)
    c.hline(0, N - 1, 126, "c")
    if rng.random() < 0.5:
        c.vline(0, cap, 127, "c")
    taken: list = []
    wanted = [kind] if kind in ("slit", "grate") else []
    wanted += [rng.choice(WALL_FEATURES) for _ in range((3, 4, 6)[dens])]
    for feat in wanted:
        if feat == "slit":
            pos = free_box(rng, taken, 16, 40, 10, 230, cap + 8, cap + 12)
            if pos:
                x, y = pos
                c.fill(x + 1, y + 1, x + 12, y + 38)
                c.rect(x, y, x + 13, y + 39, "c")
        elif feat == "grate":
            pos = free_box(rng, taken, 62, 36, 10, 180, cap + 6, cap + 14)
            if pos:
                x, y = pos
                c.fill(x + 1, y + 1, x + 59, y + 33)
                c.rect(x, y, x + 60, y + 34, "f")
                for gx in range(x + 8, x + 58, 8):
                    c.vline(gx, y + 2, y + 32, "f")
        elif feat == "plaque":
            pos = free_box(rng, taken, 40, 26, 10, 200, cap + 6, 90)
            if pos:
                label(c, rng, pos[0], pos[1], 36, 20)
        elif feat == "stain":
            stain(c, rng, rng.randint(20, 236), rng.randint(cap + 10, 118), rng.randint(8, 22))
        elif feat == "crack":
            crack(c, rng, rng.randint(20, 236), rng.randint(cap + 6, 110), rng.randint(18, 44))
        elif feat == "scribble":
            pos = free_box(rng, taken, 44, 24, 10, 200, cap + 6, 96)
            if pos:
                scribbles(c, rng, pos[0], pos[1], 40, 18)
        elif feat == "lamp":
            pos = free_box(rng, taken, 16, 24, 10, 230, cap + 6, 90)
            if pos:
                lamp(c, rng, pos[0] + 8, pos[1] + 14)
        elif feat == "bolts":
            pos = free_box(rng, taken, 30, 12, 10, 220, cap + 6, 100)
            if pos:
                bolts(c, pos[0], pos[1])
        else:
            pos = free_box(rng, taken, 44, 30, 10, 200, cap + 6, 90)
            if pos:
                vents(c, rng, pos[0], pos[1], 3, 40)
    if dens >= 1:
        rivets(c, cap + 5, rng.randint(6, 20), N - 4, rng.choice((24, 32)))


def tower_face(c: Canvas, rng: random.Random, dens: int, band_cols) -> None:
    """A tower shaft (147 units; the 38 top rows come round again at the foot: a plinth)."""
    # cornice rows 0..37, seen again as plinth
    c.fill(0, 0, N - 1, 9)
    c.hline(0, N - 1, 10, "c")
    c.hline(0, N - 1, 30, "f")
    for x in range(rng.randint(10, 30), N - 6, rng.choice((28, 36))):
        c.vline(x, 12, 28, "f")                                            # cornice teeth
    # bands (their own colour: painted as flat rows)
    bands = sorted(rng.sample((66, 104, 148), rng.choice((1, 2)) if dens < 2 else 3))
    for b in bands:
        for y in range(b, b + 16):
            for x in range(N):
                if c.get(x, y) == c.base:
                    c.g[y][x] = band_cols
    taken = [(0, b - 4, N, 24) for b in bands] + [(0, 0, N, 40), (0, 200, N, 56)]
    # slits and windows
    for _ in range((2, 3, 5)[dens]):
        h = rng.choice((26, 34, 40))
        pos = free_box(rng, taken, 14, h, 12, 230, 44, 140)
        if pos:
            x, y = pos
            c.fill(x + 1, y + 1, x + 12, y + h - 1)
            c.rect(x, y, x + 13, y + h, "c")
    for _ in range((1, 2, 4)[dens]):
        feat = rng.choice(("label", "lamp", "bolts", "dial", "scribble", "ladder"))
        sizes = {"label": (38, 18), "lamp": (16, 24), "bolts": (30, 12), "dial": (22, 22), "scribble": (46, 26), "ladder": (20, 70)}
        w, h = sizes[feat]
        pos = free_box(rng, taken, w, h, 10, 230 - w, 44, 140)
        if pos:
            x, y = pos
            {"label": lambda: label(c, rng, x, y), "lamp": lambda: lamp(c, rng, x + 8, y + 14),
             "bolts": lambda: bolts(c, x, y), "dial": lambda: dial(c, rng, x + 11, y + 11),
             "scribble": lambda: scribbles(c, rng, x, y), "ladder": lambda: ladder(c, rng, x, y, y + 66)}[feat]()
    # seams
    for y in rng.sample(range(40, 150), 3):
        if not any(b - 6 < y < b + 22 for b in bands):
            c.hline(0, N - 1, y, "f")
    # the door / hatch at the foot (rows up to ~238)
    dw = rng.choice((56, 64, 72))
    dh = rng.choice((70, 80, 88))
    dx = (N - dw) // 2 + rng.choice((-30, 0, 0, 30))
    dy = 238 - dh
    c.clear(dx - 8, dy - 8, dx + dw + 8, 244)
    c.fill(dx + 1, dy + 1, dx + dw - 1, dy + dh - 1)
    c.rect(dx, dy, dx + dw, dy + dh, "c")
    c.rect(dx - 5, dy - 5, dx + dw + 5, 242, "f")                          # frame
    c.vline(dx + dw // 2, dy + 2, dy + dh - 2, "f")
    c.ring(dx + dw // 2 - 8, dy + dh // 2, 3, "f")
    c.ring(dx + dw // 2 + 8, dy + dh // 2, 3, "f")
    if dens >= 1:
        rivets(c, 24, 6, N - 4, 28)
    for _ in range(dens + 1):
        stain(c, rng, rng.randint(20, 236), rng.randint(60, 190), rng.randint(10, 26))
    if dens == 2:
        crack(c, rng, rng.randint(30, 226), rng.randint(60, 150), 40)


def plain_face(c: Canvas) -> None:
    pass


# =======================================================================================
# floors and tops (flats: one per cell, row 0 north)
# =======================================================================================

def drain(c, rng, x, y):
    """A gutter grating: a short slotted strip."""
    w, h = rng.choice((56, 64)), 16
    c.clear(x - 2, y - 2, x + w + 2, y + h + 2)
    c.fill(x + 1, y + 1, x + w - 1, y + h - 1)
    c.rect(x, y, x + w, y + h, "c")
    for gx in range(x + 7, x + w - 3, 7):
        c.vline(gx, y + 3, y + h - 3, "f")


def _split(rng, rect, depth, leaves, lines):
    """Guillotine plates: split a rectangle at a random place, remember the joint, recurse."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if depth == 0 or (w < 80 and h < 80):
        leaves.append(rect)
        return
    if (w >= h and w >= 80) or h < 80:
        x = x0 + rng.randint(int(w * 0.3), int(w * 0.7))
        lines.append(("v", x, y0, y1))
        parts = ((x0, y0, x, y1), (x, y0, x1, y1))
    else:
        y = y0 + rng.randint(int(h * 0.3), int(h * 0.7))
        lines.append(("h", y, x0, x1))
        parts = ((x0, y0, x1, y), (x0, y, x1, y1))
    for p in parts:
        if rng.random() < 0.75:
            _split(rng, p, depth - 1, leaves, lines)
        else:
            leaves.append(p)


def ground_flat(c: Canvas, rng: random.Random, dens: int, edges: int) -> None:
    """The ground of one cell. `edges`: 1 = a joint on the west edge, 2 = on the south edge."""
    leaves: list = []
    lines: list = []
    _split(rng, (0, 0, N - 1, N - 1), (2, 3, 3)[dens], leaves, lines)
    for x0, y0, x1, y1 in leaves:                      # some plates a little darker, a few lighter
        r = rng.random()
        if r < (0.2, 0.3, 0.4)[dens]:
            c.fill(x0 + 1, y0 + 1, x1 - 1, y1 - 1, c.alt)
        elif r > 0.955:
            c.fill(x0 + 1, y0 + 1, x1 - 1, y1 - 1, c.alt2)
    if edges & 1:
        c.vline(0, 0, N - 1, "c")
    if edges & 2:
        c.hline(0, N - 1, N - 1, "c")
    for kind, pos, a0, a1 in lines:
        if kind == "v":
            c.vline(pos, a0 + 1, a1 - 1, "c")
        else:
            c.hline(a0 + 1, a1 - 1, pos, "c")
    for _ in range((1, 2, 3)[dens] + rng.choice((0, 1))):
        stain(c, rng, rng.randint(20, 236), rng.randint(20, 236), rng.randint(14, 40))
    # a cover (round) or a hatch (square)
    pick = rng.random()
    if (dens >= 1 and pick < 0.4) or (dens == 0 and pick < 0.2):
        cx, cy, r = rng.randint(50, 206), rng.randint(50, 206), rng.choice((18, 22, 26))
        c.clear(cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3)
        c.disc(cx, cy, r, c.alt)
        c.ring(cx, cy, r, "c")
        c.ring(cx, cy, r - 6, "f")
        for k in range(-r + 9, r - 8, 7):
            half = int(math.sqrt(max(0, (r - 8) ** 2 - k * k)))
            c.hline(cx - half, cx + half, cy + k, "f")
    elif dens >= 1 and pick < 0.65:
        x, y = rng.randint(30, 170), rng.randint(30, 170)
        w, h = rng.choice((44, 52, 60)), rng.choice((36, 44))
        c.clear(x - 2, y - 2, x + w + 2, y + h + 2)
        c.fill(x + 1, y + 1, x + w - 1, y + h - 1)
        c.rect(x, y, x + w, y + h, "c")
        c.line(x + 4, y + 4, x + w - 4, y + h - 4, "f")
        c.line(x + w - 4, y + 4, x + 4, y + h - 4, "f")
    # cracks
    for _ in range((1, 2, 4)[dens]):
        crack(c, rng, rng.randint(20, 236), rng.randint(20, 236), rng.randint(24, 64))
    # little things: scraps of paper, rubble, pebbles
    for _ in range((4, 9, 16)[dens] + rng.choice((0, 1, 2))):
        x, y = rng.randint(12, 236), rng.randint(12, 236)
        w, h = rng.randint(14, 28), rng.randint(9, 18)
        r = rng.random()
        if r < 0.5:
            pts = [(x, y), (x + w, y + rng.randint(-3, 4)), (x + w + rng.randint(-3, 3), y + h), (x + rng.randint(-3, 4), y + h)]
            c.poly(pts, c.alt2_s)
            for a, b in zip(pts, pts[1:] + pts[:1]):
                c.line(a[0], a[1], b[0], b[1], "f")
            if rng.random() < 0.6:
                c.hline(x + 3, x + w - 4, y + h // 2, "f")
        elif r < 0.8:
            c.blob(rng, x, y, rng.randint(3, 7), 1.0, c.alt_s)
            c.ring(x, y, rng.randint(3, 6), "f")
        else:
            for _k in range(rng.randint(2, 4)):
                c.dot(x + rng.randint(-8, 8), y + rng.randint(-6, 6), 2)
    if dens >= 1:
        scribbles(c, rng, rng.randint(30, 180), rng.randint(30, 200), 44, 20)
    for _ in range((0, 1, 2)[dens]):
        drain(c, rng, rng.randint(30, 190), rng.randint(30, 210))


def top_block(c: Canvas, rng: random.Random, style: str, dens: int) -> None:
    """The top of a cell: lid, grating, plate cross, vents."""
    m = rng.choice((14, 18, 22))
    if style == "lid":
        c.fill(m + 1, m + 1, N - 1 - m, N - 1 - m)
        c.rect(m, m, N - 1 - m, N - 1 - m, "c")
        r = rng.choice((38, 46, 54))
        c.clear(128 - r - 6, 128 - r - 6, 128 + r + 6, 128 + r + 6)
        c.fill(m + 1, m + 1, N - 1 - m, N - 1 - m)
        c.disc(128, 128, r)
        c.ring(128, 128, r, "c")
        c.ring(128, 128, r - 9, "f")
        c.hline(128 - r + 12, 128 + r - 12, 128, "f")
        c.vline(128, 128 - r + 12, 128 + r - 12, "f")
        for sx in (-1, 1):
            for sy in (-1, 1):
                c.dot(128 + sx * (128 - m - 12) - 1, 128 + sy * (128 - m - 12) - 1, 2)
    elif style == "grate":
        c.rect(m, m, N - 1 - m, N - 1 - m, "c")
        step = rng.choice((12, 14, 16))
        for x in range(m + step, N - m - 4, step):
            c.vline(x, m + 3, N - m - 4, "f")
        for y in (rng.randint(80, 100), rng.randint(150, 175)):
            c.hline(m + 1, N - 2 - m, y, "c")
    elif style == "cross":
        a, b = rng.randint(100, 156), rng.randint(100, 156)
        c.fill(0, 0, a, b)
        c.fill(a + 1, b + 1, N - 1, N - 1)
        c.vline(a, m, N - 1 - m, "c")
        c.hline(m, N - 1 - m, b, "c")
        rivets(c, m + 6, m + 8, N - m - 6, 36)
        rivets(c, N - m - 8, m + 8, N - m - 6, 36, 12)
    elif style == "vents":
        c.rect(m, m, N - 1 - m, N - 1 - m, "c")
        for k in range(2):
            vents(c, rng, rng.randint(30, 60) + k * 100, rng.randint(40, 70) + k * 80, 5, 70)
        c.hline(m, N - 1 - m, 128, "f")
    elif style == "hatch":
        x, y = rng.randint(40, 100), rng.randint(40, 110)
        c.fill(x + 1, y + 1, x + 110, y + 90)
        c.rect(x, y, x + 111, y + 91, "c")
        c.rect(x + 12, y + 12, x + 99, y + 79, "f")
        c.ring(x + 55, y + 45, 8, "f")
        for k in range(rng.randint(2, 4)):
            stain(c, rng, rng.randint(30, 226), rng.randint(130, 230), rng.randint(8, 20))
    else:   # calm
        c.hline(0, N - 1, rng.randint(80, 176), "c")
        rivets(c, 30, 20, N - 10, 40)
        stain(c, rng, rng.randint(40, 216), rng.randint(40, 216), rng.randint(14, 30))
    if dens:
        for _ in range(dens):
            crack(c, rng, rng.randint(24, 232), rng.randint(24, 232), rng.randint(20, 44))


def top_wall(c: Canvas, rng: random.Random, dens: int) -> None:
    """The top of a wall: coping slabs in two rows."""
    y = rng.randint(100, 156)
    c.hline(0, N - 1, y, "c")
    for ya, yb in ((0, y), (y + 1, N - 1)):
        x = rng.randint(40, 120)
        xs = [0]
        while x < N - 30:
            xs.append(x)
            x += rng.randint(80, 150)
        for bx in xs[1:]:
            c.vline(bx, ya + 1, yb - 1, "c")
        for a, b in zip(xs, xs[1:] + [N]):
            if rng.random() < 0.3:
                c.fill(a + 2, ya + 2, b - 2, yb - 2)
    for _ in range(dens + rng.choice((0, 1))):
        crack(c, rng, rng.randint(30, 226), rng.randint(30, 226), rng.randint(20, 46))
    if dens:
        rivets(c, 20, 20, N - 10, 36)


def top_tower(c: Canvas, rng: random.Random, style: str, dens: int) -> None:
    """The top of a tower: a round platform, a hatch, a cross of beams."""
    c.disc(128, 128, 104)
    c.ring(128, 128, 104, "c")
    c.ring(128, 128, 88, "f")
    if style == "hatch":
        c.paint_disc(128, 128, 34, c.base)
        c.ring(128, 128, 34, "c")
        c.ring(128, 128, 24, "f")
        c.hline(104, 152, 128, "f")
        c.vline(128, 104, 152, "f")
    elif style == "cross":
        c.hline(24, 232, 128, "c")
        c.vline(128, 24, 232, "c")
        c.ring(128, 128, 14, "c")
    elif style == "posts":
        for k in range(8):
            a = k * math.pi / 4
            x, y = int(128 + 96 * math.cos(a)), int(128 + 96 * math.sin(a))
            c.dot(x - 2, y - 2, 4)
        c.ring(128, 128, 30, "f")
    else:
        for k in range(rng.randint(3, 5)):
            stain(c, rng, rng.randint(70, 186), rng.randint(70, 186), rng.randint(8, 18))
        c.hline(60, 196, 128, "f")
    if dens:
        crack(c, rng, rng.randint(80, 170), rng.randint(80, 170), 40)


def top_own(c: Canvas, rng: random.Random, v: int) -> None:
    """The top of an own cell: the diamond in its frame in the middle (the same sign as on the sides),
    around it a little of the block family; nothing near the middle that the sign would have to clear."""
    if v == 0:
        c.rect(14, 14, N - 15, N - 15, "c")
        rivets(c, 24, 28, N - 20, 40)
    elif v == 1:
        c.hline(0, 70, 128, "c")
        c.hline(186, N - 1, 128, "c")
        rivets(c, 30, 20, N - 10, 36)
        stain(c, rng, 40, 200, 24)
    elif v == 2:
        c.rect(22, 22, N - 23, N - 23, "c")
        for k in range(36, N - 30, 14):
            c.dot(k, 28, 2)
            c.dot(k, N - 31, 2)
    else:
        c.vline(128, 0, 62, "c")
        c.vline(128, 194, N - 1, "c")
        c.line(20, 20, 60, 60, "f")
        c.line(N - 21, N - 21, N - 61, N - 61, "f")
        rivets(c, N - 28, 24, N - 20, 36)
    emblem(c, rng, 128, 128, 52, clear=False)
