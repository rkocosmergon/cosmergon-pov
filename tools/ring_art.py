#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""The faces of the field's rim (COSMERGON.md, "The field's rim"): the plain stretch of the ring and the gold of a shaft.
Standard library only, deterministic. Used by tools/make_theme.py; the pictures are made of palette indices like every
face of tools/theme_art.py, in the colours of the role `wall` (the rim is built of the same stuff as a wall), the gold
in the colour of the bands.

A face is 256 x 256 texels over one cell edge of 128 units (4 m): 64 texels a metre, row 0 is the top of the rim, row
255 the floor. The bunk and the shaft are not drawn: they are recesses of the map (pov_control.c, a ceiling of their
own). What is drawn is what a recess is made of: the stuff of the rim, which is also the wall over a bunk's opening
(the top rows of the face) and its inside, and the gold of a shaft (its lintel, the top 19 units of the face, and the
walls inside it).
"""

from __future__ import annotations

import random

import theme_art as art

N = art.N


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


# ---- the gold frame of a shaft (the lintel above the opening and the side walls inside it): the colour of the bands

def gold_face(c: art.Canvas, band: int) -> None:
    """A face all in the colour of the bands: a bar at the top (the lintel is the top 19 units of it), a band of rivets, a
    joint at either edge, studs below. Drawn as one with the rim: the same strokes."""
    paint_rect(c, 0, 0, N - 1, N - 1, band)
    c.hline(0, N - 1, 16, "w")
    c.hline(0, N - 1, 34, "w")
    art.rivets(c, 8, 12, N - 8, 24)
    art.rivets(c, 25, 12, N - 8, 24)
    c.vline(0, 0, N - 1, "w")
    c.vline(N - 1, 0, N - 1, "w")
    for y in (80, 140, 200):
        c.hline(0, N - 1, y, "f")
        art.rivets(c, y + 10, 12, N - 8, 32)
