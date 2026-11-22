#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Draw the field's rim in every theme: out/muster-rand/rand-<theme>-<view>-<size>.png. Standard library only.

    make -C doomgeneric -f Makefile.headless
    python3 tools/make_map.py                      # assets/cosmergon.wad (once)
    python3 tools/ring_samples.py [--out out/muster-rand] [--size 672x324] [--dim 32]

The scene is what a bridge sends (COSMERGON.md, "The field's rim"): a field of `dim` cells in the window, the ring
around it one cell wide with the bunks and the portals placed by the rules of the concept, a few cells inside.
Views: 1 a wall with bunks, face on; 2 slanting along the wall; 3 a shaft portal; 4 a corner.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import make_theme  # noqa: E402
import ppm2png  # noqa: E402

THEME_ORDER = (("A", "wueste"), ("B", "gelbestadt"), ("C", "blaustadt"))
SLOTS_PER_WALL = 16
SHAFT_POS = (1, 2)                  # the two cells of a shaft, from the start of a wall (lower coordinate first)
GRID = 48
FRAMES = (1, 1, 1, 1, 60, 1, 1)               # the shaft floor travels 64 units in 21 steps: the view inside waits for it
VIEW_NAMES = ("koje-frontal", "wand-schraeg", "aus-der-koje", "schacht-schraeg", "schacht-innen", "ecke", "schacht-tief")


def rim_char(side: int, x: int, y: int) -> str | None:
    """The row character the bridge sends for the field square (x east, y SOUTH) (pov_bridge._rim): R, K, P, Q or None."""
    if not (-1 <= x <= side and -1 <= y <= side) or (0 <= x < side and 0 <= y < side):
        return None
    along = x if y in (-1, side) and 0 <= x < side else y if 0 <= y < side else None
    if along is None:
        return "R"
    if along in SHAFT_POS:
        flipped = x in (-1, side)
        return "P" if along == (SHAFT_POS[1] if flipped else SHAFT_POS[0]) else "Q"
    spacing = side // SLOTS_PER_WALL
    if spacing and along % spacing == spacing // 2 and along // spacing < SLOTS_PER_WALL:
        return "K"
    return "R"


def window(dim: int) -> tuple[int, int]:
    """Where the bridge puts the window of a field that fits it (pov_bridge._axis): the field square at its west, south."""
    first, last = -1, dim + 1 - GRID
    return ((first + last) // 2,) * 2


def control_lines(dim: int, views_in: list[str] | None = None, shaft_h: int | None = None) -> list[str]:
    """What the bridge sends: world, origin, 48 rows (x east, program y north: row 0 is the field row oy + 47), the field's
    things, then the views. The program's world y is the field's y negated."""
    ox, oy = window(dim)
    lines = ["world 0 0 0 0 %d" % dim, "origin %d %d" % (ox, -(oy + GRID - 1))]
    inside = {}
    for dx, dy in ((9, 9), (10, 9), (9, 10), (15, 14), (16, 14), (17, 14)):
        inside[(dx, dy)] = "#"
    inside[(20, 6)] = "O"
    inside[(24, 20)] = "T"
    inside[(12, 22)] = "="
    inside[(13, 22)] = "="
    for py in range(GRID):
        row = ""
        for px in range(GRID):
            fx, fy = ox + px, oy + GRID - 1 - py
            row += rim_char(dim, fx, fy) or inside.get((fx, fy), ".")
        lines.append("row %d %s" % (py, row))
    return lines


def view_lines(dim: int, shaft_h: int) -> list[str]:
    """(x, y, angle) in program coordinates. The south wall of a field of 32 is the window row 7 (face at y = 8), its
    bunks at the window columns 11, 13, 15 ..., the shaft at 9 and 10."""
    ox, oy = window(dim)
    south_face = oy + GRID - 1 - dim          # window row of the south ring
    face = south_face + 1.0                   # its north face: the field side
    v = [
        (13.5, face + 1.5, 270.0),            # a bunk face on from 6 m (1.5 cells)
        (10.2, face + 0.7, 5.0),              # slanting along the wall, looking east: several bunks
        (13.5, face - 0.5, 90.0),             # from inside a bunk into the field
        (14.0, face + 3.0, 217.0),            # the shaft (window columns 9 and 10) slanting
        (10.0, face - 0.85, 90.0),            # inside the shaft (at its back), the floor at half height
        (12.0, 12.0, 225.0),                  # the south-west corner
        (10.5, face + 1.6, 270.0),            # from the field into the shaft whose floor is at half height
    ]
    out = []
    for i, (x, y, a) in enumerate(v):
        if i == 3:
            out.append("shaft 9 %d 0" % south_face)
        if i == 4:
            out.append("shaft 9 %d %d" % (south_face, shaft_h))
        out += ["cam %.2f %.2f %.1f" % (x, y, a), "next %d" % FRAMES[i]]
    return out


def run_engine(theme_wad: str, work: str, size: str, dim: int) -> list[str]:
    binary = os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless")
    cmd = [binary, "-iwad", os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"),
           "-file", os.path.join(ROOT, "assets", "cosmergon.wad"), "-pov-theme", theme_wad, "-pov-control",
           "-warp", "1", "1", "-pov-size", size]
    os.makedirs(work, exist_ok=True)
    proc = subprocess.run(cmd, input="\n".join(control_lines(dim) + view_lines(dim, -64) + ["quit"]) + "\n", text=True,
                          env=dict(os.environ, POV_OUT=work), capture_output=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit("engine failed (%d)" % proc.returncode)
    return [os.path.join(work, f) for f in sorted(os.listdir(work)) if f.endswith(".ppm")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "muster-rand"))
    ap.add_argument("--size", default="672x324")
    ap.add_argument("--dim", type=int, default=32)
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    work = os.path.join(out, "_ppm")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    try:
        for letter, name in THEME_ORDER:
            wad = os.path.join(out, "_theme-%s.wad" % name)
            with open(wad, "wb") as handle:
                handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))
            ppms = run_engine(wad, os.path.join(work, name), args.size, args.dim)
            os.remove(wad)
            last = [sum(FRAMES[:i + 1]) - 1 for i in range(len(FRAMES))]
            for view, ppm in zip(VIEW_NAMES, [ppms[i] for i in last]):
                w, h, pix = ppm2png.read_ppm(ppm)
                ppm2png.write_png(os.path.join(out, "rand-%s-%s-%s.png" % (letter, view, args.size)), w, h, pix)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
