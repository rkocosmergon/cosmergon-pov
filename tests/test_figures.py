# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests of the own figures: the templates (assets/figures, tools/figures.py), their making (tools/make_figures.py), the
sprites in the theme PWADs (tools/make_theme.py) and the figures in the picture (doomgeneric/pov_control.c `s_thing_kind`).

    python3 -m unittest tests.test_figures

Standard library only; starts the headless binary like tests.test_control.
"""

import os
import re
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import figures  # noqa: E402
import make_figures  # noqa: E402
import make_map  # noqa: E402
import make_theme  # noqa: E402
import theme_art as art  # noqa: E402
from tests import test_control as tc  # noqa: E402

WORK = tempfile.TemporaryDirectory()
MAP = os.path.join(WORK.name, "flat.wad")
THEMES = sorted(make_theme.THEMES)
SOURCE = os.path.join(ROOT, "doomgeneric", "pov_control.c")
POS = "27.5 24.5"            # three cells ahead of the default camera: 384 units, 0.833 points a unit at 640 x 400
SCALE = 320 / 384
# the indices a figure may use: the navy, and the tops and the y side of each role (the x keys haze earlier than a
# sprite's light does, the ground and the sky are not for a figure)
ALLOWED = {art.I_OUTLINE} | {art.I_ROLE[r][k] for r in art.ROLES for k in ("t0", "t1", "y0", "y1")}
EXPECTED_NAMES = sorted(["TROOA%d" % n for n in range(1, 9)] + ["BOSSA%d" % n for n in range(1, 9)]
                        + ["HEADA%d" % n for n in range(1, 9)] + ["POL5A0", "BPAKA0"])


def setUpModule():
    with open(MAP, "wb") as handle:
        handle.write(make_map.wad_bytes(make_map.build_map("flat")))
    for name in THEMES:
        with open(os.path.join(WORK.name, name + ".wad"), "wb") as handle:
            handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))


def tearDownModule():
    WORK.cleanup()


def frame_of(lines, theme=None):
    args = ["-warp", "1", "1"] + (["-pov-theme", os.path.join(WORK.name, theme + ".wad")] if theme else [])
    res = tc.run(lines, wad=MAP, args=args)
    assert res.rc == 0, res.err
    assert res.summary[1] == 0, res.err
    return res.frames[-1]


def thing(kind, angle=180, ident=1, pos=POS):
    return "thing %d %s %s %s\n" % (ident, kind, pos, angle)


def box(frame, base):
    """Bounding box (x0, y0, x1, y1) of the points where `frame` differs from `base`."""
    xs, ys = [], []
    for y in range(tc.H):
        a = tc.HEADER + 3 * y * tc.W
        if frame[a:a + 3 * tc.W] != base[a:a + 3 * tc.W]:
            for x in range(tc.W):
                if frame[a + 3 * x:a + 3 * x + 3] != base[a + 3 * x:a + 3 * x + 3]:
                    xs.append(x)
                    ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def templates():
    for kind, (_sprite, _frame, rotations) in figures.KINDS.items():
        for direction in range(8) if rotations else (0,):
            yield kind, direction, os.path.join(figures.FIGURES_DIR, figures.template_name(kind, direction))


def parse_patch(data):
    """A Doom picture as (width, height, left, top, columns of (first row, [values])); checks the structure."""
    width, height, left, top = struct.unpack("<hhhh", data[:8])
    offsets = struct.unpack("<%di" % width, data[8:8 + 4 * width])
    columns = []
    for off in offsets:
        assert 8 + 4 * width <= off < len(data)
        posts, pos = [], off
        while data[pos] != 0xFF:
            first, count = data[pos], data[pos + 1]
            assert count > 0 and first + count <= height
            assert data[pos + 2] == 0 and data[pos + 3 + count] == 0
            posts.append((first, list(data[pos + 3:pos + 3 + count])))
            pos += count + 4
        columns.append(posts)
    return width, height, left, top, columns


class Templates(unittest.TestCase):
    def test_every_figure_has_its_templates_and_they_are_small(self):
        paths = [p for _k, _d, p in templates()]
        self.assertEqual(len(paths), 26)            # 3 kinds x 8 directions, corpse and loot one look
        total = 0
        for path in paths:
            self.assertTrue(os.path.exists(path), path)
            size = os.path.getsize(path)
            self.assertLess(size, 2048, path)
            total += size
        self.assertLess(total, 40000)
        self.assertEqual(sorted(os.listdir(figures.FIGURES_DIR)), sorted(os.path.basename(p) for p in paths), "no stray file")

    def test_templates_are_wellformed_and_use_only_the_allowed_indices(self):
        for kind, direction, path in templates():
            grid, left, top = figures.read_template(path)
            self.assertTrue(all(len(line) == len(grid[0]) for line in grid), path)
            used = {v for line in grid for v in line if v is not None}
            self.assertLessEqual(used, ALLOWED, (path, sorted(used - ALLOWED)))
            self.assertTrue(all(any(v is not None for v in line) for line in grid), "cut to its box: " + path)
            self.assertTrue(0 <= left < len(grid[0]), path)
            self.assertGreater(top, 0, path)

    def test_the_sizes_in_units_are_those_of_the_concept(self):
        # one point = one unit, 32 to the metre: the monster is the largest and about 3.5 m high, the marauder a man's height
        height = {}
        for kind, direction, path in templates():
            if direction == 0:
                grid, _left, top = figures.read_template(path)
                height[kind] = (len(grid), len(grid[0]), top)
        self.assertTrue(100 <= height["monster"][0] <= 124, height)              # 3.1 .. 3.9 m
        self.assertTrue(72 <= height["monster"][1] <= 96, height)                # 2.3 .. 3.0 m wide
        self.assertTrue(56 <= height["marauder"][0] <= 70, height)               # 1.75 .. 2.2 m
        self.assertTrue(height["monster"][0] > height["marauder"][0] * 1.6, height)
        self.assertLess(height["bird"][0], 50)
        self.assertGreater(height["bird"][1], height["bird"][0] * 2, "a bird with its wings spread")
        for kind in ("marauder", "monster", "bird"):
            self.assertLessEqual(height[kind][0] - height[kind][2], 1, "the feet (the lowest point of the bird) are at the origin: " + kind)

    def test_the_monster_is_the_darkest_figure_in_every_theme(self):
        def mean(kind, theme):
            pal = make_theme.build_palette(dict(make_theme.THEMES[theme]))
            points = []
            for direction in range(8):
                grid = figures.read_template(os.path.join(figures.FIGURES_DIR, figures.template_name(kind, direction)))[0]
                points += [pal[v] for line in grid for v in line if v is not None]
            return sum(luminance(c) for c in points) / len(points)
        for theme in THEMES:
            self.assertLess(mean("monster", theme), mean("marauder", theme) - 8, theme)
            self.assertLess(mean("monster", theme), mean("bird", theme) - 15, theme)

    def test_eyes_and_mouth_stand_out_in_every_theme(self):
        # eyes and teeth in the `own` tone, the mouth and the body in the navy: the contrast must hold in all themes, which
        # differ (yellow, orange); the limbs are the tower's y1
        for theme in THEMES:
            pal = make_theme.build_palette(dict(make_theme.THEMES[theme]))
            bright = luminance(pal[art.I_ROLE["own"]["t0"]])
            self.assertGreater(bright - luminance(pal[art.I_OUTLINE]), 90, theme)
            self.assertGreater(bright - luminance(pal[art.I_ROLE["tower"]["y1"]]), 45, theme)
            self.assertGreater(bright - luminance(pal[art.I_ROLE["tower"]["t1"]]), 15, theme)
        grid = figures.read_template(os.path.join(figures.FIGURES_DIR, figures.template_name("monster", 0)))[0]
        used = {v for line in grid for v in line if v is not None}
        self.assertIn(art.I_ROLE["own"]["t0"], used, "eyes")
        self.assertIn(art.I_OUTLINE, used)

    def test_a_template_of_a_direction_differs_from_every_other(self):
        for kind in ("marauder", "monster", "bird"):
            seen = {}
            for direction in range(8):
                grid, left, top = figures.read_template(os.path.join(figures.FIGURES_DIR, figures.template_name(kind, direction)))
                seen[direction] = (tuple(map(tuple, grid)), left, top)
            self.assertEqual(len(set(seen.values())), 8, kind + ": eight different looks")


class Lumps(unittest.TestCase):
    def test_each_theme_brings_the_sprites_inside_its_own_range(self):
        for theme in THEMES:
            lumps = make_theme.build_theme(theme)
            names = [n for n, _d in lumps]
            first, last = names.index("S_START"), names.index("S_END")
            self.assertGreater(first, names.index("F_END"), "after the floors")
            self.assertEqual(sorted(names[first + 1:last]), EXPECTED_NAMES, theme)
            self.assertEqual(len(names), len(set(names)), "no name twice: " + theme)
            self.assertFalse([n for n in names if re.match(r"TROO[B-M]", n)], "no placeholders for a death frame")

    def test_a_picture_lump_is_wellformed_and_uses_the_allowed_indices(self):
        checked = 0
        for name, data in make_theme.build_theme("wueste"):
            if name in EXPECTED_NAMES:
                checked += 1
                width, height, _left, top, columns = parse_patch(data)
                self.assertTrue(8 <= width <= 128 and 8 <= height <= 128, name)
                self.assertEqual(len(columns), width)
                values = {v for posts in columns for _f, run in posts for v in run}
                self.assertLessEqual(values, ALLOWED, name)
                self.assertTrue(any(posts for posts in columns))
                self.assertGreater(top, 0)
        self.assertEqual(checked, len(EXPECTED_NAMES))

    def test_the_rotations_are_the_directions_mirrored_round(self):
        lumps = dict(make_theme.build_theme("wueste"))
        for sprite, kind in (("TROO", "marauder"), ("BOSS", "monster"), ("HEAD", "bird")):
            for n in range(1, 9):
                direction = (-(n - 1)) % 8
                grid, left, top = figures.read_template(os.path.join(figures.FIGURES_DIR, figures.template_name(kind, direction)))
                self.assertEqual(lumps["%sA%d" % (sprite, n)], figures.patch_lump(grid, left, top), (kind, n))

    def test_a_theme_is_the_same_bytes_every_time(self):
        for theme in THEMES:
            self.assertEqual(make_theme.wad_bytes(make_theme.build_theme(theme)), make_theme.wad_bytes(make_theme.build_theme(theme)))
        sprites = figures.sprite_lumps()
        self.assertEqual(sprites, figures.sprite_lumps())

    def test_the_sprite_lumps_are_the_same_in_every_theme(self):
        # the templates hold indices of the layout, not colours: one set of lumps, the colours come from PLAYPAL
        def sprites(theme):
            lumps = make_theme.build_theme(theme)
            names = [n for n, _d in lumps]
            return lumps[names.index("S_START"):]
        self.assertEqual(sprites("wueste"), sprites("blaustadt"))
        self.assertEqual(sprites("wueste"), sprites("gelbestadt"))


def synthetic_render(path, shift=0):
    """A 160 x 160 RGBA picture: a body in one source colour with a line round it, the feet 16 points above the bottom."""
    width = height = 160
    rows = []
    for y in range(height):
        row = bytearray(width * 4)
        for x in range(width):
            inside = 50 + shift <= x < 110 + shift and 30 <= y < 144
            edge = inside and (x in (50 + shift, 109 + shift) or y in (30, 143))
            if inside:
                row[x * 4:x * 4 + 4] = bytes((90, 103, 122, 255)) if edge else bytes((44, 33, 65, 255))
        rows.append(b"\0" + bytes(row))
    raw = b"".join(rows)

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Making(unittest.TestCase):
    def make(self, out, shift=0):
        with tempfile.TemporaryDirectory() as pictures:
            for kind, (pattern, _table) in make_figures.KINDS.items():
                os.makedirs(os.path.join(pictures, kind))
                for direction in range(8):
                    synthetic_render(os.path.join(pictures, kind, pattern % direction if "%d" in pattern else pattern), shift)
            return make_figures.make_templates(pictures, out)

    def test_the_templates_are_made_the_same_every_time_and_follow_the_picture(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b, tempfile.TemporaryDirectory() as c:
            written = self.make(a)
            self.make(b)
            self.make(c, shift=20)
            self.assertEqual(len(written), 26)
            for name in sorted(os.listdir(a)):
                with open(os.path.join(a, name), "rb") as one, open(os.path.join(b, name), "rb") as two:
                    self.assertEqual(one.read(), two.read(), name)
            grid, left, top = figures.read_template(os.path.join(a, "monster-0.png"))
            self.assertEqual((len(grid[0]), len(grid)), (12, 23))                # 60 x 114 render points, 5 to a point
            self.assertEqual(top, 23, "the foot row (16 points over the bottom of the picture) is the origin")
            self.assertEqual(left, 6, "the origin (the middle of the picture) is in the middle of the body")
            shifted = figures.read_template(os.path.join(c, "monster-0.png"))
            self.assertEqual(shifted[1], 2, "a body 20 points (4 sprite points) to the right has its origin 4 nearer the left")
            self.assertEqual(grid[len(grid) // 2][len(grid[0]) // 2], art.I_OUTLINE, "the monster's body is the navy")


class Engine(unittest.TestCase):
    def test_the_table_of_the_program_names_the_sprites_of_the_templates(self):
        text = tc.read_text(SOURCE)
        body = re.search(r"s_thing_kind\[\] = \{(.*?)\n\};", text, re.S).group(1)
        rows = {n: (s, int(f)) for n, s, f, _l in re.findall(r'\{ "(\w+)",\s+SPR_(\w+),\s+(\d+),\s+(\d+) \}', body)}
        for kind, (sprite, frame, _rot) in figures.KINDS.items():
            self.assertEqual(rows[kind], (sprite, ord(frame) - ord("A")), kind)

    def boxes(self, theme):
        base = frame_of("next\n", theme)
        return {k: box(frame_of(thing(k) + "next\n", theme), base) for k in figures.KINDS}

    def test_the_figures_stand_where_they_should_and_have_their_size(self):
        for theme in THEMES:
            b = self.boxes(theme)
            for kind in ("marauder", "monster", "bird"):
                grid, _left, _top = figures.read_template(os.path.join(figures.FIGURES_DIR, figures.template_name(kind, 0)))
                self.assertAlmostEqual(b[kind][3] - b[kind][1] + 1, len(grid) * SCALE, delta=6, msg=(theme, kind, "height"))        # + the outline round it
                self.assertAlmostEqual(b[kind][2] - b[kind][0] + 1, len(grid[0]) * SCALE, delta=6, msg=(theme, kind, "width"))
                self.assertAlmostEqual((b[kind][0] + b[kind][2]) / 2, tc.W / 2, delta=3, msg=(theme, kind, "in the middle"))
            self.assertLessEqual(abs(b["monster"][3] - b["marauder"][3]), 3, "both stand on the floor: " + theme)
            self.assertLessEqual(abs(b["loot"][3] - b["marauder"][3]), 8, theme)
            self.assertGreater(b["monster"][3] - b["monster"][1], 1.6 * (b["marauder"][3] - b["marauder"][1]), theme)
            self.assertLess(b["corpse"][3] - b["corpse"][1], (b["marauder"][3] - b["marauder"][1]) // 3, "it lies: " + theme)

    def test_the_bird_floats_over_the_floor_and_under_the_top_of_a_cell(self):
        for theme in THEMES:
            b = self.boxes(theme)
            gap = b["marauder"][3] - b["bird"][3]
            self.assertAlmostEqual(gap, 40 * SCALE, delta=4, msg=theme)         # the lift of 40 units, its lowest point at the origin
            self.assertAlmostEqual(b["bird"][3] - b["bird"][1] + 1, 41 * SCALE, delta=6, msg=theme)      # the own bird, 41 points high
            base = frame_of("next\n", theme)
            high = frame_of(thing("bird") + "cell 24 24 cell\nnext\n", theme)
            self.assertIsNotNone(box(high, base))
            grid, _l, top = figures.read_template(os.path.join(figures.FIGURES_DIR, figures.template_name("bird", 0)))
            self.assertLess(40 + top, 128, "the top of the bird under the top of a cell")

    def test_a_turn_changes_the_picture_in_every_step(self):
        for theme in ("wueste",):
            for kind in ("marauder", "monster", "bird"):
                base = frame_of("next\n", theme)
                frames = [frame_of(thing(kind, a) + "next\n", theme) for a in range(0, 360, 45)]
                self.assertEqual(len(set(frames)), 8, (theme, kind))
                for angle, frame in zip(range(0, 360, 45), frames):
                    got = box(frame, base)
                    grid = figures.read_template(os.path.join(figures.FIGURES_DIR, figures.template_name(kind, (-(angle - 180) // 45) % 8)))[0]
                    self.assertAlmostEqual(got[3] - got[1] + 1, len(grid) * SCALE, delta=6, msg=(kind, angle))
                    self.assertAlmostEqual(got[2] - got[0] + 1, len(grid[0]) * SCALE, delta=6, msg=(kind, angle))

    def test_a_corpse_and_a_loot_do_not_turn(self):
        a = frame_of(thing("corpse", 0) + "next\n", "wueste")
        for angle in (45, 90, 200, 359):
            self.assertEqual(frame_of(thing("corpse", angle) + "next\n", "wueste"), a, angle)

    def test_the_themes_colour_the_same_figure_differently(self):
        frames = {t: frame_of(thing("monster") + "next\n", t) for t in THEMES}
        self.assertEqual(len(set(frames.values())), len(THEMES))

    def test_the_figure_is_drawn_in_the_palette_of_its_theme(self):
        for theme in THEMES:
            pal = set(make_theme.build_palette(dict(make_theme.THEMES[theme])))
            body = frame_of(thing("monster") + thing("bird", 90, 2, "27.5 26.5") + "next\n", theme)[tc.HEADER:]
            seen = {tuple(body[i:i + 3]) for i in range(0, len(body), 3)}
            self.assertLessEqual(seen, pal, theme)

    def test_without_a_theme_the_placeholders_are_drawn(self):
        # no theme: the IWAD's sprite (69 units high), not ours (117)
        res = tc.run("next\n" + thing("monster") + "next\n", wad=MAP, args=["-warp", "1", "1"])
        self.assertEqual(res.summary, (3, 0), res.err)
        base, with_monster = res.frames
        x0, y0, x1, y1 = box(with_monster, base)
        self.assertAlmostEqual(y1 - y0 + 1, 69 * SCALE, delta=6)
        self.assertGreater(len({with_monster[i:i + 3] for i in range(tc.HEADER, len(with_monster), 3)}), 16, "the IWAD's colours")
        themed = frame_of(thing("monster") + "next\n", "wueste")
        self.assertNotEqual(themed, with_monster)

    def test_the_documentation_names_the_figures_their_size_and_their_licence(self):
        text = tc.read_text(os.path.join(ROOT, "COSMERGON.md"))
        section = text[text.index("## Own figures"):]
        section = section[:section.index("\n## ", 5)] if "\n## " in section[5:] else section
        for word in ("assets/figures", "tools/make_figures.py", "GPL-2.0", "3.7 m", "32 points to the metre", "own work"):
            self.assertIn(word, section)


if __name__ == "__main__":
    unittest.main()
