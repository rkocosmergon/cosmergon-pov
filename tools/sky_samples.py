#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Samples of the sky (tools/theme_samples.py --sky): out/muster-himmel/.

    make -C doomgeneric -f Makefile.headless
    python3 tools/theme_samples.py --sky

Per theme A and B and per size (672x324, 1280x640): the day (8 times, the view towards the sun or moon, neighbour cubes
all round), all round (four directions, none to the south), the clouds (5 steps of 10 s, one passes in front of a
cube), a walk (the camera goes 5 steps across: near clouds move more than far ones and than the cubes), the haze
(off / light / clear), and the levels (a low, a middle and a high plane of the cube). The scene is a sparse field
around the eye; the field lies in the middle of its cube (`origin 40 40`), the cube at (0, 0, 0).
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import make_theme  # noqa: E402
import ppm2png  # noqa: E402
import sky_art  # noqa: E402
import theme_samples as ts  # noqa: E402

TIMES = (360, 480, 720, 960, 1110, 1200, 1380, 180)        # 06:00 08:00 12:00 16:00 18:30 20:00 23:00 03:00
EYE = (24.5, 24.5)                                          # in the window; the window is cells 40..88 of the field
LEVEL = 40                                                  # the plane of the field in its cube (0..127)
RING = [(1, 0, 0), (0, 1, 0), (-1, 0, 0), (1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0), (0, -1, 0)]
NO_SOUTH = [c for c in RING if c[1] >= 0]
CUBE_DIM = 128
DIR_E = 90.0                                               # looking north: the wind (east) crosses the view


@dataclass
class Frame:
    minute: int = 720
    angle: float = 0.0
    seconds: float = 0.0
    pos: tuple = EYE
    level: int = LEVEL
    extra: list = field(default_factory=list)


def sky_scene() -> list[str]:
    """Few low groups around the eye, spread on all sides at 6..15 cells, so that the sky is free in every
    direction (the field of the other samples is dense)."""
    glider = [(1, 0), (2, 1), (0, 2), (1, 2), (2, 2)]
    block = [(0, 0), (1, 0), (0, 1), (1, 1)]
    blinker = [(0, 0), (1, 0), (2, 0)]
    cells: dict[tuple[int, int], str] = {}
    for k in range(10):
        ang = math.radians(k * 36 + 11)
        cx, cy = int(round(24 + (6 + (k * 7) % 10) * math.cos(ang))), int(round(24 + (6 + (k * 7) % 10) * math.sin(ang)))
        for dx, dy in (glider, block, blinker)[k % 3]:
            cells[(cx + dx, cy + dy)] = "own" if k % 4 == 1 else "cell"
    for y in range(14, 30):
        cells[(8, y)] = "wall"
    cells[(8, 13)] = cells[(8, 30)] = "tower"
    cells[(36, 40)] = cells[(40, 36)] = "tower"
    return ["cell %d %d %s" % (x, y, k) for (x, y), k in sorted(cells.items())]


def run(wad: str, work: str, size: str, frames: list[Frame], cubes) -> list[str]:
    """One engine run, one picture per frame."""
    lines = sky_scene() + ["origin 40 40"]
    lines += ["cube %d %d %d %d %d" % ((i,) + c + (CUBE_DIM,)) for i, c in enumerate(cubes)]
    for fr in frames:
        lines += ["daytime %d" % fr.minute, "clouds %d" % round(fr.seconds), "world 0 0 0 %d %d" % (fr.level, CUBE_DIM)]
        lines += fr.extra + ["cam %.2f %.2f %.2f" % (fr.pos + (fr.angle,)), "next"]
    lines.append("quit")
    binary = os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless")
    cmd = [binary, "-iwad", os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"),
           "-file", os.path.join(ROOT, "assets", "cosmergon.wad"), "-pov-theme", wad,
           "-pov-control", "-warp", "1", "1", "-pov-size", size]
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    proc = subprocess.run(cmd, input="\n".join(lines) + "\n", text=True, env=dict(os.environ, POV_OUT=work),
                          capture_output=True, check=False)
    if proc.returncode != 0 or "rejected=0" not in proc.stderr:
        sys.stderr.write(proc.stderr)
        raise SystemExit("engine failed (%d)" % proc.returncode)
    return [os.path.join(work, f) for f in sorted(os.listdir(work)) if f.endswith(".ppm")]


def eye_units(fr: Frame) -> tuple:
    """The eye in the world for the geometry (what the engine computes from `world`, `origin`, `cam`)."""
    return sky_art.eye((0, 0, 0), fr.level, CUBE_DIM, (40 + fr.pos[0]) * 128, (40 + fr.pos[1]) * 128, 41)


def pass_time(size: str) -> float:
    """A start time (seconds) at which, within 40 s, a cloud that is nearer than the east cube crosses the cube's
    middle (looking north at noon): the sample shows a cloud in front of a cube."""
    w, h = map(int, size.split("x"))
    eye = eye_units(Frame())
    cube_mid = w / 2.0
    near = 30000                                            # units: the east cube's face is at about 32700
    best = None
    for t0 in range(0, 1800, 10):
        for cl in sky_art.cloud_list():
            seen = [sky_art.cloud_screen(cl, t0 + 10 * k, eye, DIR_E, w, h) for k in range(5)]
            if any(s is None or s[4] > near or s[2] < 50 or s[2] > w / 2 for s in seen):
                continue
            left, right = seen[0][0] - seen[0][2] / 2, seen[-1][0] - seen[-1][2] / 2
            if min(left, right) < cube_mid < max(left, right) + seen[0][2] and 0 < seen[0][1] < h / 2 + 20:
                best = best or t0
        if best is not None:
            break
    return float(best or 0)


def write_theme(out: str, name: str, fog: float | None = None) -> str:
    wad = os.path.join(out, "_theme-%s-%s.wad" % (name, fog))
    with open(wad, "wb") as handle:
        handle.write(make_theme.wad_bytes(make_theme.build_theme(name, fog=fog)))
    return wad


def single(out: str, letter: str, size: str, tag: str, ppm: str) -> None:
    w, h, pix = ppm2png.read_ppm(ppm)
    ppm2png.write_png(os.path.join(out, "einzel-%s-%s-%s.png" % (letter, size, tag)), w, h, pix)


def sheets_for(out: str, letter: str, name: str, size: str, work: str) -> None:
    wad = write_theme(out, name)
    day = run(wad, work, size, [Frame(m, sky_art.view_towards(m)) for m in TIMES], RING)
    for m, ppm in zip(TIMES, day):
        single(out, letter, size, ts.clock(m).replace(":", ""), ppm)
    ts.sheet([day[:4], day[4:]], os.path.join(out, "tageslauf-%s-%s.png" % (letter, size)), gap=18,
             labels=[[ts.clock(m) for m in TIMES[:4]], [ts.clock(m) for m in TIMES[4:]]])
    around = run(wad, work, size, [Frame(960, a) for a in (0.0, 90.0, 180.0, 270.0)], NO_SOUTH)
    ts.sheet([around[:2], around[2:]], os.path.join(out, "rundblick-%s-%s.png" % (letter, size)), gap=18,
             labels=[["16:00 E", "16:00 N"], ["16:00 W", "16:00 S"]])
    t0 = pass_time(size)
    drift = run(wad, work, size, [Frame(720, DIR_E, t0 + 10 * k) for k in range(5)], NO_SOUTH)
    ts.sheet([drift], os.path.join(out, "wolkenzug-%s-%s.png" % (letter, size)), gap=18,
             labels=[["%d s" % (t0 + 10 * k) for k in range(5)]])
    walk = run(wad, work, size, [Frame(720, 90.0, 0, (x, 24.5)) for x in (4.5, 14.5, 24.5, 34.5, 44.5)], NO_SOUTH)
    ts.sheet([walk], os.path.join(out, "gang-%s-%s.png" % (letter, size)), gap=18,
             labels=[["x %d" % x for x in (4, 14, 24, 34, 44)]])
    levels = run(wad, work, size, [Frame(720, 90.0, 0, EYE, lv) for lv in (5, 60, 115)], NO_SOUTH)
    ts.sheet([levels], os.path.join(out, "ebenen-%s-%s.png" % (letter, size)), gap=18,
             labels=[["05", "60", "115"]])
    os.remove(wad)
    hazes = []
    for k in (0.0, 1.0, 2.0):
        wad = write_theme(out, name, k)
        hazes.append(run(wad, os.path.join(work, "h%d" % int(k)), size, [Frame(720, 90.0, 0, (24.5, 12.5))], NO_SOUTH)[0])
        os.remove(wad)
    ts.sheet([hazes], os.path.join(out, "dunst-%s-%s.png" % (letter, size)), gap=18, labels=[["0", "1", "2"]])


def write_sky(out: str, size: str) -> None:
    os.makedirs(out, exist_ok=True)
    work = os.path.join(out, "_ppm")
    try:
        for letter, name in ts.THEME_ORDER[:2]:
            sheets_for(out, letter, name, size, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
