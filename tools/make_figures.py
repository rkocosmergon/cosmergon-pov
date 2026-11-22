#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""The figure templates (`assets/figures/`) from rendered pictures. Standard library only, deterministic.

    python3 tools/make_figures.py <picture-dir> [-o assets/figures] [--kind bird]

Only needed to change the figures; `tools/make_theme.py` builds a theme from the templates alone.

<picture-dir> holds one folder per kind (marauder, monster, bird, corpse, loot) with the rendered pictures: 8 directions
`<frame>_dir0.png` .. `_dir7.png` (direction 0 = the figure faces the viewer, 1 = it turns towards the viewer's right, and so
on counter-clockwise seen from above; a single `idle_dir0.png` for corpse and loot), RGBA, transparent background, orthographic,
160 render points to the metre, the figure's origin 16 points above the bottom edge. The figures are our own work, made as
3D models by a script in the Blender tool chain of the project (`COSMERGON.md`, "Own figures").

Each picture is reduced by 5 (160 -> 32 points to the metre, one point = one unit of the engine, as the walls' 128 units are
a cell of 4 m). Every point is put on the nearest colour of a table of source colours -> palette indices of the roles
(cell/own/wall/tower, the navy line) and cut to its box; the result is a template (`figures.py`). The indices are those of
the theme layout, so the templates are the same for every theme.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import figures  # noqa: E402
import make_theme  # noqa: E402
import theme_art as art  # noqa: E402

STEP = 5                    # render points per sprite point (160 per metre -> 32 per metre = 1 unit)
FOOT_MARGIN = 16            # render points between the origin and the bottom edge of a picture
LINE_SRC = (90, 103, 122)   # the outline colour as rendered (navy drawn through the standard view transform)
LINE_TOL = 18

# source colour -> where it goes: (role, face key), the keys of theme_art.I_ROLE, or "navy". Only the keys t* (top) and y*
# (side) are used: the COLORMAP hazes the x* keys one step earlier than a sprite's light does, so a figure in them would look
# hazed at 10 m.
DARK = {(39, 45, 57): ("tower", "y1"), (39, 39, 51): ("tower", "y1"), (45, 33, 39): ("tower", "y1"),
        (57, 63, 75): ("tower", "y0"), (63, 63, 75): ("tower", "y0"), (51, 51, 63): ("tower", "y0"),
        (81, 81, 93): ("tower", "t1"), (81, 93, 111): ("tower", "t1"), (69, 81, 93): ("tower", "t1"),
        (141, 129, 117): ("tower", "t0"), (111, 111, 111): ("tower", "t0"),
        (141, 81, 27): ("wall", "t0"), (135, 87, 57): ("wall", "t1"), (111, 69, 45): ("wall", "y1"),
        (123, 93, 93): ("wall", "t1"), (51, 3, 9): ("wall", "y1"), (69, 15, 15): ("wall", "y1"),
        (255, 207, 63): ("own", "t0"), (219, 183, 87): ("own", "t0"),
        (165, 129, 51): ("own", "t1"), (159, 123, 39): ("own", "t1"), (135, 105, 45): ("own", "t1")}
LOOT = {(87, 93, 105): ("cell", "t0"), (57, 57, 63): ("cell", "y1"), (111, 117, 129): ("cell", "t0"),
        (69, 75, 87): ("cell", "y0"), (153, 63, 63): ("wall", "t0"), (123, 87, 99): ("wall", "t1")}
# the monster: the body in the darkest tone of the layout (the navy of the lines), limbs and armour in the tower's tops, the
# mouth in the navy with teeth, eyes and spores in the tone of `own` (bright in every theme)
MONSTER = {(44, 33, 65): "navy", (22, 16, 33): "navy", (77, 60, 100): ("tower", "y1"), (38, 30, 50): ("tower", "y1"),
           (114, 97, 138): ("tower", "y0"), (57, 48, 69): ("tower", "y0"), (149, 44, 36): "navy", (75, 22, 18): "navy",
           (255, 206, 63): ("own", "t0"), (249, 243, 137): ("own", "t0"), (174, 164, 146): ("own", "t0")}
BIRD = {(41, 39, 59): ("tower", "y1"), (77, 69, 104): ("tower", "y0"), (124, 115, 144): ("tower", "t0"),
        (183, 162, 61): ("own", "t0"), (174, 137, 47): ("wall", "t0"), (93, 87, 86): ("tower", "y0"),
        (255, 237, 160): ("own", "t0")}
# kind -> (picture name pattern, table); directions 0..7 where the pattern has %d. A tuple of patterns: one look each, in the
# order of the frames (the bird: glide, wings up, wings down, perched), written as one strip per direction
KINDS = {
    "marauder": ("idle_dir%d.png", DARK),
    "monster": ("idle_dir%d.png", MONSTER),
    "bird": (("glide_dir%d.png", "flap_a_dir%d.png", "flap_b_dir%d.png", "sit_dir%d.png"), BIRD),
    "corpse": ("idle_dir0.png", DARK),
    "loot": ("idle_dir0.png", LOOT),
}


def target_index(target) -> int:
    return art.I_OUTLINE if target == "navy" else art.I_ROLE[target[0]][target[1]]


def quantiser(table: dict):
    """rgb -> palette index (cached). The outline colour wins within LINE_TOL; else the nearest source colour."""
    cache: dict[tuple[int, int, int], int] = {}

    def dist(a, b):
        return sum((a[i] - b[i]) ** 2 for i in range(3))

    def index(rgb):
        got = cache.get(rgb)
        if got is None:
            if dist(rgb, LINE_SRC) <= LINE_TOL ** 2:
                got = art.I_OUTLINE
            else:
                best = min(table, key=lambda src: dist(rgb, src))
                got = target_index(table[best])
            cache[rgb] = got
        return got
    return index


def reduce_picture(width: int, height: int, rgba: bytes, table: dict):
    """A render as a grid of palette indices (None = transparent): blocks of STEP x STEP points, the grid laid so that the
    origin (centre column, FOOT_MARGIN above the bottom) is on a block edge. Returns (grid, origin column, foot row)."""
    quant = quantiser(table)
    col0 = (width // 2) % STEP
    foot = height - FOOT_MARGIN
    row0 = foot % STEP
    nbx, nby = (width - col0) // STEP, (height - row0) // STEP
    grid: list[list] = [[None] * nbx for _ in range(nby)]
    for by in range(nby):
        for bx in range(nbx):
            seen: Counter = Counter()
            opaque = 0
            for y in range(row0 + by * STEP, row0 + by * STEP + STEP):
                base = (y * width + col0 + bx * STEP) * 4
                for x in range(STEP):
                    r, g, b, a = rgba[base + x * 4:base + x * 4 + 4]
                    if a >= 128:
                        opaque += 1
                        seen[quant((r, g, b))] += 1
            if opaque * 2 <= STEP * STEP:
                continue
            lines = seen.pop(art.I_OUTLINE, 0)
            if lines * 2 >= opaque or not seen:
                grid[by][bx] = art.I_OUTLINE
            else:
                grid[by][bx] = seen.most_common(1)[0][0]
    return grid, (width // 2 - col0) // STEP, (foot - row0) // STEP


def thin_edge(grid) -> None:
    """The engine draws the outline round a thing on the side of the lower rank (the ground), so a line point on the rim of a
    sprite is a second line: it takes the colour of the body next to it. A rim that is only line (a wing, a barrel) stays.
    A line point with no line next to it is a speck of the reduction and takes the colour round it as well."""
    h, w = len(grid), len(grid[0])

    def at(y, x):
        return grid[y][x] if 0 <= y < h and 0 <= x < w else None
    fixes = []
    for y in range(h):
        for x in range(w):
            if grid[y][x] != art.I_OUTLINE:
                continue
            ring = [at(y + dy, x + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]
            lone = art.I_OUTLINE not in ring            # a single line point (a speck), not part of a line
            if not lone and all(at(y + dy, x + dx) is not None for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                continue
            body = Counter(at(y + dy, x + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                           if (dy or dx) and at(y + dy, x + dx) not in (None, art.I_OUTLINE))
            if body:
                fixes.append((y, x, body.most_common(1)[0][0]))
    for y, x, value in fixes:
        grid[y][x] = value


def crop(grid, origin_col: int, foot_row: int):
    """The grid cut to its box: (cropped grid, left offset, top offset) as the Doom picture wants them."""
    rows = [y for y, line in enumerate(grid) if any(v is not None for v in line)]
    cols = [x for x in range(len(grid[0])) if any(line[x] is not None for line in grid)]
    top, bottom, left, right = rows[0], rows[-1], cols[0], cols[-1]
    return [line[left:right + 1] for line in grid[top:bottom + 1]], origin_col - left, foot_row - top


def make_templates(picture_dir: str, out_dir: str, only=None) -> list[str]:
    palette = make_theme.build_palette(dict(make_theme.THEMES["wueste"]))
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for kind, (pattern, table) in KINDS.items():
        if only and kind not in only:
            continue
        rotations = figures.KINDS[kind][2]
        patterns = pattern if isinstance(pattern, tuple) else (pattern,)
        assert len(patterns) == figures.FRAMES.get(kind, 1), kind
        for direction in range(8) if rotations else (0,):
            looks = []
            for one in patterns:
                width, height, rgba = figures.read_png(os.path.join(picture_dir, kind, one % direction if rotations else one))
                grid, origin, foot = reduce_picture(width, height, rgba, table)
                thin_edge(grid)
                looks.append(crop(grid, origin, foot))
            path = os.path.join(out_dir, figures.template_name(kind, direction))
            if len(looks) == 1:
                figures.write_template(path, *looks[0], palette)
            else:
                figures.write_strip(path, looks, palette)
            written.append(path)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pictures")
    ap.add_argument("-o", "--output", default=figures.FIGURES_DIR)
    ap.add_argument("--kind", action="append", choices=sorted(KINDS), help="only this kind (repeatable); default all")
    args = ap.parse_args()
    written = make_templates(args.pictures, args.output, args.kind)
    print("wrote %d templates to %s" % (len(written), args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
