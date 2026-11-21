#!/usr/bin/env python3
"""Generate a look ("theme") as a PWAD. Standard library only, deterministic, no outside images.

    python3 tools/make_theme.py <name> [-o assets/theme-<name>.wad]
    python3 tools/make_theme.py --list

A theme replaces, for the program, everything the picture is coloured from:
  PLAYPAL   256 colours: the surfaces of the theme in their stages, a sky gradient, navy lines
  COLORMAP  34 tables, no dimming with distance (only the lines fold away, see below)
  PNAMES, TEXTURE1, TEXTURE2   the wall textures: 256 x 256 texels over a cell edge of 128 units (two texels
            to the unit), per kind and wall direction several variants (names CX00.., CY00.. cell, OX/OY own,
            WX/WY wall, TX/TY tower), plain PEX/PEY (empty), STARTAN3 and STONE3 (named by the map), SKY1
  F_START..F_END   the floors: one 256 x 256 flat per cell (row 0 north): the ground in variants with
            joints on the west/south edge or not (LE<variant><edges>), the tops of the kinds (LC.., LO.., LW.., LT..)
  POVTHEME  switches, the light level of all sectors, class and rank of each colour index for
            the outline pass (pov_control.c)
  POVX      the geometry (texels to the unit) and 16 weighted slots of variants per kind; the engine picks a
            slot from the WORLD position of a cell (pov_control.c, `origin` line)
Load with `-pov-theme <file>` (the file is added after the map, its lumps win). The theme's own
flat range replaces the IWAD's.

Look (ligne claire): flat surfaces, each in a few stages
(surface, a darker side, a fleck stage; no gradient on bodies); lines in the navy of the project, never
black; the sky nearly flat with a few flat shapes. The pictures (theme_art.py) are made of palette INDICES,
the same in every theme; a block has three faces (top, side east/west, side north/south) in two stages each,
the faces differ in their palette entry (so the outline pass can tell them apart) even where the colour is
the same.

Lines are drawn into the pictures with "twin" indices (navy, one per surface colour and kind of line:
core, halo, fine). The engine picks the COLORMAP row from the distance; with the light level LIGHT a
surface starts at row S (floors S, walls whose edge runs along y: S - 4, along x: S + 4, r_segs.c) and the
row is S - 1280 / distance (r_draw, r_plane, r_main light tables). From a row on, a twin maps to the colour
of its surface: the line is drawn up to 1280 / (q + 1) units and vanishes beyond (FOLD_Q). A line is one
texel (half a unit) near the viewer; a second texel, the halo, is navy only between its own two
distances, so far away the coarse lines are two texels (one unit) and keep about the weight of the
outline (one point, two from 901 wide), while the fine things (rivets, scraps, cracks) fold away earlier.
A joint across the view on the floor is thinner than one picture row beyond sqrt(eye height * w / 2 * t)
units for a line t units thick; the floor folds at 160 units (looked at in 672 x 324). The light index of a
wall is normalised to a 320 wide picture in the engine, so these distances hold at every picture size.
"""

from __future__ import annotations

import argparse
import functools
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme_art as art  # noqa: E402

NAVY = (0x1A, 0x23, 0x32)
SKY_ROWS = 100            # rows above the horizon that can show sky (full screen view: centre 100)
SKY_FIRST = art.SKY_FIRST  # first palette index of the gradient: one index per row, 156..255
SKY_COLS = 1024           # the sky texture runs once around (angle >> 22)
SKY_HEIGHT = 128

# Palette indices: the layout is in theme_art (the pictures are made of indices).
I_OUTLINE = art.I_OUTLINE
I_GROUND, I_GROUND_SHADE, I_BORDER, I_GROUND_LIGHT = art.I_GROUND, art.I_GROUND_SHADE, art.I_BORDER, art.I_GROUND_LIGHT
I_ROLE = art.I_ROLE
I_BAND = art.I_BAND
I_SHAPES = art.I_SHAPES
LIGHT = 160                  # light level of all sectors: lightnum 10, colormap start row 20

# When the lines of a surface fold into its colour, as q: the COLORMAP row S + offset - q (S the start row
# of the light level, offset by the orientation) and beyond; a row is about 1280 / distance rows below S, so
# a line folds at 1280 / (q + 1) units. Per orientation: core, halo start, fine.
#   floor: core 128 units; the halo (second texel) joins from 80 units; fine things fold at 80 units
#   walls: core 320 units; the halo joins from 160 units; fine things fold at 160 units
FOLD_Q = {"floor": (9, 15, 15), "x": (3, 7, 7), "y": (3, 7, 7)}
SMALL_Q = {"floor": 9, "x": 3, "y": 3}      # small flecks fold into their surface (floor 128 units, walls 320)
OFFSET = {"floor": 0, "x": -4, "y": 4}      # vertical edges (x const) get lightnum + 1, along x lightnum - 1

SHADE = 0.88

BASES = art.BASES
TWIN_OF = {b: art.TW[b][0] for b, _o in BASES}        # base -> its core twin
HALO_OF = {b: art.TW[b][1] for b, _o in BASES}
FINE_OF = {b: art.TW[b][2] for b, _o in BASES}


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
    pal[I_GROUND_LIGHT] = mix(g, (255, 255, 255), 0.5)
    pal[I_BORDER] = hexrgb(theme["border"])
    for role in art.ROLES:
        base = hexrgb(theme[role])
        s1 = hexrgb(theme[role + "_shade"]) if role + "_shade" in theme else shade(base)
        top = hexrgb(theme["tower_top"]) if role == "tower" else base
        top1 = shade(top) if role == "tower" else s1
        i = I_ROLE[role]
        pal[i["t0"]], pal[i["t1"]] = top, top1
        pal[i["x0"]], pal[i["x1"]] = base, s1
        pal[i["y0"]], pal[i["y1"]] = s1, shade(s1)
    band = hexrgb(theme["band"])
    pal[I_BAND["x"]] = band
    pal[I_BAND["y"]] = hexrgb(theme["band_shade"]) if "band_shade" in theme else shade(band)
    for idx, key in zip(I_SHAPES, ("disc", "cloud")):
        pal[idx] = hexrgb(theme[key])
    top, hor = hexrgb(theme["sky_top"]), hexrgb(theme["sky_horizon"])
    for row in range(SKY_ROWS):
        pal[SKY_FIRST + row] = mix(top, hor, row / (SKY_ROWS - 1))
    for trio in art.TW.values():
        for twin in trio:
            pal[twin] = NAVY
    for small, fleck in art.FLECK_OF_SMALL.items():
        pal[small] = pal[fleck]
        pal[art.SMALL_TWIN[small]] = NAVY
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


def navy_rows() -> dict[int, tuple[int, int]]:
    """For each twin the COLORMAP rows [lo, hi) in which it stays navy (elsewhere it shows its surface)."""
    start = (15 - (LIGHT >> 4)) * 4
    out = {}
    for base, orient in BASES:
        q_core, q_halo, q_fine = FOLD_Q[orient]
        row = start + OFFSET[orient]
        out[art.TW[base][0]] = (0, row - q_core)
        out[art.TW[base][1]] = (row - q_halo, row - q_core)
        out[art.TW[base][2]] = (0, row - q_fine)
    return out


def colormap(pal) -> bytes:
    windows = navy_rows()
    base_of = {t: b for b, trio in art.TW.items() for t in trio}
    start = (15 - (LIGHT >> 4)) * 4
    out = bytearray()
    for row in range(32):                # 32 light levels: no dimming, only the twins and small flecks fold
        table = bytearray(range(256))
        for twin, (lo, hi) in windows.items():
            if not (lo <= row < hi):
                table[twin] = base_of[twin]
        for small, surface in art.SURFACE_OF_SMALL.items():
            orient = art.ORIENT_OF[art.FLECK_OF_SMALL[small]]
            row_s = start + OFFSET[orient]
            gone = row >= row_s - SMALL_Q[orient]
            if gone:
                table[small] = surface
            # its fine line: navy up to the fine distance, then the fleck's colour until the fleck folds
            twin = art.SMALL_TWIN[small]
            if row >= row_s - FOLD_Q[orient][2]:
                table[twin] = surface if gone else small
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


# ---- the surfaces: variants of each kind (theme_art.py draws them), the same for every theme

SLOTS = 16
# per kind: (family, density of each variant); the weighted slots (variant numbers: calm ones twice) follow
WALL_KINDS = {
    "cell": ("C", (0, 0, 0, 0, 1, 1, 1, 1, 2, 2),
             (0, 0, 1, 1, 2, 2, 3, 3, 4, 5, 6, 7, 8, 9, 4, 6)),
    "own": ("O", (0, 0, 0, 1, 1, 1, 2, 2),
            (0, 0, 1, 1, 2, 2, 3, 4, 5, 3, 6, 7, 0, 1, 4, 5)),
    "wall": ("W", (0, 0, 0, 1, 1, 1, 2, 2),
             (0, 0, 1, 1, 2, 2, 3, 3, 4, 5, 6, 4, 7, 0, 1, 5)),
    "tower": ("T", (0, 0, 1, 1, 1, 2),
              (0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 0, 1, 2, 3, 4)),
}
GROUND_DENS = (0, 0, 0, 0, 1, 1, 1, 2)
GROUND_SLOTS = (0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 0)
TOP_STYLES = {
    "cell": ("C", ("lid", "grate", "cross", "vents", "hatch", "calm"), (5, 5, 2, 2, 0, 0, 1, 3, 4, 5, 2, 0, 1, 5, 3, 4)),
    "own": ("O", (0, 1, 2, 3), (0, 0, 1, 1, 2, 3, 0, 1, 0, 1, 2, 3, 0, 1, 0, 1)),
    "wall": ("W", (0, 0, 1, 1, 2), (0, 0, 1, 1, 2, 0, 1, 0, 1, 2, 3, 4, 0, 1, 3, 3)),
    "tower": ("T", ("hatch", "cross", "posts", "calm"), (0, 0, 1, 1, 2, 3, 0, 1, 0, 1, 2, 3, 0, 1, 0, 1)),
}
WALL_VARIANT_KIND = {("wall", 3): "slit", ("wall", 5): "grate", ("wall", 6): "slit"}


def wall_names(kind: str, v: int) -> tuple[str, str]:
    return "%sX%02d" % (WALL_KINDS[kind][0], v), "%sY%02d" % (WALL_KINDS[kind][0], v)


def ground_name(v: int, edges: int) -> str:
    return "LE%02d%d" % (v, edges)


def top_name(kind: str, v: int) -> str:
    return "L%s%02d" % (TOP_STYLES[kind][0], v)


def _rng(*parts) -> "art.random.Random":
    return art.random.Random("cosmergon-pov/" + "/".join(str(p) for p in parts))


@functools.lru_cache(maxsize=1)
def surfaces() -> dict:
    """Every wall texture (256 rows as grids) and flat (65536 bytes), by name. Independent of the theme."""
    tex: dict[str, list[bytearray]] = {}
    flats: dict[str, bytes] = {}
    for kind, (letter, dens, _slots) in WALL_KINDS.items():
        for v, d in enumerate(dens):
            for axis, name in zip("xy", wall_names(kind, v)):
                ids = I_ROLE[kind]
                c = art.Canvas(ids[axis + "0"], ids[axis + "1"], small_r=11)
                rng = _rng(kind, v)
                if kind in ("cell", "own"):
                    art.block_face(c, rng, d)
                    if kind == "own":
                        positions = ((128, 100), (128, 128), (90, 110), (166, 110), (128, 84), (110, 140), (146, 90), (128, 120))
                        art.emblem(c, _rng("emblem", v), positions[v][0], positions[v][1], 44 if d < 2 else 38)
                elif kind == "wall":
                    art.wall_face(c, rng, d, WALL_VARIANT_KIND.get((kind, v), ""))
                else:
                    art.tower_face(c, rng, d, I_BAND[axis])
                tex[name] = c.g
    flat_ids = {"cell": "cell", "own": "own", "wall": "wall", "tower": "tower"}
    for kind, (letter, styles, _slots) in TOP_STYLES.items():
        ids = I_ROLE[flat_ids[kind]]
        for v, style in enumerate(styles):
            c = art.Canvas(ids["t0"], ids["t1"], small_r=14)
            rng = _rng("top", kind, v)
            if kind == "cell":
                art.top_block(c, rng, style, v % 3 == 2)
            elif kind == "own":
                art.top_own(c, rng, style)
            elif kind == "wall":
                art.top_wall(c, rng, style)
            else:
                art.top_tower(c, rng, style, v % 2)
            flats[top_name(kind, v)] = b"".join(bytes(r) for r in c.g)
    for v, d in enumerate(GROUND_DENS):
        for edges in range(4):
            c = art.Canvas(I_GROUND, I_GROUND_SHADE, I_GROUND_LIGHT, small_r=20)
            art.ground_flat(c, _rng("ground", v), d, edges)
            flats[ground_name(v, edges)] = b"".join(bytes(r) for r in c.g)
    return {"tex": tex, "flats": flats}


def plain_texture(idx: int) -> list[bytearray]:
    return [bytearray([idx]) * art.N for _ in range(art.N)]


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
    for i in (I_GROUND, I_GROUND_SHADE, I_GROUND_LIGHT):    # the ground's stages are one surface
        cls[i], rank[i] = I_GROUND, 1
    rank[I_BORDER] = 2
    for role in art.ROLES:               # a face's stages are one surface; its top keeps its area (the line sits on the side)
        ids = I_ROLE[role]
        for keys, r in ((("t0", "t1"), 5), (("x0", "x1"), 4), (("y0", "y1"), 3)):
            for k in keys:
                cls[ids[k]], rank[ids[k]] = ids[keys[0]], r
    rank[I_BAND["x"]], rank[I_BAND["y"]] = 4, 3
    for base, trio in art.TW.items():    # a line counts as the surface it lies in
        for twin in trio:
            cls[twin], rank[twin] = cls[base], rank[base]
    for small, fleck in art.FLECK_OF_SMALL.items():      # and a small fleck as its fleck (and so as its surface)
        for i in (small, art.SMALL_TWIN[small]):
            cls[i], rank[i] = cls[fleck], rank[fleck]
    # version 1, outline on, outline colour index, light level of all sectors
    return b"POVT" + bytes([1, 1, I_OUTLINE, LIGHT]) + bytes(cls) + bytes(rank)


def povx_lump() -> bytes:
    """Geometry and the slots (see pov_control.c variants_init)."""
    out = bytearray(b"POVX" + bytes([1, 1, 8, 1]))
    for s in range(SLOTS):
        for edges in range(4):
            out += name8(ground_name(GROUND_SLOTS[s], edges))
    for kind in ("cell", "wall", "tower", "own"):
        for s in range(SLOTS):
            x, y = wall_names(kind, WALL_KINDS[kind][2][s])
            out += name8(x) + name8(y)
        for s in range(SLOTS):
            out += name8(top_name(kind, TOP_STYLES[kind][2][s]))
    assert len(out) == 2056
    return bytes(out)


def split_patches(rows: list[bytearray]) -> list[bytes]:
    """A 256 x 256 grid as two picture lumps of 128 rows (a texture of two patches: a column of 256 rows would
    not fit one post, and the engine keeps column offsets in 16 bits)."""
    def transpose(grid):
        return [[grid[r][c] for r in range(len(grid))] for c in range(len(grid[0]))]
    return [column_patch(transpose(rows[0:128])), column_patch(transpose(rows[128:256]))]


def build_theme(name: str) -> list[tuple[str, bytes]]:
    theme = THEMES[name]
    pal = build_palette(theme)
    lumps: list[tuple[str, bytes]] = [
        ("POVTHEME", theme_lump()),
        ("POVX", povx_lump()),
        ("PLAYPAL", playpal(pal)),
        ("COLORMAP", colormap(pal)),
    ]
    surf = surfaces()
    faces: dict[str, list[bytearray]] = dict(surf["tex"])
    faces.update({"STARTAN3": plain_texture(I_GROUND_SHADE), "STONE3": plain_texture(I_BORDER),
                  "PEX": plain_texture(I_GROUND_SHADE), "PEY": plain_texture(I_GROUND_SHADE)})
    pnames = ["PQSKY"]
    lumps.append(("PQSKY", column_patch(sky_columns())))
    defs = [("SKY1", SKY_COLS, SKY_HEIGHT, [0])]
    for i, (tex, rows) in enumerate(faces.items()):
        two = []
        for half, data in enumerate(split_patches(rows)):
            patch = "PQ%03d" % (2 * i + half)
            lumps.append((patch, data))
            pnames.append(patch)
            two.append(len(pnames) - 1)
        defs.append((tex, art.N, art.N, two))
    lumps.append(("PNAMES", struct.pack("<i", len(pnames)) + b"".join(name8(p) for p in pnames)))

    blob, offsets = bytearray(), []
    base = 4 + 4 * len(defs)
    for tex, width, height, patches in defs:
        offsets.append(base + len(blob))
        blob += struct.pack("<8siHHiH", name8(tex), 0, width, height, 0, len(patches))
        for k, patch in enumerate(patches):
            blob += struct.pack("<hhhhh", 0, 128 * k, patch, 1, 0)
    lumps.append(("TEXTURE1", struct.pack("<i", len(defs)) + struct.pack(f"<{len(defs)}i", *offsets)
                  + bytes(blob)))
    lumps.append(("TEXTURE2", struct.pack("<i", 0)))      # the IWAD's TEXTURE2 would point into PNAMES

    lumps.append(("F_START", b""))
    lumps.append(("FLOOR4_8", bytes([I_GROUND]) * 4096))   # named by the map's sectors, replaced at once by a variant
    for flat, data in surf["flats"].items():
        lumps.append((flat, data))
    lumps.append(("F_SKY1", bytes([SKY_FIRST]) * 4096))
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
