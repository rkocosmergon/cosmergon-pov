#!/usr/bin/env python3
"""Draw the sample scene in every theme: out/muster/muster-<A|B|C>-<1|2|3>.png, the comparison
muster-heute-1.png (no theme) and the overview uebersicht.png. Standard library only.

    make -C doomgeneric -f Makefile.headless
    python3 tools/make_map.py                      # assets/cosmergon.wad (once)
    python3 tools/theme_samples.py [--out out/muster] [--size 672x324]
    python3 tools/theme_samples.py --fine          # out/muster-fein: 672x324 and 1280x640
    python3 tools/theme_samples.py --detail        # out/muster-detail: six viewpoints, A and B, two sizes, sheets
    python3 tools/theme_samples.py --sky           # out/muster-himmel: the sky over the day, all round, clouds drifting

The scene is sent over the control channel (cells, no things: the sprites are still the IWAD's and
would be wrong in a theme's palette). Three viewpoints: 1 eye level on open ground, 2 along the
wall with a tower, 3 standing on a block (eye 169 units), looking over the field.
The frames are written as PPM next to the PNG files and removed again (768 kB each at the default
size, 2.4 MB at 1280 x 640; the twelve of one run exist together).

Without --size the engine draws its default (320 x 200, shown at 640 x 400) and the files are
named as before. With --size <w>x<h> the engine draws exactly that many points (-pov-size, one point
a pixel) and the size is part of every file name: muster-A-1-672x324.png, uebersicht-672x324.png.
"""

from __future__ import annotations

import argparse
import math
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
VIEWS_BASIC = (
    (24.3, 4.4, 90.0),      # 1: open ground, patterns near and far
    (32.8, 7.2, 90.0),      # 2: along the wall (x = 34), tower at its far end
    (20.5, 9.5, 80.0),      # 3: standing on the block at (20..21, 9..10), eye 169 units
)
# the detail set (--detail): the same scene, six views
VIEWS = (
    (24.3, 4.4, 90.0),      # 1: eye level, open ground, cells near and far
    (16.1, 12.9, 38.0),     # 2: close to a block, slanting (detail from the near)
    (32.8, 7.2, 90.0),      # 3: along the wall (x = 34) with a tower at its far end
    (23.6, 2.6, 88.0),      # 4: own cells next to foreign ones
    (20.5, 9.5, 80.0),      # 5: standing on the block at (20..21, 9..10), eye 169 units
    (3.5, 22.0, 4.0),       # 6: long view over open ground to the wall
)
VIEW_NAMES = ("Augenhoehe", "nah-schraeg", "Mauer-Turm", "eigene", "auf-Zelle", "lange-Sicht")


def scene(rich: bool = True) -> list[tuple[int, int, str]]:
    """The field as (x, y, kind). Patterns of Conway's game, a wall with towers, own cells; `rich`
    adds groups for the detail views (tools/measure_size.py keeps the basic scene)."""
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
    if rich:
        # a long building, a second block group, a loose wall, a second tower near the start
        for x in range(8, 13):
            for y in range(18, 21):
                cells[(x, y)] = "cell"
        cells[(10, 19)] = "empty"
        for x in range(26, 29):
            cells[(x, 4)] = "wall"
        cells[(29, 4)] = "tower"
        put(glider, 12, 5)
        put(block, 30, 6)
        put(blinker_h, 14, 9)
        put(rpent, 38, 20)
        put(beehive, 39, 14)
        for x in range(36, 41):
            cells[(x, 26)] = "wall"
        # own cells next to foreign ones, in front of the start for view 4
        put([(0, 0), (1, 0), (1, 1)], 21, 6, "own")
        put([(0, 0), (0, 1)], 24, 6)
        put([(0, 0)], 23, 7, "own")
        put(blinker_v, 26, 6, "own")
        put(blinker_h, 21, 10, "own")
    return [(x, y, k) for (x, y), k in sorted(cells.items()) if k != "empty"]


def control_lines(views=None, rich: bool = True) -> list[str]:
    lines = ["cell %d %d %s" % c for c in scene(rich)]
    for x, y, angle in (VIEWS if views is None else views):
        lines += ["cam %.2f %.2f %.1f" % (x, y, angle), "next"]
    lines.append("quit")
    return lines


def run_engine(theme_wad: str | None, work: str, size: str | None = None, views=None,
               rich: bool = True) -> list[str]:
    views = VIEWS if views is None else views
    binary = os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless")
    cmd = [binary, "-iwad", os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"),
           "-file", os.path.join(ROOT, "assets", "cosmergon.wad")]
    if theme_wad:
        cmd += ["-pov-theme", theme_wad]
    cmd += ["-pov-control", "-warp", "1", "1"]
    if size:
        cmd += ["-pov-size", size]
    os.makedirs(work, exist_ok=True)
    env = dict(os.environ, POV_OUT=work)
    proc = subprocess.run(cmd, input="\n".join(control_lines(views, rich)) + "\n", text=True, env=env,
                          capture_output=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit("engine failed (%d)" % proc.returncode)
    frames = sorted(f for f in os.listdir(work) if f.endswith(".ppm"))
    if len(frames) != len(views):
        raise SystemExit("expected %d frames, got %d" % (len(views), len(frames)))
    return [os.path.join(work, f) for f in frames]


FONT = {  # 3 x 5 digits and a few signs, one string a row
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
    "8": "111101111101111", "9": "111101111001111", ":": "000010000010000", " ": "000000000000000",
    "s": "011100110001110", "+": "000010111010000", "x": "101101010101101",
    "E": "111100111100111", "N": "101111111101101", "W": "101101111111101", "S": "111100111001111",
}


def stamp(canvas: list, text: str, x0: int, y0: int, scale: int = 2, ink: bytes = bytes((26, 35, 50))) -> None:
    """Draw `text` (FONT) into the canvas rows (bytearrays of RGB) at x0, y0."""
    for k, ch in enumerate(text):
        for i, bit in enumerate(FONT[ch]):
            if bit == "1":
                for dy in range(scale):
                    for dx in range(scale):
                        x = x0 + (k * 4 + i % 3) * scale + dx
                        canvas[y0 + (i // 3) * scale + dy][x * 3:x * 3 + 3] = ink


def sheet(ppms: list[list[str]], out_png: str, gap: int = 12, labels: list[list[str]] | None = None) -> None:
    """Grid: one column per theme, one row per viewpoint, a thin light margin between. `labels` (same shape)
    are written into the margin above each picture (gap at least 14)."""
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
            if labels:
                stamp(canvas, labels[c][r], x0, y0 - 12)
    ppm2png.write_png(out_png, total_w, total_h, b"".join(bytes(row) for row in canvas))


def write_all(out: str, size: str | None) -> None:
    """The nine theme pictures, the comparison and the overview, in `size` (None: the default)."""
    work = os.path.join(out, "_ppm")
    suffix = "-" + size if size else ""
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    try:
        columns = []
        for letter, name in THEME_ORDER:
            wad = os.path.join(out, "_theme-%s.wad" % name)
            with open(wad, "wb") as handle:
                handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))
            ppms = run_engine(wad, os.path.join(work, name), size, VIEWS_BASIC, rich=False)
            os.remove(wad)
            for i, ppm in enumerate(ppms, 1):
                w, h, pix = ppm2png.read_ppm(ppm)
                ppm2png.write_png(os.path.join(out, "muster-%s-%d%s.png" % (letter, i, suffix)), w, h, pix)
            columns.append(ppms)
        today = run_engine(None, os.path.join(work, "heute"), size, VIEWS_BASIC, rich=False)
        w, h, pix = ppm2png.read_ppm(today[0])
        ppm2png.write_png(os.path.join(out, "muster-heute-1%s.png" % suffix), w, h, pix)
        sheet(columns, os.path.join(out, "uebersicht%s.png" % suffix))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_detail(out: str, size: str) -> None:
    """Six viewpoints in the themes A and B (C only in the overview), the overview sheet of this size.
    The PPM frames of one size (18 of them, at most 2.5 MB each) exist until the overview is written."""
    work = os.path.join(out, "_ppm")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    try:
        columns = []
        for letter, name in THEME_ORDER:
            wad = os.path.join(out, "_theme-%s.wad" % name)
            with open(wad, "wb") as handle:
                handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))
            ppms = run_engine(wad, os.path.join(work, name), size)
            os.remove(wad)
            for i, ppm in enumerate(ppms, 1):
                w, h, pix = ppm2png.read_ppm(ppm)
                if letter in ("A", "B"):
                    ppm2png.write_png(os.path.join(out, "muster-%s-%d-%s-%s.png" % (letter, i, VIEW_NAMES[i - 1], size)),
                                      w, h, pix)
            columns.append(ppms)
            if letter == "C":
                sheet(columns, os.path.join(out, "uebersicht-%s.png" % size))
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- the sky (--sky): tools/sky_samples.py


def berlin_minutes() -> int:
    """Minutes since midnight now in Berlin (the sender's default; the program itself has no clock)."""
    import datetime
    import zoneinfo
    now = datetime.datetime.now(zoneinfo.ZoneInfo("Europe/Berlin"))
    return now.hour * 60 + now.minute


def clock(minute: int) -> str:
    return "%02d:%02d" % (minute // 60, minute % 60)


def texture_sheets(out: str) -> None:
    """Every variant of every kind side by side, 1 texel to 1 point (a texture is 256 points, 128 units):
    texturbogen-<theme>-<n>.png. Wall faces east/west and one row of the shaded sides, the tops, the ground."""
    os.makedirs(out, exist_ok=True)
    surf = make_theme.surfaces()
    for letter, name in THEME_ORDER[:2]:
        pal = make_theme.build_palette(make_theme.THEMES[name])

        def tile(key):
            if key in surf["tex"]:
                return [bytes(r) for r in surf["tex"][key]]
            data = surf["flats"][key]
            return [data[i * 256:(i + 1) * 256] for i in range(256)]

        pages = []
        for kind, (_l, dens, _s) in make_theme.WALL_KINDS.items():
            pages.append(("seiten-" + kind, [make_theme.wall_names(kind, v)[0] for v in range(len(dens))]
                          + [make_theme.wall_names(kind, v)[1] for v in range(min(3, len(dens)))]))
        pages.append(("boden", [make_theme.ground_name(v, e) for v in range(len(make_theme.GROUND_DENS)) for e in (3, 0)]))
        pages.append(("oben", [make_theme.top_name(k, v) for k in make_theme.TOP_STYLES
                               for v in range(len(make_theme.TOP_STYLES[k][1]))]))
        for page, names in pages:
            cols = 4
            gap = 10
            rows = (len(names) + cols - 1) // cols
            total_w, total_h = cols * 256 + (cols + 1) * gap, rows * 256 + (rows + 1) * gap
            canvas = [bytearray(bytes((244, 244, 244)) * total_w) for _ in range(total_h)]
            for k, key in enumerate(names):
                x0, y0 = gap + (k % cols) * (256 + gap), gap + (k // cols) * (256 + gap)
                rows_k = tile(key)
                for y in range(256):
                    canvas[y0 + y][x0 * 3:(x0 + 256) * 3] = b"".join(bytes(pal[v]) for v in rows_k[y])
            ppm2png.write_png(os.path.join(out, "texturbogen-%s-%s.png" % (letter, page)), total_w, total_h,
                              b"".join(bytes(r) for r in canvas))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None)
    ap.add_argument("--size", help="<width>x<height> in points (default: the engine's 320 x 200 shown at 640 x 400)")
    ap.add_argument("--fine", action="store_true", help="672x324 and 1280x640 into out/muster-fein")
    ap.add_argument("--sky", action="store_true",
                    help="the sky over the day, all round, the clouds, a walk, the haze and the levels, themes A and B, "
                         "672x324 and 1280x640, into out/muster-himmel (tools/sky_samples.py)")
    ap.add_argument("--detail", action="store_true",
                    help="six viewpoints, themes A and B, 672x324 and 1280x640, overview and texture sheets "
                         "into out/muster-detail")
    args = ap.parse_args()
    if args.sky:
        out = os.path.abspath(args.out or os.path.join(ROOT, "out", "muster-himmel"))
        import sky_samples
        for size in ("672x324", "1280x640"):
            sky_samples.write_sky(out, size)
    elif args.detail:
        out = os.path.abspath(args.out or os.path.join(ROOT, "out", "muster-detail"))
        for size in ("672x324", "1280x640"):
            write_detail(out, size)
        texture_sheets(out)
    elif args.fine:
        out = os.path.abspath(args.out or os.path.join(ROOT, "out", "muster-fein"))
        for size in ("672x324", "1280x640"):
            write_all(out, size)
    else:
        out = os.path.abspath(args.out or os.path.join(ROOT, "out", "muster"))
        write_all(out, args.size)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
