#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Time per picture of the headless engine for several picture sizes, with and without a theme.

    make -C doomgeneric -f Makefile.headless
    python3 tools/measure_size.py [--frames 400] [--repeat 3]

Scene: the one of tools/theme_samples.py (cells, walls, towers), the camera walks and turns through
its three viewpoints, a new picture each step. The engine writes no frame but the last one
(POV_EVERY), and its own measure (`work_ms`, `worst_ms` on stderr) leaves the writing out: it is the
time from the end of one picture to the call that hands the next one to the platform layer
(control lines, renderer, outline pass, conversion to RGB). Standard library only.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import make_theme  # noqa: E402
import theme_samples  # noqa: E402

SIZES = (("320x200 (default, shown 640x400)", None), ("672x324", "672x324"), ("1280x800", "1280x800"))


def lines(frames: int) -> str:
    out = ["cell %d %d %s" % c for c in theme_samples.scene(rich=False)]
    views = theme_samples.VIEWS_BASIC
    for i in range(frames):
        t = i / frames * len(views)
        a, b = views[int(t) % len(views)], views[(int(t) + 1) % len(views)]
        f = t - int(t)
        x = a[0] + (b[0] - a[0]) * f
        y = a[1] + (b[1] - a[1]) * f
        angle = a[2] + (b[2] - a[2]) * f + 12.0 * math.sin(i / 7.0)
        out.append("cam %.3f %.3f %.2f" % (x, y, angle))
        out.append("next")
    out.append("quit")
    return "\n".join(out) + "\n"


def run(size, theme, data) -> tuple[float, float]:
    cmd = [os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless"), "-iwad",
           os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"),
           "-file", os.path.join(ROOT, "assets", "cosmergon.wad")]
    if theme:
        cmd += ["-pov-theme", theme]
    cmd += ["-pov-control", "-warp", "1", "1"]
    if size:
        cmd += ["-pov-size", size]
    out = tempfile.mkdtemp(prefix="pov-measure-")
    try:
        env = dict(os.environ, POV_OUT=out, POV_EVERY="1000000")
        proc = subprocess.run(cmd, input=data, text=True, env=env, capture_output=True, check=True)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    m = re.search(r"work_ms=([\d.]+) worst_ms=([\d.]+)", proc.stderr)
    return float(m.group(1)), float(m.group(2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--frames", type=int, default=400)
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()
    data = lines(args.frames)
    work = tempfile.mkdtemp(prefix="pov-theme-")
    try:
        theme = os.path.join(work, "theme.wad")
        with open(theme, "wb") as handle:
            handle.write(make_theme.wad_bytes(make_theme.build_theme("wueste")))
        print("%d pictures per run, %d runs; ms per picture without writing it" % (args.frames, args.repeat))
        print("%-34s %-10s %8s %10s" % ("size", "theme", "mean", "slowest"))
        for label, size in SIZES:
            for name, path in (("none", None), ("wueste", theme)):
                runs = [run(size, path, data) for _ in range(args.repeat)]
                mean = sum(r[0] for r in runs) / len(runs)
                worst = max(r[1] for r in runs)
                print("%-34s %-10s %8.2f %10.2f" % (label, name, mean, worst))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
