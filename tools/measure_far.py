#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""How calm the floor is in the far band, and how much of it changes in a short drive.

    python3 tools/measure_far.py [--root <checkout>] [--theme gelbestadt] [--size 672x324]

The band is the rows from the horizon to 12 percent of the picture height below it (a floor seen at more than
about 300 units). Two numbers: the share of points whose right neighbour has another colour (a still picture: speck
and sliver make it high), and the mean share of points of the band that change from one picture to the next in a
drive of 24 steps of 6 units forward with a slow turn (flicker and popping make it high). Several viewpoints (the
open ground of tools/theme_samples.py). `--root` measures another checkout (built). Standard library only.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STARTS = ((24.3, 4.4, 90.0), (3.5, 22.0, 4.0), (20.0, 2.0, 60.0))
STEPS = 24


def read_ppm(path: str) -> tuple[int, int, bytes]:
    with open(path, "rb") as handle:
        data = handle.read()
    parts = data.split(b"\n", 3)
    w, h = (int(v) for v in parts[1].split())
    return w, h, parts[3]


def drive(start: tuple[float, float, float]) -> list[str]:
    import math
    x, y, a = start
    out = []
    for i in range(STEPS):
        rad = math.radians(a + 0.4 * i)
        out += ["cam %.4f %.4f %.2f" % (x + i * 6 / 128.0 * math.cos(rad), y + i * 6 / 128.0 * math.sin(rad), a + 0.4 * i), "next"]
    return out


def band_rows(h: int) -> range:
    return range(h // 2 + 2, h // 2 + 2 + int(h * 0.12))


def measures(root: str, theme_name: str, size: str) -> tuple[float, float]:
    sys.path.insert(0, os.path.join(root, "tools"))
    for name in ("make_theme", "theme_art", "theme_samples", "theme_day", "sky_art", "ppm2png"):
        sys.modules.pop(name, None)
    import make_theme
    import theme_samples
    work = tempfile.mkdtemp(prefix="pov-far-")
    edges, changed, n_edge, n_change = 0.0, 0.0, 0, 0
    try:
        wad = os.path.join(work, "theme.wad")
        with open(wad, "wb") as handle:
            handle.write(make_theme.wad_bytes(make_theme.build_theme(theme_name)))
        for start in STARTS:
            frames = os.path.join(work, "f")
            shutil.rmtree(frames, ignore_errors=True)
            os.makedirs(frames)
            cells = ["cell %d %d %s" % c for c in theme_samples.scene(rich=True)]
            cmd = [os.path.join(root, "doomgeneric", "cosmergon-pov-headless"), "-iwad",
                   os.path.join(root, "assets", "freedoom", "freedoom1.wad"), "-file",
                   os.path.join(root, "assets", "cosmergon.wad"), "-pov-theme", wad, "-pov-control", "-warp", "1", "1",
                   "-pov-size", size]
            subprocess.run(cmd, input="\n".join(cells + drive(start) + ["quit"]) + "\n", text=True,
                           env=dict(os.environ, POV_OUT=frames, POV_EVERY="1"), capture_output=True, check=True)
            prev = None
            for name in sorted(os.listdir(frames)):
                w, h, rgb = read_ppm(os.path.join(frames, name))
                os.remove(os.path.join(frames, name))
                rows = [rgb[y * w * 3:(y + 1) * w * 3] for y in band_rows(h)]
                for r in rows:
                    edges += sum(1 for x in range(w - 1) if r[x * 3:x * 3 + 3] != r[x * 3 + 3:x * 3 + 6]) / (w - 1)
                    n_edge += 1
                if prev is not None:
                    for a, b in zip(prev, rows):
                        changed += sum(1 for x in range(w) if a[x * 3:x * 3 + 3] != b[x * 3:x * 3 + 3]) / w
                        n_change += 1
                prev = rows
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return edges / n_edge, changed / n_change


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--theme", default="gelbestadt")
    ap.add_argument("--size", default="672x324")
    args = ap.parse_args()
    e, c = measures(os.path.abspath(args.root), args.theme, args.size)
    print("%s %s: edge share %.4f, changed per step %.4f" % (args.theme, args.size, e, c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
