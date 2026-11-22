# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests of the field's rim: the kinds `ring`, `alcove`, `shaftlo`, `shafthi` (recesses with a ceiling of their own, the back
wall, the shaft's floor and its `shaft` line), their faces (tools/ring_art.py, lump POVRING of tools/make_theme.py) and the
placement rules of tools/ring_samples.py (COSMERGON.md, "The field's rim").

    python3 -m unittest tests.test_ring

Standard library only; starts the headless binary like tests.test_control.
"""

import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import make_map  # noqa: E402
import make_theme  # noqa: E402
import ring_art  # noqa: E402
import ring_samples  # noqa: E402
import theme_art as art  # noqa: E402
from tests import test_control as tc  # noqa: E402

WORK = tempfile.TemporaryDirectory()
MAP = os.path.join(WORK.name, "flat.wad")
THEME = os.path.join(WORK.name, "wueste.wad")
OLD_THEME = os.path.join(WORK.name, "wueste-without-ring.wad")      # a theme made before the rim: no POVRING
LUMPS = None


def setUpModule():
    global LUMPS
    with open(MAP, "wb") as handle:
        handle.write(make_map.wad_bytes(make_map.build_map("flat")))
    LUMPS = make_theme.build_theme("wueste")
    with open(THEME, "wb") as handle:
        handle.write(make_theme.wad_bytes(LUMPS))
    with open(OLD_THEME, "wb") as handle:
        handle.write(make_theme.wad_bytes([(n, d) for n, d in LUMPS if n != "POVRING"]))


def tearDownModule():
    WORK.cleanup()


def render(lines, theme=THEME, size="672x324"):
    """The last frame of a run (blocking mode) as (width, height, rgb bytes)."""
    import subprocess
    cmd = tc.command(MAP) + ["-warp", "1", "1", "-pov-size", size, "-pov-rise", "0"]     # a line after the rows would travel
    if theme:
        cmd += ["-pov-theme", theme]
    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run(cmd, input=lines.encode("ascii"), env=tc.engine_env(out), stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=60)
        err = proc.stderr.decode("ascii", "replace")
        assert proc.returncode == 0, err
        assert "rejected=0" in err, err
        frame = tc.read_frames(out)[-1]
    head = frame.split(b"\n", 3)
    w, h = (int(v) for v in head[1].split())
    return w, h, bytes(head[3])


def golds(theme_name="wueste"):
    pal = make_theme.build_palette(make_theme.THEMES[theme_name])
    return {tuple(pal[art.I_BAND["x"]]), tuple(pal[art.I_BAND["y"]])}


def gold_box(frame):
    """Bounding box (x0, y0, x1, y1) of the points in the colour of the bands, None if there are none."""
    w, h, rgb = frame
    want = golds()
    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            if tuple(rgb[3 * (y * w + x):3 * (y * w + x) + 3]) in want:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def floors(lines, cells=None):
    """Floor height (16.16) of every raised cell after the last frame, from the engine's measure POV_RISE_TRACE (a cell that is
    not empty is listed even at 0)."""
    import re
    import subprocess
    cmd = tc.command(MAP) + ["-warp", "1", "1", "-pov-rise", "0", "-pov-theme", THEME]
    with tempfile.TemporaryDirectory() as out:
        env = tc.engine_env(out, every=100000)
        env["POV_RISE_TRACE"] = "1"
        proc = subprocess.run(cmd, input=lines.encode("ascii"), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=60)
    err = proc.stderr.decode("ascii", "replace")
    assert proc.returncode == 0, err
    frames = [(int(f), int(c), int(h)) for f, c, h in re.findall(r"rise: frame=(\d+) cell=(\d+) h=(-?\d+)", err)]
    last = max(f for f, _c, _h in frames)
    return {c: h for f, c, h in frames if f == last}


U = 65536                          # one unit in 16.16


def cell(x, y):
    return y * 48 + x


# the bridge's window for a field of 32 (ring_samples.window): the field square (0, 0) at the window column 8 and, the rows
# running the other way, the field's y = 0 at the window row 39. South wall: the ring row 7; north: 40; west: column 7;
# east: column 40. A bunk at the field position 3.
WALLS = {"south": ((11, 7), (0, -1)), "north": ((11, 40), (0, 1)), "west": ((7, 36), (-1, 0)), "east": ((40, 36), (1, 0))}


class Accepted(unittest.TestCase):
    def test_cell_lines_and_row_characters(self):
        res = tc.run("cell 3 3 ring\ncell 4 3 alcove\ncell 5 3 shaftlo\ncell 6 3 shafthi\nrow 4 RKPQ" + "." * 44 + "\nnext\n",
                     wad=MAP)
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.summary, (6, 0), res.err)

    def test_other_names_and_characters_are_still_rejected(self):
        res = tc.run("cell 3 3 shaft\ncell 3 3 Ring\nrow 4 X" + "." * 47 + "\nrow 5 r" + "." * 47 + "\nnext\n", wad=MAP)
        self.assertEqual(res.summary, (5, 4), res.err)

    def test_the_shaft_line(self):
        ok = "shaft 3 3 0\nshaft 0 47 -512\nshaft 47 0 100\nshaft 3 3 -64\nnext\n"
        self.assertEqual(tc.run(ok, wad=MAP).summary, (5, 0))
        bad = "shaft 3 3\nshaft 3 3 -513\nshaft 3 3 101\nshaft 48 3 0\nshaft 3 3 1.5\nshaft 3 3 0 0\nshaft -1 3 0\nnext\n"
        self.assertEqual(tc.run(bad, wad=MAP).summary, (8, 7))


class Heights(unittest.TestCase):
    def test_the_ring_is_one_storey_high_a_bunk_is_on_the_ground_and_a_built_wall_stays_half(self):
        lines = "next\n" + "".join("cell %d 20 %s\n" % (x, k) for x, k in
                                   enumerate(("ring", "alcove", "shaftlo", "shafthi", "wall", "cell")))
        heights = floors(lines + "next\n")
        self.assertEqual(heights[20 * 48], 128 * U)
        for x in (1, 2, 3):
            self.assertEqual(heights[20 * 48 + x], 0, x)             # a bunk and a shaft are on the floor of the field
        self.assertEqual(heights[20 * 48 + 4], 64 * U)
        self.assertEqual(heights[20 * 48 + 5], 128 * U)

    def test_the_shaft_floor_is_set_by_a_line_for_both_cells_of_a_shaft(self):
        base = "next\ncell 5 20 shaftlo\ncell 6 20 shafthi\ncell 8 20 shaftlo\ncell 12 20 ring\n"
        h = floors(base + "shaft 6 20 -64\nnext\n")
        self.assertEqual((h[cell(5, 20)], h[cell(6, 20)]), (-64 * U, -64 * U))
        self.assertEqual(h[cell(8, 20)], 0, "another shaft stays")
        h = floors(base + "shaft 5 20 100\nnext\n")
        self.assertEqual((h[cell(5, 20)], h[cell(6, 20)]), (100 * U, 100 * U))
        # a line for a cell that is no shaft changes nothing, and is forgotten when the kind comes
        h = floors("next\nshaft 12 20 -64\ncell 12 20 ring\nnext\n")
        self.assertEqual(h[cell(12, 20)], 128 * U)

    def test_a_window_set_anew_forgets_the_shaft_floors(self):
        h = floors("next\ncell 5 20 shaftlo\ncell 6 20 shafthi\nshaft 5 20 -64\nnext\norigin 0 0\ncell 5 20 shaftlo\n"
                   "cell 6 20 shafthi\nnext\n")
        self.assertEqual((h[cell(5, 20)], h[cell(6, 20)]), (0, 0))

    def test_the_shaft_floor_glides_like_a_cell_rises(self):
        import re
        import subprocess
        lines = "next\ncell 5 20 shaftlo\ncell 6 20 shafthi\nnext\nshaft 5 20 -128\nnext 60\n"
        cmd = tc.command(MAP) + ["-warp", "1", "1", "-pov-theme", THEME]
        with tempfile.TemporaryDirectory() as out:
            env = tc.engine_env(out, every=100000)
            env["POV_RISE_TRACE"] = "1"
            err = subprocess.run(cmd, input=lines.encode("ascii"), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 timeout=60).stderr.decode("ascii", "replace")
        track = [int(h) for f, c, h in re.findall(r"rise: frame=(\d+) cell=(\d+) h=(-?\d+)", err) if int(c) == cell(5, 20)]
        self.assertEqual(track[-1], -128 * U)
        steps = [b - a for a, b in zip(track, track[1:])]
        self.assertTrue(all(d <= 0 for d in steps), "never up")
        self.assertGreater(sum(1 for d in steps if d < 0), 30, "it takes about 42 steps, like a cell of 128 units")


def scene(extra=""):
    return "\n".join(ring_samples.control_lines(32)) + "\n" + extra


class Placement(unittest.TestCase):
    def kinds(self, dim, wall):
        out = []
        for p in range(dim):
            x, y = {"north": (p, -1), "west": (-1, p), "south": (p, dim), "east": (dim, p)}[wall]
            out.append(ring_samples.rim_char(dim, x, y))
        return out

    def test_the_ring_is_one_cell_thick_around_the_field(self):
        cells = {(x, y) for x in range(-2, 35) for y in range(-2, 35) if ring_samples.rim_char(32, x, y)}
        self.assertEqual(len(cells), 4 * 32 + 4)
        self.assertTrue(all(x in (-1, 32) or y in (-1, 32) for x, y in cells))

    def test_sixteen_bunks_a_wall_at_the_concepts_offsets(self):
        for wall in ("south", "west", "north", "east"):
            k128 = self.kinds(128, wall)
            self.assertEqual([p for p, k in enumerate(k128) if k == "K"], [4 + 8 * i for i in range(16)])
            self.assertEqual([p for p, k in enumerate(k128) if k in "PQ"], [1, 2])
            k32 = self.kinds(32, wall)
            self.assertEqual([p for p, k in enumerate(k32) if k == "K"], [3 + 2 * i for i in range(15)])

    def test_the_shaft_is_two_cells_and_beats_a_bunk(self):
        for wall in ("south", "west", "north", "east"):
            k = self.kinds(32, wall)
            self.assertEqual(sorted(k[1:3]), ["P", "Q"], wall)
            self.assertEqual(sum(1 for v in k if v in "PQ"), 2)


class Back(unittest.TestCase):
    """Nothing exists beyond the rim: the cell behind a bunk or a shaft is raised to the rim and looks like it. Which
    cell that is follows from `world` and `origin` (the program knows no wall), whichever of the four walls."""

    def test_the_cell_behind_every_recess_is_raised_on_all_four_walls_and_the_field_side_is_not(self):
        h = floors(scene("next\n"))
        for wall, ((x, y), (dx, dy)) in WALLS.items():
            self.assertEqual(h[cell(x, y)], 0, wall)                                   # the bunk
            self.assertEqual(h[cell(x + dx, y + dy)], 128 * U, (wall, "behind"))
            self.assertEqual(h.get(cell(x - dx, y - dy), 0), 0, (wall, "field side"))
        # the two cells behind a shaft (field position 1, 2: south wall columns 9 and 10)
        self.assertEqual((h[cell(9, 6)], h[cell(10, 6)]), (128 * U, 128 * U))
        self.assertEqual((h[cell(9, 7)], h[cell(10, 7)]), (0, 0))

    def test_without_world_the_back_stays_open_and_with_another_dim_it_moves(self):
        lines = "\n".join(l for l in ring_samples.control_lines(32) if not l.startswith("world")) + "\nnext\n"
        self.assertEqual(floors(lines).get(cell(11, 6), 0), 0, "dim 128 by default: the rim is not where the rows put it")
        h = floors(scene("next\n"))
        self.assertEqual(h[cell(11, 6)], 128 * U)

    def test_a_cell_that_is_not_a_recess_keeps_its_height(self):
        h = floors(scene("cell 20 20 empty\nnext\n"))
        self.assertEqual(h.get(cell(20, 20), 0), 0)

    def test_the_back_goes_when_the_bunk_goes(self):
        h = floors(scene("cell 11 7 ring\nnext\n"))
        self.assertEqual(h.get(cell(11, 6), 0), 0)
        self.assertEqual(h[cell(11, 7)], 128 * U)

    def test_the_view_from_inside_a_bunk_to_the_back_is_a_wall_not_the_outside(self):
        def pixel(lines):
            w, h, rgb = render(lines)
            i = 3 * (80 * w + 336)                      # 14 degrees over the horizon, straight out through the back
            return rgb[i:i + 3]
        closed = pixel(scene("cam 11.5 7.5 270\nnext\n"))
        without = pixel("\n".join(l for l in ring_samples.control_lines(32) if not l.startswith("world")) + "\ncam 11.5 7.5 270\nnext\n")
        self.assertLess(closed[1] / closed[0], 0.75, "orange: the back wall")
        self.assertGreater(without[1] / without[0], 0.9, "beige: the far border wall of the window, seen through the open back")


class Recess(unittest.TestCase):
    """A bunk is a hollow in the map: a ceiling of 2.2 m, a floor on the ground, the wall over the opening up to the top of
    the rim."""

    def column(self, frame, x):
        w, h, rgb = frame
        return [rgb[3 * (y * w + x):3 * (y * w + x) + 3] for y in range(h)]

    def test_the_wall_over_the_opening_reaches_the_top_of_the_rim_and_the_opening_is_2_2_m_high(self):
        # 6 m (1.5 cells) in front of the bunk at (11, 7), looking south at its middle
        eye = "cam 11.5 9.5 270\nnext\n"
        ring = self.column(render(scene("cell 11 7 ring\n" + eye), theme=None), 336)
        bunk = self.column(render(scene(eye), theme=None), 336)
        gone = self.column(render(scene("cell 11 7 empty\n" + eye), theme=None), 336)
        top = next(i for i in range(len(ring)) if ring[i] != gone[i])           # the top of the rim: where the wall begins
        self.assertEqual(next(i for i in range(len(bunk)) if bunk[i] != gone[i]), top, "the wall over the opening is as high as the rim")
        brown = next(i for i in range(95, len(bunk)) if bunk[i][0] - bunk[i][2] >= 10 and bunk[i][0] < 90)   # the ceiling of the bunk: the first brown row under the lintel
        f, d = 336.0, 1.5 * 128                                                 # a picture 672 wide shows 90 degrees across
        self.assertAlmostEqual(top, 162 - f * (128 - 41) / d, delta=2.5)
        self.assertAlmostEqual(brown, 162 - f * (70 - 41) / d, delta=3.5)
        self.assertNotEqual(ring[115:150], bunk[115:150], "under the lintel there is a hollow, not the flat wall")

    def test_the_ceiling_is_not_the_sky(self):
        # from inside the bunk the upper picture is the ceiling, not the sky of the field
        w, h, rgb = render(scene("cam 11.5 7.5 90\nnext\n"))
        i = 3 * (5 * w + 336)
        self.assertLess(rgb[i + 2], rgb[i], "orange of the ceiling, not the blue of the sky")

    def test_a_marauder_in_a_bunk_is_seen(self):
        eye = "cam 11.5 9.5 270\nnext\n"
        none = render(scene(eye))[2]

        def changed(kind):
            shot = render(scene("thing 1 %s 11.5 7.4 0\n" % kind + eye))[2]
            return sum(1 for i in range(0, len(none), 3) if none[i:i + 3] != shot[i:i + 3])
        # the sprite is some 70 x 85 points at 6 m: in a solid block only a sliver of it would show
        self.assertGreater(changed("marauder"), 1500)
        self.assertGreater(changed("monster"), 1500, "the largest body (69 units) is under the ceiling of 70")

    def test_the_shaft_is_framed_in_gold_over_both_cells_and_wide(self):
        shot = render(scene("cam 10.0 11.0 270\nnext\n"))
        box = gold_box(shot)
        self.assertIsNotNone(box)
        self.assertGreater(box[2] - box[0], 150, "the lintel and the sides: the frame is wide")
        inside = render(scene("cam 10.4 7.5 180\nnext\n"))           # looking west along the wall: the side wall of the shaft
        wall = gold_box(inside)
        self.assertIsNotNone(wall, "inside the shaft the walls are gold")
        plain = render(scene("cell 9 7 ring\ncell 10 7 ring\ncam 10.0 11.0 270\nnext\n"))
        self.assertIsNone(gold_box(plain))

    def test_the_shaft_floor_can_be_lowered_and_the_picture_changes(self):
        eye = "cam 10.0 11.0 270\nnext\n"
        up = render(scene(eye))
        down = render(scene("shaft 9 7 -64\nnext 60\n" + eye))
        self.assertNotEqual(up[2], down[2])


class Faces(unittest.TestCase):
    def test_a_bunk_is_a_recess_not_a_picture(self):
        self.assertFalse(hasattr(ring_art, "alcove_face"))
        self.assertFalse(hasattr(ring_art, "portal_half"))

    def test_the_lump_lists_faces_that_exist_and_has_its_size(self):
        lump = dict(LUMPS)["POVRING"]
        self.assertEqual(lump[:5], b"POVE\x01")
        self.assertEqual(len(lump), 8 + 4 * 16 * 16)
        tex = make_theme.surfaces()["tex"]
        names = {lump[8 + 8 * i:16 + 8 * i].rstrip(b"\0").decode() for i in range(4 * 16 * 2)}
        self.assertTrue(names <= set(tex), sorted(names - set(tex)))
        for kind, (_l, variants, slots) in make_theme.RING_KINDS.items():
            self.assertEqual(set(slots), set(range(variants)), kind)

    def test_faces_differ_and_use_only_the_walls_indices_and_the_gold(self):
        tex = make_theme.surfaces()["tex"]
        ids = art.I_ROLE["wall"]
        for kind, (_l, variants, _s) in make_theme.RING_KINDS.items():
            for axis, (a, b) in zip((0, 1), (("x0", "x1"), ("y0", "y1"))):
                faces = [bytes(b"".join(tex[make_theme.ring_names(kind, v)[axis]])) for v in range(variants)]
                self.assertEqual(len(set(faces)), variants, (kind, axis))
                allowed = {ids[a], ids[b]} | {t for key in (ids[a], ids[b]) for t in art.TW[key]}
                allowed |= {art.SMALL_OF[ids[b]], art.SMALL_TWIN[art.SMALL_OF[ids[b]]]}
                band = art.I_BAND["xy"[axis]]
                allowed |= {band, *art.TW[band]}
                for v in range(variants):
                    seen = {x for row in tex[make_theme.ring_names(kind, v)[axis]] for x in row}
                    self.assertLessEqual(seen, allowed, (kind, v, axis, sorted(seen - allowed)))

    def test_the_gold_face_is_gold_all_over_the_top_19_units_the_lintel_shows(self):
        tex = make_theme.surfaces()["tex"]
        for axis in (0, 1):
            band = art.I_BAND["xy"[axis]]
            face = tex[make_theme.ring_names("portal-left", 0)[axis]]
            self.assertEqual(face[2][5], band)
            for y in range(0, 38):                                # 19 units of the lintel = 38 texels
                self.assertTrue(sum(1 for x in face[y] if x in (band, *art.TW[band])) > 200, (axis, y))


if __name__ == "__main__":
    unittest.main()
