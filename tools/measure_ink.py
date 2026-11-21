#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Thickness of the strokes drawn into the walls, in points, as the engine shows them.

    python3 tools/measure_ink.py [--root <checkout>] [--theme wueste]

A block is seen from the south at a given distance from its face (64, 128, 256 units) in two picture sizes
(672 x 324 and 1280 x 640). The theme is built with every stroke index in pure red (floor) or green (wall; the outline stays navy), so
a red or green point is a stroke point and nothing else. Of the red points above the horizon (that is the wall) the
thickness of a point is the smaller of the two run lengths through it (along the row and along the column); the
numbers are the median, the 90th percentile and the largest of those. `--root` measures another checkout
(git archive of an older commit, built): its tools and binary are used. `strip_ink` leaves the POVINK lump out of the
theme (the thinning pass off): the counter-test of tests/test_ink.py. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import shutil
import statistics
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DISTANCES = (64, 128, 256)
SIZES = ("672x324", "1280x640")
RED = (255, 0, 0)       # a stroke on a floor
GREEN = (0, 255, 0)     # a stroke on a wall


def read_ppm(path: str) -> tuple[int, int, bytes]:
    with open(path, "rb") as handle:
        data = handle.read()
    parts = data.split(b"\n", 3)
    w, h = (int(v) for v in parts[1].split())
    return w, h, parts[3]


def strokes_to_red(make_theme, art):
    """A build_palette that paints every stroke index red."""
    plain = make_theme.build_palette

    def red(theme):
        pal = plain(theme)
        for base, trio in art.TW.items():
            for twin in trio:
                pal[twin] = RED if art.ORIENT_OF[base] == "floor" else GREEN
        for small, twin in art.SMALL_TWIN.items():
            pal[twin] = RED if art.ORIENT_OF[art.FLECK_OF_SMALL[small]] == "floor" else GREEN
        return pal
    return red


def thickness(rgb: bytes, w: int, h: int) -> list[int]:
    """Per red point above the horizon: the smaller run length through it, along row and column."""
    limit = h // 2
    ink = (bytes(RED), bytes(GREEN))
    red = [[rgb[(y * w + x) * 3:(y * w + x) * 3 + 3] in ink for x in range(w)] for y in range(limit)]
    hrun = [[0] * w for _ in range(limit)]
    vrun = [[0] * w for _ in range(limit)]
    for y in range(limit):
        x = 0
        while x < w:
            if red[y][x]:
                e = x
                while e < w and red[y][e]:
                    e += 1
                for k in range(x, e):
                    hrun[y][k] = e - x
                x = e
            else:
                x += 1
    for x in range(w):
        y = 0
        while y < limit:
            if red[y][x]:
                e = y
                while e < limit and red[e][x]:
                    e += 1
                for k in range(y, e):
                    vrun[k][x] = e - y
                y = e
            else:
                y += 1
    return [min(hrun[y][x], vrun[y][x]) for y in range(limit) for x in range(w) if red[y][x]]


def measure(root: str, theme_name: str, strip_ink: bool = False) -> dict:
    sys.path.insert(0, os.path.join(root, "tools"))
    import importlib
    for name in ("make_theme", "theme_art", "theme_samples", "theme_day", "sky_art", "ppm2png"):
        sys.modules.pop(name, None)
    import make_theme
    import theme_art as art
    make_theme.build_palette = strokes_to_red(make_theme, art)
    out: dict = {}
    work = tempfile.mkdtemp(prefix="pov-ink-")
    try:
        wad = os.path.join(work, "theme.wad")
        with open(wad, "wb") as handle:
            lumps = [(n, d) for n, d in make_theme.build_theme(theme_name) if not (strip_ink and n == "POVINK")]
            handle.write(make_theme.wad_bytes(lumps))
        binary = os.path.join(root, "doomgeneric", "cosmergon-pov-headless")
        for size in SIZES:
            for d in DISTANCES:
                lines = ["cell 10 10 cell", "cam 10.5 %.4f 90" % (10 - d / 128.0), "next", "quit"]
                frames = os.path.join(work, "f")
                shutil.rmtree(frames, ignore_errors=True)
                os.makedirs(frames)
                cmd = [binary, "-iwad", os.path.join(root, "assets", "freedoom", "freedoom1.wad"), "-file",
                       os.path.join(root, "assets", "cosmergon.wad"), "-pov-theme", wad, "-pov-control", "-warp", "1", "1",
                       "-pov-size", size]
                subprocess.run(cmd, input="\n".join(lines) + "\n", text=True, env=dict(os.environ, POV_OUT=frames),
                               capture_output=True, check=True)
                w, h, rgb = read_ppm(os.path.join(frames, sorted(os.listdir(frames))[-1]))
                t = sorted(thickness(rgb, w, h))
                out[(size, d)] = (len(t), statistics.median(t) if t else 0, t[int(len(t) * 0.9)] if t else 0,
                                  t[int(len(t) * 0.99)] if t else 0, t[-1] if t else 0)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out


def floor_stroke_points(root: str, theme_name: str, size: str = "672x324") -> int:
    """Stroke points on the floor between 150 and 400 units from the eye (eye height 41 units, a point row below
    the horizon is f * 41 / distance with f half the width), summed over three viewpoints on open ground."""
    sys.path.insert(0, os.path.join(root, "tools"))
    for name in ("make_theme", "theme_art", "theme_samples", "theme_day", "sky_art", "ppm2png"):
        sys.modules.pop(name, None)
    import make_theme
    import theme_art as art
    import theme_samples
    make_theme.build_palette = strokes_to_red(make_theme, art)
    work = tempfile.mkdtemp(prefix="pov-ink-")
    total = 0
    try:
        wad = os.path.join(work, "theme.wad")
        with open(wad, "wb") as handle:
            handle.write(make_theme.wad_bytes(make_theme.build_theme(theme_name)))
        cells = ["cell %d %d %s" % c for c in theme_samples.scene(rich=True)]
        views = (theme_samples.VIEWS[0], theme_samples.VIEWS[5], (20.0, 2.0, 60.0))
        cmd = [os.path.join(root, "doomgeneric", "cosmergon-pov-headless"), "-iwad",
               os.path.join(root, "assets", "freedoom", "freedoom1.wad"), "-file",
               os.path.join(root, "assets", "cosmergon.wad"), "-pov-theme", wad, "-pov-control", "-warp", "1", "1",
               "-pov-size", size]
        lines = cells + sum((["cam %.2f %.2f %.1f" % v, "next"] for v in views), []) + ["quit"]
        frames = os.path.join(work, "f")
        os.makedirs(frames)
        subprocess.run(cmd, input="\n".join(lines) + "\n", text=True, env=dict(os.environ, POV_OUT=frames),
                       capture_output=True, check=True)
        for name in sorted(os.listdir(frames)):
            w, h, rgb = read_ppm(os.path.join(frames, name))
            f = w / 2
            for y in range(h // 2 + int(f * 41 / 400), h // 2 + int(f * 41 / 150)):
                total += sum(1 for x in range(w) if rgb[(y * w + x) * 3:(y * w + x) * 3 + 3] == bytes(RED))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--theme", default="wueste")
    args = ap.parse_args()
    print("floor stroke points 150..400 units (3 views, 672x324): %d" % floor_stroke_points(os.path.abspath(args.root), args.theme))
    print("%-9s %5s %8s %7s %5s %5s %5s" % ("size", "units", "points", "median", "p90", "p99", "max"))
    for (size, d), (n, med, p90, p99, mx) in measure(os.path.abspath(args.root), args.theme).items():
        print("%-9s %5d %8d %7.1f %5d %5d %5d" % (size, d, n, med, p90, p99, mx))
    return 0


if __name__ == "__main__":
    sys.exit(main())
