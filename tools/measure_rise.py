#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Time per picture with the whole field travelling at once (COSMERGON.md, "Rise and sink", "Measured").

    make -C doomgeneric -f Makefile.headless
    python3 tools/measure_rise.py [--frames 420] [--repeat 3]

Scene: a checkerboard of cells on the whole 48 x 48 window; every 42 pictures (the length of a travel) every cell
flips (the cells that stood sink, the empty ones rise), so that all 2304 sectors travel in every picture. The camera
turns on the spot at the field's edge. The same lines are run with `-pov-rise 0` (every flip is a jump, the checkerboard
stands still between the flips): the difference is what travelling costs. Also the field at rest (no line changes
anything) with the default rise, for the cost of a rest. Prints ms per picture without writing it (the engine's `work_ms`).
Standard library only.
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

SIZES = ("672x324", "1280x800")
TICK = 42


def checker(parity: int) -> list[str]:
    return ["cell %d %d %s" % (x, y, "cell" if (x + y) % 2 == parity else "empty") for y in range(48) for x in range(48)]


def lines(frames: int, flips: bool) -> str:
    out = ["cam 24.5 1.5 90", "next"]
    out += checker(0)
    out += ["next"]
    for i in range(frames):
        if flips and i % TICK == 0:
            out += checker((i // TICK + 1) % 2)
        out += ["cam 24.5 1.5 %.2f" % (90 + 25 * math.sin(i / 20.0)), "next"]
    out.append("quit")
    return "\n".join(out) + "\n"


def run(size: str, theme: str | None, data: str, rise: str | None) -> tuple[float, float]:
    cmd = [os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless"), "-iwad",
           os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"),
           "-file", os.path.join(ROOT, "assets", "cosmergon.wad")]
    if theme:
        cmd += ["-pov-theme", theme]
    cmd += ["-pov-control", "-warp", "1", "1", "-pov-size", size]
    if rise is not None:
        cmd += ["-pov-rise", rise]
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
    ap.add_argument("--frames", type=int, default=420)
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()
    work = tempfile.mkdtemp(prefix="pov-theme-")
    try:
        theme = os.path.join(work, "theme.wad")
        with open(theme, "wb") as handle:
            handle.write(make_theme.wad_bytes(make_theme.build_theme("wueste")))
        print("%d pictures per run, %d runs; ms per picture without writing it" % (args.frames, args.repeat))
        print("%-9s %-8s %-34s %8s %10s" % ("size", "theme", "run", "mean", "slowest"))
        cases = (("field at rest, default rise", False, None), ("all cells flip, -pov-rise 0 (jumps)", True, "0"),
                 ("all cells flip, default rise (travel)", True, None))
        for size in SIZES:
            for name, path in (("none", None), ("wueste", theme)):
                for label, flips, rise in cases:
                    data = lines(args.frames, flips)
                    runs = [run(size, path, data, rise) for _ in range(args.repeat)]
                    mean = sum(r[0] for r in runs) / len(runs)
                    print("%-9s %-8s %-34s %8.2f %10.2f" % (size, name, label, mean, max(r[1] for r in runs)))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
