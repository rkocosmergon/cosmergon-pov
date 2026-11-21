#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Small PPM (P6) helpers for the tests. Standard library only.

  ppm_stats.py colors FILE            print the number of distinct colors
  ppm_stats.py same-view A B [ROWS]   exit 0 if the first ROWS rows (default 336 = the 3D view incl. weapon) match
"""

import sys


def read_ppm(path: str) -> tuple[int, int, bytes]:
    with open(path, "rb") as handle:
        data = handle.read()
    parts = data.split(None, 4)
    if parts[0] != b"P6" or parts[3] != b"255":
        raise SystemExit(f"{path}: not a P6 255 file")
    width, height = int(parts[1]), int(parts[2])
    pixels = parts[4]
    if len(pixels) != width * height * 3:
        raise SystemExit(f"{path}: wrong pixel data size {len(pixels)}")
    return width, height, pixels


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "colors":
        _, _, pixels = read_ppm(argv[2])
        print(len({pixels[i:i + 3] for i in range(0, len(pixels), 3)}))
        return 0
    if len(argv) >= 4 and argv[1] == "same-view":
        w1, _, a = read_ppm(argv[2])
        w2, _, b = read_ppm(argv[3])
        rows = int(argv[4]) if len(argv) > 4 else 336
        cut = w1 * rows * 3
        return 0 if w1 == w2 and a[:cut] == b[:cut] else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
