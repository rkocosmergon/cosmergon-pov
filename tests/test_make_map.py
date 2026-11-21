# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/make_map.py (standard library only). Run: python3 -m unittest tests.test_make_map"""

import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_map  # noqa: E402
import pov_measures as pm  # noqa: E402

IWAD = os.environ.get("POV_TEST_IWAD", os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"))
N = 48

# Counts from the grid formula (not read back from the generator).
SECTORS = N * N  # 2304
VERTEXES = (N + 1) ** 2  # 2401
LINES_INTERIOR = 2 * N * (N - 1)  # 4512: 47 inner vertical + 47 inner horizontal lines of 48 pieces
LINES_BORDER = 4 * N  # 192
LINES = LINES_INTERIOR + LINES_BORDER  # 4704
SIDES = 2 * LINES_INTERIOR + LINES_BORDER  # 9216
SEGS = 4 * SECTORS  # 9216: four per cell
NODES = SECTORS - 1  # binary tree with 2304 leaves


def read_wad(data: bytes):
    magic, count, diroff = struct.unpack("<4sii", data[:12])
    lumps = []
    for i in range(count):
        pos, size, name = struct.unpack("<ii8s", data[diroff + 16 * i: diroff + 16 * i + 16])
        lumps.append((name.rstrip(b"\0").decode(), data[pos:pos + size], pos))
    return magic, lumps, diroff


def wad_names(path: str):
    """Lump names of a WAD and the names between two markers."""
    with open(path, "rb") as handle:
        data = handle.read()
    _, lumps, _ = read_wad(data)
    return [(n, d, p) for n, d, p in lumps], data


def cstr(raw: bytes) -> str:
    return raw.rstrip(b"\0").decode("ascii")


def iwad_names():
    lumps, data = wad_names(IWAD)
    names = [n for n, _, _ in lumps]
    start = names.index("F1_START") if "F1_START" in names else names.index("F_START")
    end = names.index("F1_END") if "F1_END" in names else names.index("F_END")
    flats = set(names[start + 1:end])
    texlump = [d for n, d, _ in lumps if n == "TEXTURE1"][0]
    count = struct.unpack("<i", texlump[:4])[0]
    textures = set()
    for i in range(count):
        off = struct.unpack("<i", texlump[4 + 4 * i: 8 + 4 * i])[0]
        textures.add(cstr(texlump[off:off + 8]))
    return flats, textures


class MapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lumps = make_map.build_map("flat")
        cls.data = {n: d for n, d in cls.lumps}
        cls.wad = make_map.wad_bytes(cls.lumps)

    def unpack(self, name, fmt):
        raw = self.data[name]
        size = struct.calcsize(fmt)
        self.assertEqual(len(raw) % size, 0, name)
        return [struct.unpack(fmt, raw[i:i + size]) for i in range(0, len(raw), size)]

    def test_wad_header_and_directory(self):
        magic, lumps, diroff = read_wad(self.wad)
        self.assertEqual(magic, b"PWAD")
        self.assertEqual([n for n, _, _ in lumps], [pm.LEVEL_NAME] + list(make_map.LUMP_ORDER))
        self.assertEqual(diroff + 16 * len(lumps), len(self.wad))
        pos = 12
        for name, data, filepos in lumps:
            self.assertEqual(filepos, pos, name)
            pos += len(data)
        self.assertEqual(pos, diroff)

    def test_lump_sizes_are_multiples_of_structs(self):
        for name, size in make_map.SIZES.items():
            self.assertEqual(len(self.data[name]) % size, 0, name)

    def test_counts_from_grid_formula(self):
        self.assertEqual(len(self.data["SECTORS"]) // 26, SECTORS)
        self.assertEqual(len(self.data["SSECTORS"]) // 4, SECTORS)
        self.assertEqual(len(self.data["VERTEXES"]) // 4, VERTEXES)
        self.assertEqual(len(self.data["LINEDEFS"]) // 14, LINES)
        self.assertEqual(len(self.data["SIDEDEFS"]) // 30, SIDES)
        self.assertEqual(len(self.data["SEGS"]) // 12, SEGS)
        self.assertEqual(len(self.data["NODES"]) // 28, NODES)
        self.assertEqual(len(self.data["THINGS"]) // 10, 1)
        self.assertEqual(len(self.data["REJECT"]), (SECTORS * SECTORS + 7) // 8)
        self.assertEqual(self.data["REJECT"].count(0), len(self.data["REJECT"]))
        # everything must fit the signed 16-bit fields of the engine
        self.assertLess(max(SECTORS, SEGS, SIDES, LINES, VERTEXES), 32768)

    def test_coordinates_are_16_bit_and_on_the_grid(self):
        for x, y in self.unpack("VERTEXES", "<hh"):
            self.assertTrue(-pm.MAP_SIZE // 2 <= x <= pm.MAP_SIZE // 2)
            self.assertTrue(-pm.MAP_SIZE // 2 <= y <= pm.MAP_SIZE // 2)
            self.assertEqual((x - pm.ORIGIN) % pm.CELL_SIZE, 0)
            self.assertEqual((y - pm.ORIGIN) % pm.CELL_SIZE, 0)
        self.assertEqual(pm.CELL_SIZE, 128)
        self.assertEqual(pm.MAP_SIZE, 6144)

    def test_two_sided_lines_have_lower_texture_on_both_sides(self):
        sides = self.unpack("SIDEDEFS", "<hh8s8s8sH")
        verts = self.unpack("VERTEXES", "<hh")
        two_sided = border = 0
        for v1, v2, flags, special, tag, s0, s1 in self.unpack("LINEDEFS", "<HHHHHHH"):
            x1, y1 = verts[v1]
            x2, y2 = verts[v2]
            self.assertEqual(abs(x2 - x1) + abs(y2 - y1), pm.CELL_SIZE)  # one cell edge, axis aligned
            self.assertTrue(x1 == x2 or y1 == y2)
            if flags & make_map.ML_TWOSIDED:
                two_sided += 1
                self.assertEqual(flags & make_map.ML_BLOCKING, 0)
                self.assertNotEqual(s1, make_map.NO_SIDE)
                for s in (s0, s1):
                    self.assertEqual(cstr(sides[s][3]), pm.TEX_LOWER)  # lower
                    self.assertEqual(cstr(sides[s][2]), "-")  # upper
                    self.assertEqual(cstr(sides[s][4]), "-")  # middle
                self.assertNotEqual(sides[s0][5], sides[s1][5])
            else:
                border += 1
                self.assertEqual(s1, make_map.NO_SIDE)
                self.assertEqual(cstr(sides[s0][4]), pm.TEX_BORDER)
        self.assertEqual((two_sided, border), (LINES_INTERIOR, LINES_BORDER))

    def test_every_texture_and_flat_exists_in_freedoom(self):
        if not os.path.exists(IWAD):
            self.skipTest("freedoom1.wad missing (bash scripts/download-freedoom.sh)")
        flats, textures = iwad_names()
        used_tex, used_flats = set(), set()
        for _, _, upper, lower, mid, _sector in self.unpack("SIDEDEFS", "<hh8s8s8sH"):
            used_tex.update(cstr(t) for t in (upper, lower, mid))
        for _, _, floor, ceil, *_rest in self.unpack("SECTORS", "<hh8s8shhh"):
            used_flats.update((cstr(floor), cstr(ceil)))
        used_tex.discard("-")
        self.assertTrue(used_tex, "no textures used")
        self.assertEqual(used_tex - textures, set(), 'textures missing in freedoom1.wad')
        self.assertEqual(used_flats - flats, set(), 'flats missing in freedoom1.wad')
        self.assertIn("F_SKY1", used_flats)

    def test_sector_geometry(self):
        for floor, ceiling, _f, _c, light, special, tag in self.unpack("SECTORS", "<hh8s8shhh"):
            self.assertEqual(floor, 0)
            self.assertEqual(ceiling, pm.CEILING)
            self.assertEqual((special, tag), (0, 0))
        self.assertGreater(pm.CEILING, 2 * pm.TOWER_TOP)

    def test_segs_belong_to_their_cell(self):
        verts = self.unpack("VERTEXES", "<hh")
        lines = self.unpack("LINEDEFS", "<HHHHHHH")
        sides = self.unpack("SIDEDEFS", "<hh8s8s8sH")
        segs = self.unpack("SEGS", "<HHHHHH")
        for c, (numsegs, first) in enumerate(self.unpack("SSECTORS", "<HH")):
            self.assertEqual((numsegs, first), (4, 4 * c))
            x0 = pm.ORIGIN + (c % N) * pm.CELL_SIZE
            y0 = pm.ORIGIN + (c // N) * pm.CELL_SIZE
            edges = set()
            for v1, v2, angle, line, side, offset in segs[first:first + 4]:
                self.assertEqual(sides[lines[line][5 + side]][5], c)  # own side of the line
                (ax, ay), (bx, by) = verts[v1], verts[v2]
                for px, py in ((ax, ay), (bx, by)):
                    self.assertTrue(x0 <= px <= x0 + 128 and y0 <= py <= y0 + 128)
                # the cell lies on the right of the seg: cross product of direction and (centre - start) < 0
                cross = (bx - ax) * (y0 + 64 - ay) - (by - ay) * (x0 + 64 - ax)
                self.assertLess(cross, 0)
                expected = {(1, 0): 0, (0, 1): 0x4000, (-1, 0): 0x8000, (0, -1): 0xC000}[
                    ((bx > ax) - (bx < ax), (by > ay) - (by < ay))]
                self.assertEqual(angle, expected)
                edges.add(frozenset(((ax, ay), (bx, by))))
            self.assertEqual(len(edges), 4)

    def test_bsp_reaches_every_subsector_once_and_boxes_hold_cells(self):
        nodes = self.unpack("NODES", "<hhhh4h4hHH")
        seen = {}
        reached_nodes = set()

        def walk(child, box):
            if child & make_map.NF_SUBSECTOR:
                ss = child & 0x7FFF
                self.assertNotIn(ss, seen)
                # the leaf's cell must lie inside the bounding box recorded on the way down
                x0 = pm.ORIGIN + (ss % N) * pm.CELL_SIZE
                y0 = pm.ORIGIN + (ss // N) * pm.CELL_SIZE
                top, bottom, left, right = box
                self.assertTrue(left <= x0 and x0 + 128 <= right and bottom <= y0 and y0 + 128 <= top)
                seen[ss] = True
                return
            self.assertNotIn(child, reached_nodes)
            reached_nodes.add(child)
            n = nodes[child]
            px, py, dx, dy = n[:4]
            for i, k in enumerate(n[12:14]):
                walk(k, n[4 + 4 * i: 8 + 4 * i])

        root = len(nodes) - 1
        walk(root, (pm.MAP_SIZE // 2, -pm.MAP_SIZE // 2, -pm.MAP_SIZE // 2, pm.MAP_SIZE // 2))
        self.assertEqual(len(seen), SECTORS)
        self.assertEqual(len(reached_nodes), NODES)

    def test_bsp_side_convention_matches_the_engine(self):
        """Child 0 is the side R_PointOnSide returns 0 for (r_main.c), checked with the same arithmetic."""
        nodes = self.unpack("NODES", "<hhhh4h4hHH")

        def point_on_side(x, y, px, py, dx, dy):
            if dx == 0:
                return (dy > 0) if x <= px else (dy < 0)
            if dy == 0:
                return (dx < 0) if y <= py else (dx > 0)
            return 0 if (y - py) * dx < dy * (x - px) else 1

        def locate(x, y):
            child = len(nodes) - 1
            while not child & make_map.NF_SUBSECTOR:
                n = nodes[child]
                child = n[12 + int(point_on_side(x, y, *n[:4]))]
            return child & 0x7FFF

        for cy in range(N):
            for cx in range(N):
                px = pm.ORIGIN + cx * pm.CELL_SIZE + 37
                py = pm.ORIGIN + cy * pm.CELL_SIZE + 91
                self.assertEqual(locate(px, py), cy * N + cx)

    def test_blockmap(self):
        raw = self.data["BLOCKMAP"]
        words = struct.unpack(f"<{len(raw) // 2}h", raw)
        self.assertEqual(words[:4], (pm.ORIGIN, pm.ORIGIN, N, N))
        offsets = words[4:4 + N * N]
        self.assertLess(max(offsets), 32768)
        verts = self.unpack("VERTEXES", "<hh")
        lines = self.unpack("LINEDEFS", "<HHHHHHH")
        expected = {b: [] for b in range(N * N)}
        for i, (v1, v2, *_r) in enumerate(lines):
            (ax, ay), (bx2, by2) = verts[v1], verts[v2]
            lo_x, hi_x = sorted((ax - pm.ORIGIN, bx2 - pm.ORIGIN))
            lo_y, hi_y = sorted((ay - pm.ORIGIN, by2 - pm.ORIGIN))
            # blocks with an overlap of positive length along the line; across it, every block
            # whose closed range contains the line (a line on a block edge is in both blocks)
            xs = range(lo_x // 128, -(-hi_x // 128)) if hi_x > lo_x else \
                [k for k in (lo_x // 128 - 1, lo_x // 128) if 0 <= k < N]
            ys = range(lo_y // 128, -(-hi_y // 128)) if hi_y > lo_y else \
                [k for k in (lo_y // 128 - 1, lo_y // 128) if 0 <= k < N]
            for by in ys:
                for bx in xs:
                    expected[by * N + bx].append(i)
        for b, off in enumerate(offsets):
            listed = []
            while words[off] != -1:
                listed.append(words[off])
                off += 1
            self.assertEqual(listed, sorted(expected[b]), f"block {b % N},{b // N}")

    def test_player_start(self):
        (x, y, angle, kind, options), = self.unpack("THINGS", "<hhhhh")
        self.assertEqual((x, y, angle, kind), (64, 64, 0, 1))
        self.assertEqual(options & 7, 7)

    def test_patterns_and_start_cell_stays_free(self):
        for pattern in make_map.PATTERNS:
            for start in ((24.5, 24.5, 0), (0.5, 0.5, 45), (0.5, 24.5, 90)):
                lumps = dict(make_map.build_map(pattern, 3, start))
                heights = [struct.unpack_from("<h", lumps["SECTORS"], 26 * i)[0] for i in range(SECTORS)]
                self.assertEqual(heights[pm.sector_index(int(start[0]), int(start[1]))], 0, (pattern, start))
                self.assertLessEqual(max(heights), pm.MAX_FLOOR)
                self.assertGreaterEqual(min(heights), 0)
        sectors = dict(make_map.build_map("full"))["SECTORS"]
        full = [struct.unpack_from("<h", sectors, 26 * i)[0] for i in range(SECTORS)]
        self.assertEqual(full.count(pm.H_CELL), SECTORS - 1)

    def test_start_floor_option_and_validation(self):
        lumps = dict(make_map.build_map("flat", start_floor=pm.TOWER_TOP))
        self.assertEqual(struct.unpack_from("<h", lumps["SECTORS"], 26 * pm.sector_index(24, 24))[0], pm.TOWER_TOP)
        for bad in ((0, 5, 0), (48.0, 5, 0), (5, 5, 30)):
            with self.assertRaises(ValueError):
                make_map.build_map("flat", start=bad)
        with self.assertRaises(ValueError):
            make_map.build_map("flat", start_floor=pm.CEILING)

    def test_deterministic(self):
        for pattern in make_map.PATTERNS:
            a = make_map.wad_bytes(make_map.build_map(pattern, 7))
            b = make_map.wad_bytes(make_map.build_map(pattern, 7))
            self.assertEqual(a, b, pattern)
        r1 = make_map.wad_bytes(make_map.build_map("random", 1))
        r2 = make_map.wad_bytes(make_map.build_map("random", 2))
        self.assertNotEqual(r1, r2)

    def test_two_generator_runs_are_byte_identical(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            outs = []
            for i in range(2):
                path = os.path.join(tmp, f"{i}.wad")
                subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_map.py"),
                                "--pattern", "random", "--seed", "5", "--start", "0.5,0.5,45", "-o", path],
                               check=True, stdout=subprocess.DEVNULL)
                with open(path, "rb") as handle:
                    outs.append(handle.read())
            self.assertEqual(outs[0], outs[1])


if __name__ == "__main__":
    unittest.main()
