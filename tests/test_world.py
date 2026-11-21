# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests of the sky as a place in the world: clouds with depth, neighbour cubes, the haze
(doomgeneric/pov_sky.c, pov_control.c; tools/sky_art.py; COSMERGON.md, "The sky").

    python3 -m unittest tests.test_world

Standard library only; starts the headless binary like tests.test_control. A theme with chosen clouds is built for each
test (`make_theme.build_theme(clouds=...)`), with the haze off (`fog=0`) where a colour is looked for.
"""

import functools
import itertools
import math
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import make_map  # noqa: E402
import make_theme  # noqa: E402
import sky_art  # noqa: E402
import theme_art as art  # noqa: E402
import theme_day  # noqa: E402
from tests import test_control as tc  # noqa: E402
from tests.test_sky import parse, pixels  # noqa: E402

WORK = tempfile.TemporaryDirectory()
MAP = os.path.join(WORK.name, "flat.wad")
M = sky_art.UNITS_PER_M
SHAPE = 0


def setUpModule():
    with open(MAP, "wb") as handle:
        handle.write(make_map.wad_bytes(make_map.build_map("flat")))


def tearDownModule():
    WORK.cleanup()


DEFAULT_SKY = "default"          # the theme's own clouds


@functools.lru_cache(maxsize=None)
def theme_file(name, fog, clouds):
    path = os.path.join(WORK.name, "t%d.wad" % len(os.listdir(WORK.name)))
    with open(path, "wb") as handle:
        handle.write(make_theme.wad_bytes(make_theme.build_theme(
            name, fog=fog, clouds=None if clouds == DEFAULT_SKY else list(clouds))))
    return path


def shot(clouds=(), cubes=(), size="672x324", cam=(24.5, 24.5, 0.0), level=0, extra="", fog=0.0, name="wueste",
         minute=720, seconds=0, origin=(0, 0), world=(0, 0, 0)):
    """One picture: (w, h, points). cubes: (cube_x, cube_y, cube_z) at dim 128."""
    lines = ["origin %d %d" % origin, "daytime %d" % minute, "clouds %d" % seconds,
             "world %d %d %d %d 128" % (world + (level,))]
    lines += ["cube %d %d %d %d 128" % ((i,) + c) for i, c in enumerate(cubes)]
    lines += ([extra] if extra else []) + ["cam %.3f %.3f %.3f" % cam, "next", "quit"]
    cmd = tc.command(MAP) + ["-warp", "1", "1", "-pov-theme", theme_file(name, fog, clouds if clouds == DEFAULT_SKY else tuple(clouds)), "-pov-size", size]
    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run(cmd, input=("\n".join(lines) + "\n").encode(), env=tc.engine_env(out),
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
        err = proc.stderr.decode("ascii", "replace")
        frames = tc.read_frames(out)
    assert proc.returncode == 0 and "rejected=0" in err, err
    if tc.SANITIZED:
        assert not tc.sanitizer_findings(err), err[:500]
    w, h, rgb = parse(bytes(frames[-1]))
    return w, h, pixels(rgb)


def eye_of(cam, level, origin=(0, 0), world=(0, 0, 0)):
    return sky_art.eye(world, level, 128, (origin[0] + cam[0]) * 128, (origin[1] + cam[1]) * 128, 41)


def put(eye, angle, depth_m, lateral_m, dz_m, width_m, shape=SHAPE):
    """A cloud at (depth ahead, lateral to the right, height over the eye) in metres, as world units."""
    th = math.radians(angle)
    x = eye[0] + (depth_m * math.cos(th) + lateral_m * math.sin(th)) * M
    y = eye[1] + (depth_m * math.sin(th) - lateral_m * math.cos(th)) * M
    return (int(x), int(y), int(eye[2] + dz_m * M), int(width_m * M), shape)


def palette(fog=0.0, name="wueste"):
    return make_theme.build_palette(dict(make_theme.THEMES[name], fog=fog))


def cloud_colours(pal):
    return {pal[make_theme.I_SKY["cloud"]], pal[make_theme.I_SKY["shade"]]}


def points_of(pts, w, colours):
    return [(i % w, i // w) for i, p in enumerate(pts) if p in colours]


@functools.lru_cache(maxsize=None)
def sprite_box(shape):
    """(first and last column, base row, last column of the base) of the sprite's texels (row 0 is the base)."""
    data = sky_art._sprite(shape)
    h, w = sky_art.SPR_H, sky_art.SPR_W
    cols = [c for c in range(w) if any(data[c * h:(c + 1) * h])]
    base = [c for c in range(w) if data[c * h + 10]]
    return cols[0], cols[-1], base[0], base[-1]


class Lines(unittest.TestCase):
    def run_lines(self, lines):
        cmd = tc.command(MAP) + ["-warp", "1", "1", "-pov-theme", theme_file("wueste", 1.0, DEFAULT_SKY)]
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.run(cmd, input=lines.encode(), env=tc.engine_env(out), stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE, timeout=60)
        return proc.returncode, proc.stderr.decode("ascii", "replace")

    def test_world_cube_nocube_valid_and_invalid(self):
        good = ("world 0 0 0 0 128\nworld -10000 10000 -3 127 128\nworld 0 0 0 7 8\nworld 1 2 3 1023 1024\n"
                "cube 0 1 0 0 128\ncube 63 -1 -1 -1 8\nnocube 0\nnocube 63\nnocube 5\nnext\nquit\n")
        bad = ("world 0 0 0 0\nworld 0 0 0 128 128\nworld 0 0 0 -1 128\nworld 0 0 0 0 7\nworld 0 0 0 0 1025\n"
               "world 10001 0 0 0 128\nworld a 0 0 0 128\nworld 0 0 0 0 128 1\n"
               "cube 64 0 0 0 128\ncube -1 0 0 0 128\ncube 0 0 0 0\ncube 0 10001 0 0 128\ncube 0 0 0 0 7\n"
               "nocube\nnocube 64\nnocube 1 2\nnext\nquit\n")
        rc, err = self.run_lines(good)
        self.assertEqual(rc, 0, err)
        self.assertIn("lines=11 rejected=0", err)
        rc, err = self.run_lines(bad)
        self.assertEqual(rc, 0, err)
        self.assertIn("lines=18 rejected=16", err)

    def test_without_theme_the_lines_change_nothing(self):
        scene = "cell 24 26 cell\ncell 25 26 own\ncam 24.5 22.5 90\nnext\n"
        plain = []
        for extra in ("", "world 3 4 5 6 128\ncube 0 1 0 0 128\nnocube 0\n"):
            cmd = tc.command(MAP) + ["-warp", "1", "1"]
            with tempfile.TemporaryDirectory() as out:
                proc = subprocess.run(cmd, input=(extra + scene).encode(), env=tc.engine_env(out),
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
                self.assertIn("rejected=0", proc.stderr.decode())
                plain.append(bytes(tc.read_frames(out)[-1]))
        self.assertEqual(plain[0], plain[1])


class CloudGeometry(unittest.TestCase):
    def test_clouds_stand_where_the_perspective_puts_them(self):
        # size, base row and place of a cloud follow its position in the world (the engine against sky_art.cloud_screen)
        for size in ("320x200", "672x324", "1280x640"):
            w, h = map(int, size.split("x"))
            cam, level = (24.5, 24.5, 0.0), 30
            eye = eye_of(cam, level)
            cloud = put(eye, 0.0, 1500, 250, 500, 500)
            xc, yb, pw, ph, _d = sky_art.cloud_screen(cloud, 0, eye, 0.0, w, h)
            c0, c1, _b0, _b1 = sprite_box(SHAPE)
            _, _, pts = shot([cloud], size=size, cam=cam, level=level)
            pal = palette()
            got = points_of(pts, w, cloud_colours(pal))
            self.assertGreater(len(got), 100, size)
            left, right = xc - pw / 2 + c0 / sky_art.SPR_W * pw, xc - pw / 2 + (c1 + 1) / sky_art.SPR_W * pw
            xs = [p[0] for p in got]
            self.assertLessEqual(abs(min(xs) - left), 3, (size, min(xs), left))
            self.assertLessEqual(abs(max(xs) + 1 - right), 3, (size, max(xs), right))
            self.assertLessEqual(abs(max(p[1] for p in got) + 1 - (yb - 10 * ph / sky_art.SPR_H)), 3, size)

    def test_the_lower_edge_is_a_row_of_the_picture_in_every_direction(self):
        # the base is flat and turned to the viewer: at the left, in the middle and at the right of the picture, in
        # three shapes and two directions the lowest cloud points of the middle of the base lie in one row (+-1)
        for size in ("320x200", "672x324", "1280x640"):
            w, h = map(int, size.split("x"))
            for angle in (0.0, 90.0):
                for lateral in (-1000, 0, 1000):
                    cam, level = (24.5, 24.5, angle), 30
                    eye = eye_of(cam, level)
                    cloud = put(eye, angle, 1700, lateral, 500, 500)
                    xc, _yb, pw, _ph, _d = sky_art.cloud_screen(cloud, 0, eye, angle, w, h)
                    _, _, pts = shot([cloud], size=size, cam=cam, level=level)
                    got = points_of(pts, w, cloud_colours(palette()))
                    _c0, _c1, b0, b1 = sprite_box(SHAPE)
                    mid = (b0 + b1) / 2 / sky_art.SPR_W
                    lo = xc - pw / 2 + (mid - 0.15 * (b1 - b0) / sky_art.SPR_W) * pw
                    hi = xc - pw / 2 + (mid + 0.15 * (b1 - b0) / sky_art.SPR_W) * pw
                    bottoms = {}
                    for x, y in got:
                        if lo <= x <= hi:
                            bottoms[x] = max(bottoms.get(x, -1), y)
                    self.assertGreater(len(bottoms), 3, (size, angle, lateral))
                    self.assertLessEqual(max(bottoms.values()) - min(bottoms.values()), 1, (size, angle, lateral))

    def test_a_cloud_gets_smaller_with_distance(self):
        widths = {}
        for depth in (800, 1600, 3200):
            cam, level = (24.5, 24.5, 0.0), 30
            eye = eye_of(cam, level)
            cloud = put(eye, 0.0, depth, 0, depth * 0.35, 400)
            _, _, pts = shot([cloud], cam=cam, level=level)
            xs = [p[0] for p in points_of(pts, 672, cloud_colours(palette()))]
            widths[depth] = max(xs) - min(xs) + 1
        self.assertAlmostEqual(widths[800] / widths[1600], 2.0, delta=0.2)
        self.assertAlmostEqual(widths[1600] / widths[3200], 2.0, delta=0.2)

    def test_near_things_move_more_than_far_ones(self):
        # a step of the camera across, and the wind, move a near cloud over the picture further than a far one
        def centre(depth, cam, seconds=0):
            level = 30
            eye = eye_of((24.5, 24.5, 90.0), level)          # the clouds are placed from the first position
            cloud = put(eye, 90.0, depth, 0, depth * 0.35, 400)
            _, _, pts = shot([cloud], cam=cam, level=level, seconds=seconds)
            xs = [p[0] for p in points_of(pts, 672, cloud_colours(palette()))]
            return (max(xs) + min(xs)) / 2.0

        for kind, kwargs in (("step", {"cam": (24.5 + 10.0, 24.5, 90.0)}), ("wind", {"cam": (24.5, 24.5, 90.0), "seconds": 30})):
            near = abs(centre(800, **kwargs) - centre(800, (24.5, 24.5, 90.0)))
            far = abs(centre(3200, **kwargs) - centre(3200, (24.5, 24.5, 90.0)))
            self.assertGreater(far, 1.0, kind)
            self.assertAlmostEqual(near / far, 4.0, delta=0.6, msg=kind)


class OneSkyForAll(unittest.TestCase):
    def test_a_cloud_is_seen_from_every_cube_in_the_right_direction(self):
        w, h = 672, 324
        eye0 = eye_of((24.5, 24.5, 0.0), 30)
        cloud = put(eye0, 0.0, 3000, 400, 700, 600)
        seen = {}
        for cube in ((0, 0, 0), (1, 0, 0), (1, 1, 0)):
            eye = eye_of((24.5, 24.5, 0.0), 30, world=cube)
            expect = sky_art.cloud_screen(cloud, 0, eye, 0.0, w, h)
            _, _, pts = shot([cloud], cam=(24.5, 24.5, 0.0), level=30, world=cube)
            got = points_of(pts, w, cloud_colours(palette()))
            if expect is None:
                self.assertEqual(got, [], cube)
                continue
            c0, c1, _b0, _b1 = sprite_box(SHAPE)
            xc, _yb, pw, _ph, _d = expect
            left, right = xc - pw / 2 + c0 / sky_art.SPR_W * pw, xc - pw / 2 + (c1 + 1) / sky_art.SPR_W * pw
            if left < 2 or right > w - 2:                          # partly out of the picture: only that it is there
                self.assertEqual(bool(got), right > 0 and left < w, cube)
                continue
            xs = [p[0] for p in got]
            self.assertLessEqual(abs(min(xs) - left), 3, cube)
            self.assertLessEqual(abs(max(xs) + 1 - right), 3, cube)
            seen[cube] = max(xs) - min(xs)
        self.assertGreater(seen[(1, 0, 0)], 1.5 * seen[(0, 0, 0)])        # one step (1280 m) nearer

    def test_the_same_place_in_the_world_is_the_same_sky(self):
        # cube (1, 0, 0) with the window at cells 0.. is the place cube (0, 0, 0) has with the window 320 cells on
        # (a step is 2.5 cubes of 128 cells): the sky above the border wall is the same, point for point. The view
        # is one in which clouds stand in the upper rows (computed from the clouds), so that this means something.
        w, h = 672, 324
        eye = eye_of((24.5, 24.5, 0.0), 30, world=(1, 0, 0))
        angle = max(range(0, 360, 15), key=lambda a: sum(
            1 for cl in sky_art.cloud_list() if (s := sky_art.cloud_screen(cl, 300, eye, a, w, h)) and 0 < s[0] < w and s[1] < 100))
        a = shot(DEFAULT_SKY, cam=(24.5, 24.5, angle), level=30, world=(1, 0, 0), origin=(0, 0), minute=720, seconds=300)
        b = shot(DEFAULT_SKY, cam=(24.5, 24.5, angle), level=30, world=(0, 0, 0), origin=(320, 0), minute=720, seconds=300)
        c = shot(DEFAULT_SKY, cam=(24.5, 24.5, angle), level=30, world=(0, 0, 0), origin=(0, 0), minute=720, seconds=300)
        top = slice(0, 100 * w)
        cloud = palette()
        self.assertGreater(sum(1 for p in a[2][top] if p in cloud_colours(cloud)), 500)
        self.assertEqual(a[2][top], b[2][top])
        self.assertNotEqual(a[2][top], c[2][top])


class Cubes(unittest.TestCase):
    def test_a_cube_has_the_size_and_the_place_the_geometry_gives(self):
        # a 512 m cube one step (1280 m) east, seen from the middle of its neighbour: edges and top against the corners
        for size in ("320x200", "672x324", "1280x640"):
            w, h = map(int, size.split("x"))
            cam, level = (24.5, 24.5, 0.0), 60
            eye = eye_of(cam, level, origin=(40, 40))
            step, wid = 2.5 * 128 * 128, 128 * 128
            corners = [(step + dx * wid - eye[0], dy * wid - eye[1]) for dx in (0, 1) for dy in (0, 1)]
            f = w / 2.0
            xs = [w / 2.0 + f * (-dy) / dx for dx, dy in corners]
            top = h / 2.0 - f * ((wid - eye[2]) / min(dx for dx, _dy in corners))
            pal = palette()
            tones = {pal[art.i_cube(lv, t)] for lv in range(4) for t in art.CUBE_TONES}
            _, _, pts = shot(cubes=[(1, 0, 0)], size=size, cam=cam, level=level, origin=(40, 40))
            got = points_of(pts, w, tones)
            self.assertGreater(len(got), 1000, size)
            tol = 3                                              # the outline takes a point, the row a point
            self.assertLessEqual(abs(min(p[0] for p in got) - min(xs)), tol, (size, min(p[0] for p in got), min(xs)))
            self.assertLessEqual(abs(max(p[0] for p in got) + 1 - max(xs)), tol, size)
            self.assertLessEqual(abs(min(p[1] for p in got) - top), tol, (size, min(p[1] for p in got), top))

    def test_a_cube_stands_where_it_is_and_nowhere_else(self):
        pal = palette()
        tones = {pal[art.i_cube(lv, t)] for lv in range(4) for t in art.CUBE_TONES}
        for angle, cube, expect in ((90.0, (0, 1, 0), True), (270.0, (0, 1, 0), False), (180.0, (-1, 0, 0), True),
                                    (0.0, (-1, 0, 0), False)):
            _, _, pts = shot(cubes=[cube], cam=(24.5, 24.5, angle), level=60, origin=(40, 40))
            self.assertEqual(any(p in tones for p in pts), expect, (angle, cube))

    def test_a_cloud_passes_in_front_of_a_cube_and_behind_it(self):
        w, h = 672, 324
        cam, level = (24.5, 24.5, 0.0), 60
        eye = eye_of(cam, level, origin=(40, 40))
        pal = palette()
        cloud_c = cloud_colours(pal)
        near_front = 32704 / M                                     # metres to the cube's face
        result = {}
        for name, depth in (("in front", 0.5 * near_front), ("behind", 2.0 * near_front)):
            scale = depth / (0.5 * near_front)
            # the same direction and the same apparent size: a bigger cloud further away
            cloud = put(eye, 0.0, depth, 0, scale * 120, scale * 300)
            _, _, pts = shot([cloud], cubes=[(1, 0, 0)], cam=cam, level=level, origin=(40, 40))
            xc, yb, pw, ph, _d = sky_art.cloud_screen(cloud, 0, eye, 0.0, w, h)
            c0, c1, b0, b1 = sprite_box(SHAPE)
            x = int(xc - pw / 2 + (b0 + b1) / 2 / sky_art.SPR_W * pw)
            y = int(yb - 40 * ph / sky_art.SPR_H)
            result[name] = pts[y * w + x]
        self.assertIn(result["in front"], cloud_c)
        self.assertNotIn(result["behind"], cloud_c)
        tones = {pal[art.i_cube(lv, t)] for lv in range(4) for t in art.CUBE_TONES}
        self.assertIn(result["behind"], tones)


class Haze(unittest.TestCase):
    def test_the_field_goes_into_the_haze_in_three_flat_steps(self):
        # along the middle of the floor, from the bottom to the horizon, the colour of the ground only goes
        # on to the next step (0, 1, 2, 3) and never back: no gradient, no more than three hazed colours
        for name in ("wueste", "gelbestadt"):
            pal = palette(1.0, name)
            level_of = {pal[i]: 0 for i in (art.I_GROUND, art.I_GROUND_SHADE, art.I_GROUND_LIGHT)}
            level_of.update({pal[art.i_fog(0, lv)]: lv for lv in (1, 2, 3)})
            w, h, pts = shot(cam=(1.5, 1.5, 45.0), fog=1.0, name=name)
            seq = [level_of[pts[y * w + w // 2]] for y in range(h - 1, h // 2 + 1, -1) if pts[y * w + w // 2] in level_of]
            self.assertEqual(sorted(set(seq)), [0, 1, 2, 3], (name, sorted(set(seq))))
            self.assertEqual(seq, sorted(seq), name)
            ground_colours = {p for p in pts if p in level_of}
            self.assertLessEqual(len(ground_colours), 3 + 3 + 3, name)       # the three plates' colours at step 0 and the 3 hazes

    def test_haze_off_is_no_haze(self):
        w, h, a = shot(cam=(1.5, 1.5, 45.0), fog=0.0)
        pal = palette(0.0)
        self.assertEqual(len({pal[art.i_fog(0, lv)] for lv in (1, 2, 3)} - {pal[art.I_GROUND]}), 0)
        light = shot(cam=(1.5, 1.5, 45.0), fog=1.0)
        self.assertNotEqual(a, light[2])

    def test_far_clouds_and_cubes_stand_paler_in_the_haze(self):
        pal = palette(1.0)
        eye = eye_of((24.5, 24.5, 0.0), 30)
        near = put(eye, 0.0, 800, 0, 300, 400)
        far = put(eye, 0.0, 6000, 0, 2000, 1500)
        for cloud, level in ((near, 0), (far, 3)):
            w, _h, pts = shot([cloud], cam=(24.5, 24.5, 0.0), level=30, fog=1.0)
            fill = pal[make_theme.I_SKY["cloud"]] if level == 0 else pal[art.I_CLOUD_FOG[level][0]]
            self.assertGreater(sum(1 for p in pts if p == fill), 50, level)
        hazy = [pal[art.i_cube(lv, "xs")] for lv in range(4)]
        self.assertEqual(len(set(hazy)), 4)
        bright = [sum(c) for c in hazy]
        self.assertEqual(bright, sorted(bright))                      # the further, the paler (towards the horizon)

    def test_roles_stay_apart_in_the_farthest_step_of_the_field(self):
        # the roles' colours in step L are the roles' colours mixed with the horizon colour by the same share, so the
        # difference of two of them is (1 - share) times the difference at step 0: the bound is the day's weakest pair
        # times that and times the light of the section (as in tests.test_sky), less sqrt(3) for the rounding
        groups = {name: g for g, (name, _m, _o) in enumerate(art.FOG_GROUPS)}
        roles = ("ground", "cell-x", "own-x", "wall-x", "tower-x")
        base = [art.I_GROUND] + [art.I_ROLE[r]["x0"] for r in art.ROLES]
        for name, k in itertools.product(make_theme.THEMES, (1.0, 2.0)):
            theme = dict(make_theme.THEMES[name], fog=k)
            pals = theme_day.key_palettes(theme, make_theme.build_palette)
            day = min(math.dist(pals[4][a], pals[4][b]) for a, b in itertools.combinations(base, 2))
            for i, (_minute, sec) in enumerate(theme_day.KEYS):
                s = theme_day.SECTIONS[sec]
                light = min(s["mul"]) * (1 - s.get("haze", (0, 0))[1])
                for level in (1, 2, 3):
                    share = min(0.95, make_theme.FIELD_S[level - 1] * k)
                    idx = [art.i_fog(groups[r], level) for r in roles]
                    low = min(math.dist(pals[i][a], pals[i][b]) for a, b in itertools.combinations(idx, 2))
                    self.assertGreaterEqual(low, day * light * (1 - share) - math.sqrt(3), (name, k, sec, level))


if __name__ == "__main__":
    unittest.main()
