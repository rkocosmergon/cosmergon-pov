"""Tests of the sky (doomgeneric/pov_sky.c, tools/sky_art.py, tools/theme_day.py; COSMERGON.md, "The sky").

    python3 -m unittest tests.test_sky

Standard library only; starts the headless binary like tests.test_control. The pictures of 1280 x 800 are
3 MB: every run keeps a handful and removes them at once.
"""

import hashlib
import itertools
import math
import os
import subprocess
import sys
import tempfile
import time
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

WORK = tempfile.TemporaryDirectory()
MAP = os.path.join(WORK.name, "flat.wad")
EYE = "24.5 24.5"


def setUpModule():
    with open(MAP, "wb") as handle:
        handle.write(make_map.wad_bytes(make_map.build_map("flat")))
    for name in make_theme.THEMES:
        with open(os.path.join(WORK.name, name + ".wad"), "wb") as handle:
            handle.write(make_theme.wad_bytes(make_theme.build_theme(name)))


def tearDownModule():
    WORK.cleanup()


def render(data, theme=None, size=None, raw=False):
    """(returncode, stderr, [(w, h, rgb bytes)]) of one run (raw: the PPM files as bytes)."""
    cmd = tc.command(MAP) + ["-warp", "1", "1"]
    if theme:
        cmd += ["-pov-theme", os.path.join(WORK.name, theme + ".wad")]
    if size:
        cmd += ["-pov-size", size]
    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run(cmd, input=data.encode("ascii"), env=tc.engine_env(out), stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=120)
        frames = [bytes(f) if raw else parse(f) for f in tc.read_frames(out)]
    if tc.SANITIZED:
        assert not tc.sanitizer_findings(proc.stderr.decode("ascii", "replace")), proc.stderr[:500]
    return proc.returncode, proc.stderr.decode("ascii", "replace"), frames


def parse(frame):
    head = frame[:20].split(b"\n")
    w, h = map(int, head[1].split())
    return w, h, frame[len(head[0]) + len(head[1]) + len(head[2]) + 3:]


def pixels(rgb):
    return [tuple(rgb[i:i + 3]) for i in range(0, len(rgb), 3)]


def lab(rgb):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    x, y, z = ((0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, 0.2126 * r + 0.7152 * g + 0.0722 * b,
               (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883)

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e(a, b):
    return math.dist(lab(a), lab(b))


def sun_scene(minute, size, seconds=0, theme="wueste"):
    angle = sky_art.view_towards(minute)
    data = "daytime %d\nclouds %d\ncam %s %.3f\nnext\nquit\n" % (minute, seconds, EYE, angle)
    return render(data, theme, size)


class Line(unittest.TestCase):
    def test_valid_and_invalid_lines(self):
        good = "daytime 0\ndaytime 1439\ndaytime 720\nclouds 0\nclouds 10000000\nnext\nquit\n"
        bad = "daytime -1\ndaytime 1440\ndaytime x\ndaytime\ndaytime 1 2\ndaytime 12.5\nclouds -1\nclouds 10000001\n" \
              "clouds\nclouds 1 2\nnext\nquit\n"
        for theme in (None, "wueste"):
            rc, err, _ = render(good, theme)
            self.assertEqual(rc, 0, err)
            self.assertIn("lines=7 rejected=0", err)
            rc, err, _ = render(bad, theme)
            self.assertEqual(rc, 0, err)
            self.assertIn("lines=12 rejected=10", err)

    def test_without_theme_the_lines_change_nothing(self):
        # the pictures of a38a6b4 (hash as in test_theme: unchanged since 81fb3a0)
        scene = ("cell 24 26 cell\ncell 25 26 own\ncell 26 26 wall\ncell 27 26 tower\ncam 24.5 22.5 90\nnext\n")
        plain = render(scene, raw=True)[2][-1]
        self.assertEqual(hashlib.sha256(plain).hexdigest(),
                         "2d8f291e3a4c88a54880c32afd374528a77bbb7517c76f2618ff5c79c4790d88")
        for extra in ("daytime 0\n", "daytime 1100\nclouds 500\n"):
            rc, err, frames = render(extra + scene, raw=True)
            self.assertIn("rejected=0", err)
            self.assertEqual(frames[-1], plain)

    def test_same_input_same_picture(self):
        data = "daytime 1190\nclouds 777\ncam %s 200\nnext\nquit\n" % EYE
        a = render(data, "gelbestadt")[2][0]
        self.assertEqual(a, render(data, "gelbestadt")[2][0])


class Sun(unittest.TestCase):
    def disc(self, minute, size, theme="wueste"):
        """Frame with the sun fully visible (a cloud phase without a cloud over it), the sun's pixels."""
        w, h = map(int, size.split("x"))
        cx, cy, r = sky_art.project(minute, sky_art.view_towards(minute), w, h)
        want = math.pi * r * r
        sun = tuple(make_theme.hexrgb(make_theme.THEMES[theme]["disc"]))
        for seconds in range(0, 12000, 600):
            rc, err, frames = sun_scene(minute, size, seconds, theme)
            self.assertEqual(rc, 0, err)
            pts = [(i % w, i // w) for i, p in enumerate(pixels(frames[0][2])) if p == sun]
            if abs(len(pts) - want) < 0.01 * want:
                return pts, (cx, cy, r)
        self.fail("no cloud phase leaves the sun free at " + size)

    def test_the_sun_is_round_in_four_shapes(self):
        for size in ("320x200", "672x324", "1280x640", "1280x800"):
            pts, (cx, cy, r) = self.disc(720, size)
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
            self.assertLessEqual(abs(width - height), 1, (size, width, height))
            self.assertLessEqual(abs(width - 2 * r), 2, (size, width, r))
            # and where the arc puts it (the Python and the C arithmetic agree)
            self.assertLess(abs(sum(xs) / len(xs) + 0.5 - cx), 1.0, size)
            self.assertLess(abs(sum(ys) / len(ys) + 0.5 - cy), 1.0, size)


class Clouds(unittest.TestCase):
    def test_drift_changes_only_sky_points(self):
        for theme in ("wueste", "gelbestadt"):
            pal = make_theme.build_palette(make_theme.THEMES[theme])
            sky = {pal[i] for i in (*range(make_theme.SKY_FIRST, make_theme.SKY_FIRST + make_theme.SKY_BANDS),
                                    *make_theme.I_SKY.values())} | {make_theme.NAVY}
            field = "".join("cell %d %d wall\n" % (x, 30) for x in range(14, 34))
            frames = []
            for seconds in (0, 40):
                data = field + "daytime 720\nclouds %d\ncam %s 90\nnext\nquit\n" % (seconds, EYE)
                rc, err, fr = render(data, theme, "672x324")
                self.assertEqual(rc, 0, err)
                frames.append(pixels(fr[0][2]))
            diff = [(a, b) for a, b in zip(*frames) if a != b]
            self.assertGreater(len(diff), 300)
            self.assertTrue(all(a in sky and b in sky for a, b in diff))

    def test_clouds_move_by_whole_points(self):
        # 10 s = 2.5 degrees = 14.7 points at 672 wide: the drift is the floor of that
        self.assertEqual(sky_art.drift_points(10, 672), 14)
        self.assertEqual(sky_art.drift_points(0.5, 672), 0)
        self.assertEqual(sky_art.drift_points(10, 1280), 27)


class Live(unittest.TestCase):
    def test_drifting_clouds_draw_only_when_they_moved_a_point(self):
        # live mode, a tick every 20 ms (virtual clock too): in 5 s the clouds move 1.25 degrees = 7.3 points at
        # 672 wide; one picture at the start and one per point, not one per tick (250 ticks)
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.Popen(tc.command(MAP) + ["-warp", "1", "1", "-pov-theme", os.path.join(WORK.name, "wueste.wad"),
                                                       "-pov-size", "672x324"],
                                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    env=tc.engine_env(out, live=True, every=1))
            time.sleep(5.0)
            proc.stdin.close()
            err = proc.stderr.read().decode()
            proc.stderr.close()
            self.assertEqual(proc.wait(timeout=30), 0, err)
            frames = len([n for n in os.listdir(out) if n.endswith(".ppm")])
        self.assertGreaterEqual(frames, 5)
        self.assertLessEqual(frames, 12)


class Palette(unittest.TestCase):
    MINUTES = (0, 1, 100, 269, 270, 271, 359, 360, 361, 449, 451, 600, 719, 720, 959, 1079, 1080, 1081, 1129, 1131,
               1199, 1201, 1274, 1276, 1439)

    def test_themes_draw_only_their_palette_at_every_time(self):
        for name, theme in make_theme.THEMES.items():
            pals = theme_day.key_palettes(theme, make_theme.build_palette)
            for minute in self.MINUTES:
                allowed = set(theme_day.palette_at(pals, minute))
                data = ("cell 24 26 cell\ncell 25 26 own\ncell 26 26 wall\ncell 27 26 tower\ndaytime %d\n"
                        "cam 24.5 22.5 90\nnext\nquit\n" % minute)
                rc, err, frames = render(data, name)
                self.assertEqual(rc, 0, err)
                seen = set(pixels(frames[0][2]))
                self.assertLessEqual(seen, allowed, (name, minute, sorted(seen - allowed)[:3]))
                self.assertNotIn((255, 0, 255), seen)

    def test_default_is_the_noon(self):
        for name, theme in make_theme.THEMES.items():
            pals = theme_day.key_palettes(theme, make_theme.build_palette)
            self.assertEqual(theme_day.palette_at(pals, 720), make_theme.build_palette(theme))

    def test_steps_of_a_minute_are_below_what_the_eye_sees(self):
        # the largest change of one colour between two minutes, in the weakest channel step of the day
        for name, theme in make_theme.THEMES.items():
            pals = theme_day.key_palettes(theme, make_theme.build_palette)
            worst = 0
            prev = theme_day.palette_at(pals, 0)
            for minute in range(1, 1440):
                cur = theme_day.palette_at(pals, minute)
                worst = max(worst, max(abs(a[c] - b[c]) for a, b in zip(cur, prev) for c in range(3)))
                prev = cur
            self.assertLessEqual(worst, 4, (name, worst))

    def test_contrast_of_the_roles_in_every_minute(self):
        # The roles: ground, border, cell, own, wall, tower. The light of a section is a multiply by `mul`
        # and a haze (1 - h) of the lit colour plus h of a colour: for two surfaces the difference of their
        # colours (RGB) is multiplied by (1 - h) * mul per channel, so its length falls to at most the smallest
        # of these factors times the DAY state's. That is the bound (less the rounding of whole colour values,
        # sqrt(3)). Between two keys the mix of two palettes keeps the weaker factor of the two.
        roles = [art.I_GROUND, art.I_BORDER] + [art.I_ROLE[r]["x0"] for r in art.ROLES]
        for name, theme in make_theme.THEMES.items():
            pals = theme_day.key_palettes(theme, make_theme.build_palette)
            day = min(math.dist(pals[4][a], pals[4][b]) for a, b in itertools.combinations(roles, 2))
            factors = [min(theme_day.SECTIONS[sec]["mul"]) * (1 - theme_day.SECTIONS[sec].get("haze", (0, 0))[1])
                       for _m, sec in theme_day.KEYS]
            for minute in range(1440):
                k = 0
                while k + 2 < len(theme_day.KEYS) and minute >= theme_day.KEYS[k + 1][0]:
                    k += 1
                bound = day * min(factors[k], factors[k + 1]) - math.sqrt(3)
                pal = theme_day.palette_at(pals, minute)
                low = min(math.dist(pal[a], pal[b]) for a, b in itertools.combinations(roles, 2))
                self.assertGreaterEqual(low, bound, (name, minute, round(low, 2), round(bound, 2)))

    def test_night_is_bright(self):
        # a blue comic night, not a dark one: the world's mean lightness (Lab L) stays above 60 percent of the day's
        for name, theme in make_theme.THEMES.items():
            pals = theme_day.key_palettes(theme, make_theme.build_palette)
            roles = [art.I_GROUND, art.I_BORDER] + [art.I_ROLE[r]["x0"] for r in art.ROLES]
            mean = [sum(lab(p[i])[0] for i in roles) / len(roles) for p in (pals[0], pals[4])]
            self.assertGreater(mean[0], 0.6 * mean[1], (name, mean))


class Outline(unittest.TestCase):
    def test_no_line_inside_the_sky_and_one_around_a_cloud(self):
        # the clouds' own colours are one surface: navy appears only where two different things meet
        rc, err, frames = sun_scene(720, "672x324", 1200)
        self.assertEqual(rc, 0, err)
        w, h, rgb = frames[0]
        pal = make_theme.build_palette(make_theme.THEMES["wueste"])
        cloud, shade = pal[make_theme.I_SKY["cloud"]], pal[make_theme.I_SKY["shade"]]
        pts = pixels(rgb)
        # a navy point inside a cloud's fill (all four neighbours cloud or shade) would be a doubled line
        inner = 0
        for y in range(1, h // 2):
            for x in range(1, w - 1):
                if pts[y * w + x] == make_theme.NAVY:
                    around = [pts[y * w + x + d] for d in (-1, 1, -w, w)]
                    if all(a in (cloud, shade) for a in around):
                        inner += 1
        self.assertEqual(inner, 0)


if __name__ == "__main__":
    unittest.main()
