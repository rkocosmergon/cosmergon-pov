#!/usr/bin/env python3
"""The time of day of the themes: key palettes and the way the engine mixes them. Standard library only.

A theme has one palette per KEY (a minute of the day); the engine (doomgeneric/pov_sky.c, `daytime` line)
mixes the two neighbouring keys for the minute it is told, so there is no step: every minute is its own
palette (integer mix, `palette_at` is the same arithmetic as POV_SkyPalette).

Each section (night, dawn, morning, day, evening, sunset, dusk) says
  haze    (colour, amount) a mix of the lit world towards a colour: night and dusk are bluish, not only darker
  mul     the world: every surface colour is multiplied by it (a warm or a blue light; the colours keep their
          differences, a multiply keeps the ratio of two colours and so their contrast in a ratio sense),
  top/hor the sky at its top and at the horizon, mixed into the theme's own sky by k,
  sun     the colour of the sun (ksun), cloud the colour of the clouds (kcloud), moon, and whether stars show.
The night is blue, not dark: the multiply is at least 0.66.
"""

from __future__ import annotations

# (minute of the day, section). The last key repeats the first (the minute 1440 = 0).
KEYS = [(0, "night"), (270, "night"), (360, "dawn"), (450, "morning"), (600, "day"), (960, "day"),
        (1080, "evening"), (1130, "sunset"), (1200, "dusk"), (1275, "night"), (1440, "night")]

SECTIONS = {
    "day": {"mul": (1.0, 1.0, 1.0), "stars": 0},
    "morning": {"mul": (1.0, 0.97, 0.91), "top": "#a8cdee", "hor": "#f6dcae", "k": 0.4,
                "sun": "#ffe39a", "ksun": 0.6, "cloud": "#fff2e0", "kcloud": 0.4, "stars": 0},
    "evening": {"mul": (1.0, 0.93, 0.82), "top": "#9fc2e8", "hor": "#f8d08a", "k": 0.5,
                "sun": "#ffc863", "ksun": 0.8, "cloud": "#ffe9c4", "kcloud": 0.5, "stars": 0},
    "dawn": {"mul": (1.0, 0.88, 0.84), "top": "#9db7e6", "hor": "#f3a38a", "k": 0.85,
             "sun": "#ffb070", "ksun": 1.0, "cloud": "#ffd9cc", "kcloud": 0.85, "stars": 0},
    "sunset": {"mul": (1.0, 0.82, 0.72), "top": "#8c78c0", "hor": "#f59a58", "k": 0.9,
               "sun": "#ff8a4a", "ksun": 1.0, "cloud": "#ffb894", "kcloud": 0.9, "stars": 0},
    "dusk": {"mul": (0.82, 0.78, 1.0), "haze": ("#5a5ab8", 0.08), "top": "#3e4da0", "hor": "#c880b4", "k": 1.0,
             "sun": "#ff8a4a", "ksun": 1.0, "cloud": "#c9a6d8", "kcloud": 1.0, "stars": 0},
    "night": {"mul": (0.68, 0.78, 1.0), "haze": ("#4a66c0", 0.14), "top": "#27408f", "hor": "#6f8fd8", "k": 1.0,
              "sun": "#ff8a4a", "ksun": 1.0, "cloud": "#aab9ee", "kcloud": 1.0, "stars": 1},
}
MOON = "#f6f3da"
# the colours a theme gives the world; each is multiplied by the section's light
WORLD_KEYS = ("ground", "border", "cell", "cell_shade", "own", "wall", "tower", "band", "tower_top",
              "ground_shade", "own_shade", "wall_shade", "tower_shade", "band_shade")


def _hex(text: str) -> tuple[int, int, int]:
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))


def _text(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


def _mix(a: str, b: str, t: float) -> str:
    ra, rb = _hex(a), _hex(b)
    return _text(tuple(ra[i] + (rb[i] - ra[i]) * t for i in range(3)))


def section_theme(theme: dict, sec: str) -> dict:
    """The theme as the section shows it: its colours, the world multiplied, the sky mixed."""
    s = SECTIONS[sec]
    out = dict(theme)
    for key in WORLD_KEYS:
        if key in theme:
            lit = _text(tuple(c * m for c, m in zip(_hex(theme[key]), s["mul"])))
            out[key] = _mix(lit, s["haze"][0], s["haze"][1]) if "haze" in s else lit
    if "top" in s:
        out["sky_top"] = _mix(theme["sky_top"], s["top"], s["k"])
        out["sky_horizon"] = _mix(theme["sky_horizon"], s["hor"], s["k"])
        out["disc"] = _mix(theme["disc"], s["sun"], s["ksun"])
        out["cloud"] = _mix(theme["cloud"], s["cloud"], s["kcloud"])
    out["moon"] = MOON
    out["stars"] = s["stars"]
    return out


def key_palettes(theme: dict, build_palette) -> list[list[tuple[int, int, int]]]:
    """One palette per key, built from the section's theme."""
    cache: dict[str, list] = {}
    out = []
    for _minute, sec in KEYS:
        if sec not in cache:
            cache[sec] = build_palette(section_theme(theme, sec))
        out.append(cache[sec])
    return out


def key_bytes() -> list[tuple[int, int]]:
    """(minute, stars) per key, for the POVSKY lump."""
    return [(minute, SECTIONS[sec]["stars"]) for minute, sec in KEYS]


def palette_at(pals, minute: int) -> list[tuple[int, int, int]]:
    """The palette of a minute: the integer mix of the two keys around it (the engine's arithmetic)."""
    k = 0
    while k + 2 < len(KEYS) and minute >= KEYS[k + 1][0]:
        k += 1
    span = KEYS[k + 1][0] - KEYS[k][0]
    t = ((minute - KEYS[k][0]) * 256 + span // 2) // span
    a, b = pals[k], pals[k + 1]
    return [tuple((a[i][c] * (256 - t) + b[i][c] * t + 128) >> 8 for c in range(3)) for i in range(256)]
