#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Time per picture of the headless engine on the field's rim: a wall with bunks and a shaft, the camera walking along it.

    make -C doomgeneric -f Makefile.headless
    python3 tools/measure_rim.py [--frames 400] [--repeat 3] [--bin PATH] [--theme-tools DIR]

Two scenes, both with the field of 32 cells that the bridge puts in the middle of the window (tools/ring_samples.py): "wall"
(the camera walks along the south wall at 6 m from it, turning to the bunks), "shaft" (it circles in front of the shaft; the
shaft floor goes down and up every 60 pictures, so that it travels most of the time). The engine writes no frame but
the last (POV_EVERY) and its own measure (`work_ms` on stderr) leaves the writing out. `--bin` and `--theme-tools` let the
same scene run on an older build (its program, and the tools directory that made its theme); an older program rejects the
`shaft` lines (counted, harmless). Standard library only.
"""

from __future__ import annotations

import argparse
import importlib
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
import ring_samples  # noqa: E402

SIZES = (("672x324", "672x324"), ("1280x800", "1280x800"))


def lines(scene: str, frames: int) -> str:
    out = ring_samples.control_lines(32)
    face = 8.0                                   # the field side of the south wall (window row 7 + 1)
    for i in range(frames):
        t = i / frames
        if scene == "wall":
            x = 11.5 + 14.0 * (0.5 - 0.5 * math.cos(2 * math.pi * t))
            out.append("cam %.3f %.3f %.2f" % (x, face + 1.5, 270.0 + 35.0 * math.sin(4 * math.pi * t)))
        else:
            x = 10.0 + 5.0 * math.sin(2 * math.pi * t)
            y = face + 3.0 + 1.0 * math.cos(4 * math.pi * t)
            out.append("cam %.3f %.3f %.2f" % (x, y, math.degrees(math.atan2(face - y, 10.0 - x)) % 360))
            if i % 60 == 0:
                out.append("shaft 9 7 %d" % (-96 if (i // 60) % 2 == 0 else 0))
        out.append("next")
    out.append("quit")
    return "\n".join(out) + "\n"


def run(binary: str, theme: str, size: str, data: str) -> tuple[float, float]:
    base = os.path.dirname(binary)
    cmd = [binary, "-iwad", os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"),
           "-file", os.path.join(ROOT, "assets", "cosmergon.wad"), "-pov-theme", theme, "-pov-control", "-warp", "1", "1",
           "-pov-size", size]
    out = tempfile.mkdtemp(prefix="pov-measure-")
    try:
        env = dict(os.environ, POV_OUT=out, POV_EVERY="1000000")
        proc = subprocess.run(cmd, input=data, text=True, env=env, capture_output=True, check=True, cwd=base)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    m = re.search(r"work_ms=([\d.]+) worst_ms=([\d.]+)", proc.stderr)
    return float(m.group(1)), float(m.group(2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--frames", type=int, default=400)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--bin", default=os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless"))
    ap.add_argument("--theme-tools", default=HERE, help="the tools directory whose make_theme.py makes the theme")
    args = ap.parse_args()
    sys.path.insert(0, args.theme_tools)
    make_theme = importlib.import_module("make_theme")
    work = tempfile.mkdtemp(prefix="pov-theme-")
    try:
        theme = os.path.join(work, "theme.wad")
        with open(theme, "wb") as handle:
            handle.write(make_theme.wad_bytes(make_theme.build_theme("wueste")))
        print("%d pictures per run, %d runs; ms per picture without writing it; theme wueste" % (args.frames, args.repeat))
        print("%-10s %-8s %8s %10s" % ("size", "scene", "mean", "slowest"))
        for label, size in SIZES:
            for scene in ("wall", "shaft"):
                data = lines(scene, args.frames)
                runs = [run(args.bin, theme, size, data) for _ in range(args.repeat)]
                print("%-10s %-8s %8.2f %10.2f   runs: %s" % (label, scene, sum(r[0] for r in runs) / len(runs),
                                                             max(r[1] for r in runs), " ".join("%.2f" % r[0] for r in runs)))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
