# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests of the field's rim: the ring kinds `ring`, `alcove`, `shaftlo`, `shafthi`, their faces (tools/ring_art.py, lump
POVRING of tools/make_theme.py) and the placement rules of tools/ring_samples.py (COSMERGON.md, "The field's rim").

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
    cmd = tc.command(MAP) + ["-warp", "1", "1", "-pov-size", size]
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


def crop(frame, box):
    w, _h, rgb = frame
    x0, y0, x1, y1 = box
    return b"".join(rgb[3 * (y * w + x0):3 * (y * w + x1 + 1)] for y in range(y0, y1 + 1))


def floors(lines):
    """Floor height (16.16) of every raised cell after the last frame, from the engine's measure POV_RISE_TRACE."""
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


class Accepted(unittest.TestCase):
    def test_cell_lines_and_row_characters(self):
        res = tc.run("cell 3 3 ring\ncell 4 3 alcove\ncell 5 3 shaftlo\ncell 6 3 shafthi\nrow 4 RKPQ" + "." * 44 + "\nnext\n",
                     wad=MAP)
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.summary, (6, 0), res.err)

    def test_other_names_and_characters_are_still_rejected(self):
        res = tc.run("cell 3 3 shaft\ncell 3 3 Ring\nrow 4 X" + "." * 47 + "\nrow 5 r" + "." * 47 + "\nnext\n", wad=MAP)
        self.assertEqual(res.summary, (5, 4), res.err)

    def test_the_ring_is_one_storey_high_and_a_built_wall_stays_half(self):
        lines = "next\n" + "".join("cell %d 20 %s\n" % (x, k) for x, k in
                                   enumerate(("ring", "alcove", "shaftlo", "shafthi", "wall", "cell")))
        heights = floors(lines + "next\n")
        for x in range(4):
            self.assertEqual(heights[20 * 48 + x], 128 * 65536, x)
        self.assertEqual(heights[20 * 48 + 4], 64 * 65536)
        self.assertEqual(heights[20 * 48 + 5], 128 * 65536)

    def test_the_kinds_look_different(self):
        eye = "cam 24.5 24.5 0\nnext\n"
        shots = {k: render("cell 27 24 %s\n%s" % (k, eye)) for k in ("ring", "alcove", "shaftlo", "shafthi", "wall", "cell")}
        for k in shots:
            for other in shots:
                if k < other:
                    self.assertNotEqual(shots[k][2], shots[other][2], (k, other))


class Height(unittest.TestCase):
    def test_a_ring_face_reaches_as_high_as_a_cell_and_higher_than_a_wall(self):
        eye = "cam 24.5 24.5 0\nnext\n"
        empty = render(eye)

        def top(kind):
            w, h, rgb = render("cell 27 24 %s\n%s" % (kind, eye))
            col = w // 2
            for y in range(h):
                if rgb[3 * (y * w + col):3 * (y * w + col) + 3] != empty[2][3 * (y * w + col):3 * (y * w + col) + 3]:
                    return y
            return None
        self.assertEqual(top("ring"), top("cell"))
        self.assertEqual(top("alcove"), top("cell"))
        self.assertLess(top("ring"), top("wall"))

    def test_without_the_lump_a_theme_still_draws_the_ring(self):
        eye = "cam 24.5 24.5 0\nnext\n"
        old = render("cell 27 24 ring\n" + eye, theme=OLD_THEME)
        self.assertNotEqual(old[2], render(eye, theme=OLD_THEME)[2])
        self.assertNotEqual(old[2], render("cell 27 24 ring\n" + eye)[2], "the lump changes the look")
        none = render("cell 27 24 alcove\n" + eye, theme=None)           # no theme at all: still a wall of one storey
        self.assertNotEqual(none[2], render(eye, theme=None)[2])


def portal_scene(dim, ox, oy, wall=None):
    """The shaft cells of one wall (all four when `wall` is None)."""
    edge = {"south": lambda x, y: y == oy - 1, "north": lambda x, y: y == oy + dim, "west": lambda x, y: x == ox - 1,
            "east": lambda x, y: x == ox + dim, None: lambda x, y: True}[wall]
    cells = [(x, y, k) for x, y, k in ring_samples.ring_cells(dim, ox, oy) if k in ("shaftlo", "shafthi") and edge(x, y)]
    return "".join("cell %d %d %s\n" % c for c in cells)


class Portal(unittest.TestCase):
    """The two cells of a portal are one picture whichever wall they stand in: a viewer in front of the south wall and one in
    front of the north wall (a half turn apart) see the same portal, and so for east and west. Seen from the wrong side
    the halves would be exchanged and the frame would stand in the middle."""

    def look(self, wall):
        dim, ox, oy = 32, 8, 8
        cams = {"south": (ox + 2.0, oy + 4.0, 270), "north": (ox + 2.0, oy + dim - 4.0, 90),
                "west": (ox + 4.0, oy + 2.0, 180), "east": (ox + dim - 4.0, oy + 2.0, 0)}
        x, y, a = cams[wall]
        shot = render(portal_scene(dim, ox, oy, wall) + "cam %.2f %.2f %d\nnext\n" % (x, y, a))
        box = gold_box(shot)
        self.assertIsNotNone(box, wall)
        return box, crop(shot, box)

    def test_opposite_walls_show_the_same_portal(self):
        for a, b in (("south", "north"), ("west", "east")):
            (box_a, pic_a), (box_b, pic_b) = self.look(a), self.look(b)
            self.assertEqual((box_a[2] - box_a[0], box_a[3] - box_a[1]), (box_b[2] - box_b[0], box_b[3] - box_b[1]), (a, b))
            # the picture is the same but for the columns at the join of the two cells (a seam of the renderer: the texel
            # column that a one-point difference of the cell edge lands in)
            width = box_a[2] - box_a[0] + 1
            seam = range(width // 2 - 2, width // 2 + 3)
            same = [i for i in range(len(pic_a)) if pic_a[i] != pic_b[i] and (i % (3 * width)) // 3 not in seam]
            self.assertEqual(same, [], (a, b))

    def test_the_frame_is_one_frame_two_cells_wide(self):
        # one cell of the pair alone has about half the width of the pair (the frame runs over both)
        box, _pic = self.look("south")
        one = gold_box(render(portal_scene(32, 8, 8, "south").split("\n")[0] + "\ncam 10.00 12.00 270\nnext\n"))
        ratio = (box[2] - box[0] + 1) / (one[2] - one[0] + 1)
        self.assertTrue(1.8 < ratio < 2.2, ratio)


class Placement(unittest.TestCase):
    def kinds(self, dim, wall):
        cells = {(x, y): k for x, y, k in ring_samples.ring_cells(dim, 0, 0)}
        out = []
        for p in range(dim):
            out.append(cells[{"south": (p, -1), "west": (-1, p), "north": (p, dim), "east": (dim, p)}[wall]])
        return out

    def test_the_ring_is_one_cell_thick_around_the_field(self):
        cells = {(x, y) for x, y, _k in ring_samples.ring_cells(32, 5, 5)}
        self.assertEqual(len(cells), 4 * 32 + 4)
        self.assertTrue(all(x in (4, 37) or y in (4, 37) for x, y in cells))
        self.assertFalse(any(5 <= x < 37 and 5 <= y < 37 for x, y in cells))

    def test_sixteen_bunks_a_wall_at_the_concepts_offsets(self):
        for wall in ("south", "west", "north", "east"):
            k128 = self.kinds(128, wall)
            self.assertEqual([p for p, k in enumerate(k128) if k == "alcove"], [4 + 8 * i for i in range(16)])
            self.assertEqual([p for p, k in enumerate(k128) if k.startswith("shaft")], [1, 2])
            k32 = self.kinds(32, wall)
            self.assertEqual([p for p, k in enumerate(k32) if k == "alcove"], [1 + 2 * i for i in range(16) if 1 + 2 * i != 1])

    def test_the_shaft_is_two_cells_lower_coordinate_first_and_beats_a_bunk(self):
        for wall in ("south", "west", "north", "east"):
            k = self.kinds(32, wall)
            self.assertEqual(k[1:3], ["shaftlo", "shafthi"], wall)       # position 1 is a bunk on a field of 32: the shaft wins
            self.assertEqual(sum(1 for v in k if v.startswith("shaft")), 2)


class Faces(unittest.TestCase):
    def test_the_measures_are_the_concepts(self):
        self.assertEqual(ring_art.BUNK, round(2.2 / 4.0 * art.N))               # 2.2 m of a 4 m storey
        self.assertEqual(ring_art.PORTAL_H, round(3.4 / 4.0 * art.N))           # 3.4 m
        self.assertEqual(ring_art.PORTAL_H, round(0.85 * art.N))
        self.assertEqual(ring_art.PORTAL_X1 - ring_art.PORTAL_X0 + 1, 2 * art.N - 2 * ring_art.PORTAL_X0)
        self.assertEqual(ring_art.FLOOR_ROW + 1, art.N)

    def test_the_lump_lists_faces_that_exist_and_has_its_size(self):
        lump = dict(LUMPS)["POVRING"]
        self.assertEqual(lump[:5], b"POVE\x01")
        self.assertEqual(len(lump), 8 + 4 * 16 * 16)
        tex = make_theme.surfaces()["tex"]
        names = {lump[8 + 8 * i:16 + 8 * i].rstrip(b"\0").decode() for i in range(4 * 16 * 2)}
        self.assertTrue(names <= set(tex), sorted(names - set(tex)))
        # every face of the kinds is used in some slot, the halves of a portal have one picture each
        for kind, (_l, variants, slots) in make_theme.RING_KINDS.items():
            self.assertEqual(set(slots), set(range(variants)), kind)
        self.assertEqual(len(make_theme.RING_KINDS["portal-left"][2]), 16)

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

    def test_the_halves_of_a_portal_join_without_a_post_and_have_posts_outside(self):
        tex = make_theme.surfaces()["tex"]
        for axis in (0, 1):
            band = art.I_BAND["xy"[axis]]
            left = tex[make_theme.ring_names("portal-left", 0)[axis]]
            right = tex[make_theme.ring_names("portal-right", 0)[axis]]
            rows = range(ring_art.PORTAL_Y0 + ring_art.FRAME + 2, ring_art.FLOOR_ROW - 12)
            for y in rows:
                self.assertNotIn(band, left[y][236:], (axis, y, "left half, at the join"))
                self.assertNotIn(band, right[y][:20], (axis, y, "right half, at the join"))
                self.assertEqual(left[y][ring_art.PORTAL_X0 + 6], band, (axis, y, "the left post"))
                self.assertEqual(right[y][ring_art.PORTAL_X1 - art.N - 6], band, (axis, y, "the right post"))

    def test_the_portal_is_3_4_m_high_and_the_bunk_2_2_m(self):
        tex = make_theme.surfaces()["tex"]
        ids = art.I_ROLE["wall"]
        # the portal: the gold of the left post runs from the lintel to the sill, 218 rows
        band = art.I_BAND["x"]
        left = tex[make_theme.ring_names("portal-left", 0)[0]]
        col = [y for y in range(art.N) if left[y][ring_art.PORTAL_X0 + 2] in (band, *art.TW[band])]
        self.assertEqual(max(col) - min(col) + 1, ring_art.PORTAL_H - 1)        # the frame's own outline takes the last row
        # the bunk: the opening (the dark stage and what lies in it) is as wide and as high as the concept says, from the
        # floor up; its frame is the outline of the opening
        c = art.Canvas(ids["x0"], ids["x1"], small_r=11)
        ring_art.alcove_face(c, make_theme._rng("ring", "alcove", 0), 0, art.I_BAND["x"])
        x0 = (art.N - ring_art.BUNK) // 2
        row = c.g[ring_art.FLOOR_ROW - 1 - ring_art.BUNK // 2]
        wide = {*art.TW[ids["x0"]], *art.TW[ids["x1"]]}
        inside = [x for x in range(art.N) if row[x] in wide and x0 - 1 <= x <= x0 + ring_art.BUNK]
        self.assertTrue(inside and min(inside) <= x0 + 2 and max(inside) >= x0 + ring_art.BUNK - 3)


if __name__ == "__main__":
    unittest.main()
