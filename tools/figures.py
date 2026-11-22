#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""The figures of the thing kinds as sprites (picture lumps) of a theme. Standard library only, deterministic.

The pictures are our own work (see COSMERGON.md, "Own figures"). They are kept as small templates in
`assets/figures/<kind>-<direction>.png`: 8 bit paletted PNG files at one point per unit of the engine (32 to the metre), cut
to their box. A template holds palette INDICES of the theme layout (`theme_art.py`: the same indices in every theme), so it is
the same file for every theme; the colours of a theme come from its PLAYPAL. In the file, value 0 is transparent and value
v + 1 is the palette index v (the PNG's own palette shows the picture in the colours of the theme `wueste`); the private chunk
`cORg` holds the origin of the figure as the Doom picture wants it: columns left of the origin to the first column and rows
above the origin to the first row (left and top offset; the top offset is the height of the figure over its origin).

`make_theme.build_theme` adds `S_START`, the lumps below and `S_END` to the theme: the theme's own sprite range replaces the
IWAD's. The names are those of the thing table (`s_thing_kind` in `pov_control.c`): `TROOA1`..`TROOA8` and so on, where the
rotation n of the engine (1..8) is the picture of direction -(n - 1) mod 8 (direction 0: the figure faces the viewer, 1: it
turns towards the viewer's right, counter-clockwise seen from above). `tools/make_figures.py` makes the templates from renders.
"""

from __future__ import annotations

import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
FIGURES_DIR = os.path.join(os.path.dirname(HERE), "assets", "figures")

# kind -> (sprite name, frame letter, rotations: 8, or 0 = one look from every side)
KINDS = {
    "marauder": ("TROO", "A", 8),
    "monster": ("BOSS", "A", 8),
    "bird": ("HEAD", "A", 8),
    "corpse": ("POL5", "A", 0),
    "loot": ("BPAK", "A", 0),
}

PRIVATE_ORIGIN = b"cORg"


def template_name(kind: str, direction: int) -> str:
    return "%s-%d.png" % (kind, direction)


def read_png(path):
    """Read an 8 bit PNG (grey, grey+alpha, RGB or RGBA, not interlaced); returns (width, height, RGBA bytes)."""
    width, height, ctype, rows, _chunks = _decode(path)
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise ValueError("%s: colour type %d needs read_template" % (path, ctype))
    out = bytearray(width * height * 4)
    for y, line in enumerate(rows):
        for x in range(width):
            o = (y * width + x) * 4
            if channels == 4:
                out[o:o + 4] = line[x * 4:x * 4 + 4]
            elif channels == 3:
                out[o:o + 3] = line[x * 3:x * 3 + 3]
                out[o + 3] = 255
            elif channels == 2:
                out[o] = out[o + 1] = out[o + 2] = line[x * 2]
                out[o + 3] = line[x * 2 + 1]
            else:
                out[o] = out[o + 1] = out[o + 2] = line[x]
                out[o + 3] = 255
    return width, height, bytes(out)


def _decode(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s: not a PNG" % path)
    pos, idat, header, chunks = 8, bytearray(), None, {}
    while pos < len(data):
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + size]
        pos += 12 + size
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        else:
            chunks[kind] = body
    if header is None:
        raise ValueError("%s: no header" % path)
    width, height, depth, ctype, _comp, _filt, interlace = header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or channels is None or interlace:
        raise ValueError("%s: only 8 bit grey, grey+alpha, RGB, RGBA and paletted without interlace" % path)
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    rows, prev = [], bytearray(stride)
    for y in range(height):
        base = y * (stride + 1)
        ft = raw[base]
        line = bytearray(raw[base + 1:base + 1 + stride])
        if ft == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 255
        elif ft != 0:
            raise ValueError("%s: filter %d" % (path, ft))
        rows.append(line)
        prev = line
    return width, height, ctype, rows, chunks


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def write_template(path: str, grid, left_offset: int, top_offset: int, palette) -> None:
    """A figure as a template file. `grid`: rows of palette indices or None; `palette`: the 256 colours shown."""
    height, width = len(grid), len(grid[0])
    top = max((v for line in grid for v in line if v is not None), default=0) + 2
    plte = b"".join(bytes(palette[v - 1]) if v else b"\0\0\0" for v in range(top))
    raw = b"".join(b"\0" + bytes(0 if v is None else v + 1 for v in line) for line in grid)
    png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
           + _chunk(b"PLTE", plte) + _chunk(b"tRNS", b"\0") + _chunk(PRIVATE_ORIGIN, struct.pack(">hh", left_offset, top_offset))
           + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))
    with open(path, "wb") as handle:
        handle.write(png)


def read_template(path: str):
    """A template file as (grid of palette indices or None, left offset, top offset)."""
    width, height, ctype, rows, chunks = _decode(path)
    if ctype != 3 or PRIVATE_ORIGIN not in chunks:
        raise ValueError("%s: not a figure template" % path)
    grid = [[None if v == 0 else v - 1 for v in line] for line in rows]
    left, top = struct.unpack(">hh", chunks[PRIVATE_ORIGIN])
    return grid, left, top


def patch_lump(grid, left_offset: int, top_offset: int) -> bytes:
    """The grid as a Doom picture (posts per column); the origin is `top_offset` rows under its first row."""
    width, height = len(grid[0]), len(grid)
    columns = []
    for x in range(width):
        posts, y = bytearray(), 0
        while y < height:
            if grid[y][x] is None:
                y += 1
                continue
            run = []
            while y < height and grid[y][x] is not None:
                run.append(grid[y][x])
                y += 1
            posts += bytes([y - len(run), len(run), 0]) + bytes(run) + bytes([0])
        columns.append(bytes(posts) + b"\xff")
    head = struct.pack("<hhhh", width, height, left_offset, top_offset)
    offsets, pos = [], 8 + 4 * width
    for col in columns:
        offsets.append(pos)
        pos += len(col)
    return head + struct.pack("<%di" % width, *offsets) + b"".join(columns)


def sprite_lumps(directory: str | None = None) -> list[tuple[str, bytes]]:
    """`S_START`, the sprites of every kind, `S_END`. The rotation n (1..8) of the engine is direction -(n - 1) mod 8."""
    directory = directory or FIGURES_DIR
    lumps: list[tuple[str, bytes]] = []
    for kind, (sprite, frame, rotations) in KINDS.items():
        for n in range(1, 9) if rotations else (0,):
            direction = (-(n - 1)) % 8 if rotations else 0
            grid, left, top = read_template(os.path.join(directory, template_name(kind, direction)))
            lumps.append(("%s%s%d" % (sprite, frame, n), patch_lump(grid, left, top)))
    return [("S_START", b"")] + lumps + [("S_END", b"")]
