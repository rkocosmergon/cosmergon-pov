#!/usr/bin/env python3
"""Generate a look ("theme") as a PWAD. Standard library only, deterministic, no outside images.

    python3 tools/make_theme.py <name> [-o assets/theme-<name>.wad]
    python3 tools/make_theme.py --list

A theme replaces, for the program, everything the picture is coloured from:
  PLAYPAL   256 colours: the surfaces of the theme in their stages, a sky gradient, navy joints
  COLORMAP  34 tables, no dimming with distance (only the joints fold away, see below)
  PNAMES, TEXTURE1, TEXTURE2   the wall textures, one per kind and wall direction
            (PEX/PEY empty, PCX/PCY cell, PWX/PWY wall, PTX/PTY tower, POX/POY own cell),
            plus STARTAN3 and STONE3 (named by the map) and SKY1
  F_START..F_END   the floor of each kind (one colour; the ground has tile joints)
  POVTHEME  switches, the light level of all sectors, class and rank of each colour index for
            the outline pass (pov_control.c)
Load with `-pov-theme <file>` (the file is added after the map, its lumps win). The theme's own
flat range replaces the IWAD's, so only the six flats below exist while it is loaded.

Look (ligne claire): flat surfaces, each in two
stages (surface and a darker side, no gradient on bodies); outline and fine joints in the navy of
the project, never black; the sky nearly flat with a few flat shapes. A block has three faces
(top, side east/west, side north/south) but two stages: the third is a second palette entry with
the colour of another, so the outline pass can tell the faces apart.

Joints are drawn into the textures with "twin" indices (navy). The engine picks the COLORMAP row
from the distance; with the light level LIGHT a surface starts at row S (floors S, walls whose
edge runs along y: S - 4, along x: S + 4, r_segs.c) and the row is S - 1280 / distance (r_draw,
r_plane, r_main light tables). From row S - FOLD_Q on, a twin maps to the colour of its surface:
the joints are drawn up to 1280 / (FOLD_Q + 1) units and vanish beyond.

Joints are 1 texel wide (the picture is drawn at the window's own size, one point a pixel; before it was
320 x 200 shown twice as large, with 2 texel joints). A joint across the view (a floor joint) is thinner
than one picture row beyond sqrt(eye height * w / 2) units and then breaks into dashes: 117 units at 672
points wide, 162 at 1280. So the floor folds at 160 units (FOLD_Q floor 7; looked at in 672 x 324: 213
shows dashes, 160 is clean). Wall seams stay wider than a point up to w / 2 units, so the walls fold at
320 units (FOLD_Q 3). The light index of a wall is normalised to a 320 wide picture in the engine, so these
distances hold at every picture size.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

NAVY = (0x1A, 0x23, 0x32)
SKY_ROWS = 100            # rows above the horizon that can show sky (full screen view: centre 100)
SKY_FIRST = 156           # first palette index of the gradient: one index per row, 156..255
SKY_COLS = 1024           # the sky texture runs once around (angle >> 22)
SKY_HEIGHT = 128

# Palette indices (fixed layout, the same in every theme).
I_OUTLINE = 0
I_GROUND = 1
I_GROUND_SHADE = 2
I_BORDER = 3
# per solid kind: top, side east/west, side north/south
I_CELL = (8, 9, 10)
I_OWN = (11, 12, 13)
I_WALL = (14, 15, 16)
I_TOWER = (17, 18, 19)
I_BAND = (20, 21, 22)        # tower band: top (unused), side east/west, side north/south
I_TOWER_TOP = 4
I_SHAPES = (100, 101)        # sky shapes: disc, cloud
TWIN_FIRST = 32
LIGHT = 160                  # light level of all sectors: lightnum 10, colormap start row 20
FOLD_Q = {"floor": 7, "x": 3, "y": 3}   # joints vanish beyond about 1280 / (q + 1) units (floor 160, walls 320)

SHADE = 0.88

# base index -> orientation of the surface it belongs to: floor, side east/west, side north/south
TWINS = [(I_GROUND, "floor")] + [
    (idx, orient) for kind in (I_CELL, I_OWN, I_WALL, I_TOWER, I_BAND)
    for idx, orient in ((kind[1], "x"), (kind[2], "y"))]
TWIN_OF = {base: TWIN_FIRST + i for i, (base, _o) in enumerate(TWINS)}


def shade(rgb):
    return tuple(max(0, min(255, round(c * SHADE))) for c in rgb)


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def hexrgb(text):
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))


# A theme is data. Keys ending in _shade are optional (else the base colour, 12 percent darker).
THEMES = {
    "wueste": {
        "label": "A Wueste",
        "sky_top": "#b4e4e2", "sky_horizon": "#e2f3ea",
        "ground": "#ecd9a8", "border": "#d6b574",
        "cell": "#5ab4d8", "cell_shade": "#4a9cc4",
        "own": "#e8c547", "wall": "#c86b3a",
        "tower": "#f6f0e0", "band": "#c86b3a", "tower_top": "#c86b3a",
        "disc": "#fffaea", "cloud": "#ffffff",
    },
    "gelbestadt": {
        "label": "B Gelbe Stadt",
        "sky_top": "#f3e39a", "sky_horizon": "#f7ecc0",
        "ground": "#efe4bc", "border": "#d9c68e",
        "cell": "#6aa6d6", "cell_shade": "#4a88c4",
        "own": "#e8843a", "wall": "#dcb25a",
        "tower": "#f8f2de", "band": "#c8683a", "tower_top": "#c8683a",
        "disc": "#fff8dc", "cloud": "#fbf3cc",
    },
    "blaustadt": {
        "label": "C Blaue Stadt",
        "sky_top": "#dde9f6", "sky_horizon": "#f5f9fd",
        "ground": "#cfdbe8", "border": "#b0c3d8",
        "cell": "#8fb4de", "cell_shade": "#6f98cc",
        "own": "#ff8a2a", "wall": "#5b86bf",
        "tower": "#e6eef8", "band": "#3f6aa8", "tower_top": "#3f6aa8",
        "disc": "#ffffff", "cloud": "#ffffff",
    },
}


def build_palette(theme: dict) -> list[tuple[int, int, int]]:
    pal = [(255, 0, 255)] * 256        # unused entries: magenta, so a stray index is plain
    pal[I_OUTLINE] = NAVY
    g = hexrgb(theme["ground"])
    pal[I_GROUND], pal[I_GROUND_SHADE] = g, shade(g)
    pal[I_BORDER] = hexrgb(theme["border"])
    pal[I_TOWER_TOP] = hexrgb(theme["tower_top"])
    for idx, key in ((I_CELL, "cell"), (I_OWN, "own"), (I_WALL, "wall"),
                     (I_TOWER, "tower"), (I_BAND, "band")):
        base = hexrgb(theme[key])
        dark = hexrgb(theme[key + "_shade"]) if key + "_shade" in theme else shade(base)
        pal[idx[0]], pal[idx[1]], pal[idx[2]] = base, base, dark
    for idx, key in zip(I_SHAPES, ("disc", "cloud")):
        pal[idx] = hexrgb(theme[key])
    top, hor = hexrgb(theme["sky_top"]), hexrgb(theme["sky_horizon"])
    for row in range(SKY_ROWS):
        pal[SKY_FIRST + row] = mix(top, hor, row / (SKY_ROWS - 1))
    for base, twin in TWIN_OF.items():
        pal[twin] = NAVY
    return pal


def playpal(pal) -> bytes:
    # The program does not apply its gamma table to a theme (i_video.c, pov_gamma_off): exact colours.
    one = bytearray()
    for r, g, b in pal:
        one += bytes((r, g, b))
    return bytes(one) * 14      # 14 palettes of the format; the program only uses the first


def nearest(pal, rgb) -> int:
    best, best_d = 0, 1 << 30
    for i, p in enumerate(pal):
        d = sum((p[k] - rgb[k]) ** 2 for k in range(3))
        if d < best_d:
            best, best_d = i, d
    return best


def fold_levels() -> dict[int, int]:
    """First COLORMAP row at which each twin maps to its base colour (32 = never)."""
    start = (15 - (LIGHT >> 4)) * 4
    offset = {"floor": 0, "x": -4, "y": 4}      # vertical edges (x const) get lightnum + 1
    out = {}
    for base, orient in TWINS:
        out[TWIN_OF[base]] = start + offset[orient] - FOLD_Q[orient]
    return out


def colormap(pal) -> bytes:
    fold = fold_levels()
    base_of = {TWIN_OF[b]: b for b in TWIN_OF}
    out = bytearray()
    for row in range(32):                # 32 light levels: no dimming, only the twins fold
        table = bytearray(range(256))
        for twin, first in fold.items():
            if row >= first:
                table[twin] = base_of[twin]
        out += table
    # table 32: the invulnerability table of the format (grey, inverted), unused by this program
    for p in pal:
        grey = 255 - round(0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2])
        out.append(nearest(pal, (grey, grey, grey)))
    out += bytes([I_OUTLINE]) * 256       # table 33: all "black" (the darkest entry, the navy)
    assert len(out) == 34 * 256
    return bytes(out)


def column_patch(columns: list[list[int]]) -> bytes:
    """A picture lump: every column is one post (the full height), equal columns stored once."""
    width, height = len(columns), len(columns[0])
    head = struct.pack("<hhhh", width, height, 0, 0)
    offsets, body = [], bytearray()
    base = 8 + 4 * width
    seen: dict[bytes, int] = {}
    for col in columns:
        post = bytes([0, height, 0]) + bytes(col) + bytes([0, 0xFF])
        if post not in seen:        # equal columns share their data: the engine keeps column
            seen[post] = base + len(body)       # offsets in 16 bits, a 1024 wide sky would overflow
            body += post
        offsets.append(seen[post])
    return head + struct.pack(f"<{width}i", *offsets) + bytes(body)


def name8(text: str) -> bytes:
    return text.encode("ascii").ljust(8, b"\0")


# ---- surfaces: a grid [row][column] of palette indices, 128 x 128 (row 0 = top of the face)

def blank(idx: int, size: int = 128) -> list[list[int]]:
    return [[idx] * size for _ in range(size)]


def rect(grid, x0, y0, x1, y1, idx):
    """Outline of a rectangle, one pixel wide."""
    for x in range(x0, x1 + 1):
        grid[y0][x] = grid[y1][x] = idx
    for y in range(y0, y1 + 1):
        grid[y][x0] = grid[y][x1] = idx


def hline(grid, y, idx, x0=0, x1=127):
    for x in range(x0, x1 + 1):
        grid[y][x] = idx


def vline(grid, x, idx, y0=0, y1=127):
    for y in range(y0, y1 + 1):
        grid[y][x] = idx


def face_cell(side: int) -> list[list[int]]:
    """A block: one seam at mid height and a small hatch."""
    t = TWIN_OF[side]
    g = blank(side)
    hline(g, 63, t)
    rect(g, 50, 18, 77, 36, t)
    return g


def face_wall(side: int) -> list[list[int]]:
    """A wall (64 high): slab seams, the vertical ones staggered."""
    t = TWIN_OF[side]
    g = blank(side)
    hline(g, 31, t)
    for x in (0, 64):
        vline(g, x, t, 0, 30)
    for x in (32, 96):
        vline(g, x, t, 32, 63)
    return g


def face_tower(side: int, band: int) -> list[list[int]]:
    """A tower: a coloured band near the top, one seam below, a slit."""
    t = TWIN_OF[side]
    g = blank(side)
    for y in range(12, 26):
        for x in range(128):
            g[y][x] = band
    hline(g, 71, t)
    rect(g, 56, 36, 71, 56, t)
    return g


def ground_flat() -> bytes:
    """64 x 64 floor tile: a joint, 1 texel wide, along each of two edges (a tile grid, one tile = 64 units)."""
    t = TWIN_OF[I_GROUND]
    out = bytearray([I_GROUND] * 4096)
    for i in range(64):
        out[i] = t                                # row 0
        out[i * 64] = t                           # column 0
    return bytes(out)


def sky_columns() -> list[list[int]]:
    """Gradient rows plus a few flat shapes. Column c lies at angle c / 1024 of the full circle
    (0 = east, 90 degrees = column 256); at the centre of the view a pixel is about one column."""
    cols = [[SKY_FIRST + min(r, SKY_ROWS - 1) for r in range(SKY_HEIGHT)] for _ in range(SKY_COLS)]

    def shape(cx, cy, radius, index, flat=0.0):
        # a capsule: the segment of half length `flat` (in columns) widened by the radius
        for c in range(SKY_COLS):
            dc = min((c - cx) % SKY_COLS, (cx - c) % SKY_COLS)
            for r in range(SKY_ROWS):
                dx = max(0.0, dc - flat)
                if dx * dx + (r - cy) ** 2 <= radius * radius:
                    cols[c][r] = index

    shape(256, 44, 28, I_SHAPES[0])                 # the big pale disc, north (90 degrees)
    shape(150, 20, 5, I_SHAPES[1], flat=60)         # flat cloud capsules
    shape(372, 14, 4, I_SHAPES[1], flat=44)
    shape(60, 33, 4, I_SHAPES[1], flat=70)
    shape(690, 26, 5, I_SHAPES[1], flat=64)
    shape(930, 18, 4, I_SHAPES[1], flat=50)
    return cols


def theme_lump() -> bytes:
    cls = list(range(256))
    rank = [3] * 256
    for i in range(SKY_FIRST, 256):
        cls[i], rank[i] = 0, 0           # all gradient rows are one surface: no lines in the sky
    for i in I_SHAPES:
        rank[i] = 0
    rank[I_GROUND] = rank[I_GROUND_SHADE] = 1
    rank[I_BORDER] = 2
    for kind in (I_CELL, I_OWN, I_WALL, I_TOWER, I_BAND):
        rank[kind[0]] = 5                # top: keeps its area, the line sits on the side
        rank[kind[1]] = 4
        rank[kind[2]] = 3
    rank[I_TOWER_TOP] = 5
    for base, twin in TWIN_OF.items():   # a joint counts as the surface it lies in
        cls[twin], rank[twin] = cls[base], rank[base]
    # version 1, outline on, outline colour index, light level of all sectors
    return b"POVT" + bytes([1, 1, I_OUTLINE, LIGHT]) + bytes(cls) + bytes(rank)


def build_theme(name: str) -> list[tuple[str, bytes]]:
    theme = THEMES[name]
    pal = build_palette(theme)
    lumps: list[tuple[str, bytes]] = [
        ("POVTHEME", theme_lump()),
        ("PLAYPAL", playpal(pal)),
        ("COLORMAP", colormap(pal)),
    ]

    def transpose(grid):
        return [[grid[r][c] for r in range(len(grid))] for c in range(len(grid[0]))]

    faces = {                        # texture name -> grid
        "STARTAN3": blank(I_GROUND_SHADE), "STONE3": blank(I_BORDER),
        "PEX": blank(I_GROUND_SHADE), "PEY": blank(I_GROUND_SHADE),
        "PCX": face_cell(I_CELL[1]), "PCY": face_cell(I_CELL[2]),
        "POX": face_cell(I_OWN[1]), "POY": face_cell(I_OWN[2]),
        "PWX": face_wall(I_WALL[1]), "PWY": face_wall(I_WALL[2]),
        "PTX": face_tower(I_TOWER[1], I_BAND[1]), "PTY": face_tower(I_TOWER[2], I_BAND[2]),
    }
    pnames = ["PQSKY"]
    lumps.append(("PQSKY", column_patch(sky_columns())))
    defs = [("SKY1", SKY_COLS, SKY_HEIGHT, 0)]
    for i, (tex, grid) in enumerate(faces.items()):
        patch = "PQ%03d" % i
        lumps.append((patch, column_patch(transpose(grid))))
        pnames.append(patch)
        defs.append((tex, 128, 128, i + 1))
    lumps.append(("PNAMES", struct.pack("<i", len(pnames)) + b"".join(name8(p) for p in pnames)))

    blob, offsets = bytearray(), []
    base = 4 + 4 * len(defs)
    for tex, width, height, patch in defs:
        offsets.append(base + len(blob))
        blob += struct.pack("<8siHHiH", name8(tex), 0, width, height, 0, 1)
        blob += struct.pack("<hhhhh", 0, 0, patch, 1, 0)
    lumps.append(("TEXTURE1", struct.pack("<i", len(defs)) + struct.pack(f"<{len(defs)}i", *offsets)
                  + bytes(blob)))
    lumps.append(("TEXTURE2", struct.pack("<i", 0)))      # the IWAD's TEXTURE2 would point into PNAMES

    plain = {"GRASS1": I_CELL[0], "FLAT10": I_WALL[0], "FLAT5_4": I_TOWER_TOP,
             "GRASS2": I_OWN[0], "F_SKY1": SKY_FIRST}
    lumps.append(("F_START", b""))
    lumps.append(("FLOOR4_8", ground_flat()))
    for flat, idx in plain.items():
        lumps.append((flat, bytes([idx]) * 4096))
    lumps.append(("F_END", b""))
    return lumps


def wad_bytes(lumps: list[tuple[str, bytes]]) -> bytes:
    body, directory, pos = bytearray(), bytearray(), 12
    for name, data in lumps:
        directory += struct.pack("<ii8s", pos, len(data), name8(name))
        body += data
        pos += len(data)
    return b"PWAD" + struct.pack("<ii", len(lumps), pos) + bytes(body) + bytes(directory)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name", nargs="?", choices=sorted(THEMES))
    ap.add_argument("-o", "--output")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for key in sorted(THEMES):
            print(key, THEMES[key]["label"])
        return 0
    if not args.name:
        ap.error("a theme name is required")
    out = args.output or os.path.join(os.path.dirname(__file__), "..", "assets", f"theme-{args.name}.wad")
    out = os.path.normpath(out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as handle:
        handle.write(wad_bytes(build_theme(args.name)))
    print(f"wrote {out} (theme {args.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
