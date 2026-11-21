"""Tests of the picture size (doomgeneric/pov_control.c, r_*.c; COSMERGON.md, "Picture size").

    python3 -m unittest tests.test_size

Standard library only; starts the headless binary like tests.test_control (never with DISPLAY).
Frames of 1280 x 800 are 3 MB each and /tmp is RAM on the build machines: every run here keeps at
most a handful of them (POV_EVERY thins the output where a run is long) and removes them at once.

POV_BIN and POV_SANITIZED are honoured as in tests.test_control. POV_UPSTREAM_BIN (default
doomgeneric/cosmergon-pov-headless-upstream, built if missing) is the build with Doom's own limits
(`make -f Makefile.headless UPSTREAM_LIMITS=1`), used to show that an overflow ends loudly.
"""

import os
import re
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

UPSTREAM_BIN = os.environ.get("POV_UPSTREAM_BIN",
                              os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless-upstream"))
MIN_W, MIN_H, MAX_W, MAX_H = 160, 100, 1280, 800
GRID = 48

# The renderer's limits at the largest picture (r_defs.h; derivation in COSMERGON.md).
LINES = 2 * GRID * (GRID + 1)
LIMIT_DRAWSEGS = 2 * LINES
LIMIT_VISPLANES = 2 * GRID * GRID + 2 * LIMIT_DRAWSEGS
LIMIT_OPENINGS = MAX_W * 2 * 2 * (2 * GRID - 1)
LIMIT_SOLIDSEGS = MAX_W // 2 + 2

WORK = tempfile.TemporaryDirectory()
MAP = os.path.join(WORK.name, "flat.wad")


def setUpModule():
    with open(MAP, "wb") as handle:
        handle.write(make_map.wad_bytes(make_map.build_map("flat")))
    if not os.path.exists(UPSTREAM_BIN):
        subprocess.run(["make", "-C", os.path.join(ROOT, "doomgeneric"), "-f", "Makefile.headless",
                        "UPSTREAM_LIMITS=1", "-j4"], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)


def tearDownModule():
    WORK.cleanup()


def size_of(frame):
    """(width, height) from the PPM header; checks the length of the file."""
    m = re.match(rb"P6\n(\d+) (\d+)\n255\n", frame)
    assert m, frame[:20]
    w, h = int(m.group(1)), int(m.group(2))
    assert len(frame) == len(m.group(0)) + 3 * w * h, (len(frame), w, h)
    return w, h


def pix(frame, x, y):
    m = re.match(rb"P6\n(\d+) (\d+)\n255\n", frame)
    w = int(m.group(1))
    off = len(m.group(0)) + 3 * (y * w + x)
    return tuple(frame[off:off + 3])


def engine(data, args=(), binary=None, every=1, timeout=120, wad=MAP, theme=None):
    """Run the engine on `data` (str). Returns (returncode, stderr, frames)."""
    cmd = [binary or tc.BIN, "-iwad", tc.IWAD, "-file", wad]
    if theme:
        cmd += ["-pov-theme", theme]
    cmd += ["-pov-control", "-warp", "1", "1"] + list(args)
    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run(cmd, input=data.encode("ascii"), env=tc.engine_env(out, every=every),
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout)
        err = proc.stderr.decode("ascii", "replace")
        if tc.SANITIZED and binary is None:
            assert not tc.sanitizer_findings(err), tc.sanitizer_findings(err)
        return proc.returncode, err, tc.read_frames(out)


SCENE = "cell 26 22 cell\ncell 26 23 wall\ncell 28 25 tower\ncell 22 26 cell\ncam 24.5 24.5 20\nnext\n"


class Option(unittest.TestCase):
    def test_default_is_the_old_picture(self):
        rc, err, frames = engine(SCENE)
        self.assertEqual(rc, 0, err)
        self.assertEqual(size_of(frames[0]), (640, 400))

    def test_size_option_gives_exactly_that_many_points(self):
        for w, h in ((672, 324), (MIN_W, MIN_H), (MAX_W, MAX_H), (161, 101), (777, 333), (320, 200), (200, 800)):
            rc, err, frames = engine(SCENE, ["-pov-size", "%dx%d" % (w, h)])
            self.assertEqual(rc, 0, (w, h, err))
            self.assertEqual(len(frames), 1)
            self.assertEqual(size_of(frames[0]), (w, h))
            self.assertGreater(len({pix(frames[0], x, h - 1) for x in range(0, w, 3)}), 1, (w, h))

    def test_bad_size_option_stops_with_a_message(self):
        for bad in ("159x200", "320x99", "1281x800", "1280x801", "0x0", "abc", "320", "320x", "x200",
                    "320x200x1", "-320x200", "320.5x200", " 320x200", "99999999999x200", "320x200 "):
            rc, err, frames = engine("next\n", ["-pov-size", bad], timeout=30)
            self.assertNotEqual(rc, 0, bad)
            self.assertIn("-pov-size", err, bad)
            self.assertEqual(frames, [], bad)

    def test_same_size_twice_is_bit_identical(self):
        a = engine(SCENE, ["-pov-size", "672x324"])[2][0]
        b = engine(SCENE, ["-pov-size", "672x324"])[2][0]
        self.assertEqual(a, b)


class Line(unittest.TestCase):
    def test_size_line_changes_the_picture_and_back(self):
        data = ("cam 24.5 24.5 20\nnext\nsize 672 324\nnext\nsize 1280 800\nnext\nsize 672 324\nnext\n"
                "size 160 100\nnext\nsize 640 400\nnext\n")
        rc, err, frames = engine(data)
        self.assertEqual(rc, 0, err)
        self.assertEqual([size_of(f) for f in frames],
                         [(640, 400), (672, 324), (1280, 800), (672, 324), (160, 100), (640, 400)])
        self.assertIn("rejected=0", err)
        # the same size twice in one run: the same bytes (no state of the earlier size is left)
        self.assertEqual(frames[1], frames[3])

    def test_size_in_the_middle_equals_a_run_started_in_that_size(self):
        scene = "cell 25 24 cell\ncell 27 25 tower\n"
        mid = engine(scene + "cam 24.5 24.5 10\nnext\nsize 777 333\nnext\ncam 26.5 24.5 100\nsize 400 300\nnext\n"
                     "size 777 333\nnext\n")
        self.assertEqual(mid[0], 0, mid[1])
        frames = mid[2]
        self.assertEqual([size_of(f) for f in frames], [(640, 400), (777, 333), (400, 300), (777, 333)])
        # (the world changed between frames 2 and 3: compare against fresh runs of the same state)
        for index, (cam, size) in ((1, ("24.5 24.5 10", "777x333")), (2, ("26.5 24.5 100", "400x300"))):
            fresh = engine(scene + "cam %s\nnext\n" % cam, ["-pov-size", size])[2][0]
            self.assertEqual(frames[index], fresh, index)
        fresh = engine(scene + "cam 26.5 24.5 100\nnext\n", ["-pov-size", "777x333"])[2][0]
        self.assertEqual(frames[3], fresh)

    def test_repeat_of_a_run_with_size_changes_is_bit_identical(self):
        data = SCENE + "size 500 300\nnext\nsize 1000 500\nnext\nsize 500 300\nnext\n"
        a = engine(data)
        b = engine(data)
        self.assertEqual(a[0], 0, a[1])
        self.assertEqual(a[2], b[2])

    def test_size_line_only_applies_to_the_next_picture(self):
        # `size` alone draws nothing; `next` draws in the size reached so far
        rc, err, frames = engine("size 300 200\nsize 400 250\nnext\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual([size_of(f) for f in frames], [(400, 250)])

    def test_invalid_size_lines_are_rejected_and_counted(self):
        bad = ["size", "size 320", "size 320 200 1", "size 159 200", "size 320 99", "size 1281 800",
               "size 1280 801", "size 0 0", "size -320 200", "size 320.5 200", "size 3e2 200", "size a b",
               "size 99999999999 200", "size 0x140 200", "size 320 200x", "SIZE 320 200", "size,320,200"]
        rc, err, frames = engine("".join(line + "\n" for line in bad) + "size 400 300\nnext\n")
        self.assertEqual(rc, 0, err)
        self.assertIn("control: lines=%d rejected=%d" % (len(bad) + 2, len(bad)), err)
        self.assertEqual([size_of(f) for f in frames], [(400, 300)])

    def test_rejected_size_keeps_the_size_in_force(self):
        rc, err, frames = engine("size 500 300\nnext\nsize 1281 800\nnext\nsize 500 99\nnext\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual([size_of(f) for f in frames], [(500, 300)] * 3)
        self.assertEqual(frames[0], frames[1])
        self.assertIn("rejected=2", err)

    def test_limits_are_accepted(self):
        rc, err, frames = engine("size 160 100\nnext\nsize 1280 800\nnext\nsize 160 800\nnext\nsize 1280 100\nnext\n",
                                 every=1)
        self.assertEqual(rc, 0, err)
        self.assertEqual([size_of(f) for f in frames], [(160, 100), (1280, 800), (160, 800), (1280, 100)])
        self.assertIn("rejected=0", err)

    def test_summary_names_the_size(self):
        rc, err, frames = engine("size 672 324\nnext\n")
        self.assertIn("size=672x324", err)


# ---------------------------------------------------------------------------------------------
# Aspect: square points, the horizon in the middle, a cube looks like a cube.
# ---------------------------------------------------------------------------------------------
CELL_X = 24
CELL_Y = 24
EYE = 41
HEIGHT = 128


def colour_box(frame, rgb):
    """Bounding box (x0, y0, x1, y1) of the points of one colour (None when there is none)."""
    w, h = size_of(frame)
    head = len(re.match(rb"P6\n\d+ \d+\n255\n", frame).group(0))
    pattern = bytes(rgb)
    xs, ys = [], []
    for y in range(h):
        row = frame[head + 3 * y * w: head + 3 * (y + 1) * w]
        x = row.find(pattern)
        while x >= 0:
            if x % 3 == 0:
                xs.append(x // 3)
                ys.append(y)
            x = row.find(pattern, x + 1)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


class Aspect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # the theme "wueste": flat colours, so the face of the cell is one colour (the lines lie
        # outside of it: a surface keeps its area) and its bounding box is the face itself
        cls.theme = os.path.join(WORK.name, "aspect.wad")
        with open(cls.theme, "wb") as handle:
            handle.write(make_theme.wad_bytes(make_theme.build_theme("wueste")))
        cls.colour = make_theme.hexrgb(make_theme.THEMES["wueste"]["cell"])

    def measure(self, w, h, distance_cells):
        """The face of a 128 x 128 x 128 cell seen from `distance_cells` * 128 units straight on:
        the bounding box of its colour in the picture."""
        data = ("cell %d %d cell\ncam %.3f %.3f 0\nnext\n" % (CELL_X, CELL_Y, CELL_X - distance_cells, CELL_Y + 0.5))
        rc, err, frames = engine(data, ["-pov-size", "%dx%d" % (w, h)], theme=self.theme)
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(frames), 1)
        box = colour_box(frames[0], self.colour)
        self.assertIsNotNone(box, (w, h, distance_cells))
        return box

    def test_a_cube_has_equal_width_and_height_in_points(self):
        # Focal length (points) = width / 2 for the 90 degree horizontal field; the face is 128 units
        # wide and 128 high at the distance d: both sides are 128 * (w / 2) / d points. The top and
        # the bottom edge lie (128 - 41) and 41 units above and below the eye, which is at row h / 2.
        for w, h in ((672, 324), (1280, 640), (1280, 800), (200, 800), (MIN_W, MIN_H), (320, 200), (900, 300)):
            for cells in (2.0, 3.0):
                d = cells * 128
                side = 128 * (w / 2) / d
                centre = h // 2
                if centre - (HEIGHT - EYE) * (w / 2) / d < 2 or centre + EYE * (w / 2) / d > h - 2:
                    continue        # the face does not fit into this shape at this distance
                x0, y0, x1, y1 = self.measure(w, h, cells)
                width, height = x1 - x0 + 1, y1 - y0 + 1
                msg = "%dx%d at %.0f cells: box %s" % (w, h, cells, (x0, y0, x1, y1))
                self.assertAlmostEqual(width, side, delta=2.0, msg=msg + " width")
                self.assertAlmostEqual(height, side, delta=2.0, msg=msg + " height")
                self.assertLessEqual(abs(width - height), 2, msg)
                # horizon in the middle: the eye line (row h / 2) cuts the face at 41 / 128 from its bottom
                self.assertAlmostEqual(y0, centre - (HEIGHT - EYE) * (w / 2) / d, delta=2.0, msg=msg + " top")
                self.assertAlmostEqual(y1 + 1, centre + EYE * (w / 2) / d, delta=2.0, msg=msg + " bottom")
                # and the face is centred sideways
                self.assertAlmostEqual((x0 + x1 + 1) / 2, w / 2, delta=2.0, msg=msg + " centre")

    def test_ratio_does_not_change_the_horizontal_angle(self):
        # the same horizontal field in every shape: a cell two cells away is 128 / 256 of half the width
        # wide whatever the height is
        widths = {h: self.measure(672, h, 2.0) for h in (200, 324, 500, 800)}
        spans = {h: b[2] - b[0] for h, b in widths.items()}
        self.assertLessEqual(max(spans.values()) - min(spans.values()), 1, spans)


# ---------------------------------------------------------------------------------------------
# Limits at the largest picture, in the worst field (every other cell built on, the 48 x 48 window).
# ---------------------------------------------------------------------------------------------
def checker(parity):
    return "".join("row %d %s\n" % (y, "".join("#" if (x + y) % 2 == parity else "." for x in range(GRID)))
                   for y in range(GRID))


def highwater(err):
    m = re.search(r"highwater drawsegs=(\d+) visplanes=(\d+) openings=(\d+) solidsegs=(\d+)", err)
    return tuple(int(g) for g in m.groups())


class Limits(unittest.TestCase):
    CORNERS = ("0.5 0.5 45", "47.5 0.5 135", "47.5 47.5 225", "0.5 47.5 315", "0.5 24.5 0", "24.5 24.5 45")

    def test_worst_field_at_the_largest_picture_stays_inside_the_limits(self):
        worst = [0, 0, 0, 0]
        for parity in (0, 1):
            for cam in self.CORNERS:
                rc, err, frames = engine(checker(parity) + "cam %s\nnext\n" % cam,
                                         ["-pov-size", "%dx%d" % (MAX_W, MAX_H)], every=1000)
                self.assertEqual(rc, 0, (parity, cam, err[-300:]))
                if not tc.SANITIZED:        # (a sanitizer build prints known "runtime error" lines of upstream)
                    self.assertNotRegex(err, r"(?i)no more|overflow|error")
                self.assertEqual(len(frames), 1)      # the last picture is always kept
                worst = [max(a, b) for a, b in zip(worst, highwater(err))]
        drawsegs, visplanes, openings, solidsegs = worst
        self.assertLess(drawsegs, LIMIT_DRAWSEGS)
        self.assertLess(visplanes, LIMIT_VISPLANES)
        self.assertLess(openings, LIMIT_OPENINGS)
        self.assertLess(solidsegs, LIMIT_SOLIDSEGS)
        # the measured worst case uses a good part of the derived bound (the bound is not slack by chance)
        self.assertGreater(drawsegs, LIMIT_DRAWSEGS // 4)

    def test_an_overflow_is_loud_not_a_wrong_picture(self):
        # Doom's own limits (a separate build) cannot draw this field: the program stops with a message
        # and a non-zero exit, and writes no picture.
        if not os.path.exists(UPSTREAM_BIN):
            self.skipTest("no upstream-limits build")
        rc, err, frames = engine(checker(1) + "cam 47.5 0.5 135\nnext\n", ["-pov-size", "1280x800"],
                                 binary=UPSTREAM_BIN, every=1000)
        self.assertNotEqual(rc, 0)
        self.assertRegex(err, r"no more drawsegs \(256\)")
        self.assertEqual(frames, [])


class Things(unittest.TestCase):
    def test_things_next_to_the_camera_at_the_largest_picture(self):
        # the nearest a thing may be drawn follows the picture width (pov_minz): no number leaves its range
        lines = ["cam 24.5 24.5 0"]
        for i in range(24):
            lines.append("thing %d %s %.3f %.3f %d" % (i, "marauder" if i % 2 else "loot",
                                                       24.5 + 0.02 * (i % 6) + 0.01, 24.5 + 0.03 * (i // 6) - 0.04, i * 15))
        lines += ["next", "cam 24.5 24.5 90", "next", "size 1280 100", "next", "size 160 800", "next"]
        rc, err, frames = engine("\n".join(lines) + "\n", ["-pov-size", "1280x800"], every=1000)
        self.assertEqual(rc, 0, err[-400:])
        self.assertEqual(len(frames), 1)

    def test_random_lines_with_size_changes(self):
        import random
        rng = random.Random(1337)
        lines = []
        frames_wanted = 0
        for _ in range(3000):
            r = rng.random()
            if r < 0.30:
                lines.append("cell %d %d %s" % (rng.randrange(GRID), rng.randrange(GRID),
                                                rng.choice(["empty", "cell", "wall", "tower", "own"])))
            elif r < 0.50:
                lines.append("thing %d %s %.3f %.3f %d" % (rng.randrange(256), rng.choice(["marauder", "loot"]),
                                                          rng.uniform(0, 47.99), rng.uniform(0, 47.99),
                                                          rng.randrange(-720, 720)))
            elif r < 0.70:
                lines.append("cam %.3f %.3f %d" % (rng.uniform(0, 47.99), rng.uniform(0, 47.99),
                                                   rng.randrange(-720, 720)))
            elif r < 0.85:
                lines.append("size %d %d" % (rng.randint(MIN_W, MAX_W), rng.randint(MIN_H, MAX_H)))
            elif r < 0.90:
                lines.append("size %d %d" % (rng.randint(0, 2000), rng.randint(0, 1000)))       # mostly out of range
            else:
                lines.append("next")
                frames_wanted += 1
        rc, err, frames = engine("\n".join(lines) + "\n", every=40)
        self.assertEqual(rc, 0, err[-400:])
        self.assertGreater(frames_wanted, 100)
        self.assertLessEqual(len(frames), frames_wanted // 40 + 2)
        for frame in frames:
            w, h = size_of(frame)
            self.assertTrue(MIN_W <= w <= MAX_W and MIN_H <= h <= MAX_H, (w, h))


class Window(unittest.TestCase):
    def test_a_picture_of_every_theme_in_the_target_size_uses_only_its_palette(self):
        scene = "cell 24 26 cell\ncell 25 26 own\ncell 26 26 wall\ncell 27 26 tower\ncam 24.5 22.5 90\nnext\n"
        for name, theme in make_theme.THEMES.items():
            path = os.path.join(WORK.name, name + ".wad")
            with open(path, "wb") as handle:
                handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))
            allowed = set(make_theme.build_palette(theme))
            for size in ("672x324", "1280x640"):
                rc, err, frames = engine(scene, ["-pov-size", size], theme=path)
                self.assertEqual(rc, 0, err)
                w, h = size_of(frames[0])
                head = len(re.match(rb"P6\n\d+ \d+\n255\n", frames[0]).group(0))
                body = frames[0][head:]
                seen = {tuple(body[i:i + 3]) for i in range(0, len(body), 3)}
                self.assertLessEqual(seen, allowed, (name, size, sorted(seen - allowed)[:3]))
                self.assertIn(make_theme.NAVY, seen)


if __name__ == "__main__":
    unittest.main()
