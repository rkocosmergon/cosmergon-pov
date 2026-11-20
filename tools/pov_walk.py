#!/usr/bin/env python3
"""A stand-in for the bridge: writes a moving scene to the control channel in real time.

    python3 tools/pov_walk.py <seconds> [rate] | doomgeneric/cosmergon-pov ... -pov-control

A 48 x 48 window with about a third of the squares built on, a camera that walks and turns
(one `cam` line per step, `rate` steps a second: second argument, else POV_WALK_RATE, else 35), eight marauders walking, four loot
boxes, and every 60 seconds a "generation": 200 squares change at once. The same seed gives
the same lines. Standard library only.
"""

import math
import os
import random
import sys
import time

N = 48
KINDS = "." * 66 + "#" * 26 + "=" * 6 + "T" * 2  # shares in percent


def camera(t: float) -> tuple[float, float, float]:
    """Where the camera is t seconds in: a slow figure through the window, looking ahead."""
    x = 24.0 + 16.0 * math.sin(t * 0.11)
    y = 24.0 + 16.0 * math.sin(t * 0.07 + 1.0)
    ahead = math.degrees(math.atan2(0.07 * math.cos(t * 0.07 + 1.0), 0.11 * math.cos(t * 0.11)))
    return x, y, (ahead + 20.0 * math.sin(t * 0.9)) % 360.0


def main() -> int:
    seconds = float(sys.argv[1])
    rate = float(sys.argv[2]) if len(sys.argv) > 2 else float(os.environ.get("POV_WALK_RATE", "35"))
    rng = random.Random(799)
    out = sys.stdout
    for y in range(N):
        out.write("row %d %s\n" % (y, "".join(rng.choice(KINDS) for _ in range(N))))
    for i in range(4):
        out.write("thing %d loot %.2f %.2f 0\n" % (100 + i, rng.uniform(4, 44), rng.uniform(4, 44)))
    walkers = [[rng.uniform(4, 44), rng.uniform(4, 44), rng.uniform(0, 360)] for _ in range(8)]
    start = time.monotonic()
    step = 0
    while time.monotonic() - start < seconds:
        out.write("cam %.4f %.4f %.3f\n" % camera(step / rate))
        for i, w in enumerate(walkers):
            w[2] = (w[2] + rng.uniform(-6, 6)) % 360.0
            w[0] = min(46.9, max(1.0, w[0] + 0.03 * math.cos(math.radians(w[2]))))
            w[1] = min(46.9, max(1.0, w[1] + 0.03 * math.sin(math.radians(w[2]))))
            out.write("thing %d marauder %.4f %.4f %.1f\n" % (i, w[0], w[1], w[2]))
        if step and step % int(60 * rate) == 0:
            for _ in range(200):
                kind = rng.choice(["empty", "empty", "cell", "wall", "tower"])
                out.write("cell %d %d %s\n" % (rng.randrange(N), rng.randrange(N), kind))
        out.flush()
        step += 1
        pause = start + step / rate - time.monotonic()
        if pause > 0:
            time.sleep(pause)
    out.write("quit\n")
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
