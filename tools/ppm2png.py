#!/usr/bin/env python3
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Convert a binary PPM (P6, maxval 255) to PNG using only the standard library."""
import struct
import sys
import zlib


def read_ppm(path):
    with open(path, "rb") as f:
        data = f.read()
    pos = 0
    tokens = []
    while len(tokens) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            while data[pos:pos + 1] != b"\n":
                pos += 1
            continue
        start = pos
        while not data[pos:pos + 1].isspace():
            pos += 1
        tokens.append(data[start:pos])
    pos += 1  # single whitespace after maxval
    if tokens[0] != b"P6" or tokens[3] != b"255":
        raise ValueError("only P6 with maxval 255 is supported")
    width, height = int(tokens[1]), int(tokens[2])
    pixels = data[pos:]
    if len(pixels) != width * height * 3:
        raise ValueError("pixel data has the wrong size")
    return width, height, pixels


def chunk(kind, payload):
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def write_png(path, width, height, pixels):
    stride = width * 3
    raw = b"".join(b"\x00" + pixels[y * stride:(y + 1) * stride] for y in range(height))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def main():
    if len(sys.argv) != 3:
        print("usage: ppm2png.py in.ppm out.png", file=sys.stderr)
        return 2
    width, height, pixels = read_ppm(sys.argv[1])
    write_png(sys.argv[2], width, height, pixels)
    return 0


if __name__ == "__main__":
    sys.exit(main())
