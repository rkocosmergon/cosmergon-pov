#!/usr/bin/env python3
"""Draw the sample scene in every theme: out/muster/muster-<A|B|C>-<1|2|3>.png, the comparison
muster-heute-1.png (no theme) and the overview uebersicht.png. Standard library only.

    make -C doomgeneric -f Makefile.headless
    python3 tools/make_map.py                      # assets/cosmergon.wad (once)
    python3 tools/theme_samples.py [--out out/muster]

The scene is sent over the control channel (cells, no things: the sprites are still the IWAD's and
would be wrong in a theme's palette). Three viewpoints: 1 eye level on open ground, 2 along the
wall with a tower, 3 standing on a block (eye 169 units), looking over the field.
The frames are written as PPM next to the PNG files and removed again (768 kB each).
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

# viewpoints: (x, y, angle in degrees); 0 = east, 90 = north
VIEWS = (
    (24.3, 4.4, 90.0),      # 1: open ground, patterns near and far
    (32.8, 7.2, 90.0),      # 2: along the wall (x = 34), tower at its far end
    (20.5, 9.5, 80.0),      # 3: standing on the block at (20..21, 9..10)
)


def scene() -> list[tuple[int, int, str]]:
    """The field as (x, y, kind). Patterns of Conway's game, a wall with towers, own cells."""
    cells: dict[tuple[int, int], str] = {}

    def put(pattern, x0, y0, kind="cell"):
        for dx, dy in pattern:
            cells[(x0 + dx, y0 + dy)] = kind

    block = [(0, 0), (1, 0), (0, 1), (1, 1)]
    glider = [(1, 0), (2, 1), (0, 2), (1, 2), (2, 2)]
    blinker_h = [(0, 0), (1, 0), (2, 0)]
    blinker_v = [(0, 0), (0, 1), (0, 2)]
    rpent = [(1, 0), (2, 0), (0, 1), (1, 1), (1, 2)]
    beehive = [(1, 0), (2, 0), (0, 1), (3, 1), (1, 2), (2, 2)]

    put(block, 20, 9)                       # the block of viewpoint 3
    put(block, 17, 14)
    put(block, 29, 17)
    put(block, 22, 28)
    put(glider, 24, 13)
    put(glider, 15, 22)
    put(glider, 28, 26)
    put(blinker_h, 21, 17)
    put(blinker_h, 27, 13)
    put(blinker_v, 18, 19)
    put(blinker_v, 31, 22)
    put(beehive, 24, 20)
    put(beehive, 14, 30)
    # a denser tangle: an r-pentomino and its neighbours
    for dx, dy in rpent:
        cells[(23 + dx, 24 + dy)] = "cell"
    for dx, dy in [(5, 0), (6, 1), (4, 2), (5, 2), (6, 2), (7, 3), (3, 4), (4, 4), (6, 4), (5, 5),
                   (7, 5), (8, 4), (3, 6), (4, 6), (5, 6)]:
        cells[(23 + dx, 24 + dy)] = "cell"
    # own cells
    put(glider, 26, 10, "own")
    put(block, 19, 25, "own")
    put(blinker_h, 22, 15, "own")
    put([(0, 0)], 30, 14, "own")
    # the wall along x = 34 from y = 10 to 30, a spur at its far end, towers
    for y in range(11, 30):
        if y not in (17, 18):               # a gap
            cells[(34, y)] = "wall"
    for x in range(30, 34):
        cells[(x, 30)] = "wall"
    cells[(34, 10)] = "tower"
    cells[(34, 30)] = "tower"
    cells[(15, 33)] = "tower"
    return [(x, y, k) for (x, y), k in sorted(cells.items())]


def control_lines() -> list[str]:
    lines = ["cell %d %d %s" % c for c in scene()]
    for x, y, angle in VIEWS:
        lines += ["cam %.2f %.2f %.1f" % (x, y, angle), "next"]
    lines.append("quit")
    return lines


def run_engine(theme_wad: str | None, work: str) -> list[str]:
    binary = os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless")
    cmd = [binary, "-iwad", os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"),
           "-file", os.path.join(ROOT, "assets", "cosmergon.wad")]
    if theme_wad:
        cmd += ["-pov-theme", theme_wad]
    cmd += ["-pov-control", "-warp", "1", "1"]
    os.makedirs(work, exist_ok=True)
    env = dict(os.environ, POV_OUT=work)
    proc = subprocess.run(cmd, input="\n".join(control_lines()) + "\n", text=True, env=env,
                          capture_output=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit("engine failed (%d)" % proc.returncode)
    frames = sorted(f for f in os.listdir(work) if f.endswith(".ppm"))
    if len(frames) != len(VIEWS):
        raise SystemExit("expected %d frames, got %d" % (len(VIEWS), len(frames)))
    return [os.path.join(work, f) for f in frames]


def sheet(ppms: list[list[str]], out_png: str, gap: int = 12) -> None:
    """Grid: one column per theme, one row per viewpoint, a thin light margin between."""
    images = [[ppm2png.read_ppm(p) for p in col] for col in ppms]
    w, h = images[0][0][0], images[0][0][1]
    cols, rows = len(images), len(images[0])
    total_w, total_h = cols * w + (cols + 1) * gap, rows * h + (rows + 1) * gap
    bg = bytes((244, 244, 244))
    canvas = [bytearray(bg * total_w) for _ in range(total_h)]
    for c in range(cols):
        for r in range(rows):
            _w, _h, pix = images[c][r]
            x0, y0 = gap + c * (w + gap), gap + r * (h + gap)
            for y in range(h):
                canvas[y0 + y][x0 * 3:(x0 + w) * 3] = pix[y * w * 3:(y + 1) * w * 3]
    ppm2png.write_png(out_png, total_w, total_h, b"".join(bytes(row) for row in canvas))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "muster"))
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    work = os.path.join(out, "_ppm")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    try:
        columns = []
        for letter, name in THEME_ORDER:
            wad = os.path.join(out, "_theme-%s.wad" % name)
            with open(wad, "wb") as handle:
                handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))
            ppms = run_engine(wad, os.path.join(work, name))
            os.remove(wad)
            for i, ppm in enumerate(ppms, 1):
                w, h, pix = ppm2png.read_ppm(ppm)
                ppm2png.write_png(os.path.join(out, "muster-%s-%d.png" % (letter, i)), w, h, pix)
            columns.append(ppms)
        today = run_engine(None, os.path.join(work, "heute"))
        w, h, pix = ppm2png.read_ppm(today[0])
        ppm2png.write_png(os.path.join(out, "muster-heute-1.png"), w, h, pix)
        sheet(columns, os.path.join(out, "uebersicht.png"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
