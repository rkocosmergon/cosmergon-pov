"""Tests of the themes (tools/make_theme.py, outline pass in doomgeneric/pov_control.c).

    python3 -m unittest tests.test_theme

Standard library only; starts the headless binary like tests.test_control.
"""

import hashlib
import os
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import make_map  # noqa: E402
import make_theme  # noqa: E402
import theme_art as art  # noqa: E402
import theme_day  # noqa: E402
from tests import test_control as tc  # noqa: E402

WORK = tempfile.TemporaryDirectory()
SCENE = ("cell 24 26 cell\ncell 25 26 own\ncell 26 26 wall\ncell 27 26 tower\n"
         "cam 24.5 22.5 90\nnext\n")


MAP = os.path.join(WORK.name, "flat.wad")


def setUpModule():
    with open(MAP, "wb") as handle:
        handle.write(make_map.wad_bytes(make_map.build_map("flat")))
    for name in make_theme.THEMES:
        with open(os.path.join(WORK.name, name + ".wad"), "wb") as handle:
            handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))


def tearDownModule():
    WORK.cleanup()


def render(data, theme=None):
    cmd = tc.command(MAP) + ["-warp", "1", "1"]
    if theme:
        cmd += ["-pov-theme", os.path.join(WORK.name, theme + ".wad")]
    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run(cmd, input=data.encode("ascii"), env=tc.engine_env(out), stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=60)
        err = proc.stderr.decode("ascii", "replace")
        frames = tc.read_frames(out)
    return proc.returncode, err, frames


def colours(frame):
    body = frame[tc.HEADER:]
    return {tuple(body[i:i + 3]) for i in range(0, len(body), 3)}


class Generator(unittest.TestCase):
    def test_lumps_have_the_sizes_of_the_format(self):
        for name in make_theme.THEMES:
            lumps = dict(make_theme.build_theme(name))
            self.assertEqual(len(lumps["PLAYPAL"]), len(theme_day.KEYS) * 768)   # one palette a key of the day
            self.assertEqual(len(lumps["COLORMAP"]), 34 * 256)
            self.assertEqual(len(lumps["POVTHEME"]), 520)
            self.assertEqual(len(lumps["POVX"]), 2056)
            self.assertEqual(lumps["TEXTURE2"], struct.pack("<i", 0))

    def test_colormap_does_not_dim(self):
        # every light row is the identity except the lines ("twins"), which fold to their surface
        for name in make_theme.THEMES:
            pal = make_theme.build_palette(make_theme.THEMES[name])
            cm = make_theme.colormap(pal)
            for row in range(32):
                for i in range(256):
                    if i in art.TWIN_SET or i in art.SURFACE_OF_SMALL or i in art.SMALL_TWIN.values():
                        continue
                    self.assertEqual(cm[row * 256 + i], i, (name, row, i))

    def test_lines_fold_away_with_distance(self):
        pal = make_theme.build_palette(make_theme.THEMES["wueste"])
        cm = make_theme.colormap(pal)
        for base, (core, halo, fine) in art.TW.items():
            self.assertEqual(cm[core], core)                 # near: a line
            self.assertEqual(cm[halo], base)                 # near: the second texel is not there yet
            self.assertEqual(cm[fine], fine)
            for twin in (core, halo, fine):
                self.assertEqual(cm[31 * 256 + twin], base)  # far: the surface
                self.assertEqual(pal[twin], make_theme.NAVY)
            rows = [r for r in range(32) if cm[r * 256 + halo] == halo]
            self.assertTrue(rows, base)                      # the halo shows between its two distances
            self.assertEqual(rows, list(range(rows[0], rows[-1] + 1)))
            self.assertGreater(rows[0], 0)
            # the fine things fold no later than the coarse line, and the halo ends where the core ends
            core_rows = [r for r in range(32) if cm[r * 256 + core] == core]
            fine_rows = [r for r in range(32) if cm[r * 256 + fine] == fine]
            self.assertLessEqual(len(fine_rows), len(core_rows))
            self.assertEqual(rows[-1] + 1, core_rows[-1] + 1)

    def test_small_flecks_fold_into_their_surface(self):
        pal = make_theme.build_palette(make_theme.THEMES["wueste"])
        cm = make_theme.colormap(pal)
        for small, surface in art.SURFACE_OF_SMALL.items():
            fleck = art.FLECK_OF_SMALL[small]
            self.assertEqual(pal[small], pal[fleck])                 # the colour of the fleck
            self.assertEqual(cm[small], small)                       # near: the fleck
            self.assertEqual(cm[31 * 256 + small], surface)          # far: the surface
            twin = art.SMALL_TWIN[small]
            self.assertEqual(cm[twin], twin)                         # its line, near
            self.assertEqual(cm[31 * 256 + twin], surface)
            self.assertEqual(pal[twin], make_theme.NAVY)
            # the line never shows the fleck's colour after the fleck is gone
            for row in range(32):
                if cm[row * 256 + small] == surface:
                    self.assertEqual(cm[row * 256 + twin], surface)

    def test_navy_is_not_black(self):
        self.assertNotEqual(make_theme.NAVY, (0, 0, 0))

    def test_deterministic(self):
        self.assertEqual(make_theme.build_theme("gelbestadt"), make_theme.build_theme("gelbestadt"))

    def test_every_kind_has_several_variants_and_all_differ(self):
        surf = make_theme.surfaces()
        for kind, (_l, dens, slots) in make_theme.WALL_KINDS.items():
            self.assertGreaterEqual(len(dens), 6, kind)
            self.assertEqual(len(slots), make_theme.SLOTS)
            self.assertEqual(set(slots), set(range(len(dens))), kind)       # every variant is in a slot
            for axis in (0, 1):
                faces = {bytes(b"".join(surf["tex"][make_theme.wall_names(kind, v)[axis]])) for v in range(len(dens))}
                self.assertEqual(len(faces), len(dens), (kind, axis))
        for kind, (_l, styles, slots) in make_theme.TOP_STYLES.items():
            self.assertGreaterEqual(len(styles), 4, kind)
            self.assertEqual(set(slots), set(range(len(styles))), kind)
            tops = {surf["flats"][make_theme.top_name(kind, v)] for v in range(len(styles))}
            self.assertEqual(len(tops), len(styles), kind)
        grounds = {surf["flats"][make_theme.ground_name(v, e)] for v in range(len(make_theme.GROUND_DENS)) for e in range(4)}
        self.assertEqual(len(grounds), len(make_theme.GROUND_DENS) * 4)
        self.assertEqual(set(make_theme.GROUND_SLOTS), set(range(len(make_theme.GROUND_DENS))))

    def test_the_kinds_differ_in_form_not_only_in_colour(self):
        # the same index layout is used by every theme; compare the pictures with colours taken out:
        # a pixel is "line" or "area" (a twin index or not); the forms of the kinds must differ
        surf = make_theme.surfaces()

        def form(grid):
            return b"".join(bytes(1 if v in art.TWIN_SET else 0 for v in row) for row in grid)
        shapes = {kind: {form(surf["tex"][make_theme.wall_names(kind, v)[0]]) for v in range(len(dens))}
                  for kind, (_l, dens, _s) in make_theme.WALL_KINDS.items()}
        kinds = list(shapes)
        for i, a in enumerate(kinds):
            for b in kinds[i + 1:]:
                self.assertFalse(shapes[a] & shapes[b], (a, b))
        # the own cell carries its mark in every variant: a framed plate near the middle that the cell has not
        for v in range(len(make_theme.WALL_KINDS["own"][1])):
            grid = surf["tex"][make_theme.wall_names("own", v)[0]]
            ink = sum(1 for row in grid for x in row if x in art.TWIN_SET)
            self.assertGreater(ink, 600, v)

    def test_faces_use_only_their_own_indices(self):
        surf = make_theme.surfaces()
        for kind in art.ROLES:
            ids = art.I_ROLE[kind]
            for v in range(len(make_theme.WALL_KINDS[kind][1])):
                for axis, (a, b) in zip(("x", "y"), (("x0", "x1"), ("y0", "y1"))):
                    allowed = {ids[a], ids[b]} | {t for key in (ids[a], ids[b]) for t in art.TW[key]}
                    allowed |= {art.SMALL_OF[ids[b]], art.SMALL_TWIN[art.SMALL_OF[ids[b]]]}
                    if kind == "tower":
                        allowed |= {art.I_BAND[axis], *art.TW[art.I_BAND[axis]]}
                    seen = {x for row in surf["tex"][make_theme.wall_names(kind, v)[0 if axis == "x" else 1]] for x in row}
                    self.assertLessEqual(seen, allowed, (kind, v, axis, sorted(seen - allowed)))

    def test_floors_have_three_stages_at_most(self):
        surf = make_theme.surfaces()
        stages = (art.I_GROUND, art.I_GROUND_SHADE, art.I_GROUND_LIGHT)
        ground = set(stages) | {t for b in stages for t in art.TW[b]}
        ground |= {art.SMALL_OF[b] for b in stages[1:]} | {art.SMALL_TWIN[art.SMALL_OF[b]] for b in stages[1:]}
        for v in range(len(make_theme.GROUND_DENS)):
            for e in range(4):
                self.assertLessEqual(set(surf["flats"][make_theme.ground_name(v, e)]), ground)

    def test_a_fleck_is_in_the_class_of_its_surface(self):
        # no outline around a stain: the stages of one face share a class (and a rank)
        lump = make_theme.theme_lump()
        cls, rank = lump[8:264], lump[264:520]
        for role in art.ROLES:
            ids = art.I_ROLE[role]
            for a, b in (("t0", "t1"), ("x0", "x1"), ("y0", "y1")):
                self.assertEqual(cls[ids[a]], cls[ids[b]])
                self.assertEqual(rank[ids[a]], rank[ids[b]])
            self.assertNotEqual(cls[ids["t0"]], cls[ids["x0"]])             # but top and side are different surfaces
            self.assertNotEqual(cls[ids["x0"]], cls[ids["y0"]])
        for base, trio in art.TW.items():
            for twin in trio:
                self.assertEqual((cls[twin], rank[twin]), (cls[base], rank[base]))
        self.assertEqual({cls[i] for i in (art.I_GROUND, art.I_GROUND_SHADE, art.I_GROUND_LIGHT)}, {art.I_GROUND})


class Engine(unittest.TestCase):
    def test_every_theme_draws_only_its_palette(self):
        for name, theme in make_theme.THEMES.items():
            pal = make_theme.build_palette(theme)
            allowed = set(pal)
            rc, err, frames = render(SCENE, name)
            self.assertEqual(rc, 0, err)
            self.assertEqual(len(frames), 1)
            seen = colours(frames[0])
            self.assertLessEqual(seen, allowed, (name, sorted(seen - allowed)[:5]))
            self.assertIn(make_theme.NAVY, seen)             # outlines are there
            self.assertNotIn((0, 0, 0), seen)                # and never black
            self.assertNotIn((255, 0, 255), seen)            # no stray palette entry
            self.assertIn("rejected=0", err)

    def test_no_dimming_with_distance(self):
        # the same wall colour at 2 and at 8 cells (one wall kind, one direction): no darkening
        rc, err, frames = render("cell 24 30 wall\ncell 24 44 wall\ncam 24.5 22.5 90\nnext\n", "gelbestadt")
        self.assertEqual(rc, 0, err)
        wall = make_theme.hexrgb(make_theme.THEMES["gelbestadt"]["wall"])
        dark = make_theme.shade(wall)
        seen = colours(frames[0])
        self.assertTrue(wall in seen or dark in seen)
        for c in seen:
            self.assertNotEqual(c, tuple(int(x * 0.5) for x in wall))

    def test_two_runs_are_identical(self):
        a = render(SCENE, "blaustadt")[2][0]
        b = render(SCENE, "blaustadt")[2][0]
        self.assertEqual(a, b)

    def test_without_theme_the_picture_is_the_old_one(self):
        rc, err, frames = render(SCENE)
        self.assertEqual(rc, 0, err)
        self.assertGreater(len(colours(frames[0])), 16)      # freedoom textures, many colours
        self.assertNotIn(make_theme.NAVY, colours(frames[0]) - {(26, 35, 50)} | set())

    def test_own_cell_is_a_kind(self):
        for theme in (None, "wueste"):
            rc, err, frames = render("cell 5 5 own\nrow 6 O" + "." * 47 + "\ncam 24.5 24.5 0\nnext\n", theme)
            self.assertEqual(rc, 0, err)
            self.assertIn("rejected=0", err)

    def test_without_theme_the_pictures_are_those_of_the_previous_build(self):
        # reference hashes of the build 81fb3a0 (before variants, origin and 256 texel textures)
        want = {
            "default": "2d8f291e3a4c88a54880c32afd374528a77bbb7517c76f2618ff5c79c4790d88",
            "672x324": "d3e1227f534689089b61259654c401b2f33be3e4db6e618b7cc92fa54b6e2c1b",
            "1280x640": "59f7a817614574a970d330dff4540040817fe4eb07f2009cdb35772529b812f9",
            "things": "37f02f7d25f9662cc19c98a97a0e02b4dcf82ac5072bd865faa0eb7d698eb71a",
        }
        cases = {"default": SCENE, "672x324": "size 672 324\n" + SCENE, "1280x640": "size 1280 640\n" + SCENE,
                 "things": "thing 1 marauder 24.5 25 0\nthing 2 loot 25.5 24.5 0\n" + SCENE}
        for key, data in cases.items():
            rc, err, frames = render(data)
            self.assertEqual(rc, 0, err)
            self.assertEqual(hashlib.sha256(frames[-1]).hexdigest(), want[key], key)

    def test_sky_gradient_has_no_lines(self):
        # looking at an empty field: above the horizon only sky shapes may carry outlines; a column
        # through gradient only (x = 10 at angle 0 sees column ~ 1000) shows no navy
        rc, err, frames = render("cam 24.5 24.5 200\nnext\n", "gelbestadt")
        self.assertEqual(rc, 0, err)
        navy = make_theme.NAVY
        col = [tc.pixel(frames[0], 636, y) for y in range(0, 150)]
        self.assertNotIn(navy, col[:100])


FIELD = "".join("row %d %s\n" % (y, "".join("#=OT"[(x * 7 + y * 3) % 4] if (x + y) % 3 else "." for x in range(48)))
                for y in range(48))


class Variants(unittest.TestCase):
    """The look of a cell follows its WORLD position (hash of position and side), not its place in the window."""

    @staticmethod
    def centre(frame, w=672, x0=150, x1=520):
        body = frame[tc.HEADER:]
        h = len(body) // (3 * w)
        return b"".join(body[(y * w + x0) * 3:(y * w + x1) * 3] for y in range(h))

    def look(self, theme, kind, world, place, side):
        """The middle of one cell's face seen straight on (side: 'S' sees the south face from the south,
        'W' the west face), where the cell with world coordinates `world` stands at window cell `place`;
        the ground in front of it is in the crop too."""
        (wx, wy), (a, b) = world, place
        if side == "S":
            cam = "cam %.1f %.1f 90\n" % (a + 0.5, b - 1.6)
        else:
            cam = "cam %.1f %.1f 0\n" % (a - 1.6, b + 0.5)
        data = ("size 672 324\norigin %d %d\ncell %d %d %s\n" % (wx - a, wy - b, a, b, kind) + cam + "next\n")
        rc, err, frames = render(data, theme)
        self.assertEqual(rc, 0, err)
        self.assertIn("rejected=0", err)
        body = frames[0][tc.HEADER:]
        w = 672
        return b"".join(body[(y * w + 276) * 3:(y * w + 396) * 3] for y in range(132, 324))

    def test_a_cell_keeps_its_look_when_the_window_moves(self):
        # the same world cell at three places of the window (the origin follows): the same face and ground
        worlds = ((50, 60), (51, 60), (-7, 1234), (3000, -2500))
        places = ((10, 10), (30, 26), (5, 40))
        for theme in ("wueste", "gelbestadt"):
            for char in ("cell", "own", "wall", "tower"):
                for side in "SW":
                    looks = []
                    for world in worlds:
                        shots = {self.look(theme, char, world, p, side) for p in places}
                        self.assertEqual(len(shots), 1, (theme, char, world, side))
                        looks.append(shots.pop())
                    self.assertGreater(len(set(looks)), 1, (theme, char, side))      # and the worlds differ

    def test_other_world_other_picture(self):
        # moving the origin WITHOUT moving the cells shows other variants (the hash differs)
        cam = "cam 20.5 20.5 30\nnext\n"
        a = render("size 672 324\n" + FIELD + cam, "wueste")[2][0]
        b = render("size 672 324\norigin 5 9\n" + FIELD + cam, "wueste")[2][0]
        self.assertNotEqual(a, b)

    def test_repeated_origin_is_bit_identical(self):
        data = "size 672 324\n" + FIELD + "origin 17 -3\ncam 20.5 20.5 30\nnext\norigin 17 -3\nnext\norigin 0 0\norigin 17 -3\nnext\n"
        frames = render(data, "gelbestadt")[2]
        self.assertEqual(len(frames), 3)
        self.assertEqual(frames[0], frames[1])
        self.assertEqual(frames[0], frames[2])

    def test_every_kind_shows_several_variants(self):
        # a long row of one kind seen from the south: the faces of the cells are not all alike
        for kind, char in (("cell", "#"), ("own", "O"), ("wall", "="), ("tower", "T")):
            seen = set()
            for x0 in (6, 14, 22, 30):
                row = "." * x0 + char * 12 + "." * (48 - x0 - 12)
                data = "size 672 324\nrow 30 %s\ncam %.1f 27.6 90\nnext\n" % (row, x0 + 6.0)
                frame = render(data, "wueste")[2][0]
                body = frame[tc.HEADER:]
                w = 672
                # the faces of the front side: one band of rows around the middle of the picture
                for face in range(6):
                    xa, xb = 20 + face * 105, 20 + face * 105 + 100
                    crop = b"".join(body[((y * w) + xa) * 3:((y * w) + xb) * 3] for y in range(140, 190))
                    seen.add(hashlib.sha1(crop).hexdigest())
            self.assertGreaterEqual(len(seen), 8, kind)

    def test_origin_of_a_theme_picture_stays_inside_the_palette(self):
        pal = set(make_theme.build_palette(make_theme.THEMES["blaustadt"]))
        for origin in ("0 0", "-1000000 1000000", "123456 -654321"):
            rc, err, frames = render("size 672 324\norigin %s\n" % origin + FIELD + "cam 20.5 20.5 30\nnext\n", "blaustadt")
            self.assertEqual(rc, 0, err)
            self.assertLessEqual(colours(frames[0]), pal)


if __name__ == "__main__":
    unittest.main()
