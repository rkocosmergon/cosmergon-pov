#!/usr/bin/env python3
"""Generate the fixed 48 x 48 grid map as a PWAD (map E1M1). Standard library only.

Layout (see COSMERGON.md):
  * One sector per grid cell, sector index = y * 48 + x (x east, y north, both 0..47).
  * A cell is 128 units wide. The map covers -3072..3072 in both axes (16-bit safe).
  * Every cell edge is a two-sided line with the lower texture on BOTH sides, the outer
    border is one-sided with a wall texture. One ceiling height (sky) everywhere.
  * One BSP leaf (subsector) per cell with its four segs, subsector index = sector index.
  * Exactly one thing: the player start (type 1).
All lumps are written here; no external node builder is used. Output is deterministic.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pov_measures as pm  # noqa: E402

PATTERNS = ("flat", "checker", "full", "random", "stairs")
DEFAULT_START = (pm.GRID / 2 + 0.5, pm.GRID / 2 + 0.5, 0)  # centre of cell (24, 24), facing east

ML_BLOCKING = 0x0001
ML_TWOSIDED = 0x0004
NF_SUBSECTOR = 0x8000
NO_SIDE = 0xFFFF

# Structure sizes in the file (doomdata.h).
SIZES = {
    "THINGS": 10,
    "LINEDEFS": 14,
    "SIDEDEFS": 30,
    "VERTEXES": 4,
    "SEGS": 12,
    "SSECTORS": 4,
    "NODES": 28,
    "SECTORS": 26,
}
LUMP_ORDER = (
    "THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SEGS",
    "SSECTORS", "NODES", "SECTORS", "REJECT", "BLOCKMAP",
)  # the order the engine expects after the map marker (p_setup.c ML_*)


def name8(text: str) -> bytes:
    raw = text.encode("ascii")
    if len(raw) > 8:
        raise ValueError(f"lump or texture name too long: {text}")
    return raw.ljust(8, b"\0")


def cell_heights(pattern: str, seed: int) -> list[int]:
    """Floor height of every cell, indexed like the sectors (y * GRID + x)."""
    n = pm.GRID
    if pattern == "flat":
        return [pm.H_EMPTY] * (n * n)
    if pattern == "full":
        return [pm.H_CELL] * (n * n)
    if pattern == "checker":
        return [pm.H_CELL if (x + y) % 2 == 0 else pm.H_EMPTY for y in range(n) for x in range(n)]
    if pattern == "stairs":
        # Steps of 16 units rising along x, restarting every 10 cells (0..144 <= tower top).
        return [(x % 10) * 16 for y in range(n) for x in range(n)]
    if pattern == "random":
        # Stress case: every height 0..MAX_FLOOR equally likely, so planes rarely merge.
        rng = random.Random(seed)
        return [rng.randint(0, pm.MAX_FLOOR) for _ in range(n * n)]
    raise ValueError(f"unknown pattern {pattern!r}")


def vx(i: int) -> int:
    """World coordinate of grid line i (0..GRID)."""
    return pm.ORIGIN + i * pm.CELL_SIZE


def build_map(pattern: str = "flat", seed: int = 0,
              start: tuple[float, float, int] = DEFAULT_START,
              start_floor: int = pm.H_EMPTY) -> list[tuple[str, bytes]]:
    """Return the lumps of the map as (name, data) pairs, marker first."""
    n = pm.GRID
    sx, sy, sangle = start
    if not (0 < sx < n and 0 < sy < n):
        raise ValueError(f"start {sx},{sy} is outside the map (0..{n} cells)")
    if sangle % 45 != 0:
        raise ValueError("start angle must be a multiple of 45 (the engine rounds to 45 degrees)")
    if not 0 <= start_floor <= pm.MAX_FLOOR:
        raise ValueError(f"start floor must be 0..{pm.MAX_FLOOR}")

    heights = cell_heights(pattern, seed)
    # The start cell stays free at every pattern: the player would otherwise stand inside a block.
    start_cell = pm.sector_index(int(sx), int(sy))
    heights[start_cell] = start_floor

    # ---- vertices: (i, j) -> j * (n + 1) + i
    def vert(i: int, j: int) -> int:
        return j * (n + 1) + i

    vertexes = b"".join(struct.pack("<hh", vx(i), vx(j)) for j in range(n + 1) for i in range(n + 1))

    # ---- lines and sides. A line is (v1, v2, front_cell, back_cell or None).
    lines: list[tuple[int, int, int, int | None]] = []
    line_of: dict[tuple, int] = {}  # key -> line index; key ('v', i, y) / ('h', j, x)

    def add(key: tuple, v1: int, v2: int, front: int, back: int | None) -> None:
        line_of[key] = len(lines)
        lines.append((v1, v2, front, back))

    for y in range(n):
        for i in range(n + 1):
            v1, v2 = vert(i, y), vert(i, y + 1)  # heading north: east is the right (front) side
            if i == 0:
                add(("v", i, y), v1, v2, pm.sector_index(0, y), None)
            elif i == n:
                add(("v", i, y), vert(n, y + 1), vert(n, y), pm.sector_index(n - 1, y), None)
            else:
                add(("v", i, y), v1, v2, pm.sector_index(i, y), pm.sector_index(i - 1, y))
    for x in range(n):
        for j in range(n + 1):
            v1, v2 = vert(x, j), vert(x + 1, j)  # heading east: south is the right (front) side
            if j == 0:
                add(("h", j, x), vert(x + 1, 0), vert(x, 0), pm.sector_index(x, 0), None)
            elif j == n:
                add(("h", j, x), vert(x, n), vert(x + 1, n), pm.sector_index(x, n - 1), None)
            else:
                add(("h", j, x), v1, v2, pm.sector_index(x, j - 1), pm.sector_index(x, j))

    sidedefs = bytearray()
    linedefs = bytearray()
    side_count = 0
    dash = name8("-")
    for v1, v2, front, back in lines:
        if back is None:
            flags, s0, s1 = ML_BLOCKING, side_count, NO_SIDE
            sidedefs += struct.pack("<hh8s8s8sH", 0, 0, dash, dash, name8(pm.TEX_BORDER), front)
            side_count += 1
        else:
            flags, s0, s1 = ML_TWOSIDED, side_count, side_count + 1
            for sector in (front, back):
                sidedefs += struct.pack("<hh8s8s8sH", 0, 0, dash, name8(pm.TEX_LOWER), dash, sector)
            side_count += 2
        linedefs += struct.pack("<HHHHHHH", v1, v2, flags, 0, 0, s0, s1)

    # ---- sectors
    sectors = b"".join(
        struct.pack("<hh8s8shhh", h, pm.CEILING, name8(pm.FLAT_FLOOR), name8(pm.FLAT_SKY), pm.LIGHT, 0, 0)
        for h in heights
    )

    # ---- segs and subsectors: cell c owns segs 4c..4c+3 (west, east, south, north)
    def seg_angle(a: int, b: int) -> int:
        ax, ay = divmod(a, n + 1)[::-1]
        bx, by = divmod(b, n + 1)[::-1]
        dx, dy = bx - ax, by - ay
        return {(1, 0): 0x0000, (0, 1): 0x4000, (-1, 0): 0x8000, (0, -1): 0xC000}[
            ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))]

    segs = bytearray()
    ssectors = bytearray()
    for y in range(n):
        for x in range(n):
            c = pm.sector_index(x, y)
            edges = (("v", x, y), ("v", x + 1, y), ("h", y, x), ("h", y + 1, x))
            ssectors += struct.pack("<HH", 4, 4 * c)
            for key in edges:
                li = line_of[key]
                v1, v2, front, _back = lines[li]
                side = 0 if front == c else 1
                a, b = (v1, v2) if side == 0 else (v2, v1)
                # offset 0: all walls are 128 units long and the textures are 64 or 128 wide
                segs += struct.pack("<HHHHHH", a, b, seg_angle(a, b), li, side, 0)

    # ---- BSP: split the longer side at the middle along grid lines; leaf = one cell.
    nodes = bytearray()
    node_count = 0

    def bbox(x0: int, x1: int, y0: int, y1: int) -> tuple[int, int, int, int]:
        return (vx(y1), vx(y0), vx(x0), vx(x1))  # top, bottom, left, right

    def build(x0: int, x1: int, y0: int, y1: int) -> int:
        nonlocal node_count
        if x1 - x0 == 1 and y1 - y0 == 1:
            return NF_SUBSECTOR | pm.sector_index(x0, y0)
        if x1 - x0 >= y1 - y0:
            xm = (x0 + x1) // 2
            east = build(xm, x1, y0, y1)  # right side of the upward line: children[0]
            west = build(x0, xm, y0, y1)
            px, py, dx, dy = vx(xm), vx(y0), 0, (y1 - y0) * pm.CELL_SIZE
            boxes = (bbox(xm, x1, y0, y1), bbox(x0, xm, y0, y1))
            kids = (east, west)
        else:
            ym = (y0 + y1) // 2
            south = build(x0, x1, y0, ym)  # right side of the eastward line: children[0]
            north = build(x0, x1, ym, y1)
            px, py, dx, dy = vx(x0), vx(ym), (x1 - x0) * pm.CELL_SIZE, 0
            boxes = (bbox(x0, x1, y0, ym), bbox(x0, x1, ym, y1))
            kids = (south, north)
        nodes.extend(struct.pack("<hhhh", px, py, dx, dy))
        nodes.extend(struct.pack("<4h", *boxes[0]))
        nodes.extend(struct.pack("<4h", *boxes[1]))
        nodes.extend(struct.pack("<HH", *kids))
        node_count += 1
        return node_count - 1  # post order: the root is the last node, as the engine expects

    build(0, n, 0, n)

    # ---- blockmap: one block per cell (block size 128). A line is listed in every block in
    # which it has a stretch of positive length (corner touches are not listed).
    block_lists = []
    for by in range(n):
        for bx in range(n):
            ids = sorted({
                line_of[("v", bx, by)], line_of[("v", bx + 1, by)],
                line_of[("h", by, bx)], line_of[("h", by + 1, bx)],
            })
            block_lists.append(ids)
    offset = 4 + n * n
    offsets = []
    body = bytearray()
    for ids in block_lists:
        offsets.append(offset)
        body += struct.pack(f"<{len(ids)}H", *ids) + struct.pack("<H", 0xFFFF)
        offset += len(ids) + 1
    if offset - 1 > 0x7FFF:
        raise ValueError("blockmap offsets exceed the signed 16-bit range the engine reads")
    blockmap = struct.pack("<hhhh", pm.ORIGIN, pm.ORIGIN, n, n) + struct.pack(f"<{n * n}h", *offsets) + bytes(body)

    reject = bytes((n * n * n * n + 7) // 8)

    angle = sangle % 360
    things = struct.pack("<hhhhh", round(pm.ORIGIN + sx * pm.CELL_SIZE),
                         round(pm.ORIGIN + sy * pm.CELL_SIZE), angle, 1, 7)

    data = {
        "THINGS": things, "LINEDEFS": bytes(linedefs), "SIDEDEFS": bytes(sidedefs),
        "VERTEXES": vertexes, "SEGS": bytes(segs), "SSECTORS": bytes(ssectors),
        "NODES": bytes(nodes), "SECTORS": sectors, "REJECT": reject, "BLOCKMAP": blockmap,
    }
    return [(pm.LEVEL_NAME, b"")] + [(name, data[name]) for name in LUMP_ORDER]


def wad_bytes(lumps: list[tuple[str, bytes]]) -> bytes:
    """Serialize a PWAD: header, lump data, directory."""
    body = bytearray()
    directory = bytearray()
    pos = 12
    for name, data in lumps:
        directory += struct.pack("<ii8s", pos, len(data), name8(name))
        body += data
        pos += len(data)
    return b"PWAD" + struct.pack("<ii", len(lumps), pos) + bytes(body) + bytes(directory)


def parse_start(text: str) -> tuple[float, float, int]:
    parts = text.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected X,Y,ANGLE (cells, cells, degrees)")
    try:
        return float(parts[0]), float(parts[1]), int(parts[2])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pattern", choices=PATTERNS, default="flat",
                    help="test floor heights burnt into the sectors (flat = delivery state)")
    ap.add_argument("--seed", type=int, default=0, help="seed for --pattern random")
    ap.add_argument("--start", type=parse_start, default=DEFAULT_START, metavar="X,Y,ANGLE",
                    help="player start in cells (0..48) and degrees (multiple of 45; 0 = east, 90 = north)")
    ap.add_argument("--start-floor", type=int, default=pm.H_EMPTY,
                    help="floor height of the start cell (default 0)")
    ap.add_argument("-o", "--output", default=os.path.join(os.path.dirname(__file__), "..", "assets", "cosmergon.wad"))
    args = ap.parse_args()
    try:
        lumps = build_map(args.pattern, args.seed, args.start, args.start_floor)
    except ValueError as exc:
        print(f"make_map: {exc}", file=sys.stderr)
        return 2
    out = os.path.normpath(args.output)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as handle:
        handle.write(wad_bytes(lumps))
    print(f"wrote {out} (pattern {args.pattern})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
