#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Time per picture with 20 birds in view, 672 x 324, theme `wueste` (COSMERGON.md, "Flying and perching").

    make -C doomgeneric -f Makefile.headless
    python3 tools/measure_flight.py [--frames 400] [--repeat 3] [--old-bin <build before flying and perching>]

Three scenes of 20 birds, the camera swinging a little in every picture: `standing` (the lines are sent once, so the birds sink
after 1.6 s and perch), `flying` (every bird moves in every picture) and `nobird`. The engine's own measure (`work_ms`: control
lines, renderer, outline pass, conversion to RGB, not the writing of the picture) is the figure, mean of the runs. With
--old-bin the same scenes run on that build with the same theme (it draws the first look only). Standard library only.
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


def lines(scene: str, frames: int) -> str:
    out = []
    if scene != "nobird":
        for i in range(20):
            out.append("thing %d bird %.2f %.2f %d" % (i, 26.0 + (i // 5) * 1.1, 22.5 + (i % 5) * 1.0 + (i // 5) * 0.2, (45 * i) % 360))
    for i in range(frames):
        if scene == "flying" and i:
            for b in range(20):
                out.append("thing %d bird %.2f %.2f %d" % (b, 26.0 + (b // 5) * 1.1 + 0.01 * (i % 40), 22.5 + (b % 5) * 1.0 + (b // 5) * 0.2, (45 * b) % 360))
        out.append("cam 24.5 24.5 %.2f" % (12 * math.sin(i / 9.0)))
        out.append("next")
    out.append("quit")
    return "\n".join(out) + "\n"


def run(binary: str, theme: str, data: str) -> float:
    cmd = [binary, "-iwad", os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"), "-file",
           os.path.join(ROOT, "assets", "cosmergon.wad"), "-pov-theme", theme, "-pov-control", "-warp", "1", "1",
           "-pov-size", "672x324"]
    out = tempfile.mkdtemp(prefix="pov-flight-")
    try:
        proc = subprocess.run(cmd, input=data, text=True, env=dict(os.environ, POV_OUT=out, POV_EVERY="1000000"),
                              capture_output=True, check=True)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return float(re.search(r"work_ms=([\d.]+)", proc.stderr).group(1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--frames", type=int, default=400)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--old-bin")
    args = ap.parse_args()
    new_bin = os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless")
    work = tempfile.mkdtemp(prefix="pov-theme-")
    try:
        theme = os.path.join(work, "wueste.wad")
        with open(theme, "wb") as handle:
            handle.write(make_theme.wad_bytes(make_theme.build_theme("wueste")))
        builds = [("now", new_bin)] + ([("before", args.old_bin)] if args.old_bin else [])
        print("%d pictures per run, %d runs; ms per picture, mean (runs)" % (args.frames, args.repeat))
        for scene in ("standing", "flying", "nobird"):
            data = lines(scene, args.frames)
            for name, binary in builds:
                runs = []
                for _ in range(args.repeat):
                    runs.append(run(binary, theme, data))
                print("%-9s %-7s %6.2f  (%s)" % (scene, name, sum(runs) / len(runs), ", ".join("%.2f" % r for r in runs)))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
