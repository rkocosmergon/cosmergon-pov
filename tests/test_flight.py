# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests of the bird in flight and perched (doomgeneric/pov_control.c `thing_look`; COSMERGON.md, "Flying and perching").

    python3 -m unittest tests.test_flight

A bird that moves beats its wings and swings up and down; one that stands (its position does not change for 0.8 s) sinks to the
floor of its cell and perches. The program decides from the lines it gets and from its clock (one step a picture in blocking
mode, 35 a second), nothing else is sent. Standard library only; starts the headless binary like tests.test_control.

POV_OLD_BIN (optional): a build of the state before this change; the other kinds must be drawn as it draws them.
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import figures  # noqa: E402
import make_map  # noqa: E402
import make_theme  # noqa: E402
from tests import test_control as tc  # noqa: E402

OLD_BIN = os.environ.get("POV_OLD_BIN")
WORK = tempfile.TemporaryDirectory()
MAP = os.path.join(WORK.name, "flat.wad")
THEME = os.path.join(WORK.name, "wueste.wad")
SCALE = 320 / 384                    # points a unit at three cells (384 units) and 640 x 400
POS = "27.5 24.5"                    # three cells ahead of the default camera
HOLD = 28                            # steps without a move until it perches
AIR = 28                             # steps of landing and take-off
LOOKS = {name: figures.read_frames(os.path.join(figures.FIGURES_DIR, figures.template_name("bird", 0)))[i]
         for i, name in enumerate(("glide", "up", "down", "perched"))}
UP_HEIGHT = len(LOOKS["up"][0]) * SCALE        # the wings-up look is the tallest by far
PERCHED = (len(LOOKS["perched"][0]) * SCALE, len(LOOKS["perched"][0][0]) * SCALE)


def setUpModule():
    with open(MAP, "wb") as handle:
        handle.write(make_map.wad_bytes(make_map.build_map("flat")))
    with open(THEME, "wb") as handle:
        handle.write(make_theme.wad_bytes(make_theme.build_theme("wueste")))


def tearDownModule():
    WORK.cleanup()


def run(lines, theme=True):
    args = ["-warp", "1", "1"] + (["-pov-theme", THEME] if theme else [])
    res = tc.run(lines, wad=MAP, args=args)
    assert res.rc == 0, res.err
    assert res.summary[1] == 0, res.err
    return res.frames


def thing(kind, x=27.5, y=24.5, angle=180, ident=1):
    return "thing %d %s %.2f %.2f %s\n" % (ident, kind, x, y, angle)


def box(frame, base):
    """Bounding box (x0, y0, x1, y1) of the points where `frame` differs from `base`; None where it does not."""
    xs, ys = [], []
    for y in range(tc.H):
        a = tc.HEADER + 3 * y * tc.W
        if frame[a:a + 3 * tc.W] != base[a:a + 3 * tc.W]:
            for x in range(tc.W):
                if frame[a + 3 * x:a + 3 * x + 3] != base[a + 3 * x:a + 3 * x + 3]:
                    xs.append(x)
                    ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def boxes(frames, base):
    return [box(f, base) for f in frames]


def flying(count, x=27.5, y0=23.5, step=0.01, extra=""):
    """A bird that moves a little in every picture, `count` pictures."""
    return "".join(thing("bird", x, y0 + step * k) + extra + "next\n" for k in range(count))


def base_frame(extra=""):
    return run(extra + "next\n")[-1]


class Flying(unittest.TestCase):
    def test_a_bird_that_moves_beats_its_wings_and_swings_up_and_down(self):
        base = base_frame()
        got = boxes(run(flying(70)), base)
        height = [b[3] - b[1] + 1 for b in got]
        ups = [h >= UP_HEIGHT - 4 for h in height]
        self.assertTrue(any(ups) and not all(ups), "two or more looks of the wings")
        beats = sum(1 for a, b in zip(ups, ups[1:]) if b and not a)
        self.assertTrue(6 <= beats <= 8, "70 pictures are 2 s: 3 to 4 beats a second (%d)" % beats)
        self.assertGreater(len(set(height)), 2, "at least the wings up, half spread and down")
        low = [b[3] for b in got]
        self.assertTrue(4 <= max(low) - min(low) <= 14, "it swings by a few units, not wildly (%d points)" % (max(low) - min(low)))
        self.assertTrue(all(abs(a - b) <= 5 for a, b in zip(low, low[1:])), "softly: it is sampled where the wings change, a few points at most")

    def test_the_wings_stay_in_the_air_a_moving_bird_never_perches(self):
        base = base_frame()
        got = boxes(run(flying(200)), base)
        floor = box(run(thing("marauder") + "next\n")[-1], base)[3]
        self.assertTrue(all(floor - b[3] > 25 for b in got), "always 40 units over the floor, give or take the swing")
        self.assertFalse(any(abs(b[2] - b[0] + 1 - PERCHED[1]) < 3 and abs(b[3] - b[1] + 1 - PERCHED[0]) < 3 for b in got))


class Perching(unittest.TestCase):
    def test_a_bird_that_stands_sinks_to_the_floor_and_shows_the_perched_look(self):
        base = base_frame()
        frames = run(thing("bird") + "next 100\n")
        got = boxes(frames, base)
        floor = box(run(thing("marauder") + "next\n")[-1], base)[3]
        self.assertGreater(floor - got[0][3], 25, "it starts in the air")
        self.assertTrue(all(floor - b[3] > 25 for b in got[:HOLD]), "and stays there for the first %d steps" % HOLD)
        self.assertLessEqual(abs(got[-1][3] - floor), 2, "at the end its feet are on the floor")
        h, w = got[-1][3] - got[-1][1] + 1, got[-1][2] - got[-1][0] + 1
        self.assertAlmostEqual(h, PERCHED[0], delta=6)
        self.assertAlmostEqual(w, PERCHED[1], delta=6)
        self.assertEqual(frames[-1], run(thing("bird") + "next 200\n")[-1], "perched is a rest: the clock changes nothing")
        sink = [b[3] for b in got[HOLD:HOLD + AIR + 2]]
        self.assertTrue(all(abs(a - b) <= 8 for a, b in zip(sink, sink[1:])), "it glides down, it does not jump")
        self.assertGreater(sink[len(sink) // 2], got[0][3] + 8, "half way down at half the time")

    def test_the_bird_sits_on_the_top_of_a_raised_cell(self):
        # its feet are hidden behind the edge of the cell seen from the eye (41 units), so the top of the bird is measured:
        # it stands as many units higher than on the ground as the cell is high
        ground = box(run(thing("bird") + "next 100\n")[-1], base_frame())
        for cell, top in (("wall", 64), ("tower", 147)):
            got = box(run("cell 27 24 %s\n" % cell + thing("bird") + "next 100\n")[-1], base_frame("cell 27 24 %s\n" % cell))
            self.assertAlmostEqual(ground[1] - got[1], top * SCALE, delta=2.5, msg=cell)
            self.assertAlmostEqual(got[2] - got[0] + 1, PERCHED[1], delta=6, msg="the perched look, wings folded: " + cell)

    def test_it_follows_a_cell_that_rises_under_it_and_stays_on_its_top(self):
        ground = box(run(thing("bird") + "next 100\n")[-1], base_frame())
        frames = run(thing("bird") + "next 100\ncell 27 24 tower\nnext 100\n")
        got = box(frames[-1], base_frame("cell 27 24 tower\n"))
        self.assertAlmostEqual(ground[1] - got[1], 147 * SCALE, delta=2.5)
        self.assertAlmostEqual(got[2] - got[0] + 1, PERCHED[1], delta=6, msg="perched on it")
        mid = [box(f, base_frame("cell 27 24 tower\n"))[1] for f in frames[100:140]]
        self.assertTrue(all(a >= b for a, b in zip(mid, mid[1:])), "it rides up with the cell")

    def test_when_it_moves_again_it_lifts_off_gently_and_beats_its_wings(self):
        base = base_frame()
        frames = run(thing("bird") + "next 100\n" + flying(50, x=27.5, y0=24.51, step=0.01))
        got = boxes(frames, base)
        landed = got[99][3]
        rising = [b[3] for b in got[100:]]
        self.assertGreater(landed - rising[-1], 25, "40 units up again")
        self.assertTrue(all(abs(a - b) <= 8 for a, b in zip(rising, rising[1:])), "gently")
        self.assertGreater(landed - rising[AIR // 2], 5, "already on its way at half the time")
        self.assertTrue(any(b[3] - b[1] + 1 >= UP_HEIGHT - 4 for b in got[100:]), "the wings beat")
        self.assertNotEqual(frames[100], frames[99])

    def test_a_line_that_only_turns_it_does_not_make_it_fly(self):
        base = base_frame()
        lines = thing("bird") + "next 40\n" + "".join(thing("bird", angle=a) + "next\n" for a in range(0, 360, 10)) + "next 40\n"
        last = boxes(run(lines), base)[-1]
        floor = box(run(thing("marauder") + "next\n")[-1], base)[3]
        self.assertLessEqual(abs(last[3] - floor), 2)

    def test_the_same_lines_give_the_same_pictures(self):
        lines = flying(45) + "next 60\n" + flying(20, y0=24.2)
        self.assertEqual(run(lines), run(lines))

    def test_two_birds_do_not_beat_in_step(self):
        base = base_frame()
        lines = "".join(thing("bird", 27.5, 23.0 + 0.02 * k, ident=1) + thing("bird", 27.5, 26.0 + 0.02 * k, ident=2) + "next\n"
                        for k in range(30))
        frames = run(lines)
        ups = {side: [b[3] - b[1] + 1 >= UP_HEIGHT - 4 for b in (box_in(f, base, x0, x1) for f in frames)]
               for side, (x0, x1) in (("left", (0, tc.W // 2)), ("right", (tc.W // 2, tc.W)))}
        self.assertTrue(any(ups["left"]) and any(ups["right"]), "both beat their wings")
        self.assertNotEqual(ups["left"], ups["right"])


def box_in(frame, base, x0, x1):
    """Like `box`, within the columns x0 .. x1 - 1."""
    xs, ys = [], []
    for y in range(tc.H):
        a = tc.HEADER + 3 * y * tc.W
        for x in range(x0, x1):
            if frame[a + 3 * x:a + 3 * x + 3] != base[a + 3 * x:a + 3 * x + 3]:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys))


class WithoutATheme(unittest.TestCase):
    def test_nothing_breaks_and_it_still_goes_up_and_down_and_sits_on_the_floor(self):
        base = run("next\n", theme=False)[-1]
        flight = boxes(run(flying(50), theme=False), base)
        heights = [b[3] - b[1] for b in flight]
        self.assertLessEqual(max(heights) - min(heights), 2, "the one placeholder picture, no looks of its own")
        low = [b[3] for b in flight]
        self.assertGreater(max(low) - min(low), 3, "it swings")
        floor = box(run(thing("marauder") + "next\n", theme=False)[-1], base)[3]
        sat = box(run(thing("bird") + "next 100\n", theme=False)[-1], base)
        self.assertLess(abs(sat[3] - floor), 6, "perched, 5 units under its origin at most")
        self.assertGreater(floor - flight[0][3], 20)


class OldTheme(unittest.TestCase):
    def test_a_theme_with_one_look_of_the_bird_is_drawn_with_that_look(self):
        # a theme made before the looks existed: the sprite HEAD has the frame A only
        lumps = [(n, d) for n, d in make_theme.build_theme("wueste") if not (n.startswith("HEAD") and n[4] in "BCD")]
        self.assertEqual(len(lumps), len(make_theme.build_theme("wueste")) - 24)
        old = os.path.join(WORK.name, "old.wad")
        with open(old, "wb") as handle:
            handle.write(make_theme.wad_bytes(lumps))
        res = tc.run(flying(40) + "next 100\n", wad=MAP, args=["-warp", "1", "1", "-pov-theme", old])
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.summary[1], 0, res.err)
        base = tc.run("next\n", wad=MAP, args=["-warp", "1", "1", "-pov-theme", old]).frames[-1]
        for b in boxes(res.frames, base):
            self.assertAlmostEqual(b[3] - b[1] + 1, len(LOOKS["glide"][0]) * SCALE, delta=6, msg="the first look only")


class Others(unittest.TestCase):
    def test_the_other_kinds_look_the_same_at_every_step(self):
        for kind in ("marauder", "monster", "corpse", "loot"):
            frames = run(thing(kind, angle=0 if kind == "corpse" else 90) + "next 80\n")
            self.assertEqual(len(set(frames)), 1, kind)

    @unittest.skipUnless(OLD_BIN and os.path.exists(OLD_BIN), "no build of the state before (POV_OLD_BIN)")
    def test_the_other_kinds_are_drawn_as_the_old_build_draws_them(self):
        lines = ("".join(thing(k, 26.5 + i, 24.5, a, ident=i) for i, (k, a) in enumerate(
            (("marauder", 135), ("monster", 45), ("corpse", 0), ("loot", 0)))) + "next\ncam 20 20 45\nnext 3\n")
        args = ["-warp", "1", "1", "-pov-theme", THEME]
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.run([OLD_BIN, "-iwad", tc.IWAD, "-file", MAP, "-pov-control"] + args, input=lines.encode("ascii"),
                                  env=tc.engine_env(out), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
            self.assertEqual(proc.returncode, 0)
            old = tc.read_frames(out)
        self.assertEqual(run(lines), old)


class Live(unittest.TestCase):
    """Live mode: pictures are drawn on a change; a bird in the air costs pictures, a perched one costs none."""

    def test_a_bird_that_stands_is_drawn_while_it_sinks_and_then_not_at_all(self):
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.Popen(tc.command(MAP, ["-warp", "1", "1", "-pov-theme", THEME]), stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=tc.engine_env(out, live=True, every=1))
            holder = []
            reader = threading.Thread(target=lambda: holder.append(proc.stderr.read()))
            reader.start()

            def count():
                return len([n for n in os.listdir(out) if n.endswith(".ppm")])
            try:
                time.sleep(0.5)
                proc.stdin.write(thing("bird").encode("ascii"))
                proc.stdin.flush()
                time.sleep(0.6)
                in_flight = count()
                time.sleep(3.4)            # 0.8 s hold + 0.8 s landing, with room
                at_rest = count()
                time.sleep(1.0)
                later = count()
            finally:
                proc.stdin.close()
            rc = proc.wait(timeout=30)
            reader.join()
            proc.stderr.close()
            err = holder[0].decode()
            frames = tc.read_frames(out)
        self.assertEqual(rc, 0, err)
        self.assertGreater(in_flight, 5, "in flight a picture is due when the wings change their look")
        self.assertLess(in_flight, 18, "but not one a step: 0.6 s are 21 steps")
        self.assertGreater(at_rest, in_flight + 10, "and it is drawn while it sinks")
        self.assertLessEqual(later - at_rest, 1, "a perched bird costs nothing (the clouds of the theme move a picture every 2 s)")
        # the bird's own rows (the clouds of the theme move in the sky behind its head): the same as in blocking mode
        rest = run(thing("bird") + "next 100\n")
        where = box(rest[-1], base_frame())
        for y in range(where[1] + 12, where[3] + 1):
            a = tc.HEADER + 3 * (y * tc.W + where[0])
            self.assertEqual(frames[at_rest - 1][a:a + 3 * (where[2] - where[0] + 1)], rest[-1][a:a + 3 * (where[2] - where[0] + 1)])


if __name__ == "__main__":
    unittest.main()
