#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Sheets of the bird in flight and perched: out/samples-bird/<sheet>-<theme>-<size>.png. Standard library only.

    make -C doomgeneric -f Makefile.headless
    python3 tools/bird_samples.py [--out out/samples-bird] [--themes wueste gelbestadt] [--sizes 672x324]

- `flight`: wings up, half spread, wings down (columns), seen from the front, the side and the rear (rows).
- `perched`: on the floor and on a wall (rows), from the front, the side and the rear (columns).
- `landing`: ten pictures of one bird (rows of five): flying, stopping, sinking and perched ("Flying and perching").

The scenes use the clock of the program: in blocking mode one drawn picture is one step, a bird seen first is in flight, and
the beat is 10 steps (see COSMERGON.md), so picture k shows the look `BEAT[k % 10]` for the bird with id 0.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import kinds_samples  # noqa: E402
import make_theme  # noqa: E402
import ppm2png  # noqa: E402

WINGS_UP, HALF, WINGS_DOWN = 3, 5, 8            # a picture number whose beat step is up, half spread, down (id 0)
FACES = (("front", 180), ("side", 90), ("rear", 0))
SETTLE = 80                                      # pictures until a bird that stands is perched (28 hold + 28 sink, with room)
LANDING = (4, 9, 15, 30, 44, 50, 56, 62, 68, 76)  # pictures of the landing sheet; the bird moves until picture 15
LANDING_MOVES = 15


def frames_of(wad, size, lines, work):
    """All pictures (PPM paths) of a run."""
    return kinds_samples.engine(wad, size, lines, work)


def bird_scene(angle, where="27.5 24.5", floor=None, moving=False, count=1):
    lines = []
    if floor:
        lines.append("cell 27 24 %s" % floor)
    lines.append("cam 25.5 24.5 0")
    x, y = where.split()
    for k in range(count):
        px = float(x) + (0.03 * k if moving else 0.0)
        lines += ["thing 0 bird %.2f %s %d" % (px, y, angle), "next"]
    return lines


def crop(pic, box):
    w, _h, pix = pic
    x0, y0, x1, y1 = box
    return [bytes(pix[(y * w + x0) * 3:(y * w + x1) * 3]) for y in range(y0, y1)]


def bbox(base, pic):
    w, h, a = base
    b = pic[2]
    xs, ys = [], []
    for y in range(h):
        if a[y * w * 3:(y + 1) * w * 3] != b[y * w * 3:(y + 1) * w * 3]:
            for x in range(w):
                if a[(y * w + x) * 3:(y * w + x) * 3 + 3] != b[(y * w + x) * 3:(y * w + x) * 3 + 3]:
                    xs.append(x)
                    ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def tile(cells, cols, out_png, pad=6, scale=2):
    """cells: list of (label, rows of bytes); same size; laid out in `cols` columns."""
    h, w = len(cells[0][1]), len(cells[0][1][0]) // 3
    rows = (len(cells) + cols - 1) // cols
    total_w, total_h = cols * (w * scale + pad) + pad, rows * (h * scale + pad + 14) + pad
    canvas = [bytearray(bytes((244, 244, 244)) * total_w) for _ in range(total_h)]
    for n, (label, data) in enumerate(cells):
        x0 = pad + (n % cols) * (w * scale + pad)
        y0 = pad + 14 + (n // cols) * (h * scale + pad + 14)
        for y, line in enumerate(data):
            big = b"".join(line[i:i + 3] * scale for i in range(0, len(line), 3))
            for dy in range(scale):
                canvas[y0 + y * scale + dy][x0 * 3:(x0 + w * scale) * 3] = big
        kinds_samples.stamp(canvas, label, x0, y0 - 13, scale=1)
    ppm2png.write_png(out_png, total_w, total_h, b"".join(bytes(r) for r in canvas))


def window(base, shots, size):
    """One crop box for all `shots`: centred on the union of where they differ from `base`, fixed size by picture size."""
    boxes = [b for b in (bbox(base, s) for s in shots) if b]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    w, h = base[0], base[1]
    cw, ch = max(x1 - x0 + 12, int(w * 0.26)), max(y1 - y0 + 12, int(h * 0.40))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    left = min(max(cx - cw // 2, 0), w - cw)
    top = min(max(cy - ch // 2, 0), h - ch)
    return left, top, left + cw, top + ch


def make(theme, wad, size, out, work):
    base = ppm2png.read_ppm(frames_of(wad, size, ["cam 25.5 24.5 0", "next"], work)[0])
    tag = "%s-%s" % (theme, size)
    # flight: rows front/side/back, columns up / half / down
    shots, labels = [], []
    for name, angle in FACES:
        ppms = frames_of(wad, size, bird_scene(angle, count=WINGS_DOWN), work)
        for what, k in (("wings up", WINGS_UP), ("half spread", HALF), ("wings down", WINGS_DOWN)):
            shots.append(ppm2png.read_ppm(ppms[k - 1]))
            labels.append("%s %s" % (name, what))
    box = window(base, shots, size)
    tile([(lab, crop(s, box)) for lab, s in zip(labels, shots)], 3, os.path.join(out, "flight-%s.png" % tag))
    # perched: rows floor / wall, columns front / side / back
    shots, labels = [], []
    for floor in (None, "wall"):
        for name, angle in FACES:
            ppms = frames_of(wad, size, bird_scene(angle, floor=floor, count=1) + ["next %d" % SETTLE], work)
            shots.append(ppm2png.read_ppm(ppms[-1]))
            labels.append("%s %s" % ("on a wall" if floor else "on the floor", name))
    wall_base = ppm2png.read_ppm(frames_of(wad, size, ["cell 27 24 wall", "cam 25.5 24.5 0", "next"], work)[0])
    box = window(base, shots[:3], size)
    box_wall = window(wall_base, shots[3:], size)
    cells = [(lab, crop(s, box if i < 3 else box_wall)) for i, (lab, s) in enumerate(zip(labels, shots))]
    tile([(lab, rows if len(rows) == len(cells[0][1]) else rows[:len(cells[0][1])]) for lab, rows in cells], 3,
         os.path.join(out, "perched-%s.png" % tag))
    # landing: flies on (moves every picture), stops, sinks, perches
    lines = bird_scene(180, moving=True, count=LANDING_MOVES)
    lines += ["next %d" % (max(LANDING) - LANDING_MOVES)]
    ppms = frames_of(wad, size, lines, work)
    shots = [ppm2png.read_ppm(ppms[k - 1]) for k in LANDING]
    box = window(base, shots, size)
    tile([("picture %d" % k, crop(s, box)) for k, s in zip(LANDING, shots)], 5, os.path.join(out, "landing-%s.png" % tag))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "samples-bird"))
    ap.add_argument("--themes", nargs="*", default=list(kinds_samples.THEMES))
    ap.add_argument("--sizes", nargs="*", default=["672x324"])
    args = ap.parse_args()
    work = os.path.join(args.out, "_work")
    os.makedirs(args.out, exist_ok=True)
    for theme in args.themes + [None]:
        wad = None
        if theme:
            wad = os.path.join(args.out, "_theme-%s.wad" % theme)
            with open(wad, "wb") as handle:
                handle.write(make_theme.wad_bytes(make_theme.build_theme(theme)))
        for size in args.sizes:
            make(theme or "no-theme", wad, size, args.out, work)
        if wad:
            os.remove(wad)
    for name in os.listdir(work):
        os.remove(os.path.join(work, name))
    os.rmdir(work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
