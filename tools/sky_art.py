#!/usr/bin/env python3
"""The sky of the themes: the cloud layer with its stars, and the sun/moon arc. Standard library only,
deterministic. Used by tools/make_theme.py; the engine side is doomgeneric/pov_sky.c (the numbers below
are the same there, tests/test_sky.py compares them).

Layer POVCLD: SKY_W columns around the circle (column = azimuth, angle_t >> 20), SKY_H rows of
tan(elevation) * SKY_RPT (row 0 at the horizon). One byte a texel, stored column by column:
0 = empty, 1 = cloud, 2 = the cloud's shade, plus 16 where a star is (stars do not drift with the clouds).
Comic clouds: round bumps over a flat base, one flat fill, one shade tone along the lower right edge. The
outline around them is drawn by the engine's outline pass on the finished picture, so it has the weight of
the picture's own line at every size.
"""

from __future__ import annotations

import functools
import math
import random

SKY_W = 4096
SKY_H = 512
SKY_RPT = SKY_W / (2 * math.pi)       # texels per unit of tan(elevation): 1 texel a point at 1280 wide

# Time of day (minutes since midnight): the sun runs 06:00..19:00, the moon 19:00..06:00, both on the same
# arc: east at the rise, south at the middle, west at the set; the highest point is SKY_EL_MAX degrees (a
# higher body is never in the picture: the view has no pitch and a half angle of 26 degrees at most).
SUN_RISE, SUN_SET, MOON_SPAN = 360, 1140, 660
SKY_EL_MAX = 21.0
SUN_RADIUS, MOON_RADIUS = 4.5, 3.6            # angular radius in degrees
DRIFT_DEG_PER_S = 0.25


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


def drift_points(seconds: float, w: int) -> int:
    """Whole points the clouds have moved after `seconds` on a picture w points wide (as the engine)."""
    cols = seconds * 1000.0 * (2844.4 / 1.0e6)
    return int(math.floor(cols * 2 * math.pi * (w / 2.0) / SKY_W))


# ---- the cloud layer

def _row_span(mask_rows, y, x0, x1):
    if 0 <= y < SKY_H and x1 >= x0:
        mask_rows[y] |= ((1 << (x1 - x0 + 1)) - 1) << x0


def _disc(mask_rows, cx, cy, r, floor_row):
    for y in range(max(floor_row, int(cy - r)), min(SKY_H, int(cy + r) + 1)):
        dx = math.sqrt(max(0.0, r * r - (y - cy) ** 2))
        _row_span(mask_rows, y, int(round(cx - dx)), int(round(cx + dx)))


def _cloud(rows, rng, cx, y0, width):
    """One cloud of the given width in columns over a flat base at row y0: bumps, bigger in the middle."""
    r_max = (0.14 + 0.09 * min(1.0, y0 / 300.0)) * width           # flatter near the horizon
    r_end = 0.45 * r_max
    n = max(3, int(width / (1.05 * r_max)) + 1)
    for i in range(n):
        t = i / (n - 1)
        edge = 1.0 - (2 * t - 1) ** 2
        r = (r_end + (r_max - r_end) * edge ** 0.8) * rng.uniform(0.88, 1.08)
        x = cx - width / 2 + r_end + t * (width - 2 * r_end)
        _disc(rows, x, y0 + 0.6 * r, r, y0)
    # a small puff beside the cloud
    if rng.random() < 0.6:
        side = rng.choice((-1, 1))
        r = 0.55 * r_end
        _disc(rows, cx + side * (width / 2 + 0.2 * r_max), y0 + 0.6 * r, r, y0)


def _placement(rng):
    """Clouds as (column, base row, width): uneven (clusters and strays), bigger higher up (nearer)."""
    centres = [rng.uniform(0, SKY_W) for _ in range(6)]
    boxes, out = [], []
    tries = 0
    while len(out) < 26 and tries < 4000:
        tries += 1
        c = rng.choice(centres) + rng.gauss(0, 330) if rng.random() < 0.75 else rng.uniform(0, SKY_W)
        y0 = rng.uniform(60, 380)
        width = (80 + 0.85 * y0) * rng.uniform(0.7, 1.5)
        lo, hi = c - width / 2 - 20, c + width / 2 + 20
        top = y0 + 0.34 * width + 10
        if lo < 40 or hi > SKY_W - 40:
            continue
        if any(not (hi < b[0] or lo > b[1] or top < b[2] or y0 - 10 > b[3]) for b in boxes):
            continue
        boxes.append((lo, hi, y0 - 10, top))
        out.append((c, y0, width))
    return out


def _stars(rows_star, rng, count=240):
    for _ in range(count):
        c, r = rng.randrange(8, SKY_W - 8), rng.randrange(24, 460)
        for dy in (0, 1, 2):
            _row_span(rows_star, r + dy, c, c + 2)


@functools.lru_cache(maxsize=1)
def cloud_layer() -> bytes:
    rng = random.Random("cosmergon-pov/sky")
    fill = [0] * SKY_H
    for cx, y0, width in _placement(rng):
        _cloud(fill, rng, cx, int(y0), width)
    star = [0] * SKY_H
    _stars(star, rng)
    full = (1 << SKY_W) - 1
    rows = []
    for y in range(SKY_H):
        d = max(1, int(0.045 * (80 + 0.85 * y)))                 # shade thickness grows with the row (size)
        below = fill[y - d] if y - d >= 0 else 0
        shade = fill[y] & ~(below >> d) & full                    # the lower right edge, d texels thick
        row_fill = _bits(fill[y] & ~shade)
        row_shade = _bits(shade)
        row = (int.from_bytes(row_fill, "little") + 2 * int.from_bytes(row_shade, "little")
               + 16 * int.from_bytes(_bits(star[y]), "little"))
        rows.append(row.to_bytes(SKY_W, "little"))
    return b"".join(bytes(col) for col in zip(*rows))


def _bits(mask: int) -> bytes:
    """A mask of SKY_W bits as SKY_W bytes of 0 or 1 (bit i -> byte i)."""
    return bin(mask)[2:].zfill(SKY_W)[::-1].encode().translate(bytes.maketrans(b"01", b"\x00\x01"))
