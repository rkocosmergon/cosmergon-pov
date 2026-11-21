#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Sheets of the thing kinds: out/muster-figuren/figuren-<theme>-<size>.png (marauder, monster, bird, corpse, loot side by
side, 3 cells from an eye at eye height, labelled), figuren-ohne-Thema-<size>.png and figuren-faellt-<theme>-<size>.png
(a monster, then a corpse with the same id, no `gone`). Standard library only.

    make -C doomgeneric -f Makefile.headless
    python3 tools/kinds_samples.py [--out out/muster-figuren]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import make_theme  # noqa: E402
import ppm2png  # noqa: E402

ORDER = ("marauder", "monster", "bird", "corpse", "loot")
SIZES = ("672x324", "1280x640")
THEMES = ("wueste", "gelbestadt")

GLYPHS = {  # 3 x 5, one string a row
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110",
    "E": "111100110100111", "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
    "I": "111010010010111", "L": "100100100100111", "M": "101111111101101", "N": "110101101101101",
    "O": "010101101101010", "P": "110101110100100", "R": "110101110110101", "S": "011100010001110",
    "T": "111010010010010", "U": "101101101101111", "V": "101101101101010", "W": "101101111111101",
    "Y": "101101010010010", "Z": "111001010100111", "-": "000000111000000", " ": "000000000000000",
    ">": "100010001010100", "0": "111101101101111", "1": "010110010010111", "2": "111001111100111",
    "3": "111001111001111", "4": "101101111001001", "5": "111100111001111", "6": "111100111101111",
    "7": "111001001001001", "8": "111101111101111", "9": "111101111001111", "x": "000101010101000",
}


def stamp(canvas, text, x0, y0, scale=2, ink=bytes((26, 35, 50))):
    for k, ch in enumerate(text.upper()):
        for i, bit in enumerate(GLYPHS.get(ch, GLYPHS[" "])):
            if bit == "1":
                for dy in range(scale):
                    for dx in range(scale):
                        x = x0 + (k * 4 + i % 3) * scale + dx
                        canvas[y0 + (i // 3) * scale + dy][x * 3:x * 3 + 3] = ink


def engine(theme_wad, size, lines, work):
    cmd = [os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless"), "-iwad",
           os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"), "-file", os.path.join(ROOT, "assets", "cosmergon.wad")]
    if theme_wad:
        cmd += ["-pov-theme", theme_wad]
    cmd += ["-pov-control", "-warp", "1", "1", "-pov-size", size]
    os.makedirs(work, exist_ok=True)
    for f in os.listdir(work):
        if f.endswith(".ppm"):
            os.remove(os.path.join(work, f))
    proc = subprocess.run(cmd, input="\n".join(lines) + "\nquit\n", text=True, env=dict(os.environ, POV_OUT=work),
                          capture_output=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit("engine failed")
    return [os.path.join(work, f) for f in sorted(os.listdir(work)) if f.endswith(".ppm")]


def backdrop():
    lines = ["cell %d %d wall" % (31, y) for y in range(16, 34)]
    lines += ["cell %d %d cell" % (x, y) for x in (28, 29) for y in (21, 27)]
    lines += ["cell %d %d own" % (29, 19)]
    return lines


def row_lines(kinds):
    lines = backdrop()
    for i, k in enumerate(kinds):
        lines.append("thing %d %s %.1f %.1f %d" % (i, k, 27.5, 26.5 - i, 0 if k == "corpse" else 180))
    return lines + ["cam 24.5 24.5 0", "next"]


def write_sheet(rows, out_png, gap=16):
    """rows: list of (label, ppm path); stacked."""
    images = [(lab, ppm2png.read_ppm(p)) for lab, p in rows]
    w, h = images[0][1][0], images[0][1][1]
    total_w, total_h = w + 2 * gap, len(images) * (h + gap) + gap
    canvas = [bytearray(bytes((244, 244, 244)) * total_w) for _ in range(total_h)]
    for r, (lab, (_w, _h, pix)) in enumerate(images):
        y0 = gap + r * (h + gap) + 0
        for y in range(h):
            canvas[y0 + y][gap * 3:(gap + w) * 3] = pix[y * w * 3:(y + 1) * w * 3]
        stamp(canvas, lab, gap, y0 - 13)
    ppm2png.write_png(out_png, total_w, total_h, b"".join(bytes(r) for r in canvas))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "muster-figuren"))
    out = ap.parse_args().out
    work = os.path.join(out, "_work")
    os.makedirs(out, exist_ok=True)
    wads = {None: None}
    for name in THEMES:
        wads[name] = os.path.join(out, "_theme-%s.wad" % name)
        with open(wads[name], "wb") as handle:
            handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))
    for size in SIZES:
        for theme, wad in wads.items():
            tag = theme or "ohne-Thema"
            ppm = engine(wad, size, row_lines(ORDER), work)[0]
            write_sheet([("%s %s  L>R  %s" % (tag, size, " ".join(ORDER)), ppm)],
                        os.path.join(out, "figuren-%s-%s.png" % (tag, size)))
            fall = backdrop() + ["thing 0 monster 27.5 24.5 180", "cam 24.5 24.5 0", "next",
                                 "thing 0 corpse 27.5 24.5 0", "next"]
            ppms = engine(wad, size, fall, work)
            write_sheet([("%s vorher MONSTER" % tag, ppms[0]), ("%s nachher CORPSE gleiche ID" % tag, ppms[1])],
                        os.path.join(out, "figuren-faellt-%s-%s.png" % (tag, size)))
    for f in os.listdir(work):
        os.remove(os.path.join(work, f))
    os.rmdir(work)
    for name in THEMES:
        os.remove(wads[name])
    return 0


if __name__ == "__main__":
    sys.exit(main())
