# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests of the strokes: how thick they are near the viewer, how far the floor strokes reach, and how calm the far floor is.

    python3 -m unittest tests.test_ink

Uses tools/measure_ink.py and tools/measure_far.py (theme with the stroke indices in pure red and green). The thickness
limit is the width of the outline (pov_control.c POV_OUTLINE_WIDE_FROM), not a number set for the test. Every
check has its counter-proof against the state before the thinning (`a78d36d`): the numbers are in the docstrings.
"""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import measure_far  # noqa: E402
import measure_ink  # noqa: E402


def outline_width(size: str) -> int:
    """The width of the outline in points for a picture size, from the engine's own constant."""
    with open(os.path.join(ROOT, "doomgeneric", "pov_control.c"), encoding="utf-8") as handle:
        wide_from = int(re.search(r"#define POV_OUTLINE_WIDE_FROM (\d+)", handle.read()).group(1))
    return 2 if int(size.split("x")[0]) >= wide_from else 1


class Thickness(unittest.TestCase):
    def test_a_stroke_is_no_thicker_than_the_outline_at_any_distance(self):
        # a78d36d: median 2 / 2 / 2 points at 672 wide and 5 / 3 / 3 at 1280 (64 / 128 / 256 units), 99th percentile 16..41
        got = measure_ink.measure(ROOT, "gelbestadt")
        for (size, d), (n, median, p90, p99, _largest) in got.items():
            self.assertGreater(n, 400, (size, d))
            self.assertLessEqual(median, outline_width(size), (size, d))
            self.assertLessEqual(p99, outline_width(size), (size, d))      # the corners, where two strokes cross, are the rest

    def test_the_same_measure_finds_the_old_thick_strokes_when_the_thinning_is_off(self):
        got = measure_ink.measure(ROOT, "gelbestadt", strip_ink=True)
        thick = [(size, d) for (size, d), (_n, median, _p90, p99, _l) in got.items()
                 if median > outline_width(size) or p99 > outline_width(size)]
        self.assertEqual(len(thick), len(got), got)


class Reach(unittest.TestCase):
    def test_floor_strokes_reach_the_middle_distance(self):
        # between 150 and 400 units (a good cell width and more): a78d36d had none (the lines folded at 128 units)
        self.assertGreater(measure_ink.floor_stroke_points(ROOT, "gelbestadt"), 600)


class FarBand(unittest.TestCase):
    def test_the_far_floor_is_calm_and_does_not_flicker(self):
        # the band from the horizon to 12 percent of the height below it; a78d36d: edge share 0.0506, changed per step 0.1555
        edges, changed = measure_far.measures(ROOT, "gelbestadt", "672x324")
        self.assertLess(edges, 0.045)
        self.assertLess(changed, 0.11)


if __name__ == "__main__":
    unittest.main()
