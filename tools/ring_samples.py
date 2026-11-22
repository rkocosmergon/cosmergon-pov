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
VIEW_NAMES = ("wand-frontal", "wand-schraeg", "portal", "ecke")


def ring_cells(dim: int, ox: int, oy: int) -> list[tuple[int, int, str]]:
    """The ring of a field of dim x dim cells whose cell 0, 0 lies at window cell (ox, oy): (x, y, kind). A bunk at
    spacing // 2 + i * spacing (spacing = dim // 16), a shaft at the positions 1 and 2 of every wall, the shaft before
    the bunk; everything else `ring`. x east, y north; a wall runs along its lower coordinate."""
    spacing = dim // SLOTS_PER_WALL
    bunks = {i * spacing + spacing // 2 for i in range(SLOTS_PER_WALL)}
    cells: dict[tuple[int, int], str] = {}
    for x in range(-1, dim + 1):
        for y in range(-1, dim + 1):
            if 0 <= x < dim and 0 <= y < dim:
                continue
            cells[(ox + x, oy + y)] = "ring"
    for p in range(dim):
        kind = "alcove" if p in bunks else "ring"
        shaft = {SHAFT_POS[0]: "shaftlo", SHAFT_POS[1]: "shafthi"}.get(p)
        for x, y in ((ox + p, oy - 1), (ox - 1, oy + p), (ox + p, oy + dim), (ox + dim, oy + p)):
            cells[(x, y)] = shaft or kind
    return [(x, y, k) for (x, y), k in sorted(cells.items())]


def field_cells(ox: int, oy: int) -> list[tuple[int, int, str]]:
    """A few things inside the field, so that the rim is seen against the usual surroundings."""
    out = []
    for dx, dy in ((9, 9), (10, 9), (9, 10), (15, 14), (16, 14), (17, 14)):
        out.append((ox + dx, oy + dy, "cell"))
    out += [(ox + 20, oy + 6, "own"), (ox + 24, oy + 20, "tower"), (ox + 12, oy + 22, "wall"), (ox + 13, oy + 22, "wall")]
    return out


def views(dim: int, ox: int, oy: int) -> list[tuple[float, float, float]]:
    """(x, y, angle) of the four views for the south wall (y = oy - 1) and the south-west corner."""
    return [
        (ox + 7.0, oy + 3.0, 270.0),            # face on to the south wall: the bunks at the positions 5, 7, 9
        (ox + 2.2, oy + 1.6, 12.0),             # slanting along the south wall, looking east
        (ox + 3.0, oy + 5.0, 255.0),            # at the shaft: positions 1 and 2 (x = ox + 1, ox + 2)
        (ox + 6.0, oy + 6.0, 225.0),            # the south-west corner (the shaft of each wall near it)
    ]


def control_lines(dim: int, ox: int, oy: int) -> list[str]:
    lines = ["cell %d %d %s" % c for c in ring_cells(dim, ox, oy) + field_cells(ox, oy)]
    for x, y, angle in views(dim, ox, oy):
        lines += ["cam %.2f %.2f %.1f" % (x, y, angle), "next"]
    lines.append("quit")
    return lines


def run_engine(theme_wad: str, work: str, size: str, dim: int, ox: int, oy: int) -> list[str]:
    binary = os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless")
    cmd = [binary, "-iwad", os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"),
           "-file", os.path.join(ROOT, "assets", "cosmergon.wad"), "-pov-theme", theme_wad, "-pov-control",
           "-warp", "1", "1", "-pov-size", size]
    os.makedirs(work, exist_ok=True)
    proc = subprocess.run(cmd, input="\n".join(control_lines(dim, ox, oy)) + "\n", text=True,
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
    ox = oy = (48 - args.dim) // 2
    work = os.path.join(out, "_ppm")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    try:
        for letter, name in THEME_ORDER:
            wad = os.path.join(out, "_theme-%s.wad" % name)
            with open(wad, "wb") as handle:
                handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))
            ppms = run_engine(wad, os.path.join(work, name), args.size, args.dim, ox, oy)
            os.remove(wad)
            for view, ppm in zip(VIEW_NAMES, ppms):
                w, h, pix = ppm2png.read_ppm(ppm)
                ppm2png.write_png(os.path.join(out, "rand-%s-%s-%s.png" % (letter, view, args.size)), w, h, pix)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
