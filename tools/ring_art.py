#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""The faces of the field's rim (COSMERGON.md, "The field's rim"): the plain stretch of the ring, the bunk (alcove)
and the two halves of a shaft portal. Standard library only, deterministic. Used by tools/make_theme.py; the
pictures are made of palette indices like every face of tools/theme_art.py, in the colours of the role `wall`
(the ring is built of the same stuff as a wall; the palette has no index left for a role of its own), the
portal's frame in the colour of the bands (gold in every theme).

Geometry: a face is 256 x 256 texels over one cell edge of 128 units (4 m): 64 texels a metre, row 0 is the top
of the ring, row 255 the floor. All measures are the concept's (konzept-wand-kojen-schacht, 2.3 to 2.5), so the
picture of a bunk can be read against a Marauder of 1.75 m:
  - the ring is one storey high: 4 m = 256 rows;
  - a bunk is 2.2 m high and 2.2 m wide: 141 x 141 texels, in the middle of its cell, standing on the floor;
  - a shaft portal is 3.4 m high and two cells (8 m) wide, with a frame in the colour of the bands; it is drawn in two
    halves of one cell each, the first of them with the left edge of the frame, the second with the right one.
The bunk and the portal are DRAWN on the flat face of the ring (the map keeps one sector a cell): depth is
a back panel, lines running to its corners, and the darker stage inside.
"""

from __future__ import annotations

import random

import theme_art as art

N = art.N
TEXELS_PER_M = 64
BUNK = round(2.2 * TEXELS_PER_M)            # 141: height and width of the opening
PORTAL_H = round(3.4 * TEXELS_PER_M)        # 218
FLOOR_ROW = N - 1


# ---- painting (a fill that covers whatever is there; the lines are drawn afterwards)

def paint_rect(c, x0, y0, x1, y1, idx):
    for y in range(max(0, y0), min(N - 1, y1) + 1):
        row = c.g[y]
        for x in range(max(0, x0), min(N - 1, x1) + 1):
            row[x] = idx


def paint_poly(c, pts, idx):
    ys = [p[1] for p in pts]
    for y in range(max(0, int(min(ys))), min(N - 1, int(max(ys))) + 1):
        xs = []
        for i in range(len(pts)):
            (xa, ya), (xb, yb) = pts[i], pts[(i + 1) % len(pts)]
            if (ya <= y + 0.5 < yb) or (yb <= y + 0.5 < ya):
                xs.append(xa + (y + 0.5 - ya) * (xb - xa) / (yb - ya))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            for x in range(max(0, int(xs[k] + 0.5)), min(N - 1, int(xs[k + 1] - 0.5)) + 1):
                c.g[y][x] = idx


class Shifted:
    """A canvas seen through a window that starts at x = dx of a wider picture: the drawing calls keep the coordinates
    of the wide picture (the halves of a portal are one drawing)."""

    def __init__(self, c, dx):
        self.c, self.dx = c, dx

    def paint_rect(self, x0, y0, x1, y1, idx):
        paint_rect(self.c, x0 - self.dx, y0, x1 - self.dx, y1, idx)

    def paint_poly(self, pts, idx):
        paint_poly(self.c, [(x - self.dx, y) for x, y in pts], idx)

    def hline(self, x0, x1, y, kind="c"):
        self.c.hline(x0 - self.dx, x1 - self.dx, y, kind)

    def vline(self, x, y0, y1, kind="c"):
        self.c.vline(x - self.dx, y0, y1, kind)

    def line(self, x0, y0, x1, y1, kind="f"):
        self.c.line(x0 - self.dx, y0, x1 - self.dx, y1, kind)

    def polyline(self, pts, kind="f"):
        self.c.polyline([(x - self.dx, y) for x, y in pts], kind)

    def rect(self, x0, y0, x1, y1, kind="c"):
        self.c.rect(x0 - self.dx, y0, x1 - self.dx, y1, kind)

    def dot(self, x, y, size=2):
        self.c.dot(x - self.dx, y, size)

    def disc(self, cx, cy, r, idx):
        self.c.paint_disc(cx - self.dx, cy, r, idx)

    def ring(self, cx, cy, r, kind="c"):
        self.c.ring(cx - self.dx, cy, r, kind)


# ---- the plain stretch

def ring_frame(c, rng, dens):
    """What every face of the ring has: a coping at the top, a plinth at the foot, tall panels between, joints and rivets."""
    c.fill(0, 0, N - 1, 15)
    c.hline(0, N - 1, 16, "w")
    for x in range(rng.randint(14, 40), N - 6, rng.choice((32, 40))):
        c.vline(x, 4, 12, "c")                                     # coping teeth
    c.fill(0, 236, N - 1, N - 1)
    c.hline(0, N - 1, 236, "w")
    for x in range(rng.randint(10, 30), N - 6, rng.choice((44, 56))):
        c.vline(x, 244, 252, "f")                                  # plinth slots
    # the panels: two courses of tall plates between coping and plinth, the upright joints staggered
    mid = rng.randint(112, 140)
    for y in (mid,) if dens == 0 else (mid - 30, mid + 34):
        c.hline(0, N - 1, y, "w")
    bounds = [17] + sorted({mid} if dens == 0 else {mid - 30, mid + 34}) + [236]
    for i in range(len(bounds) - 1):
        y0, y1 = bounds[i], bounds[i + 1]
        x = rng.randint(50, 110) + 40 * (i % 2)
        joints = []
        while x < N - 40:
            joints.append(x)
            x += rng.randint(86, 130)
        for jx in joints:
            c.vline(jx, y0 + 1, y1 - 1, "w")
        for a, b in zip([0] + joints, joints + [N]):
            if rng.random() < (0.2, 0.3, 0.4)[dens]:
                c.fill(a + 2, y0 + 2, b - 1, y1 - 2)
            if rng.random() < (0.4, 0.55, 0.7)[dens] and b - a > 50:
                art.rivets(c, y0 + 7, a + 9, b - 6, 24)
    c.vline(0, 17, 235, "w")


RING_FEATURES = ("label", "vents", "lamp", "grille", "hatch", "pipe", "ladder", "dial", "hazard", "bolts", "scribble",
                 "plaque", "stain", "crack", "conduit")


def ring_feature(c, rng, taken, feat):
    sizes = {"label": (38, 18), "vents": (48, 54), "lamp": (16, 24), "grille": (42, 42), "hatch": (52, 64),
             "pipe": (22, 170), "ladder": (20, 96), "dial": (22, 22), "hazard": (52, 24), "bolts": (30, 12),
             "scribble": (46, 26), "plaque": (40, 26), "stain": (0, 0), "crack": (0, 0), "conduit": (60, 40)}
    w, h = sizes[feat]
    if feat == "stain":
        art.stain(c, rng, rng.randint(20, 236), rng.randint(40, 226), rng.randint(10, 28))
        return
    if feat == "crack":
        art.crack(c, rng, rng.randint(20, 236), rng.randint(40, 200), rng.randint(20, 50))
        return
    pos = art.free_box(rng, taken, w, h, 6, None, 24, 228 - h)
    if pos is None:
        return
    x, y = pos
    if feat == "label":
        art.label(c, rng, x, y)
    elif feat == "vents":
        art.vents(c, rng, x, y, rng.randint(3, 5))
    elif feat == "lamp":
        art.lamp(c, rng, x + 8, y + 14)
    elif feat == "grille":
        art.grille(c, rng, x, y)
    elif feat == "hatch":
        art.hatch(c, rng, x + 3, y)
    elif feat == "pipe":
        art.pipe(c, rng, x, y, y + rng.randint(120, 168))
    elif feat == "ladder":
        art.ladder(c, rng, x, y, y + 90)
    elif feat == "dial":
        art.dial(c, rng, x + 11, y + 11)
    elif feat == "hazard":
        art.hazard(c, rng, x, y)
    elif feat == "bolts":
        art.bolts(c, x, y)
    elif feat in ("scribble", "plaque"):
        art.scribbles(c, rng, x, y, 40, 18) if feat == "scribble" else art.label(c, rng, x, y, 36, 20)
    else:
        art.conduit(c, rng, x, y + 20)


def ring_face(c: art.Canvas, rng: random.Random, dens: int) -> None:
    """A stretch of the ring: coping, plinth, tall panels, and a few parts (a lamp, a hatch, vents, a pipe, labels)."""
    ring_frame(c, rng, dens)
    taken: list = [(0, 0, N, 22), (0, 230, N, 26)]
    for _ in range((4, 6, 8)[dens]):
        ring_feature(c, rng, taken, rng.choice(RING_FEATURES))
    for _ in range(dens + 1):
        art.stain(c, rng, rng.randint(20, 236), rng.randint(60, 226), rng.randint(10, 26))
    if dens == 2:
        art.crack(c, rng, rng.randint(30, 226), rng.randint(60, 200), 44)


# ---- the bunk

def recess(c, x0, y0, x1, y1, depth, floor=True):
    """A hollow drawn on the flat face as in a comic: the opening in the dark stage, a lighter back panel inside it, a
    floor, and lines from the corners of the opening to the corners of the back panel. Returns the back panel."""
    paint_rect(c, x0, y0, x1, y1, c.alt)
    bx0, bx1, by0 = x0 + depth, x1 - depth, y0 + depth
    by1 = y1 - depth // 2
    paint_rect(c, bx0, by0, bx1, by1, c.base)
    if floor:
        paint_poly(c, [(x0, y1), (x1, y1), (bx1, by1), (bx0, by1)], c.base)       # the floor is the lightest part
    c.rect(x0, y0, x1, y1, "w")
    c.rect(bx0, by0, bx1, by1, "w")
    for (px, py), (qx, qy) in (((x0, y0), (bx0, by0)), ((x1, y0), (bx1, by0)), ((x0, y1), (bx0, by1)), ((x1, y1), (bx1, by1))):
        c.line(px, py, qx, qy, "w")           # wide strokes: they stay in the picture far away (make_theme.FOLD_Q)
    return bx0, by0, bx1, by1


def alcove_face(c: art.Canvas, rng: random.Random, variant: int, band: int) -> None:
    """A stretch of the ring with a bunk of 2.2 m x 2.2 m in the middle of the cell, on the floor. Variants: 0 a bed,
    1 a bed and a lamp, 2 a bed behind a curtain, 3 a shelf and a bench."""
    ring_frame(c, rng, 0)
    taken: list = [(0, 0, N, 22), (0, 100, N, 156)]
    for _ in range(2 + variant % 2):
        ring_feature(c, rng, taken, rng.choice(("label", "lamp", "bolts", "dial", "plaque", "scribble")))
    x0 = (N - BUNK) // 2
    x1 = x0 + BUNK - 1
    y1 = FLOOR_ROW - 1
    y0 = y1 - BUNK + 1
    c.clear(x0 - 12, y0 - 12, x1 + 12, N - 1)                   # no plinth, no part in front of the hollow
    bx0, by0, bx1, by1 = recess(c, x0, y0, x1, y1, 24)
    if variant in (0, 1, 2):                                    # the bed: a mattress along the back, a pillow
        paint_rect(c, bx0 + 4, by1 - 22, bx1 - 4, by1 - 2, c.alt)
        c.rect(bx0 + 4, by1 - 22, bx1 - 4, by1 - 2, "c")
        paint_rect(c, bx0 + 8, by1 - 18, bx0 + 34, by1 - 7, c.base)
        c.rect(bx0 + 8, by1 - 18, bx0 + 34, by1 - 7, "f")
    if variant == 1:                                            # a lamp in the colour of the bands under the lintel
        c.paint_disc((x0 + x1) // 2, y0 + 16, 6, band)
        c.ring((x0 + x1) // 2, y0 + 16, 6, "f")
    if variant == 2:                                            # a curtain over the right third
        for x in range(bx0 + (bx1 - bx0) * 2 // 3, bx1, 6):
            c.vline(x, by0 + 2, by1 - 2, "f")
        c.hline(bx0 + (bx1 - bx0) * 2 // 3, bx1, by0 + 6, "c")
    if variant == 3:                                            # a shelf on the back wall, a bench on the floor
        c.hline(bx0 + 8, bx1 - 8, by0 + 30, "w")
        for x in range(bx0 + 14, bx1 - 10, 28):
            c.vline(x, by0 + 30, by0 + 42, "f")
        paint_rect(c, bx0 + 12, by1 - 16, bx1 - 12, by1 - 4, c.alt)
        c.rect(bx0 + 12, by1 - 16, bx1 - 12, by1 - 4, "c")
    c.rect(x0 - 5, y0 - 5, x1 + 5, y1 + 3, "f")                # the frame of the opening in the wall
    art.label(c, rng, (x0 + x1) // 2 - 19, y0 - 30, 38, 16)      # its number plate


# ---- the shaft portal

PORTAL_X0, PORTAL_X1 = 8, 2 * N - 9                # in the picture of both halves (512 wide)
FRAME = 14
PORTAL_Y0 = FLOOR_ROW - PORTAL_H + 1               # 38


def arrow(c, cx, y0, y1, up, band):
    """A fat arrow in the colour of the bands, outlined (up or down)."""
    hw, hh = 22, 26
    sw = 9
    if up:
        head = [(cx, y0), (cx + hw, y0 + hh), (cx - hw, y0 + hh)]
        shaft = (cx - sw, y0 + hh - 1, cx + sw, y1)
    else:
        head = [(cx, y1), (cx + hw, y1 - hh), (cx - hw, y1 - hh)]
        shaft = (cx - sw, y0, cx + sw, y1 - hh + 1)
    c.paint_poly(head, band)
    c.paint_rect(*shaft, band)
    c.polyline(head + [head[0]], "c")
    c.rect(*shaft, "c")


def portal_half(c: art.Canvas, half: int, band: int) -> None:
    """One cell of the two a portal fills (half 0: the left one, 1: the right one, as the viewer sees it): a coping,
    the frame in the colour of the bands, a dark hollow with a back panel, rails and an arrow up on the left and one
    down on the right."""
    rng = random.Random("cosmergon-pov/portal")
    ring_frame(c, rng, 0)
    s = Shifted(c, N * half)
    c.clear(0, 20, N - 1, N - 1)                                 # no plinth and no panel joints behind the portal
    c.hline(0, N - 1, 16, "w")
    x0, x1, y0, y1 = PORTAL_X0, PORTAL_X1, PORTAL_Y0, FLOOR_ROW - 1
    # the frame: a lintel and two posts, a sill
    s.paint_rect(x0, y0, x1, y1, band)
    ix0, ix1, iy0, iy1 = x0 + FRAME, x1 - FRAME, y0 + FRAME, y1 - 8
    s.paint_rect(ix0, iy0, ix1, iy1, c.alt)
    # depth: a back panel and the lines to its corners; the floor of the hollow is the lightest part
    inset = 56
    bx0, bx1, by0, by1 = ix0 + inset, ix1 - inset, iy0 + inset // 2, iy1 - 14
    s.paint_rect(bx0, by0, bx1, by1, c.base)
    s.paint_poly([(ix0, iy1), (ix1, iy1), (bx1, by1), (bx0, by1)], c.base)
    s.rect(x0, y0, x1, y1, "w")
    s.rect(ix0, iy0, ix1, iy1, "c")
    s.rect(bx0, by0, bx1, by1, "w")
    for (px, py), (qx, qy) in (((ix0, iy0), (bx0, by0)), ((ix1, iy0), (bx1, by0)), ((ix0, iy1), (bx0, by1)),
                               ((ix1, iy1), (bx1, by1))):
        s.line(px, py, qx, qy, "w")
    # rails of the shaft, either side of the middle of the portal
    for rx in (N - 30, N + 30):
        s.vline(rx, by0 + 2, by1 - 2, "f")
    # the arrows, one in each half: up on the left, down on the right
    ay0, ay1 = by0 + 24, by1 - 26
    arrow(s, N // 2 + 8, ay0, ay1, True, band)
    arrow(s, N + N // 2 - 8, ay0, ay1, False, band)
