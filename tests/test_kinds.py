# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests of the thing kinds `marauder`, `loot`, `monster`, `bird`, `corpse` and of the `capabilities` file
(doomgeneric/pov_control.c `s_thing_kind`, doomgeneric/pov_capabilities.txt; COSMERGON.md, "Capabilities").

    python3 -m unittest tests.test_kinds

Standard library only; starts the headless binary like tests.test_control. POV_OLD_BIN (optional): a build of
the state before the three kinds; pictures without them must equal its pictures byte for byte.
"""

import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import make_map  # noqa: E402
from tests import test_control as tc  # noqa: E402

OLD_BIN = os.environ.get("POV_OLD_BIN") or os.path.join(ROOT, "out", "old", "pov-1d03b57")
WORK = tempfile.TemporaryDirectory()
MAP = os.path.join(WORK.name, "flat.wad")
SOURCE = os.path.join(ROOT, "doomgeneric", "pov_control.c")
CAPS_SOURCE = os.path.join(ROOT, "doomgeneric", "pov_capabilities.txt")
CAPS_FILE = os.path.join(os.path.dirname(tc.BIN), "capabilities")
BODIES = ("marauder", "monster", "bird", "corpse", "loot")
POS = "27.5 24.5"            # three cells ahead of the default camera (24.5, 24.5, east)


def setUpModule():
    with open(MAP, "wb") as handle:
        handle.write(make_map.wad_bytes(make_map.build_map("flat")))
    if not os.path.exists(CAPS_FILE):
        flavour = ["SANITIZE=1"] if "sanitize" in os.path.basename(tc.BIN) else []
        subprocess.run(["make", "-C", os.path.join(ROOT, "doomgeneric"), "-f", "Makefile.headless", "capabilities"] + flavour,
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def tearDownModule():
    WORK.cleanup()


def frame_of(lines, binary=None):
    res = tc.run(lines, wad=MAP) if binary is None else run_with(binary, lines)
    assert res.rc == 0, res.err
    assert res.summary[1] == 0, res.err
    return res.frames[-1]


def run_with(binary, lines):
    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run([binary, "-iwad", tc.IWAD, "-file", MAP, "-pov-control"], input=lines.encode("ascii"),
                              env=tc.engine_env(out), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        return tc.Result(proc.returncode, proc.stderr.decode("ascii", "replace"), tc.read_frames(out))


def thing(kind, angle=180, ident=1, pos=POS):
    return "thing %d %s %s %s\n" % (ident, kind, pos, angle)


def box(frame, base):
    """Bounding box (x0, y0, x1, y1) of the points where `frame` differs from `base`."""
    xs, ys = [], []
    for y in range(tc.H):
        a = tc.HEADER + 3 * y * tc.W
        if frame[a:a + 3 * tc.W] != base[a:a + 3 * tc.W]:
            row_f, row_b = frame[a:a + 3 * tc.W], base[a:a + 3 * tc.W]
            for x in range(tc.W):
                if row_f[3 * x:3 * x + 3] != row_b[3 * x:3 * x + 3]:
                    xs.append(x)
                    ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def table():
    """Rows of s_thing_kind in the source: (name, sprite, frame, lift)."""
    body = re.search(r"s_thing_kind\[\] = \{(.*?)\n\};", tc.read_text(SOURCE), re.S).group(1)
    return [(n, s, int(f), int(l)) for n, s, f, l in re.findall(r'\{ "(\w+)",\s+SPR_(\w+),\s+(\d+),\s+(\d+) \}', body)]


def iwad_lumps():
    with open(tc.IWAD, "rb") as handle:
        data = handle.read()
    count, off = struct.unpack("<ii", data[4:12])
    lumps = {}
    for i in range(count):
        pos, size, nm = struct.unpack("<ii8s", data[off + 16 * i: off + 16 * i + 16])
        lumps.setdefault(nm.rstrip(b"\0").decode(), data[pos:pos + size])
    return lumps


class Capabilities(unittest.TestCase):
    # one probe a word: the lines a bridge sends once it sees the word; the program must accept all of them
    PROBES = {
        "own": "cell 3 3 own\nrow 4 O" + "." * 47 + "\n",
        "origin": "origin 5 5\norigin -3 7\n",
        "daytime": "daytime 0\ndaytime 1439\n",
        "clouds": "clouds 0\nclouds 10000000\n",
        "world": "world 0 0 0 0 128\ncube 1 1 0 0 128\nnocube 1\n",
        "kinds": "thing 1 monster 5 5 0\nthing 2 bird 6 5 0\nthing 3 corpse 7 5 0\nthing 4 marauder 8 5 0\nthing 5 loot 9 5 0\n",
    }

    def words(self, path):
        return tc.read_text(path).split()

    def test_the_file_beside_the_program_is_the_listed_words(self):
        self.assertEqual(self.words(CAPS_FILE), self.words(CAPS_SOURCE))
        self.assertEqual(len(tc.read_text(CAPS_FILE).splitlines()), len(self.words(CAPS_FILE)), "one word a line")

    def test_every_word_has_a_probe_and_the_program_accepts_it(self):
        self.assertEqual(sorted(self.words(CAPS_FILE)), sorted(self.PROBES))
        for word, lines in self.PROBES.items():
            n = lines.count("\n") + 1
            res = tc.run(lines + "next\n", wad=MAP)
            self.assertEqual(res.rc, 0, (word, res.err))
            self.assertEqual(res.summary, (n, 0), (word, res.err))

    def test_a_line_of_a_word_the_build_does_not_have_is_rejected(self):
        res = tc.run("thing 1 dragon 5 5 0\nnext\n", wad=MAP)
        self.assertEqual(res.summary, (2, 1))

    def test_the_document_names_every_word(self):
        text = tc.read_text(os.path.join(ROOT, "COSMERGON.md"))
        section = text[text.index("## Capabilities"):]
        for word in self.words(CAPS_SOURCE):
            self.assertIn("`%s`" % word, section)


class Table(unittest.TestCase):
    def test_the_five_kinds_and_their_lumps(self):
        rows = table()
        self.assertEqual([r[0] for r in rows], ["marauder", "loot", "monster", "bird", "corpse"])
        lumps = iwad_lumps()
        for name, sprite, frame, _lift in rows:
            letter = chr(ord("A") + frame)
            self.assertTrue(any(k.startswith(sprite + letter) or k[4:].startswith(letter) and k.startswith(sprite)
                                for k in lumps), name)

    def test_corpse_has_a_single_look_and_the_bird_stays_under_the_top_of_a_cell(self):
        lumps = iwad_lumps()
        by = {r[0]: r for r in table()}
        _n, sprite, frame, _l = by["corpse"]
        names = [k for k in lumps if k.startswith(sprite + chr(ord("A") + frame))]
        self.assertEqual(names, [sprite + chr(ord("A") + frame) + "0"], "rotation 0: the same from every side")
        _n, sprite, frame, lift = by["bird"]
        name = [k for k in lumps if k.startswith(sprite + chr(ord("A") + frame))][0]
        top = struct.unpack("<hhhh", lumps[name][:8])[3]
        self.assertLess(lift + top, 128, "the bird's top under the top of a cell")
        self.assertGreater(lift, 0)
        for n in ("marauder", "monster", "corpse", "loot"):
            self.assertEqual(by[n][3], 0)


class Looks(unittest.TestCase):
    def test_each_kind_is_accepted_and_changes_the_picture(self):
        base = frame_of("next\n")
        for kind in BODIES:
            self.assertNotEqual(frame_of(thing(kind) + "next\n"), base, kind)

    def test_the_bodies_are_pairwise_different(self):
        frames = {k: frame_of(thing(k) + "next\n") for k in BODIES}
        self.assertEqual(len(set(frames.values())), len(BODIES))

    def test_monster_is_taller_than_the_imp_and_the_corpse_lies(self):
        base = frame_of("next\n")
        b = {k: box(frame_of(thing(k) + "next\n"), base) for k in BODIES}
        height = {k: v[3] - v[1] for k, v in b.items()}
        self.assertGreater(height["monster"], height["marauder"])
        self.assertLess(height["corpse"], height["marauder"] // 2, "it lies")

    def test_corpse_looks_the_same_at_every_angle(self):
        a = frame_of(thing("corpse", 0) + "next\n")
        for angle in (1, 45, 90, 135, 180, 225, 271, 359.5):
            self.assertEqual(frame_of(thing("corpse", angle) + "next\n"), a, angle)
        self.assertNotEqual(frame_of(thing("monster", 0) + "next\n"), frame_of(thing("monster", 90) + "next\n"))

    def test_a_change_of_kind_with_the_same_id_changes_the_look_without_gone(self):
        res = tc.run(thing("monster") + "next\n" + thing("corpse", 0) + "next\n" + thing("bird") + "next\n"
                     + thing("marauder") + "next\n" + thing("monster") + "next\n", wad=MAP)
        self.assertEqual(res.summary, (10, 0), res.err)
        want = [frame_of(thing(k, a) + "next\n") for k, a in (("monster", 180), ("corpse", 0), ("bird", 180),
                                                              ("marauder", 180), ("monster", 180))]
        self.assertEqual(res.frames, want)

    def test_a_dead_one_stays_where_it_fell(self):
        # the monster's place, then the corpse at the same place: the corpse is lower and inside the monster's box
        base = frame_of("next\n")
        m = box(frame_of(thing("monster") + "next\n"), base)
        c = box(frame_of(thing("corpse", 0) + "next\n"), base)
        self.assertLessEqual(abs(c[3] - m[3]), 12, "both stand on the same floor")
        self.assertGreater(c[1], m[1] + (m[3] - m[1]) // 2)


class Height(unittest.TestCase):
    def test_the_bird_floats_above_the_ground_bodies(self):
        base = frame_of("next\n")
        bottom = {k: box(frame_of(thing(k) + "next\n"), base)[3] for k in BODIES}
        # 3 cells = 384 units, 0.833 points a unit at 640 x 400: the bird's lowest point is 39 units over the
        # imp's (40 lift, its sprite reaches 5 under its origin, the imp's 4)
        gap = bottom["marauder"] - bottom["bird"]
        self.assertGreater(gap, 28)
        self.assertLess(gap, 37)
        for k in ("monster", "loot"):
            self.assertLess(abs(bottom[k] - bottom["marauder"]), 10, k)

    def test_the_bird_stands_over_a_raised_floor_like_the_others(self):
        for kind in ("bird", "corpse", "monster"):
            a = frame_of(thing(kind, 180, pos="26.5 24.5") + "cell 26 24 tower\nnext\n")
            b = frame_of("cell 26 24 tower\n" + thing(kind, 180, pos="26.5 24.5") + "next\n")
            self.assertEqual(a, b, kind)
            self.assertNotEqual(a, frame_of(thing(kind, 180, pos="26.5 24.5") + "next\n"), kind)

    def test_a_bird_and_a_corpse_ride_a_travelling_floor_every_step(self):
        for kind in ("bird", "corpse"):
            lines = "cam 22.5 16 90\nnext\n" + thing(kind, 0, pos="22.5 20.5") + "cell 22 20 tower\nnext 60\n"
            res = tc.run(lines, wad=MAP)
            self.assertEqual(res.rc, 0, res.err)
            moving = res.frames[5:38]
            self.assertTrue(all(x != y for x, y in zip(moving, moving[1:])), kind)
            want = frame_of("cell 22 20 tower\n" + thing(kind, 0, pos="22.5 20.5") + "cam 22.5 16 90\nnext\n")
            self.assertEqual(res.frames[-1], want, kind)


class Before(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(OLD_BIN), "no build of the state before (out/old/pov-1d03b57, POV_OLD_BIN)")
    def test_without_the_new_kinds_the_pictures_are_those_of_the_old_build(self):
        lines = (tc.SCENE + thing("marauder", 180, 1) + thing("loot", 0, 2, "28.5 26.5") + thing("marauder", 33, 3, "29.5 22.5")
                 + "next\ncam 20 20 45\nnext\ncell 26 24 tower\nnext\ngone 1\nnext\n")
        new, old = tc.run(lines, wad=MAP), run_with(OLD_BIN, lines)
        self.assertEqual(new.rc, 0, new.err)
        self.assertEqual(new.frames, old.frames)
        self.assertEqual(len(new.frames), 4)

    @unittest.skipUnless(os.path.exists(OLD_BIN), "no build of the state before")
    def test_the_old_build_rejects_the_new_kinds(self):
        res = run_with(OLD_BIN, thing("bird") + "next\n")
        self.assertEqual(res.summary, (2, 1))


if __name__ == "__main__":
    unittest.main()
