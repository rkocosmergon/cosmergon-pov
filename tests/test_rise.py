"""Tests of rise and sink (doomgeneric/pov_control.c; COSMERGON.md, "Rise and sink").

    python3 -m unittest tests.test_rise

Standard library only; starts the headless binary like tests.test_control. The engine's measure
POV_RISE_TRACE=1 prints, per frame and per raised cell, `rise: frame=<f> cell=<c> h=<16.16 floor> kind=<target>
look=<kind whose look the cell wears>`; the tests read it and compare frames by their hashes.

Blocking mode counts one engine step per drawn frame. A test that wants a cell to travel first draws one
frame (`next`): the first frame ends the "snap", in which a new window is filled at once. Frame 1 is that
empty frame; k frames after the change are frame 1 + k.

POV_OLD_BIN (optional): a build of the state before this package; the pictures with -pov-rise 0 must equal its.
"""

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import make_map  # noqa: E402
import pov_measures as pm  # noqa: E402
from tests import test_control as tc  # noqa: E402

FIX = 65536
CELL = 20 * 48 + 20            # cell 20, 20
OTHER = 20 * 48 + 22
KIND = {"empty": 0, "cell": 1, "wall": 2, "tower": 3, "own": 4}
OLD_BIN = os.environ.get("POV_OLD_BIN")
STEPS = 42                      # 1200 ms at 35 steps a second

WORK = tempfile.TemporaryDirectory()
MAP = os.path.join(WORK.name, "flat.wad")


def setUpModule():
    with open(MAP, "wb") as handle:
        handle.write(make_map.wad_bytes(make_map.build_map("flat")))


def tearDownModule():
    WORK.cleanup()


def smooth(start, end, n, k):
    """The floor k steps into a travel of n steps (C integer arithmetic: truncation towards zero)."""
    k = min(k, n)
    num = (end - start) * (k * k * (3 * n - 2 * k))
    den = n * n * n
    q = abs(num) // den
    return start + (q if num >= 0 else -q)


def steps_for(distance_units, rise_steps=STEPS):
    """Length of a travel of `distance_units` (16.16): rise_steps for pm.H_CELL units, rounded up."""
    return max(1, -(-distance_units * rise_steps // (pm.H_CELL * FIX)))


class Run:
    def __init__(self, rc, err, frames, trace):
        self.rc, self.err, self.frames, self.trace = rc, err, frames, trace

    def h(self, frame, cell=CELL):
        """Floor of the cell in the frame, in 16.16 (0 for a cell not listed)."""
        return self.trace.get(frame, {}).get(cell, (0, 0, 0))[0]

    def kind(self, frame, cell=CELL):
        return self.trace.get(frame, {}).get(cell, (0, 0, 0))[1]

    def look(self, frame, cell=CELL):
        return self.trace.get(frame, {}).get(cell, (0, 0, 0))[2]

    def series(self, first, last, cell=CELL):
        return [self.h(f, cell) for f in range(first, last + 1)]


def engine(data, args=(), every=100000, binary=None, trace=True, theme=None):
    cmd = [binary or tc.BIN, "-iwad", tc.IWAD, "-file", MAP]
    if theme:
        cmd += ["-pov-theme", theme]
    cmd += ["-pov-control", "-warp", "1", "1"] + list(args)
    with tempfile.TemporaryDirectory() as out:
        env = tc.engine_env(out, every=every)
        if trace:
            env["POV_RISE_TRACE"] = "1"
        proc = subprocess.run(cmd, input=data.encode("ascii"), env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=120)
        err = proc.stderr.decode("ascii", "replace")
        if tc.SANITIZED:
            assert not tc.sanitizer_findings(err), tc.sanitizer_findings(err)
        frames = tc.read_frames(out)
    tr = {}
    for m in re.finditer(r"^rise: frame=(\d+) cell=(\d+) h=(-?\d+) kind=(\d+) look=(\d+)$", err, re.M):
        tr.setdefault(int(m.group(1)), {})[int(m.group(2))] = (int(m.group(3)), int(m.group(4)), int(m.group(5)))
    return Run(proc.returncode, err, frames, tr)


def fresh(lines):
    """The last picture of a run that is given `lines` (blocking mode, the whole run in the first picture)."""
    r = engine(lines, every=1, trace=False)
    assert r.rc == 0, r.err
    return r.frames[-1]


def after_first_frame(lines, args=()):
    """The lines, after an empty first frame (so that the window is no longer being filled)."""
    return engine("next\n" + lines, args)


class Travel(unittest.TestCase):
    def test_rising_height_over_time(self):
        r = after_first_frame("cell 20 20 cell\nnext 50\n")
        self.assertEqual(r.rc, 0, r.err)
        series = r.series(2, 51)
        expected = [smooth(0, pm.H_CELL * FIX, STEPS, k) for k in range(1, 51)]
        self.assertEqual(series, expected)
        self.assertEqual(r.h(1), 0)
        self.assertGreater(series[0], 0, "the first frame after the change already moved")
        self.assertEqual(r.h(1 + 21), pm.H_CELL * FIX // 2, "half the time, half the height")
        self.assertEqual(r.h(1 + STEPS), pm.H_CELL * FIX, "the end is the target, exactly")
        self.assertLess(r.h(1 + STEPS - 1), pm.H_CELL * FIX, "one step before the end it is not there yet")
        self.assertTrue(all(a <= b for a, b in zip(series, series[1:])), "never down while rising")
        self.assertLessEqual(max(series), pm.H_CELL * FIX, "never beyond the target")
        # slow at both ends: the first and the last step are smaller than the one in the middle
        d = [b - a for a, b in zip([0] + series, series)]
        self.assertLess(d[0], d[20] // 4)
        self.assertLess(d[STEPS - 1], d[20] // 4)

    def test_sinking_height_over_time_and_the_look_stays_until_it_is_down(self):
        r = after_first_frame("cell 20 20 cell\nnext 45\ncell 20 20 empty\nnext 50\n")
        base = 1 + 45
        series = r.series(base + 1, base + 50)
        self.assertEqual(series, [smooth(pm.H_CELL * FIX, 0, STEPS, k) for k in range(1, 51)])
        self.assertTrue(all(a >= b for a, b in zip(series, series[1:])))
        self.assertGreaterEqual(min(series), 0, "never below the ground")
        for k in range(1, STEPS):
            self.assertEqual(r.look(base + k), KIND["cell"], "the sinking cell keeps its look (frame +%d)" % k)
            self.assertEqual(r.kind(base + k), KIND["empty"])
        # down: it is empty and looks empty (the trace lists a cell only while it is raised or looks raised)
        self.assertEqual(r.h(base + STEPS), 0)
        self.assertEqual(r.look(base + STEPS), KIND["empty"])

    def test_the_option_sets_the_length(self):
        for ms, steps in ((600, 21), (1200, 42), (3000, 105), (10000, 350), (1, 1), (14, 1), (43, 2)):
            r = engine("next\ncell 20 20 cell\nnext %d\n" % (steps + 3), ("-pov-rise", str(ms)))
            self.assertEqual(r.rc, 0, r.err)
            self.assertEqual(r.h(1 + steps), pm.H_CELL * FIX, (ms, "at the end"))
            if steps > 1:
                self.assertLess(r.h(steps), pm.H_CELL * FIX, (ms, "one step before the end"))
            self.assertEqual(r.series(2, steps + 4), [smooth(0, pm.H_CELL * FIX, steps, k) for k in range(1, steps + 4)])

    def test_default_is_1200_ms(self):
        a = after_first_frame("cell 20 20 cell\nnext 45\n")
        b = after_first_frame("cell 20 20 cell\nnext 45\n", ("-pov-rise", "1200"))
        self.assertEqual(a.frames, b.frames)
        self.assertEqual(a.trace, b.trace)
        self.assertEqual(a.h(1 + 21), pm.H_CELL * FIX // 2, "the default travel is 42 steps: half at 21")

    def test_zero_is_a_jump(self):
        r = after_first_frame("cell 20 20 cell\nnext\ncell 20 20 empty\nnext\n", ("-pov-rise", "0"))
        self.assertEqual(r.h(2), pm.H_CELL * FIX)
        self.assertEqual(r.h(3), 0)
        self.assertEqual(r.look(3), KIND["empty"])

    def test_bad_values_stop_the_program(self):
        for bad in ("-1", "10001", "abc", "", "12.5", "1e3", "99999999999999999999", " 5"):
            r = engine("next\n", ("-pov-rise", bad), trace=False)
            self.assertNotEqual(r.rc, 0, bad)
            self.assertIn("-pov-rise", r.err, bad)
        for good in ("0", "1", "10000"):
            r = engine("next\n", ("-pov-rise", good), trace=False)
            self.assertEqual(r.rc, 0, (good, r.err))

    def test_a_wall_and_a_tower_travel_at_the_same_speed(self):
        # POV_H_CELL units take the whole travel: the wall (half) half of it, the tower a little more
        r = after_first_frame("cell 20 20 wall\ncell 22 20 tower\nnext 60\n")
        self.assertEqual(r.h(1 + steps_for(pm.H_WALL * FIX)), pm.H_WALL * FIX)
        self.assertLess(r.h(steps_for(pm.H_WALL * FIX)), pm.H_WALL * FIX)
        n = steps_for(pm.TOWER_TOP * FIX)
        self.assertEqual(n, 49)
        self.assertEqual(r.h(1 + n, OTHER), pm.TOWER_TOP * FIX)
        self.assertLess(r.h(n, OTHER), pm.TOWER_TOP * FIX)

    def test_resending_the_same_kind_does_not_restart_the_travel(self):
        alone = after_first_frame("cell 20 20 cell\nnext 30\n")
        again = after_first_frame("cell 20 20 cell\nnext\n" + "cell 20 20 cell\nnext\n" * 29)
        self.assertEqual(alone.series(2, 31), [smooth(0, pm.H_CELL * FIX, STEPS, k) for k in range(1, 31)])
        self.assertEqual(alone.series(2, 31), again.series(2, 31))
        self.assertEqual(alone.frames[-1], again.frames[-1])
        # the same through whole rows, as the bridge sends them
        rows = "".join("row %d %s\n" % (y, "." * 48) for y in range(48) if y != 20)
        spec = "." * 20 + "#" + "." * 27
        send = rows + "row 20 %s\nnext\n" % spec
        r = after_first_frame(send * 30)
        self.assertEqual(r.series(2, 31), alone.series(2, 31))


class Reversal(unittest.TestCase):
    def test_death_while_rising_goes_down_from_where_it_is(self):
        r = after_first_frame("cell 20 20 cell\nnext 10\ncell 20 20 empty\nnext 50\n")
        top = r.h(1 + 10)
        self.assertEqual(top, smooth(0, pm.H_CELL * FIX, STEPS, 10))
        n = steps_for(top)
        self.assertLess(n, STEPS, "the way back is shorter, so is the time")
        series = r.series(12, 61)
        self.assertEqual(series, [smooth(top, 0, n, k) for k in range(1, 51)])
        self.assertLess(series[0], top, "it turns at once, no step up")
        self.assertTrue(all(a >= b for a, b in zip(series, series[1:])))
        self.assertGreaterEqual(min(series), 0)
        self.assertEqual(r.h(11 + n), 0)
        self.assertGreater(r.h(10 + n), 0)
        self.assertEqual(r.look(11 + n), KIND["empty"])
        self.assertEqual(r.look(10 + n), KIND["cell"])

    def test_birth_while_sinking_rises_from_where_it_is(self):
        r = after_first_frame("cell 20 20 cell\nnext 45\ncell 20 20 empty\nnext 12\ncell 20 20 cell\nnext 60\n")
        low = r.h(1 + 45 + 12)
        self.assertEqual(low, smooth(pm.H_CELL * FIX, 0, STEPS, 12))
        n = steps_for(pm.H_CELL * FIX - low)
        series = r.series(59, 59 + 59)
        self.assertEqual(series, [smooth(low, pm.H_CELL * FIX, n, k) for k in range(1, 61)])
        self.assertTrue(all(a <= b for a, b in zip(series, series[1:])))
        self.assertLessEqual(max(series), pm.H_CELL * FIX)
        self.assertEqual(r.look(59), KIND["cell"])

    def test_flicker_never_jumps_nor_leaves_the_range(self):
        # a cell that is born and dies every few steps: the height changes by a bounded amount a step
        lines = "next\n"
        for i in range(40):
            lines += "cell 20 20 %s\nnext %d\n" % ("cell" if i % 2 == 0 else "empty", 1 + i % 5)
        r = engine(lines)
        series = r.series(2, max(r.trace) + 1)
        biggest = max(abs(b - a) for a, b in zip([0] + series, series))
        # smoothstep has at most 1.5 x the mean speed: 1.5 * 128 / 42 units a step (a reversal keeps that speed)
        self.assertLessEqual(biggest, int(1.5 * pm.H_CELL * FIX / STEPS) + 2 * FIX // STEPS + 1)
        self.assertGreaterEqual(min(series), 0)
        self.assertLessEqual(max(series), pm.H_CELL * FIX)


class RandomLines(unittest.TestCase):
    def test_no_floor_ever_jumps_or_leaves_its_range(self):
        import random
        rng = random.Random(11)
        lines = ["next"]
        for _ in range(1500):
            r = rng.random()
            if r < 0.6:
                lines.append("cell %d %d %s" % (rng.randrange(48), rng.randrange(48), rng.choice(list(KIND))))
            elif r < 0.7:
                lines.append("row %d %s" % (rng.randrange(48), "".join(rng.choice(".#=TO") for _ in range(48))))
            else:
                lines.append("next %d" % rng.randrange(1, 6))
        r = engine("\n".join(lines) + "\nnext 60\n")
        self.assertEqual(r.rc, 0, r.err)
        last = {}
        biggest = 0
        for f in sorted(r.trace):
            for cell, (h, kind, look) in r.trace[f].items():
                self.assertTrue(0 <= h <= pm.TOWER_TOP * FIX, (f, cell, h))
                biggest = max(biggest, abs(h - last.get(cell, 0)))
                last[cell] = h
            for cell in set(last) - set(r.trace[f]):      # no longer listed: it is down and empty
                biggest = max(biggest, last.pop(cell))
        # smoothstep moves at most 1.5 x the mean speed (pm.H_CELL units in STEPS steps); a travel of one step may
        # be as long as the mean speed
        self.assertLessEqual(biggest, int(1.5 * pm.H_CELL * FIX / STEPS) + FIX)
        self.assertGreater(biggest, FIX, "the run has moved cells")
        # at the end everything stands at its kind's height
        heights = {0: 0, 1: pm.H_CELL, 2: pm.H_WALL, 3: pm.TOWER_TOP, 4: pm.H_CELL}
        for cell, (h, kind, look) in r.trace[max(r.trace)].items():
            self.assertEqual(h, heights[kind] * FIX, (cell, kind))
            self.assertEqual(look, kind)


class Look(unittest.TestCase):
    def test_rising_cell_wears_the_new_look_from_the_first_step(self):
        r = after_first_frame("cell 20 20 wall\ncell 22 20 own\nnext 3\n")
        for f in (2, 3, 4):
            self.assertEqual(r.look(f), KIND["wall"])
            self.assertEqual(r.look(f, OTHER), KIND["own"])
            self.assertLess(r.h(f), pm.H_WALL * FIX)

    def test_cell_and_own_have_one_height_and_change_at_once(self):
        r = after_first_frame("cell 20 20 cell\nnext 50\ncell 20 20 own\nnext\ncell 20 20 cell\nnext\n")
        self.assertEqual(r.h(52), pm.H_CELL * FIX)
        self.assertEqual(r.look(52), KIND["own"])
        self.assertEqual(r.kind(52), KIND["own"])
        self.assertEqual(r.h(53), pm.H_CELL * FIX)
        self.assertEqual(r.look(53), KIND["cell"])
        # no travel: the picture differs from the one before, and is the one of a fresh run
        same = fresh("cell 20 20 own\nnext\n")
        self.assertEqual(engine("next\ncell 20 20 cell\nnext 50\ncell 20 20 own\nnext\n", every=1).frames[-1], same)

    def test_wall_to_cell_takes_the_new_look_and_the_height_travels(self):
        r = after_first_frame("cell 20 20 wall\nnext 40\ncell 20 20 cell\nnext 30\n")
        start = pm.H_WALL * FIX
        base = 1 + 40
        n = steps_for(pm.H_CELL * FIX - start)
        self.assertEqual(n, 21)
        self.assertEqual(r.series(base + 1, base + 30), [smooth(start, pm.H_CELL * FIX, n, k) for k in range(1, 31)])
        self.assertEqual(r.look(base + 1), KIND["cell"])

    def test_tower_to_cell_sinks_the_last_19_units(self):
        r = after_first_frame("cell 20 20 tower\nnext 60\ncell 20 20 cell\nnext 30\n")
        start = pm.TOWER_TOP * FIX
        base = 1 + 60
        n = steps_for(start - pm.H_CELL * FIX)
        self.assertEqual(r.series(base + 1, base + 30), [smooth(start, pm.H_CELL * FIX, n, k) for k in range(1, 31)])
        self.assertEqual(r.look(base + 1), KIND["cell"])
        self.assertEqual(r.h(base + n), pm.H_CELL * FIX)

    def test_pictures_show_the_old_look_while_sinking_and_the_new_one_while_rising(self):
        # a sinking cell is a cell (not a bare ground) until it is down; the last frame equals the bare ground
        view = "cam 24.5 20.5 0\n"          # the default camera looks east: cell 27, 20 lies in front of it
        bare = fresh(view + "next\n")
        up = engine(view + "next\ncell 27 20 cell\nnext 20\n", every=1).frames
        self.assertEqual(len(up), 21)
        self.assertEqual(up[0], bare)
        self.assertNotEqual(up[-1], bare)
        down = engine(view + "next\ncell 27 20 cell\nnext 50\ncell 27 20 empty\nnext 20\n", every=1).frames
        self.assertNotEqual(down[-1], bare, "still on its way down after 20 of 42 steps")
        done = engine(view + "next\ncell 27 20 cell\nnext 50\ncell 27 20 empty\nnext 50\n", every=1).frames
        self.assertEqual(done[-1], bare, "down: the bare ground again")
        self.assertEqual(done[-1], done[-2], "at rest: the picture no longer changes")


class WindowIsSetAnew(unittest.TestCase):
    def test_first_fill_stands_at_once(self):
        r = engine("cell 20 20 cell\ncell 22 20 tower\nrow 30 %s\nnext\n" % ("#" * 48))
        self.assertEqual(r.h(1), pm.H_CELL * FIX)
        self.assertEqual(r.h(1, OTHER), pm.TOWER_TOP * FIX)
        self.assertEqual(r.h(1, 30 * 48 + 5), pm.H_CELL * FIX)

    def test_first_fill_equals_the_same_fill_without_a_rise(self):
        lines = "cell 20 20 cell\ncell 22 20 tower\ncell 24 20 wall\ncell 26 20 own\ncam 20 16 90\nnext\n"
        a = engine(lines, every=1)
        b = engine(lines, ("-pov-rise", "0"), every=1)
        self.assertEqual(a.frames, b.frames)
        self.assertEqual(engine(lines, trace=True).h(1), pm.H_CELL * FIX, "and it stands at once by default")

    def test_origin_sets_the_heights_at_once(self):
        empty_rows = "".join("row %d %s\n" % (y, "." * 48) for y in range(48))
        # a cell on its way up when the window moves: it stands (the world under it changed)
        r = after_first_frame("cell 20 20 cell\nnext 5\norigin 7 7\n" + empty_rows + "next\n")
        self.assertEqual(r.h(1 + 5 + 1), 0, "the new window is empty at once")
        # a window with another content: everything stands in its first frame, nothing grows
        full = "".join("row %d %s\n" % (y, "#=T." * 12) for y in range(48))
        r = after_first_frame("origin 100 -50\n" + full + "next 3\n")
        for cell in (0, 1, 2, 3, 20 * 48 + 20, 47 * 48 + 44):
            expected = {0: pm.H_CELL, 1: pm.H_WALL, 2: pm.TOWER_TOP, 3: 0}[cell % 4] * FIX
            self.assertEqual(r.series(2, 4, cell), [expected] * 3, cell)
        # a cell that travels when `origin` comes lands at once, a sinking one is empty
        r = after_first_frame("cell 20 20 cell\nnext 50\ncell 20 20 empty\nnext 5\norigin 1 1\nnext\n")
        self.assertGreater(r.h(1 + 50 + 5), 0)
        self.assertEqual(r.h(1 + 50 + 5 + 1), 0)
        self.assertEqual(r.look(1 + 50 + 5 + 1), KIND["empty"])

    def test_after_the_window_is_filled_the_next_change_travels(self):
        empty_rows = "".join("row %d %s\n" % (y, "." * 48) for y in range(48))
        # all 48 rows after `origin` close the snap, so a cell line behind them in the same picture travels
        r = after_first_frame("origin 3 3\n" + empty_rows + "cell 20 20 cell\nnext 3\n")
        self.assertEqual(r.series(2, 4), [smooth(0, pm.H_CELL * FIX, STEPS, k) for k in (1, 2, 3)])
        # the picture after the filled one: a change travels
        full = "".join("row %d %s\n" % (y, "#" * 48) for y in range(48))
        r = after_first_frame("origin 3 3\n" + full + "next\ncell 20 20 empty\nnext 3\n")
        self.assertEqual(r.h(2), pm.H_CELL * FIX)
        self.assertEqual(r.series(3, 5), [smooth(pm.H_CELL * FIX, 0, STEPS, k) for k in (1, 2, 3)])

    def test_a_partly_filled_window_stands_until_its_picture_is_drawn(self):
        # without the other rows the snap is open until the frame is drawn: what is sent stands
        r = after_first_frame("origin 3 3\nrow 20 %s\nnext 2\ncell 20 21 cell\nnext 2\n" % ("#" * 48))
        self.assertEqual(r.series(2, 3, 20 * 48 + 7), [pm.H_CELL * FIX] * 2)
        self.assertLess(r.h(4, 21 * 48 + 20), pm.H_CELL * FIX)

    def test_an_old_bridge_without_origin_travels_on_a_full_resend(self):
        # no `origin`: all rows sent again with one cell changed: only that cell travels
        base = "".join("row %d %s\n" % (y, "." * 48) for y in range(48))
        changed = "".join("row %d %s\n" % (y, "." * 20 + "#" + "." * 27 if y == 20 else "." * 48) for y in range(48))
        r = after_first_frame(base + "next\n" + changed + "next 3\n")
        self.assertEqual(r.series(3, 5), [smooth(0, pm.H_CELL * FIX, STEPS, k) for k in (1, 2, 3)])
        self.assertEqual(r.h(3, 1), 0)


class Things(unittest.TestCase):
    def test_a_thing_follows_the_travelling_floor_every_step(self):
        # a thing on a rising tower: each frame differs from the last while the tower moves, and the
        # last equals the picture of the thing on a tower that was there when it was placed
        a = engine("cam 22.5 16 90\nnext\nthing 1 marauder 22.5 20.5 180\ncell 22 20 tower\nnext 60\n",
                   every=1, trace=False).frames
        self.assertEqual(a[-1], fresh("cell 22 20 tower\nthing 1 marauder 22.5 20.5 180\ncam 22.5 16 90\nnext\n"))
        moving = a[4:38]        # (the first and the last steps of a smoothstep move less than a point)
        self.assertTrue(all(x != y for x, y in zip(moving, moving[1:])))

    def test_camera_in_a_rising_cell_rides_with_the_floor(self):
        # the server never does it, the engine must not break: the eye is 41 units above the floor each step
        r = engine("cam 20.5 20.5 0\nnext\ncell 20 20 cell\nnext 50\n", every=1, trace=False)
        self.assertEqual(r.rc, 0, r.err)
        self.assertEqual(len(r.frames), 51)
        self.assertEqual(len({f for f in r.frames[1:30]}), 29, "a different picture each step")
        self.assertEqual(r.frames[-1], r.frames[-2])


class Same(unittest.TestCase):
    def test_same_lines_same_pictures(self):
        lines = ("next\ncell 20 20 cell\ncell 21 20 wall\nthing 2 loot 22.5 20.5 0\nnext 7\ncell 20 20 empty\n"
                 "cell 22 20 tower\nnext 9\norigin 5 5\nnext 2\ncell 21 21 own\nnext 30\n")
        a = engine(lines, every=1)
        b = engine(lines, every=1)
        self.assertEqual(a.rc, 0, a.err)
        self.assertEqual(a.frames, b.frames)
        self.assertEqual(a.trace, b.trace)
        self.assertGreater(len(a.frames), 45)
        self.assertTrue(any(0 < t[0] < pm.H_CELL * FIX for cells in a.trace.values() for t in cells.values()),
                        "the run has cells on their way")

    def test_the_pipe_does_not_matter(self):
        text = "next\ncell 20 20 cell\nnext 7\ncell 20 20 empty\nnext 9\n".encode()
        whole = engine(text.decode(), every=1)
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.Popen(tc.command(MAP), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, env=dict(tc.engine_env(out), POV_RISE_TRACE="1"))
            for ch in text:
                proc.stdin.write(bytes([ch]))
                proc.stdin.flush()
            proc.stdin.close()
            err = proc.stderr.read().decode()
            proc.stderr.close()
            self.assertEqual(proc.wait(timeout=60), 0, err)
            frames = tc.read_frames(out)
        self.assertEqual(frames, whole.frames)
        self.assertEqual(sorted(re.findall(r"^rise: .*$", err, re.M)),
                         sorted(re.findall(r"^rise: .*$", whole.err, re.M)))
        self.assertTrue(whole.trace and any(0 < t[0] < pm.H_CELL * FIX for c in whole.trace.values() for t in c.values()))


class ThemesAndPasses(unittest.TestCase):
    """The outline and stroke passes run on every frame of a travel: only the palette's colours come out, and
    a travel with a theme is deterministic."""

    def test_a_travel_with_a_theme_uses_only_its_palette_and_is_repeatable(self):
        import make_theme
        for name, theme in make_theme.THEMES.items():
            path = os.path.join(WORK.name, "rise-" + name + ".wad")
            with open(path, "wb") as handle:
                handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))
            allowed = set(make_theme.build_palette(theme))
            lines = "next\ncell 20 20 cell\ncell 22 20 tower\ncell 24 20 wall\ncam 22 15 90\nnext 14\n"
            a = engine(lines, every=7, theme=path)
            b = engine(lines, every=7, theme=path)
            self.assertEqual(a.rc, 0, a.err)
            self.assertEqual(a.series(2, 15), [smooth(0, pm.H_CELL * FIX, STEPS, k) for k in range(1, 15)],
                             "the frames written are frames of a travel")
            self.assertEqual(a.frames, b.frames)
            self.assertEqual(len(a.frames), 3)
            for frame in a.frames:
                body = frame[len(re.match(rb"P6\n\d+ \d+\n255\n", frame).group(0)):]
                seen = {tuple(body[i:i + 3]) for i in range(0, len(body), 3)}
                self.assertLessEqual(seen, allowed, (name, sorted(seen - allowed)[:3]))
                self.assertIn(make_theme.NAVY, seen)


class WithoutARise(unittest.TestCase):
    SCRIPT = ("cell 20 20 cell\ncell 22 20 tower\ncell 24 20 wall\nthing 1 marauder 22.5 18.5 90\ncam 22 15 90\nnext\n"
              "cell 20 20 empty\ncell 24 20 cell\ncell 26 20 own\nnext\norigin 4 4\nnext\ncell 22 20 empty\nnext\n")

    def test_rise_zero_gives_the_pictures_of_a_world_that_was_set_in_one_go(self):
        r = engine(self.SCRIPT, ("-pov-rise", "0"), every=1)
        self.assertEqual(r.rc, 0, r.err)
        final = "cell 24 20 cell\ncell 26 20 own\nthing 1 marauder 22.5 18.5 90\ncam 22 15 90\n"
        self.assertEqual(r.frames[-1], fresh("origin 4 4\n" + final + "next\n"))
        self.assertEqual(r.frames[0], fresh(
            "cell 20 20 cell\ncell 22 20 tower\ncell 24 20 wall\nthing 1 marauder 22.5 18.5 90\ncam 22 15 90\nnext\n"))

    @unittest.skipUnless(OLD_BIN and os.path.exists(OLD_BIN), "POV_OLD_BIN: the build before this package")
    def test_rise_zero_is_bit_identical_to_the_build_before(self):
        for script in (self.SCRIPT, "next\ncell 20 20 cell\nnext\ncell 20 20 empty\nnext\ncell 21 20 tower\nnext\n"):
            new = engine(script, ("-pov-rise", "0"), every=1, trace=False)
            old = engine(script, every=1, binary=OLD_BIN, trace=False)
            self.assertEqual(new.rc, 0, new.err)
            self.assertEqual(new.frames, old.frames)
            self.assertGreaterEqual(len(new.frames), 4)


class Live(unittest.TestCase):
    """Live mode reads the clock: a travel takes about 1200 ms of the engine's clock whatever the rate of the loop."""

    def test_a_change_after_the_first_fill_travels_and_ends_at_the_target(self):
        with tempfile.TemporaryDirectory() as out:
            env = tc.engine_env(out, live=True, every=100000)
            env["POV_RISE_TRACE"] = "1"
            proc = subprocess.Popen(tc.command(MAP), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, env=env)
            holder = []
            reader = threading.Thread(target=lambda: holder.append(proc.stderr.read()))
            reader.start()
            try:
                time.sleep(0.3)
                proc.stdin.write(b"cell 22 20 cell\n")       # the first fill: stands at once
                proc.stdin.flush()
                time.sleep(1.2)                               # more than the snap's time (18 steps) on the clock
                proc.stdin.write(b"cell 20 20 cell\n")        # a change: travels
                proc.stdin.flush()
                time.sleep(3.0)
            finally:
                proc.stdin.close()
            rc = proc.wait(timeout=30)
            reader.join()
            proc.stderr.close()
            err = holder[0].decode()
        self.assertEqual(rc, 0, err)
        tr = {}
        for m in re.finditer(r"^rise: frame=(\d+) cell=(\d+) h=(-?\d+) kind=\d+ look=\d+$", err, re.M):
            tr.setdefault(int(m.group(1)), {})[int(m.group(2))] = int(m.group(3))
        first = min(f for f, cells in tr.items() if CELL in cells)
        self.assertEqual(tr[min(tr)][OTHER], pm.H_CELL * FIX, "the first fill stood at once")
        series = [tr[f].get(CELL, 0) for f in sorted(tr) if f >= first]
        self.assertTrue(all(a <= b for a, b in zip(series, series[1:])))
        self.assertLess(series[0], pm.H_CELL * FIX // 2, "it starts low")
        self.assertEqual(series[-1], pm.H_CELL * FIX, "and arrives")
        self.assertGreater(len(series), 5, "in several pictures")


if __name__ == "__main__":
    unittest.main()
