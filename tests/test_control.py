# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests of the control channel (doomgeneric/pov_control.c). Standard library only.

Every test starts the headless binary as a subprocess (never with DISPLAY, always with a timeout),
feeds command lines on stdin and compares the written PPM frames. Run:

    python3 -m unittest tests.test_control

Environment: POV_BIN (binary, default doomgeneric/cosmergon-pov-headless, built if missing),
POV_TEST_IWAD, POV_SANITIZED=1 (the binary is an ASan/UBSan build: leak check off).
"""

import hashlib
import os
import random
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_map  # noqa: E402
import pov_measures as pm  # noqa: E402

IWAD = os.environ.get("POV_TEST_IWAD", os.path.join(ROOT, "assets", "freedoom", "freedoom1.wad"))
BIN = os.environ.get("POV_BIN", os.path.join(ROOT, "doomgeneric", "cosmergon-pov-headless"))
SANITIZED = os.environ.get("POV_SANITIZED") == "1"
W, H = 640, 400
HEADER = 15  # "P6\n640 400\n255\n"
N = 48

WORK = tempfile.TemporaryDirectory()
FLAT_WAD = os.path.join(WORK.name, "flat.wad")
CHECKER_WAD = os.path.join(WORK.name, "checker.wad")


def setUpModule():
    if not os.path.exists(BIN):
        subprocess.run(["make", "-C", os.path.join(ROOT, "doomgeneric"), "-f", "Makefile.headless", "-j4"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for path, pattern in ((FLAT_WAD, "flat"), (CHECKER_WAD, "checker")):
        with open(path, "wb") as handle:
            handle.write(make_map.wad_bytes(make_map.build_map(pattern)))


def tearDownModule():
    WORK.cleanup()


class Frame(bytes):
    """A PPM file as bytes; a short repr keeps failure messages readable."""

    def __repr__(self):
        return "<Frame sha256=%s>" % hashlib.sha256(self).hexdigest()[:12]


class Result:
    def __init__(self, rc, err, frames):
        self.rc = rc
        self.err = err
        self.frames = frames

    @property
    def summary(self):
        m = re.search(r"control: lines=(\d+) rejected=(\d+)", self.err)
        return (int(m.group(1)), int(m.group(2))) if m else None


def engine_env(out, live=False, every=1):
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env["POV_OUT"] = out
    env["POV_EVERY"] = str(every)
    if live:
        env["POV_CONTROL_LIVE"] = "1"
        env["POV_LIVE_MS"] = "20"
    if SANITIZED:
        env["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
        env["UBSAN_OPTIONS"] = "print_stacktrace=1"
    return env


# Upstream behaviour that every frame shows, independent of the input (reported in COSMERGON.md):
#  - left shift of negative values (benign with gcc, formally undefined), many places
#  - r_draw.c:653-656 and 840-843 (R_DrawSpan, R_DrawSpanLow): span position shift wraps on purpose
#  - r_plane.c:464-474 reads top[-1] / top[1280]: the pad entries around visplane_t.top/bottom (r_defs.h;
#    upstream: top[320] of type byte)
UPSTREAM_UBSAN = re.compile(r"left shift of negative value|^r_draw\.c:(65[3-6]|84[0-3]):\d+: runtime error: left shift"
                            r"|^r_plane\.c:4(6[4-9]|7[0-4]):\d+: runtime error: index -?\d+ out of bounds for type "
                            r"'(byte \[320\]|short unsigned int \[1280\])'")


def sanitizer_findings(err):
    """Lines of a sanitizer report that are not one of the known upstream classes above."""
    return [l for l in err.splitlines()
            if ("runtime error" in l and not UPSTREAM_UBSAN.search(l)) or "AddressSanitizer" in l]


def command(wad, args=()):
    return [BIN, "-iwad", IWAD, "-file", wad, "-pov-control"] + list(args)


def read_frames(out):
    names = sorted(n for n in os.listdir(out) if n.startswith("frame-") and n.endswith(".ppm"))
    frames = []
    for name in names:
        with open(os.path.join(out, name), "rb") as handle:
            frames.append(Frame(handle.read()))
    return frames


def run(data, wad=FLAT_WAD, timeout=60, every=1, args=()):
    """Blocking mode: feed all of `data` (str or bytes), return Result.

    `every` > 1 thins the frames written: a frame is 768 kB and /tmp is RAM on the build machines,
    so a run with thousands of frames must not keep each of them (2.3 GB filled /tmp on 2026-11-20).
    """
    if isinstance(data, str):
        data = data.encode("ascii")
    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run(command(wad, args), input=data, env=engine_env(out, every=every), stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=timeout)
        err = proc.stderr.decode("ascii", "replace")
        if SANITIZED:
            assert not sanitizer_findings(err), sanitizer_findings(err)
        return Result(proc.returncode, err, read_frames(out))


def read_text(path):
    with open(path) as handle:
        return handle.read()


def pixel(frame, x, y):
    off = HEADER + 3 * (y * W + x)
    return tuple(frame[off:off + 3])


def lum(p):
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]


def row_of(y, spec):
    """48 characters for row y from a dict {x: char}."""
    return "row %d %s" % (y, "".join(spec.get(x, ".") for x in range(N)))


def first_frame(data, wad=FLAT_WAD):
    res = run(data, wad)
    assert res.rc == 0, res.err
    assert len(res.frames) >= 1, res.err
    return res.frames[-1]


EMPTY = None


def empty_frame():
    global EMPTY
    if EMPTY is None:
        EMPTY = first_frame("next\n")
    return EMPTY


# Default camera: cell (24.5, 24.5) facing east. World x of its eye: -3072 + 24.5 * 128 = 64.
CAM_X_WORLD = pm.ORIGIN + 24.5 * pm.CELL_SIZE


class MeasuresAndAssets(unittest.TestCase):
    def test_c_measures_equal_python(self):
        text = read_text(os.path.join(ROOT, "doomgeneric", "pov_control.c"))
        want = {"POV_H_EMPTY": pm.H_EMPTY, "POV_H_WALL": pm.H_WALL, "POV_H_CELL": pm.H_CELL,
                "POV_H_RING": pm.H_RING, "POV_H_TOWER": pm.TOWER_TOP, "POV_EYE": pm.EYE_HEIGHT, "POV_CELL_SIZE": pm.CELL_SIZE}
        for name, value in want.items():
            m = re.search(r"#define %s\s+\(?(-?\d+)\)?" % name, text)
            self.assertIsNotNone(m, name)
            self.assertEqual(int(m.group(1)), value, name)
        m = re.search(r"#define POV_ORIGIN\s+\((-?\d+)\)", text)
        self.assertEqual(int(m.group(1)), pm.ORIGIN)

    def test_names_exist_in_freedoom(self):
        text = read_text(os.path.join(ROOT, "doomgeneric", "pov_control.c"))
        table = re.search(r"s_kind\[K_COUNT\] = \{(.*?)\n\};", text, re.S).group(1)
        rows = re.findall(r'\{ "(\w+)",\s+"([^"]+)",\s+"([^"]+)"', table)
        self.assertEqual([r[0] for r in rows], ["empty", "cell", "wall", "tower", "own", "ring", "alcove", "shaftlo", "shafthi"])
        with open(IWAD, "rb") as handle:
            data = handle.read()
        count, off = struct.unpack("<ii", data[4:12])
        names = []
        lumps = {}
        for i in range(count):
            pos, size, nm = struct.unpack("<ii8s", data[off + 16 * i: off + 16 * i + 16])
            nm = nm.rstrip(b"\0").decode()
            names.append(nm)
            lumps.setdefault(nm, data[pos:pos + size])
        textures = set()
        for lump in ("TEXTURE1", "TEXTURE2"):
            blob = lumps.get(lump)
            if not blob:
                continue
            n = struct.unpack("<i", blob[:4])[0]
            for i in range(n):
                o = struct.unpack("<i", blob[4 + 4 * i: 8 + 4 * i])[0]
                name, _, w, h = struct.unpack("<8siHH", blob[o:o + 16])
                textures.add((name.rstrip(b"\0").decode(), w, h))
        flats = names[names.index("F1_START"):names.index("F1_END")]
        for _kind, lower, flat in rows:
            self.assertIn(lower, [t[0] for t in textures])
            self.assertEqual([t[2] for t in textures if t[0] == lower], [128], lower)  # 128 high
            self.assertIn(flat, flats)
        # the sprite frames the table uses (8 rotations or one for all): TROOA, BPAKA
        self.assertTrue(any(n.startswith("TROOA") for n in names))
        self.assertTrue(any(n.startswith("BPAKA") for n in names))
        # the five kinds look different: five distinct lower textures and five distinct flats; the four kinds of the
        # rim ring wear the wall's look without a theme that draws them
        self.assertEqual(len({r[1] for r in rows[:5]}), 5)
        self.assertEqual(len({r[2] for r in rows[:5]}), 5)
        for row in rows[5:]:
            self.assertEqual(row[1:], rows[2][1:], row[0])

    def test_flat_map_is_all_empty_and_start_in_the_middle(self):
        lumps = dict(make_map.build_map("flat"))
        sectors = lumps["SECTORS"]
        self.assertEqual(len(sectors), 26 * N * N)
        for i in range(N * N):
            floor, ceil, flat, _sky, light, _s, _t = struct.unpack("<hh8s8shhh", sectors[26 * i: 26 * i + 26])
            self.assertEqual(floor, pm.H_EMPTY)
            self.assertEqual(flat.rstrip(b"\0").decode(), pm.FLAT_FLOOR)
        x, y, angle, kind, _flags = struct.unpack("<hhhhh", lumps["THINGS"])
        self.assertEqual((x, y, kind), (round(CAM_X_WORLD), round(pm.ORIGIN + 24.5 * pm.CELL_SIZE), 1))

    def test_pattern_does_not_matter_at_start(self):
        a = first_frame("next\n", FLAT_WAD)
        b = first_frame("next\n", CHECKER_WAD)
        self.assertEqual(a, b)


class CellsAndRows(unittest.TestCase):
    def test_cell_changes_the_picture_and_empty_restores_it(self):
        base = empty_frame()
        changed = first_frame("cell 27 24 cell\nnext\n")
        self.assertNotEqual(base, changed)
        # -pov-rise 0: the test is about the state a cell is set to, not the way there (tests/test_rise.py:
        # by default the sinking cell is still on its way in the next frame)
        res = run("cell 27 24 cell\nnext\ncell 27 24 empty\nnext\n", args=("-pov-rise", "0"))
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(len(res.frames), 2)
        self.assertEqual(res.frames[0], changed)
        self.assertEqual(res.frames[1], base)

    def test_row_equals_cell_sequence(self):
        spec = {26: "#", 27: "=", 28: "T", 30: "#", 31: "#"}
        rows = "".join(row_of(y, spec) + "\n" for y in (23, 24, 25))
        kinds = {"#": "cell", "=": "wall", "T": "tower"}
        cells = "".join("cell %d %d %s\n" % (x, y, kinds[c]) for y in (23, 24, 25) for x, c in sorted(spec.items()))
        a = first_frame(rows + "next\n")
        b = first_frame(cells + "next\n")
        self.assertEqual(a, b)
        self.assertNotEqual(a, empty_frame())

    def test_row_overwrites_and_empties(self):
        a = first_frame(row_of(24, {27: "#"}) + "\nnext\n")
        b = first_frame(row_of(24, {27: "#"}) + "\n" + row_of(24, {}) + "\nnext\n")
        self.assertNotEqual(a, b)
        self.assertEqual(b, empty_frame())

    def test_kinds_look_different_and_have_the_right_height(self):
        # Camera (24.5, 24.5), eye 41 above floor 0, looking east at the cell (27, 24).
        # Its near face is at world x = -3072 + 27 * 128 = 384; the camera is at x = 64: d = 320 units.
        # The engine draws 320 x 200 with a 90 degree field of view (focal length 160 px) and the
        # platform doubles it to 640 x 400. A point at height z appears at output row
        #   y = 2 * (100 - 160 * (z - 41) / d)
        # so with d = 320 the face of a block of height h covers rows
        #   top = 2 * (100 - 0.5 * (h - 41))   bottom (z = 0) = 2 * (100 + 0.5 * 41) = 241
        base = empty_frame()
        d = 27 * pm.CELL_SIZE + pm.ORIGIN - CAM_X_WORLD
        self.assertEqual(d, 320)
        frames = {}
        for kind, h in (("cell", pm.H_CELL), ("wall", pm.H_WALL), ("tower", pm.TOWER_TOP)):
            frame = first_frame("cell 27 24 %s\nnext\n" % kind)
            frames[kind] = frame
            diff_rows = [y for y in range(H) if pixel(frame, 320, y) != pixel(base, 320, y)]
            self.assertTrue(diff_rows, kind)
            top_expected = 2 * (100 - 160 * (h - 41) / d)
            bottom_expected = 2 * (100 + 160 * 41 / d)
            self.assertAlmostEqual(min(diff_rows), top_expected, delta=3, msg="%s top" % kind)
            # the floor in front of the face can differ by a few rows (span rounding): wider tolerance below
            self.assertAlmostEqual(max(r for r in diff_rows if r < 250), bottom_expected, delta=6, msg="%s bottom" % kind)
        names = list(frames)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                self.assertNotEqual(frames[names[i]], frames[names[j]], (names[i], names[j]))
        self.assertNotEqual(frames["cell"], base)

    def test_camera_on_a_cell_sees_from_its_height(self):
        # Camera at (8.5, 24.5) looking west at the outer wall (x = -3072): d = 8.5 * 128 = 1088.
        # The wall reaches the sky ceiling at 512: its top edge is the row
        #   y = 2 * (100 - 160 * (512 - viewz) / d),   viewz = floor of the cell + 41.
        # The edge is found as the biggest brightness drop (bright sky to dark wall) in the centre column.
        d = 8.5 * pm.CELL_SIZE
        results = {}
        for kind, floor in (("empty", pm.H_EMPTY), ("wall", pm.H_WALL), ("cell", pm.H_CELL), ("tower", pm.TOWER_TOP)):
            frame = first_frame("cell 8 24 %s\ncam 8.5 24.5 180\nnext\n" % kind)
            col = [lum(pixel(frame, 320, y)) for y in range(0, 200)]
            drops = [(sum(col[y - 3:y]) / 3 - sum(col[y + 1:y + 4]) / 3, y) for y in range(3, 190)]
            edge = max(drops)[1] + 0.5
            expected = 2 * (100 - 160 * (512 - (floor + pm.EYE_HEIGHT)) / d)
            results[kind] = (edge, expected)
            self.assertAlmostEqual(edge, expected, delta=3, msg="%s: edge %s expected %s" % (kind, edge, expected))
        # the heights are ordered: higher eye -> edge lower on the screen (larger row)
        order = [results[k][0] for k in ("empty", "wall", "cell", "tower")]
        self.assertEqual(order, sorted(order))
        self.assertGreater(results["tower"][0] - results["empty"][0], 20)

    def test_camera_on_a_cell_is_allowed_in_every_kind(self):
        for kind in ("cell", "wall", "tower"):
            res = run("cell 24 24 %s\ncam 24.5 24.5 0\nnext\n" % kind)
            self.assertEqual(res.rc, 0, res.err)
            self.assertEqual(res.summary, (3, 0))

    def test_full_screen_no_bar_no_weapon(self):
        # Every cell is a 'cell' (floor flat GRASS1, green). The camera stands on a cell: no steps, the
        # whole lower half is that one green floor. A status bar (rows 336..399) or a weapon sprite
        # would show other colours there.
        rows = "".join("row %d %s\n" % (y, "#" * N) for y in range(N))
        frame = first_frame(rows + "next\n")
        self.assertEqual(len(frame), HEADER + 3 * W * H)
        bad = 0
        for y in range(240, H):
            for x in range(0, W, 8):
                r, g, b = pixel(frame, x, y)
                if not (g > r and g > b):
                    bad += 1
        self.assertEqual(bad, 0)
        for x in (0, 1, 319, 320, 638, 639):
            r, g, b = pixel(frame, x, H - 1)
            self.assertTrue(g > r and g > b, (x, (r, g, b)))
        # and the bottom row is the textured floor, not one flat colour (a bar would be)
        self.assertGreater(len({pixel(frame, x, H - 1) for x in range(W)}), 1)


SCENE = ("cell 26 22 cell\ncell 26 23 cell\ncell 26 25 wall\ncell 26 26 tower\n"
         "cell 22 26 cell\ncell 21 21 wall\ncell 23 28 tower\ncell 28 28 cell\n")


class Things(unittest.TestCase):
    def test_thing_appears_moves_and_goes(self):
        base = first_frame(SCENE + "next\n")
        res = run(SCENE + "next\n"
                  "thing 5 marauder 30.5 24.5 180\nnext\n"
                  "thing 5 marauder 29.5 24.5 180\nnext\n"
                  "gone 5\nnext\n")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(len(res.frames), 4)
        self.assertEqual(res.frames[0], base)
        self.assertNotEqual(res.frames[1], base)
        self.assertNotEqual(res.frames[2], res.frames[1])
        self.assertNotEqual(res.frames[2], base)
        self.assertEqual(res.frames[3], base)

    def test_loot_and_marauder_differ_and_marauder_turns(self):
        a = first_frame("thing 1 marauder 30.5 24.5 180\nnext\n")
        b = first_frame("thing 1 loot 30.5 24.5 180\nnext\n")
        c = first_frame("thing 1 marauder 30.5 24.5 0\nnext\n")
        d = first_frame("thing 1 marauder 30.5 24.5 90\nnext\n")
        self.assertEqual(len({a, b, c, d}), 4)
        # loot has one look, the facing does not matter
        b2 = first_frame("thing 1 loot 30.5 24.5 45\nnext\n")
        self.assertEqual(b, b2)

    def test_thing_behind_a_cell_is_hidden(self):
        # a tower 147 high, five cells wide, between the camera and the thing
        wall = "".join(row_of(y, {27: "T"}) + "\n" for y in range(20, 29))
        without = first_frame(wall + "next\n")
        with_thing = first_frame(wall + "thing 1 marauder 31.5 24.5 180\nthing 2 loot 33.5 24.5 0\nnext\n")
        self.assertEqual(with_thing, without)
        in_front = first_frame(wall + "thing 1 marauder 25.5 24.5 180\nnext\n")
        self.assertNotEqual(in_front, without)

    def test_thing_follows_the_floor(self):
        # same thing on a cell that is empty, then raised to a tower: it must stand on the new floor,
        # so the picture equals the one where the cell was already raised when it was placed.
        a = first_frame("thing 1 marauder 26.5 24.5 180\ncell 26 24 tower\nnext\n")
        b = first_frame("cell 26 24 tower\nthing 1 marauder 26.5 24.5 180\nnext\n")
        self.assertEqual(a, b)
        c = first_frame("thing 1 marauder 26.5 24.5 180\nnext\n")
        self.assertNotEqual(a, c)
        # standing on the tower (floor 147) it sticks out above the tower's edge for a camera at eye 41;
        # at z = 0 it would be inside the block and the picture would equal the bare tower
        bare = first_frame("cell 26 24 tower\nnext\n")
        self.assertNotEqual(a, bare)

    def test_many_things(self):
        lines = []
        for i in range(256):
            lines.append("thing %d %s %.2f %.2f %d" % (i, "marauder" if i % 2 else "loot",
                                                       2.5 + (i % 16) * 2.5, 2.5 + (i // 16) * 2.5, i * 7))
        res = run("\n".join(lines) + "\nnext\ncam 1 1 45\nnext\ncam 46 46 225\nnext\n")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.summary, (261, 0))
        self.assertEqual(len(res.frames), 3)
        m = re.search(r"vissprites=(\d+)", res.err)
        self.assertLessEqual(int(m.group(1)), 256)


class Camera(unittest.TestCase):
    def test_full_turn_returns_to_the_start(self):
        steps = "".join("cam 24.5 24.5 %d\nnext\n" % a for a in range(45, 361, 45))
        res = run(SCENE + "next\n" + steps)
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(len(res.frames), 9)
        self.assertEqual(res.frames[8], res.frames[0])
        self.assertEqual(len(set(res.frames[:8])), 8)  # every 45 degrees looks different in this scene

    def test_turn_in_small_steps(self):
        steps = "".join("cam 24.5 24.5 %d\nnext\n" % (a * 10) for a in range(1, 37))
        res = run(SCENE + "next\n" + steps)
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.frames[36], res.frames[0])

    def test_negative_and_large_angles(self):
        a = first_frame("cam 24.5 24.5 -90\nnext\n")
        b = first_frame("cam 24.5 24.5 270\nnext\n")
        c = first_frame("cam 24.5 24.5 %d\nnext\n" % (270 + 360 * 1000))
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_edge_and_corner_positions(self):
        spots = [(0, 0), (0, 47.999), (47.999, 0), (47.999, 47.999), (0, 24), (24, 0), (47.9999999, 24),
                 (1e-9, 1e-9), (0.5, 0.5)]
        text = ""
        for x, y in spots:
            for angle in (0, 45, 90, 135, 180, 225, 270, 315):
                text += "cam %r %r %d\nnext\n" % (x, y, angle)
        text += "cell 0 0 tower\ncell 47 47 tower\ncam 0 0 45\nnext\ncam 47.5 47.5 225\nnext\n"
        res = run(text)
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.summary[1], 0)
        self.assertEqual(len(res.frames), len(spots) * 8 + 2)

    def test_light_changes_the_picture_and_is_bounded(self):
        a = first_frame("light 255\nnext\n")
        b = first_frame("light 0\nnext\n")
        c = first_frame("light 100\nnext\n")
        self.assertEqual(len({a, b, c, empty_frame()}), 4)
        res = run("light 256\nlight -1\nlight x\nlight\nlight 1 2\nnext\n")
        self.assertEqual(res.summary, (6, 5))


def garbage_lines(count, seed=7):
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        n = rng.randint(1, 40)
        s = "".join(chr(rng.randint(33, 126)) for _ in range(n))
        if s.split(" ")[0] in ("cell", "row", "thing", "gone", "cam", "light", "next", "quit"):
            s = "x" + s
        out.append(s)
    return out


class BadInput(unittest.TestCase):
    VALID = SCENE + "thing 3 marauder 30.5 24.5 180\ncam 24.5 24.5 20\n"

    def bad_lines(self):
        long_line = "cell 27 24 " + "a" * 300
        lines = [
            "",                                  # empty line
            "   ",                               # only blanks
            long_line,                           # too long
            "x" * 255, "x" * 256, "x" * 100000,  # at and over the limit, huge
            "cell -1 0 cell", "cell 48 0 cell", "cell 0 -1 cell", "cell 0 48 cell", "cell 1.5 2 cell",
            "cell nan 2 cell", "cell NaN 2 cell", "cell 1e99 2 cell", "cell 2 1e99 cell", "cell inf 2 cell",
            "cell 0x10 2 cell", "cell 1e-400 2 cell",
            "cam 48 1 0", "cam -1 1 0", "cam 1 48 0", "cam nan 1 0", "cam 1 1 nan", "cam 1 1 1e99", "cam 1e99 1 0",
            "cam 1 1", "cam 1 1 0 0", "cam a b c",
            "row 0 " + "." * 47, "row 0 " + "." * 49, "row 0 " + "." * 47 + "x", "row 0 " + "?" * 48,
            "row 48 " + "." * 48, "row -1 " + "." * 48, "row 0", "row 0 " + "." * 24 + " " + "." * 24,
            "thing 256 marauder 1 1 0", "thing -1 marauder 1 1 0", "thing 1 dragon 1 1 0",
            "thing 1 marauder 48 1 0", "thing 1 marauder 1 -0.5 0", "thing 1 marauder 1 1", "thing 1.5 loot 1 1 0",
            "thing 1 loot 1 1 nan", "thing 99999999999999999999 loot 1 1 0",
            "gone 256", "gone", "gone -1", "gone x",
            "cell 1 1 tree", "cell 1 1", "cell 1 1 cell extra", "CELL 1 1 cell", "celll 1 1 cell",
            "next 0", "next -1", "next x", "next 1 2", "next 1000001",
            "quit now", "light 256", "light -1",
            "origin", "origin 1", "origin 1 2 3", "origin 1.5 2", "origin 2 1.5", "origin 1000001 0", "origin 0 -1000001",
            "origin nan 0", "origin 1e3 0", "origin a b", "ORIGIN 0 0", "origin 0x1 0", "origin 99999999999 0", "origin - 0",
            " ".join(["cell"] * 200),            # too many fields
        ]
        lines += garbage_lines(10000)
        rng = random.Random(11)
        for _ in range(50):                       # binary data: bytes 0..255 without newline
            blob = bytes(rng.choice([b for b in range(256) if b != 10]) for _ in range(rng.randint(1, 60)))
            if all(0x20 <= b <= 0x7E or b == 9 for b in blob):
                blob += b"\x00"
            lines.append(blob)
        lines.append(b"cell 1 1 cell\x00")
        lines.append(b"cell 1 1 cell\xff")
        lines.append(b"\x00")
        return lines

    def test_bad_lines_are_rejected_exactly_and_change_nothing(self):
        good = self.VALID + "next\n"
        want = first_frame(good)
        bad = self.bad_lines()
        parts = [self.VALID.encode()]
        for line in bad:
            parts.append((line if isinstance(line, bytes) else line.encode("ascii")) + b"\n")
        parts.append(b"next\n")
        res = run(b"".join(parts))
        self.assertEqual(res.rc, 0, res.err[-500:])
        valid_count = good.count("\n") - 1 + 1  # valid lines incl. next
        self.assertEqual(res.summary, (valid_count + len(bad), len(bad)), res.err[-300:])
        self.assertEqual(len(res.frames), 1)
        self.assertEqual(res.frames[0], want)
        msgs = [l for l in res.err.splitlines() if l.startswith("control: line ")]
        self.assertEqual(len(msgs), 20)  # at most the first 20 are named

    def test_a_valid_line_between_bad_ones_still_works(self):
        res = run("cell 1\ncell 27 24 cell\n\nnext\n")
        self.assertEqual(res.summary, (4, 2))
        self.assertEqual(res.frames[0], first_frame("cell 27 24 cell\nnext\n"))

    def test_line_limit_at_the_edge(self):
        # 255 bytes is the longest accepted line (here a thing line padded with blanks), 256 is rejected
        core = "light 100"
        ok = core + " " * (255 - len(core))
        too_long = core + " " * (256 - len(core))
        res = run(ok + "\n" + too_long + "\nnext\n")
        self.assertEqual(res.summary, (3, 1))
        self.assertEqual(res.frames[0], first_frame("light 100\nnext\n"))

    def test_crlf_and_tabs(self):
        res = run("cell\t27  24 \tcell\r\nnext\r\n")
        self.assertEqual(res.summary, (2, 0))
        self.assertEqual(res.frames[0], first_frame("cell 27 24 cell\nnext\n"))

    def test_pure_noise_does_not_crash(self):
        rng = random.Random(5)
        blob = bytes(rng.randrange(256) for _ in range(300000))
        res = run(blob + b"\nnext\n")
        self.assertEqual(res.rc, 0, res.err[-300:])
        self.assertEqual(res.summary[0] - res.summary[1], 1)  # only `next` is valid, nothing else
        self.assertEqual(res.frames[0], empty_frame())


class OriginLine(unittest.TestCase):
    """`origin <x> <y>`: world coordinates of cell 0, 0 of the window (variants of a theme follow them)."""

    def test_valid_lines_are_accepted_at_the_edges(self):
        good = ["origin 0 0", "origin 5 -7", "origin -1000000 1000000", "origin 1000000 -1000000", "origin 007 0",
                "origin\t1\t2", "origin   -0 0"]
        res = run("\n".join(good) + "\nnext\n")
        self.assertEqual(res.rc, 0, res.err[-300:])
        self.assertEqual(res.summary, (len(good) + 1, 0), res.err[-300:])

    def test_without_a_theme_the_origin_changes_nothing(self):
        # without a theme every kind has one look: the picture cannot depend on where the window lies
        a = first_frame(SCENE + "next\n")
        b = first_frame("origin 123 -456\n" + SCENE + "next\n")
        c = first_frame(SCENE + "origin -1000000 999999\nnext\n")
        self.assertEqual(a, b)
        self.assertEqual(a, c)


class EndOfInput(unittest.TestCase):
    def test_eof_without_quit(self):
        res = run("cell 27 24 cell\nnext\n")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.summary, (2, 0))
        self.assertEqual(len(res.frames), 1)

    def test_eof_in_the_middle_of_a_line(self):
        res = run("cell 27 24 cell\nnext")
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.summary, (2, 0))
        self.assertEqual(len(res.frames), 1)
        res = run("cell 27 24 ce")
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.summary, (1, 1))

    def test_empty_input(self):
        res = run("")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.summary, (0, 0))
        self.assertEqual(res.frames, [])

    def test_quit_in_the_middle(self):
        res = run("cell 27 24 cell\nnext\nquit\ncell 27 24 wall\nnext 5\ngarbage\n")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.summary, (3, 0))  # nothing after quit is read
        self.assertEqual(len(res.frames), 1)
        self.assertEqual(res.frames[0], first_frame("cell 27 24 cell\nnext\n"))

    def test_quit_first(self):
        res = run("quit\nnext\n")
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.summary, (1, 0))
        self.assertEqual(res.frames, [])

    def test_next_n_and_batch_is_atomic(self):
        res = run("cell 27 24 cell\ncell 28 24 tower\nnext 3\ncell 27 24 empty\nnext\n")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(len(res.frames), 4)
        self.assertEqual(res.frames[0], res.frames[1])
        self.assertEqual(res.frames[1], res.frames[2])
        self.assertNotEqual(res.frames[2], res.frames[3])


class Determinism(unittest.TestCase):
    def test_same_input_same_frames(self):
        rng = random.Random(3)
        lines = []
        for i in range(300):
            r = rng.random()
            if r < 0.4:
                lines.append("cell %d %d %s" % (rng.randrange(N), rng.randrange(N), rng.choice(["empty", "cell", "wall", "tower"])))
            elif r < 0.6:
                lines.append("thing %d %s %.3f %.3f %.1f" % (rng.randrange(256), rng.choice(["marauder", "loot"]),
                                                              rng.uniform(0, 47.99), rng.uniform(0, 47.99), rng.uniform(0, 360)))
            elif r < 0.7:
                lines.append("gone %d" % rng.randrange(256))
            elif r < 0.9:
                lines.append("cam %.3f %.3f %.1f" % (rng.uniform(0, 47.99), rng.uniform(0, 47.99), rng.uniform(0, 360)))
            else:
                lines.append("next")
        text = "\n".join(lines) + "\nnext\n"
        a = run(text)
        b = run(text)
        self.assertEqual(a.rc, 0, a.err)
        self.assertGreater(len(a.frames), 10)
        self.assertEqual(a.frames, b.frames)
        self.assertEqual(a.summary, b.summary)
        self.assertEqual(a.summary[1], 0)

    def test_checker_start_and_pipe_chunking_do_not_matter(self):
        text = SCENE + "thing 1 marauder 30.5 24.5 10\nnext\ncam 20 20 45\nnext\n"
        whole = run(text)
        # feed it byte by byte through a pipe: the lines are the same, so the frames must be equal
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.Popen(command(FLAT_WAD), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, env=engine_env(out))
            for ch in text.encode():
                proc.stdin.write(bytes([ch]))
                proc.stdin.flush()
            proc.stdin.close()
            err = proc.stderr.read().decode()
            proc.stderr.close()
            self.assertEqual(proc.wait(timeout=60), 0, err)
            frames = read_frames(out)
        self.assertEqual(frames, whole.frames)


class LongRandomSequence(unittest.TestCase):
    def test_20000_valid_lines(self):
        rng = random.Random(20261120)
        edge = [0, 0.0, 1e-9, 0.5, 23.99999, 47.5, 47.9999999, 47]
        kinds = ["empty", "cell", "wall", "tower"]

        def pos():
            return rng.choice(edge) if rng.random() < 0.3 else rng.uniform(0, 47.9999999)

        lines = []
        nexts = 0
        while len(lines) < 20000:
            r = rng.random()
            if r < 0.30:
                lines.append("cell %d %d %s" % (rng.randrange(N), rng.randrange(N), rng.choice(kinds)))
            elif r < 0.36:
                lines.append("row %d %s" % (rng.randrange(N), "".join(rng.choice(".#=T") for _ in range(N))))
            elif r < 0.55:
                lines.append("thing %d %s %r %r %r" % (rng.randrange(256), rng.choice(["marauder", "loot"]), pos(), pos(),
                                                       rng.choice([0, 90, -45, 359.999, 720, rng.uniform(-1e5, 1e5)])))
            elif r < 0.65:
                lines.append("gone %d" % rng.randrange(256))
            elif r < 0.85:
                lines.append("cam %r %r %r" % (pos(), pos(), rng.uniform(-720, 720)))
            elif r < 0.88:
                lines.append("light %d" % rng.randrange(256))
            elif r < 0.89:
                lines.append("origin %d %d" % (rng.randint(-1000000, 1000000), rng.randint(-1000000, 1000000)))
            else:
                n = rng.choice([1, 1, 1, 2])
                lines.append("next %d" % n if n > 1 else "next")
                nexts += n
        every = 64
        res = run("\n".join(lines) + "\n", timeout=600, every=every)
        self.assertEqual(res.rc, 0, res.err[-500:])
        self.assertEqual(res.summary, (20000, 0))
        drawn = re.search(r"headless: frames=(\d+)", res.err)
        self.assertIsNotNone(drawn, res.err[-500:])
        self.assertEqual(int(drawn.group(1)), nexts)
        # every 64th frame, plus the last one when the count is not a multiple (doomgeneric_headless.c)
        self.assertEqual(len(res.frames), nexts // every + (1 if nexts % every else 0))


class LiveMode(unittest.TestCase):
    def test_live_reads_without_blocking_and_follows_the_writer(self):
        steps = [(0.0, b""), (0.0, b"cell 27 24 ce"), (0.0, b"ll\n"), (0.0, b"thing 1 marauder 30.5 24.5 180\n")]
        expect_a = first_frame("next\n")
        expect_b = first_frame("cell 27 24 cell\nnext\n")
        expect_c = first_frame("cell 27 24 cell\nthing 1 marauder 30.5 24.5 180\nnext\n")
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.Popen(command(FLAT_WAD), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, env=engine_env(out, live=True, every=1))
            err_holder = []
            reader = threading.Thread(target=lambda: err_holder.append(proc.stderr.read()))
            reader.start()
            try:
                time.sleep(0.8)                       # nothing written: one picture, then it waits
                n0 = len([n for n in os.listdir(out) if n.endswith(".ppm")])
                self.assertEqual(n0, 1, "live draws once at the start and then only on a change")
                proc.stdin.write(b"cell 27 24 ce")    # half a line: nothing may change
                proc.stdin.flush()
                time.sleep(0.4)
                proc.stdin.write(b"ll\n")
                proc.stdin.flush()
                time.sleep(0.5)
                proc.stdin.write(b"thing 1 marauder 30.5 24.5 180\n")
                proc.stdin.flush()
                time.sleep(0.5)
            finally:
                proc.stdin.close()
            rc = proc.wait(timeout=30)
            reader.join()
            proc.stderr.close()
            err = err_holder[0].decode()
            frames = read_frames(out)
        self.assertEqual(rc, 0, err)
        self.assertIn("control: lines=2 rejected=0", err)
        # one picture per change: the start, the cell, the thing; the half line drew nothing
        self.assertEqual(frames, [expect_a, expect_b, expect_c])

    def test_live_with_a_file_on_stdin_ends_by_itself(self):
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.run(command(FLAT_WAD), input=b"cell 27 24 cell\n", stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE, env=engine_env(out, live=True, every=1), timeout=30)
            frames = read_frames(out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(frames[-1], first_frame("cell 27 24 cell\nnext\n"))

    def test_live_quit_and_idle_pipe(self):
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.Popen(command(FLAT_WAD), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, env=engine_env(out, live=True, every=1))
            time.sleep(0.3)
            proc.stdin.write(b"quit\n")
            proc.stdin.flush()
            rc = proc.wait(timeout=30)
            err = proc.stderr.read().decode()
            proc.stderr.close()
            proc.stdin.close()
        self.assertEqual(rc, 0, err)
        self.assertIn("control: lines=1 rejected=0", err)


class WithoutTheSwitch(unittest.TestCase):
    def test_no_pov_control_means_the_old_behaviour(self):
        # without -pov-control the engine ignores stdin and draws the game (status bar, weapon): 3 frames
        with tempfile.TemporaryDirectory() as out:
            env = engine_env(out, every=1)
            env["POV_FRAMES"] = "3"
            proc = subprocess.run([BIN, "-iwad", IWAD, "-file", FLAT_WAD, "-warp", "1", "1"], input=b"cell 27 24 cell\n",
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
            frames = read_frames(out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(frames), 3)
        self.assertNotIn(b"control:", proc.stderr)
        self.assertNotEqual(frames[-1], empty_frame())


if __name__ == "__main__":
    unittest.main()
