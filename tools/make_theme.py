#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
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
  POVINK    per stroke index the colour a thinned point is set back to, and whether it is a floor stroke
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

Strokes are drawn into the pictures with "twin" indices (navy, one per surface colour and width: fine, core,
wide). The engine picks the COLORMAP row from the distance; with the light level LIGHT a surface starts at row S
(floors S, walls whose edge runs along y: S - 4, along x: S + 4, r_segs.c) and the row is S - 1280 / distance (r_draw,
r_plane, r_main light tables). From a row on, a twin maps to the colour of its surface: the stroke is drawn up to
1280 / (q + 1) units and vanishes beyond (FOLD_Q). The width in the texture decides how far it is seen; the engine
thins it on the picture to the width of the outline (POVINK lump, pov_control.c ink_pass). A joint across the view
on the floor is thinner than one picture row beyond sqrt(eye height * w / 2 * t) units for a line t units thick;
the engine drops such strokes there. The light index of a wall is normalised to a 320 wide picture in the engine,
so these distances hold at every picture size.
"""

from __future__ import annotations

import argparse
import functools
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sky_art  # noqa: E402
import theme_day  # noqa: E402
import theme_art as art  # noqa: E402
import ring_art  # noqa: E402

NAVY = (0x1A, 0x23, 0x32)
SKY_FIRST = art.SKY_FIRST  # first palette index of the sky bands, 156..; band 0 is at the horizon
SKY_BANDS = 16            # bands of elevation, each a flat colour
BAND_DEG10 = 30           # a band is 3.0 degrees: 48 degrees of elevation, flat above
I_SKY = art.I_SKY
FOG_FAR_UNITS = 3000                  # beyond this distance the field is one row (step) further in the COLORMAP
# Haze: how far a colour goes to the horizon colour at each step (times the theme's `fog`: 0 off, 1 light, 2 clear)
FIELD_S = (0.12, 0.26, 0.42)          # the field, steps 1..3
CLOUD_S = (0.30, 0.50, 0.70)          # a cloud, steps 1..3 (step 0, near: none)
CUBE_S = (0.45, 0.60, 0.72, 0.85)     # a neighbour cube, steps 0..3: always hazy, the nearest least
NAVYF_S = (0.15, 0.30, 0.45, 0.60, 0.72, 0.85)    # the lines of far things: the navy of the project, hazed
FIELD_NAVYF, CLOUD_NAVYF, CUBE_NAVYF = (0, 1, 2), (1, 2, 4), (2, 3, 4, 5)   # index into NAVYF_S per step

# Palette indices: the layout is in theme_art (the pictures are made of indices).
I_OUTLINE = art.I_OUTLINE
I_GROUND, I_GROUND_SHADE, I_BORDER, I_GROUND_LIGHT = art.I_GROUND, art.I_GROUND_SHADE, art.I_BORDER, art.I_GROUND_LIGHT
I_ROLE = art.I_ROLE
I_BAND = art.I_BAND
I_SHAPES = art.I_SHAPES
LIGHT = 160                  # light level of all sectors: lightnum 10, colormap start row 20

# When the lines of a surface fold into its colour, as q: the COLORMAP row S + offset - q (S the start row
# of the light level, offset by the orientation) and beyond; a row is about 1280 / distance rows below S, so
# a line folds at 1280 / (q + 1) units. Per orientation: core (two texels), wide (four texels), fine (one).
# The engine thins every stroke on the picture to the width of the outline (ink_pass), so the width in the
# picture decides how far a line can still be seen, not how thick it looks: a wide stroke is a 2 unit band
# that stays at least a point wide to about 640 units.
#   floor: wide 640 units; core 128 units; fine things fold at 80 units
#   walls: wide 640 units; core 320 units; fine things fold at 160 units
FOLD_Q = {"floor": (9, 1, 15), "x": (3, 1, 7), "y": (3, 1, 7)}
FAR_Q = 2                                   # the tints of the ground fold into the ground (floor 427 units)
SMALL_Q = {"floor": 9, "x": 3, "y": 3}      # small flecks fold into their surface (floor 128 units, walls 320)
OFFSET = {"floor": 0, "x": -4, "y": 4}      # vertical edges (x const) get lightnum + 1, along x lightnum - 1

SHADE = 0.88

BASES = art.BASES
TWIN_OF = {b: art.TW[b][0] for b, _o in BASES}        # base -> its core twin
WIDE_OF = {b: art.TW[b][1] for b, _o in BASES}
FINE_OF = {b: art.TW[b][2] for b, _o in BASES}


def shade(rgb, factor=SHADE):
    return tuple(max(0, min(255, round(c * factor))) for c in rgb)


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
        "tower": "#7a52a8", "band": "#f0c850", "tower_top": "#a284cc",
        "disc": "#fffaea", "cloud": "#ffffff",
    },
    "gelbestadt": {
        "label": "B Gelbe Stadt",
        "sky_top": "#f3e39a", "sky_horizon": "#f7ecc0",
        "ground": "#efe4bc", "border": "#d9c68e",
        "cell": "#6aa6d6", "cell_shade": "#4a88c4",
        "own": "#e8843a", "wall": "#dcb25a",
        "tower": "#7e5cae", "band": "#f2b84a", "tower_top": "#a68ad0",
        "disc": "#fff6d0", "cloud": "#fffdf2",
    },
    "blaustadt": {
        "label": "C Blaue Stadt",
        "sky_top": "#dde9f6", "sky_horizon": "#f5f9fd",
        "ground": "#cfdbe8", "border": "#b0c3d8",
        "cell": "#8fb4de", "cell_shade": "#6f98cc",
        "own": "#ff8a2a", "wall": "#5b86bf",
        "tower": "#6c3f96", "band": "#f0c850", "tower_top": "#9470bc",
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
    top, hor = hexrgb(theme["sky_top"]), hexrgb(theme["sky_horizon"])
    for band in range(SKY_BANDS):
        pal[SKY_FIRST + band] = mix(hor, top, band / (SKY_BANDS - 1))       # band 0 is at the horizon
    cloud = hexrgb(theme["cloud"])
    pal[I_SKY["sun"]] = hexrgb(theme["disc"])
    pal[I_SKY["moon"]] = hexrgb(theme.get("moon", "#f6f3da"))
    pal[I_SKY["cloud"]] = cloud
    pal[I_SKY["shade"]] = shade(mix(cloud, top, 0.55), 0.94)       # one shade tone on a cloud's lower edge
    pal[I_SKY["star"]] = (255, 255, 255) if theme.get("stars", 0) else mix(hor, top, 0.5)
    add_haze(pal, theme, hor)
    for trio in art.TW.values():
        for twin in trio:
            pal[twin] = NAVY
    for small, fleck in art.FLECK_OF_SMALL.items():
        pal[small] = pal[fleck]
        pal[art.SMALL_TWIN[small]] = NAVY
    return pal


def haze(rgb, hor, step_s, theme):
    """A colour hazed towards the horizon colour by a step's strength times the theme's `fog`."""
    return mix(rgb, hor, min(0.95, step_s * theme.get("fog", 1.0)))


def add_haze(pal, theme, hor) -> None:
    """The hazed indices: the field's groups, the clouds, the hazed navies and the neighbour cubes (theme_art)."""
    for g, (_name, members, _orient) in enumerate(art.FOG_GROUPS):
        for level in range(1, art.FOG_LEVELS + 1):
            pal[art.i_fog(g, level)] = haze(pal[members[0]], hor, FIELD_S[level - 1], theme)
    for level, (fill, shd) in art.I_CLOUD_FOG.items():
        pal[fill] = haze(pal[I_SKY["cloud"]], hor, CLOUD_S[level - 1], theme)
        pal[shd] = haze(pal[I_SKY["shade"]], hor, CLOUD_S[level - 1], theme)
    for i, strength in enumerate(NAVYF_S):
        pal[art.I_NAVYF[i]] = haze(NAVY, hor, strength, theme)
    face = hexrgb(theme["cell"])
    tones = {"xs": face, "ys": hexrgb(theme["cell_shade"]) if "cell_shade" in theme else shade(face),
             "b": shade(shade(face))}
    tones["xl"], tones["yl"] = mix(tones["xs"], NAVY, 0.40), mix(tones["ys"], NAVY, 0.40)
    for level in range(4):
        for tone, rgb in tones.items():
            pal[art.i_cube(level, tone)] = haze(rgb, hor, CUBE_S[level], theme)


def playpal(pals) -> bytes:
    """One palette per key of the day (theme_day.KEYS). The program does not apply its gamma table to a theme
    (i_video.c, pov_gamma_off): exact colours."""
    out = bytearray()
    for pal in pals:
        for r, g, b in pal:
            out += bytes((r, g, b))
    return bytes(out)


def povsky_lump() -> bytes:
    """Header of the sky (see pov_sky.c POV_SkyLoad): indices (stars, sun, moon, the bands, the hazed clouds, the
    cubes) and the minute and star flag of each key of the day."""
    out = bytearray(b"POVS" + bytes([2, SKY_BANDS, len(theme_day.KEYS), BAND_DEG10]))
    out += bytes([I_SKY["sun"], I_SKY["moon"], I_SKY["star"], SKY_FIRST])
    for level in range(4):
        pair = (I_SKY["cloud"], I_SKY["shade"]) if level == 0 else art.I_CLOUD_FOG[level]
        out += bytes(pair)
    for level in range(4):
        out += bytes(art.i_cube(level, tone) for tone in art.CUBE_TONES)
    assert len(out) == 40
    for minute, stars in theme_day.key_bytes():
        out += struct.pack("<HBB", minute, stars, 0)
    return bytes(out)


def povfog_lump() -> bytes:
    """Lump POVFOG: "POVF", version, the distance (units) beyond which the field is one COLORMAP row further, and per
    colour index the index a line on a point of it gets (the navy, or a hazed navy on a hazed surface)."""
    line = bytearray([I_OUTLINE]) * 256
    for g in range(len(art.FOG_GROUPS)):
        for level in range(1, art.FOG_LEVELS + 1):
            line[art.i_fog(g, level)] = art.I_NAVYF[FIELD_NAVYF[level - 1]]
    for level, (fill, shd) in art.I_CLOUD_FOG.items():
        line[fill] = line[shd] = art.I_NAVYF[CLOUD_NAVYF[level - 1]]
    for level in range(4):
        for tone in art.CUBE_TONES:
            line[art.i_cube(level, tone)] = art.I_NAVYF[CUBE_NAVYF[level]]
    return b"POVF" + struct.pack("<BBH", 1, 0, FOG_FAR_UNITS) + bytes(line)


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
        q_core, q_wide, q_fine = FOLD_Q[orient]
        row = start + OFFSET[orient]
        out[art.TW[base][0]] = (0, row - q_core)
        out[art.TW[base][1]] = (0, row - q_wide)
        out[art.TW[base][2]] = (0, row - q_fine)
    return out


def apply_haze(table: bytearray, row: int, start: int) -> None:
    """The field's haze in one COLORMAP row: every surface index (and every line or fleck that has folded into
    one) becomes the hazed index of its group at the step the row stands for: row_s - 1 step 1 (640 units), row_s
    step 2 (1280), row_s + 1 step 3 (beyond FOG_FAR_UNITS). The border wall has no orientation (one texture for
    all four sides): it is always at the last step, the far horizon."""
    member_group = {}
    for g, (_name, members, orient) in enumerate(art.FOG_GROUPS):
        for m in members:
            member_group[m] = (g, orient)
    for i in range(256):
        hit = member_group.get(table[i])
        if hit is None or i == I_OUTLINE:
            continue
        g, orient = hit
        row_s = start + OFFSET.get(orient, 0)
        level = art.FOG_LEVELS if orient == "border" else max(0, min(art.FOG_LEVELS, row - row_s + 2))
        if level:
            table[i] = art.i_fog(g, level)


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
        if row >= start - FAR_Q:             # far away the ground is one calm plane: its tints are gone
            table[I_GROUND_SHADE] = table[I_GROUND_LIGHT] = I_GROUND
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
        apply_haze(table, row, start)
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
# the faces of the field's rim (tools/ring_art.py), in the order of the lump POVRING: family letter, the variants, the slots.
# A shaft portal is two cells wide: its halves have one variant each, so that the two cells of a portal always match.
RING_KINDS = {
    "ring": ("R", 4, (0, 0, 1, 1, 2, 2, 3, 3, 0, 1, 2, 0, 1, 2, 3, 0)),
    "alcove": ("K", 4, (0, 0, 1, 1, 2, 2, 3, 3, 0, 1, 2, 3, 0, 1, 2, 3)),
    "portal-left": ("G", 1, (0,) * 16),
    "portal-right": ("H", 1, (0,) * 16),
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


def ring_names(kind: str, v: int) -> tuple[str, str]:
    return "%sX%02d" % (RING_KINDS[kind][0], v), "%sY%02d" % (RING_KINDS[kind][0], v)


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
    wall_ids = I_ROLE["wall"]                     # the rim is built of the stuff of a wall; the portal's frame is gold
    for kind, (_letter, variants, _slots) in RING_KINDS.items():
        for v in range(variants):
            for axis, name in zip("xy", ring_names(kind, v)):
                c = art.Canvas(wall_ids[axis + "0"], wall_ids[axis + "1"], small_r=11)
                rng = _rng("ring", kind, v)
                if kind == "ring":
                    ring_art.ring_face(c, rng, (0, 1, 1, 2)[v])
                elif kind == "alcove":
                    ring_art.ring_face(c, rng, (0, 1, 1, 2)[v])     # a bunk is a real recess: its faces are the rim's
                else:
                    ring_art.gold_face(c, I_BAND[axis])             # a shaft: gold lintel and side walls
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
            c = art.Canvas(I_GROUND, I_GROUND_SHADE, I_GROUND_LIGHT, small_r=28)
            art.ground_flat(c, _rng("ground", v), d, edges)
            flats[ground_name(v, edges)] = b"".join(bytes(r) for r in c.g)
    return {"tex": tex, "flats": flats}


def plain_texture(idx: int) -> list[bytearray]:
    return [bytearray([idx]) * art.N for _ in range(art.N)]


def sky_columns() -> list[list[int]]:
    """The texture SKY1 the map names; the engine's sky (POVSKY) does not use it, but it must exist."""
    return [[SKY_FIRST] * 128 for _ in range(256)]


def theme_lump() -> bytes:
    cls = list(range(256))
    rank = [3] * 256
    for i in range(SKY_FIRST, 256):
        cls[i], rank[i] = 0, 1           # all sky bands are one surface: no lines in the sky (rank 1: things in the sky are 0)
    cls[I_SKY["star"]] = 0               # a star is a speck of the sky, no outline
    # sun and moon: class 5 (the sky, class 0, takes the line: it lies outside the disc). Clouds and cubes are
    # rank 0: the line is on their own side (a hazed navy on a hazed thing); a cloud is class 6, a cube's sides 50/51/52
    for key, c, r in (("sun", 5, 1), ("moon", 5, 1), ("cloud", 6, 0), ("shade", 6, 0)):
        cls[I_SKY[key]], rank[I_SKY[key]] = c, r
    for lv, pair in art.I_CLOUD_FOG.items():
        for i in pair:
            cls[i], rank[i] = 6, 0
    for lv in range(4):
        for tone in art.CUBE_TONES:
            cls[art.i_cube(lv, tone)], rank[art.i_cube(lv, tone)] = 50 + {"x": 0, "y": 1, "b": 2}[tone[0]], 0
    for i in (I_GROUND, I_GROUND_SHADE, I_GROUND_LIGHT):    # the ground's stages are one surface
        cls[i], rank[i] = I_GROUND, 1
    rank[I_BORDER] = 2
    for role in art.ROLES:               # a face's stages are one surface; its top keeps its area (the line sits on the side)
        ids = I_ROLE[role]
        for keys, r in ((("t0", "t1"), 5), (("x0", "x1"), 4), (("y0", "y1"), 3)):
            for k in keys:
                cls[ids[k]], rank[ids[k]] = ids[keys[0]], r
    rank[I_BAND["x"]], rank[I_BAND["y"]] = 4, 3
    for g, (_name, members, _orient) in enumerate(art.FOG_GROUPS):     # a hazed surface is its surface
        for level in range(1, art.FOG_LEVELS + 1):
            cls[art.i_fog(g, level)], rank[art.i_fog(g, level)] = cls[members[0]], rank[members[0]]
    for base, trio in art.TW.items():    # a line counts as the surface it lies in
        for twin in trio:
            cls[twin], rank[twin] = cls[base], rank[base]
    for small, fleck in art.FLECK_OF_SMALL.items():      # and a small fleck as its fleck (and so as its surface)
        for i in (small, art.SMALL_TWIN[small]):
            cls[i], rank[i] = cls[fleck], rank[fleck]
    # version 1, outline on, outline colour index, light level of all sectors
    return b"POVT" + bytes([1, 1, I_OUTLINE, LIGHT]) + bytes(cls) + bytes(rank)


def povink_lump() -> bytes:
    """The strokes for the thinning pass (pov_control.c ink_pass): version 1, then per colour index the index a
    thinned stroke point is replaced by (0: not a stroke) and a flag (1: a stroke on a floor)."""
    repl, floor = bytearray(256), bytearray(256)
    for base, trio in art.TW.items():
        for twin in trio:
            repl[twin], floor[twin] = base, art.ORIENT_OF[base] == "floor"
    for small, twin in art.SMALL_TWIN.items():
        repl[twin], floor[twin] = small, art.ORIENT_OF[art.FLECK_OF_SMALL[small]] == "floor"
    return b"POVK" + bytes([1, 0, 0, 0]) + bytes(repl) + bytes(floor)


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


def povring_lump() -> bytes:
    """The faces of the rim (see pov_control.c ring_variants): ring, alcove, left and right half of a portal, 16 slots each."""
    out = bytearray(b"POVE" + bytes([1, 0, 0, 0]))
    for kind, (_letter, _variants, slots) in RING_KINDS.items():
        for s in range(SLOTS):
            x, y = ring_names(kind, slots[s])
            out += name8(x) + name8(y)
    assert len(out) == 1032
    return bytes(out)


def split_patches(rows: list[bytearray]) -> list[bytes]:
    """A 256 x 256 grid as two picture lumps of 128 rows (a texture of two patches: a column of 256 rows would
    not fit one post, and the engine keeps column offsets in 16 bits)."""
    def transpose(grid):
        return [[grid[r][c] for r in range(len(grid))] for c in range(len(grid[0]))]
    return [column_patch(transpose(rows[0:128])), column_patch(transpose(rows[128:256]))]


def build_theme(name: str, fog: float | None = None, clouds=None) -> list[tuple[str, bytes]]:
    """The lumps of a theme. `fog`: the strength of the haze (0 off, 1 light = the default, 2 clear); `clouds`: a list
    of (x, y, base height, width, shape) in units instead of the theme's own sky (tests)."""
    theme = dict(THEMES[name])
    if fog is not None:
        theme["fog"] = fog
    pal = build_palette(theme)
    pals = theme_day.key_palettes(theme, build_palette)
    lumps: list[tuple[str, bytes]] = [
        ("POVTHEME", theme_lump()),
        ("POVX", povx_lump()),
        ("POVRING", povring_lump()),
        ("POVINK", povink_lump()),
        ("POVSKY", povsky_lump()),
        ("POVWLD", sky_art.world_lump(clouds)),
        ("POVCLS", sky_art.sprite_lump()),
        ("POVSTR", sky_art.stars_lump()),
        ("POVFOG", povfog_lump()),
        ("PLAYPAL", playpal(pals)),
        ("COLORMAP", colormap(pal)),
    ]
    surf = surfaces()
    faces: dict[str, list[bytearray]] = dict(surf["tex"])
    faces.update({"STARTAN3": plain_texture(I_GROUND_SHADE), "STONE3": plain_texture(I_BORDER),
                  "PEX": plain_texture(I_GROUND_SHADE), "PEY": plain_texture(I_GROUND_SHADE)})
    pnames = ["PQSKY"]
    lumps.append(("PQSKY", column_patch(sky_columns())))
    defs = [("SKY1", 256, 128, [0])]
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
