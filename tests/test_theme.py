"""Tests of the themes (tools/make_theme.py, outline pass in doomgeneric/pov_control.c).

    python3 -m unittest tests.test_theme

Standard library only; starts the headless binary like tests.test_control.
"""

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
            self.assertEqual(len(lumps["PLAYPAL"]), 14 * 768)
            self.assertEqual(len(lumps["COLORMAP"]), 34 * 256)
            self.assertEqual(len(lumps["POVTHEME"]), 520)
            self.assertEqual(lumps["TEXTURE2"], struct.pack("<i", 0))

    def test_colormap_does_not_dim(self):
        # every light row is the identity except the joints ("twins"), which fold to their surface
        for name in make_theme.THEMES:
            pal = make_theme.build_palette(make_theme.THEMES[name])
            cm = make_theme.colormap(pal)
            for row in range(32):
                for i in range(256):
                    if i in make_theme.TWIN_OF.values():
                        continue
                    self.assertEqual(cm[row * 256 + i], i, (name, row, i))

    def test_joints_fold_away_with_distance(self):
        pal = make_theme.build_palette(make_theme.THEMES["wueste"])
        cm = make_theme.colormap(pal)
        for base, twin in make_theme.TWIN_OF.items():
            self.assertEqual(cm[twin], twin)                 # near: a joint
            self.assertEqual(cm[31 * 256 + twin], base)      # far: the surface
            self.assertEqual(pal[twin], make_theme.NAVY)

    def test_navy_is_not_black(self):
        self.assertNotEqual(make_theme.NAVY, (0, 0, 0))

    def test_deterministic(self):
        self.assertEqual(make_theme.build_theme("gelbestadt"), make_theme.build_theme("gelbestadt"))


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

    def test_sky_gradient_has_no_lines(self):
        # looking at an empty field: above the horizon only sky shapes may carry outlines; a column
        # through gradient only (x = 10 at angle 0 sees column ~ 1000) shows no navy
        rc, err, frames = render("cam 24.5 24.5 200\nnext\n", "gelbestadt")
        self.assertEqual(rc, 0, err)
        navy = make_theme.NAVY
        col = [tc.pixel(frames[0], 636, y) for y in range(0, 150)]
        self.assertNotIn(navy, col[:100])


if __name__ == "__main__":
    unittest.main()
