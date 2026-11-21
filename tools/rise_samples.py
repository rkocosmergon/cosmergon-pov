#!/usr/bin/env python3
"""Samples of rise and sink (COSMERGON.md, "Rise and sink"): out/muster-fahrt/.

    make -C doomgeneric -f Makefile.headless
    python3 tools/make_map.py                      # assets/cosmergon.wad (once)
    python3 tools/rise_samples.py [--out out/muster-fahrt]

Per theme (wueste, gelbestadt) and size (672x324, 1280x640) three sheets: "auftauchen" (a group of cells rises
out of the ground), "versinken" (it sinks again) and "glider" (a Conway glider over three ticks), seen
slantwise from eye level. The first four sheets of a theme show the times 0, 20, 40, 60, 80 and 100 percent of
the travel (0 percent is the state before the change); the glider sheet shows three moments of each of three
ticks (a tick every TICK_STEPS steps, the cells travel POV_RISE_STEPS: they overlap, as in the game).
Every picture is a run of its own that replays the lines up to its moment (blocking mode, a step is one
frame), so only the last frame of a run is written and kept. Standard library only.
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

RISE_STEPS = 42                 # 1200 ms at 35 steps a second
TICK_STEPS = 36                 # a world tick of about a second
SIZES = ("672x324", "1280x640")
THEMES = ("wueste", "gelbestadt")
CAMERA = (22.0, 21.8, 28.0)     # eye level, looking east-north-east over the group

FONT = {
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
    "8": "111101111101111", "9": "111101111001111", " ": "000000000000000", "%": "101001010100101",
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110",
    "E": "111100110100111", "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
    "I": "111010010010111", "K": "101101110101101", "L": "100100100100111", "N": "111101101101101",
    "R": "110101110101101", "S": "011100010001110", "T": "111010010010010", "U": "101101101101111",
    "V": "101101101101010", "W": "101101111111101", "Z": "111001010100111", "O": "111101101101111",
    "-": "000000111000000", "M": "101111111101101",
}


def stamp(canvas: list, text: str, x0: int, y0: int, scale: int = 2) -> None:
    ink = bytes((26, 35, 50))
    for k, ch in enumerate(text):
        for i, bit in enumerate(FONT[ch]):
            if bit == "1":
                for dy in range(scale):
                    for dx in range(scale):
                        x = x0 + (k * 4 + i % 3) * scale + dx
                        canvas[y0 + (i // 3) * scale + dy][x * 3:x * 3 + 3] = ink


def group() -> list[tuple[int, int, str]]:
    """The cells of the first two sheets: a block, an own cell, a wall with a tower, a blinker."""
    cells = [(26, 24, "cell"), (27, 24, "cell"), (26, 25, "cell"), (27, 25, "cell"),
             (25, 28, "own"), (26, 28, "cell"), (27, 28, "cell"),
             (30, 22, "wall"), (30, 23, "wall"), (30, 24, "wall"), (30, 25, "tower"),
             (24, 25, "cell")]
    return cells


def life_step(cells: set[tuple[int, int]]) -> set[tuple[int, int]]:
    """One generation of Conway's game on an unbounded plane."""
    counts: dict[tuple[int, int], int] = {}
    for x, y in cells:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    counts[(x + dx, y + dy)] = counts.get((x + dx, y + dy), 0) + 1
    return {c for c, n in counts.items() if n == 3 or (n == 2 and c in cells)}


def glider_cells(gen: int) -> set[tuple[int, int]]:
    """Generation `gen` of a glider that moves up and to the right (north-east)."""
    cells = {(25 + x, 24 + y) for x, y in ((0, 2), (1, 2), (2, 2), (2, 1), (1, 0))}
    for _ in range(gen):
        cells = life_step(cells)
    return cells


def lines_for(sheet: str, step_of: int, tick: int = 0) -> list[str]:
    """Control lines of one picture. step_of: frames after the last change (the picture's moment)."""
    out = ["cam %.2f %.2f %.1f" % CAMERA, "next"]          # the empty window: the first frame ends the snap
    if sheet == "auftauchen":
        if step_of == 0:
            return out + ["next"]
        out += ["cell %d %d %s" % c for c in group()]
        return out + ["next %d" % step_of]
    if sheet == "versinken":
        out += ["cell %d %d %s" % c for c in group()] + ["next %d" % (RISE_STEPS + 2)]
        if step_of == 0:
            return out
        out += ["cell %d %d empty" % (x, y) for x, y, _ in group()]
        return out + ["next %d" % step_of]
    # glider: tick 0 is settled; ticks 1..3 change the generation, the picture is at step_of into tick `tick`
    out += ["cell %d %d cell" % c for c in sorted(glider_cells(0))] + ["next %d" % (RISE_STEPS + 2)]
    for t in range(1, tick + 1):
        now, before = glider_cells(t), glider_cells(t - 1)
        out += ["cell %d %d empty" % c for c in sorted(before - now)]
        out += ["cell %d %d cell" % c for c in sorted(now - before)]
        n = step_of if t == tick else TICK_STEPS
        out.append("next %d" % n)
    return out


def run(wad: str, size: str, lines: list[str], work: str) -> tuple:
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    cmd = [os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless"), "-iwad",
           os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"), "-file",
           os.path.join(ROOT, "assets", "cosmergon.wad"), "-pov-theme", wad, "-pov-control", "-warp", "1", "1",
           "-pov-size", size]
    env = dict(os.environ, POV_OUT=work, POV_EVERY="100000000")
    proc = subprocess.run(cmd, input="\n".join(lines + ["quit"]) + "\n", text=True, env=env, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit("engine failed")
    return ppm2png.read_ppm(os.path.join(work, sorted(os.listdir(work))[-1]))


def write_sheet(path: str, title: str, tiles: list[list[tuple[tuple, str]]]) -> None:
    """tiles[row][col] = ((w, h, pixels), label); a title above, a label above each picture."""
    images = [[(pic, label) for pic, label in row] for row in tiles]
    w, h = images[0][0][0][0], images[0][0][0][1]
    gap, head = 14, 26
    cols, rows = len(images[0]), len(images)
    total_w, total_h = cols * w + (cols + 1) * gap, head + rows * (h + gap + 4)
    canvas = [bytearray(bytes((244, 244, 244)) * total_w) for _ in range(total_h)]
    stamp(canvas, title, gap, 6, 3)
    for r, row in enumerate(images):
        for c, ((_w, _h, pix), label) in enumerate(row):
            x0, y0 = gap + c * (w + gap), head + r * (h + gap + 4) + gap
            stamp(canvas, label, x0, y0 - 12)
            for y in range(h):
                canvas[y0 + y][x0 * 3:(x0 + w) * 3] = pix[y * w * 3:(y + 1) * w * 3]
    ppm2png.write_png(path, total_w, total_h, b"".join(bytes(row) for row in canvas))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "muster-fahrt"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(args.out, "_run")
    try:
        for name in THEMES:
            wad = os.path.join(args.out, "_theme-%s.wad" % name)
            with open(wad, "wb") as handle:
                handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))
            for size in SIZES:
                for sheet in ("auftauchen", "versinken"):
                    tiles = []
                    for r in range(2):
                        row = []
                        for c in range(3):
                            pct = (r * 3 + c) * 20
                            steps = round(RISE_STEPS * pct / 100)
                            row.append((run(wad, size, lines_for(sheet, steps), work), "%d %%" % pct))
                        tiles.append(row)
                    write_sheet(os.path.join(args.out, "%s-%s-%s.png" % (sheet, name, size)),
                                "%s %s %s" % (sheet.upper(), name.upper(), size.replace("x", " ")), tiles)
                tiles = []
                for tick in (1, 2, 3):
                    row = []
                    for k in (12, 24, 36):
                        row.append((run(wad, size, lines_for("glider", k, tick), work), "TICK %d %d" % (tick, k)))
                    tiles.append(row)
                write_sheet(os.path.join(args.out, "glider-%s-%s.png" % (name, size)),
                            "GLIDER %s %s" % (name.upper(), size.replace("x", " ")), tiles)
            os.remove(wad)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
