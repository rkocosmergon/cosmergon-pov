#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""The sky of the themes: clouds and stars, and the sun/moon arc. Standard library only, deterministic. Used by
tools/make_theme.py; the engine side is doomgeneric/pov_sky.c (the numbers are the same there, tests/test_sky.py
compares them).

The clouds are bodies in the WORLD (COSMERGON.md, "The sky"): upright, turned to the viewer, at world positions
(x, y, height of the base) on a periodic tile of PERIOD_M metres a side, in four layers of height. The drawing is a
perspective of the world: size and height in the picture follow the distance, the lower edge is a row of the
picture. A cloud is a sprite (a picture of the cloud, SPR_W x SPR_H texels, with three smaller copies for the far
ones), flat fill, one shade tone along the lower right edge; the outline is drawn by the engine's outline pass on
the finished picture.

Units: the engine's: 128 units are a cell = 4 m, so 32 units a metre.
"""

from __future__ import annotations

import functools
import math
import random
import struct

UNITS_PER_M = 32
PERIOD_M = 16000.0                     # the tile of clouds repeats every 16 km (the clouds around any place)
WIND_M_S = 4.0                         # to the east, every cloud alike (a light breeze: 14 km/h)
LAYERS_M = (450.0, 650.0, 900.0, 1250.0)    # height of the cloud bases above the lowest cube
N_CLOUDS = 220
SPR_W, SPR_H, SPR_MIPS = 1024, 320, 4
N_COMPLEX, N_SIMPLE = 5, 3             # shapes 0..4 have many bumps, 5..7 few (for the small, far clouds)
N_STARS = 240

# Time of day (minutes since midnight): the sun runs 06:00..19:00, the moon 19:00..06:00, both on the same
# arc: east at the rise, south at the middle, west at the set; the highest point is SKY_EL_MAX degrees (a
# higher body is never in the picture: the view has no pitch and a half angle of 26 degrees at most).
SUN_RISE, SUN_SET, MOON_SPAN = 360, 1140, 660
SKY_EL_MAX = 21.0
SUN_RADIUS, MOON_RADIUS = 4.5, 3.6            # angular radius in degrees


def body(minute: int) -> tuple[str, float, float, float]:
    """(kind, elevation, azimuth, angular radius), degrees. Azimuth: 0 east, -90 south, -180 west (angle of the
    engine's map: counter-clockwise from east)."""
    if SUN_RISE <= minute < SUN_SET:
        p = (minute - SUN_RISE) / (SUN_SET - SUN_RISE)
        kind, radius = "sun", SUN_RADIUS
    else:
        p = ((minute - SUN_SET) if minute >= SUN_SET else (minute + 1440 - SUN_SET)) / MOON_SPAN
        kind, radius = "moon", MOON_RADIUS
    return kind, SKY_EL_MAX * math.sin(math.pi * p), -180.0 * p, radius


def project(minute: int, view_deg: float, w: int, h: int):
    """Where the body lies in a picture of w x h points seen at angle view_deg: (x, y, radius) in points
    (a disc), or None when it is behind (|angle| >= 85 degrees)."""
    _kind, el, az, radius = body(minute)
    delta = math.remainder(math.radians(az - view_deg), 2 * math.pi)
    if abs(delta) >= math.radians(85):
        return None
    f = w / 2.0
    return (w / 2.0 - f * math.tan(delta), h / 2.0 - f * math.tan(math.radians(el)) / math.cos(delta),
            f * math.tan(math.radians(radius)))


def view_towards(minute: int) -> float:
    """The viewing angle (degrees, engine's convention) that puts the body of this minute in the middle."""
    return body(minute)[2] % 360.0



# ---- the cloud sprites

def _span(rows, y, x0, x1):
    if 0 <= y < SPR_H and x1 >= x0:
        rows[y] |= ((1 << (x1 - x0 + 1)) - 1) << max(0, x0)


def _disc(rows, cx, cy, r, floor_row):
    for y in range(max(floor_row, int(cy - r)), min(SPR_H, int(cy + r) + 1)):
        dx = math.sqrt(max(0.0, r * r - (y - cy) ** 2))
        _span(rows, y, int(round(cx - dx)), min(SPR_W - 1, int(round(cx + dx))))


def _bits(mask: int) -> bytes:
    """A mask of SPR_W bits as SPR_W bytes of 0 or 1 (bit i -> byte i)."""
    return bin(mask)[2:].zfill(SPR_W)[::-1].encode().translate(bytes.maketrans(b"01", b"\x00\x01"))


def _sprite(shape: int) -> bytes:
    """One cloud (column by column, row 0 is the flat base): bumps over a flat base, bigger in the middle.
    Shapes 0..4 have 5 to 9 bumps, 5..7 have 3 or 4 (the far clouds: a calm silhouette)."""
    rng = random.Random("cosmergon-pov/cloud/%d" % shape)
    n = (6, 7, 5, 8, 6, 3, 3, 4)[shape]
    width, base = 0.94 * SPR_W, 10
    gap = width / n                                    # the middle of a bump to the next
    r_max = min(0.9 * gap * (1.9 if n < 5 else 1.35), (SPR_H - base) / 1.62)
    rows = [0] * SPR_H
    for i in range(n):
        t = (i + 0.5) / n
        bell = 1.0 - (2 * t - 1) ** 2                  # the middle bumps are the big ones
        r = r_max * (0.50 + 0.50 * bell ** 0.8) * rng.uniform(0.80, 1.0)
        x = SPR_W / 2 - width / 2 + t * width
        _disc(rows, x, base + 0.62 * r, r, base)
    full = (1 << SPR_W) - 1
    out = []
    for y in range(SPR_H):
        d = max(1, int(0.075 * min(r_max * 1.6, SPR_H)))                # the shade is a band along the lower right edge
        below = rows[y - d] if y - d >= 0 else 0
        shade = rows[y] & ~(below >> d) & full
        fill = rows[y] & ~shade
        out.append((int.from_bytes(_bits(fill), "little") + 2 * int.from_bytes(_bits(shade), "little"))
                   .to_bytes(SPR_W, "little"))
    return b"".join(bytes(col) for col in zip(*out))


@functools.lru_cache(maxsize=1)
def sprite_lump() -> bytes:
    """Lump POVCLS: "POVC", version, shapes, mips, W, H; then per shape the mips from the full size down; a mip
    keeps every second column and row of the one above (nearest)."""
    out = bytearray(b"POVC" + struct.pack("<BBBBHH", 1, N_COMPLEX + N_SIMPLE, SPR_MIPS, 0, SPR_W, SPR_H))
    for shape in range(N_COMPLEX + N_SIMPLE):
        full = _sprite(shape)
        for m in range(SPR_MIPS):
            step, h = 1 << m, SPR_H >> m
            for c in range(0, SPR_W, step):
                out += full[c * SPR_H:(c + 1) * SPR_H:step][:h]
    return bytes(out)


# ---- the clouds in the world

def cloud_list() -> list[tuple[int, int, int, int, int]]:
    """(x, y, height of the base, width, shape) in units: 220 clouds on the periodic tile, in four layers (a
    cloud only where no other of its layer is), wider and bigger bodies higher up; small ones have the calm shapes."""
    rng = random.Random("cosmergon-pov/clouds")
    placed: list[list[tuple[float, float, float]]] = [[] for _ in LAYERS_M]
    out = []
    tries = 0
    while len(out) < N_CLOUDS and tries < 20000:
        tries += 1
        layer = len(out) % len(LAYERS_M)
        width = rng.uniform(250.0, 650.0) * (1.0 + 0.3 * layer)
        if rng.random() < 0.65:                  # most clouds stand over the cubes (the world's middle), the rest all round
            x, y = rng.gauss(0, 1800.0) % PERIOD_M, rng.gauss(0, 1800.0) % PERIOD_M
        else:
            x, y = rng.uniform(0, PERIOD_M), rng.uniform(0, PERIOD_M)
        if any(math.hypot(x - a, y - b) < 0.55 * (width + w) for a, b, w in placed[layer]):
            continue
        placed[layer].append((x, y, width))
        z = LAYERS_M[layer] + rng.gauss(0, 50.0)
        shape = rng.randrange(N_COMPLEX, N_COMPLEX + N_SIMPLE) if width < 330 else rng.randrange(N_COMPLEX)
        out.append((int(x * UNITS_PER_M), int(y * UNITS_PER_M), int(z * UNITS_PER_M), int(width * UNITS_PER_M), shape))
    return out


def world_lump(clouds=None) -> bytes:
    """Lump POVWLD: "POVW", version, the period (units), the wind (units a second), the count, then per cloud
    x, y, base height, width (int32 units) and the shape."""
    clouds = cloud_list() if clouds is None else clouds
    out = bytearray(b"POVW" + struct.pack("<BBBB", 1, 0, 0, 0))
    out += struct.pack("<iffi", int(PERIOD_M * UNITS_PER_M), WIND_M_S * UNITS_PER_M, 0.0, len(clouds))
    for x, y, z, w, shape in clouds:
        out += struct.pack("<iiiiBBBB", x, y, z, w, shape, 0, 0, 0)
    return bytes(out)


def stars_lump() -> bytes:
    """Lump POVSTR: "POVR", version, the count, then per star the azimuth (360 degrees / 65536) and the
    elevation (90 degrees / 65536, 2..60 degrees). Fixed to the world."""
    rng = random.Random("cosmergon-pov/stars")
    out = bytearray(b"POVR" + struct.pack("<BBBBi", 1, 0, 0, 0, N_STARS))
    for _ in range(N_STARS):
        out += struct.pack("<HH", rng.randrange(65536), int(rng.uniform(2.0, 60.0) / 90.0 * 65536))
    return bytes(out)


def eye(cube, level: int, dim: int, field_x: float, field_y: float, floor_eye: float):
    """World position (units) of the eye: the cube (grid position), the level of the field in it, the cube's
    dimension in cells, the position in the field (units from the cube's corner), the eye above the field plane."""
    step = 2.5 * dim * 128
    return (cube[0] * step + field_x, cube[1] * step + field_y, cube[2] * step + level * 128 + floor_eye)


def cloud_screen(cloud, seconds: float, eye_pos, view_deg: float, w: int, h: int):
    """(centre x, base row, width, height, depth) in points of a cloud as the engine draws it (nearest image on the
    tile), or None when it is behind the eye. Perspective: size = f * width / depth, f = w / 2."""
    x, y, z, width, _shape = cloud
    period = PERIOD_M * UNITS_PER_M
    dx = math.remainder(x + WIND_M_S * UNITS_PER_M * seconds - eye_pos[0], period)
    dy = math.remainder(y - eye_pos[1], period)
    th = math.radians(view_deg)
    depth = dx * math.cos(th) + dy * math.sin(th)
    lateral = dx * math.sin(th) - dy * math.cos(th)
    if depth <= 0:
        return None
    f = w / 2.0
    pw = f * width / depth
    return (w / 2.0 + f * lateral / depth, h / 2.0 - f * (z - eye_pos[2]) / depth, pw, pw * SPR_H / SPR_W, depth)
