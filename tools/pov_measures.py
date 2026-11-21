# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
"""Measures shared by the map generator and later packages (stdlib only).

Doom units: 32 units per metre. All heights are in Doom units (integers, the
format stores them as 16-bit signed numbers).

Sources of the proportions (read-only, in the cosmergon-agent repository):
  - cell edge 4 m:    src/cosmergon_agent/_posture.py:37  (CELL_M = 4.0)
  - storey = 4 m:     src/cosmergon_agent/scope.py:38     (_CEILING = 1.0, "floor to ceiling 4 m")
  - wall 0.5 storey:  src/cosmergon_agent/scope.py:37     (HEIGHT = {..., WALL: 0.5, ...})
  - cell 1.0 storey:  src/cosmergon_agent/scope.py:37     (HEIGHT = {CELL: 1.0, OWN: 1.0, ...})
  - tower shaft 0.95: src/cosmergon_agent/scope.py:37     (HEIGHT = {..., TOWER: 0.95})
  - tower deck + battlements: 0.12 E + 0.20 E = 0.32 model units E, where one storey is 1.634 E:
        the Cosmergon web view (storey 1.634 E, shaft + 0.32 E)
        => 0.32 / 1.634 = 0.1958 storey = 25 units (scope.py:34-35 only says "plus deck and battlements")
  - eye height 0.32 storey: scope.py:36 (EYE = 0.32), 0.32 * 128 = 41 = Doom's default view height.
"""

UNITS_PER_METER = 32
CELL_METERS = 4
CELL_SIZE = CELL_METERS * UNITS_PER_METER  # 128 units
STOREY = 4 * UNITS_PER_METER  # 128 units

GRID = 48  # cells per side
MAP_SIZE = GRID * CELL_SIZE  # 6144 units
ORIGIN = -MAP_SIZE // 2  # world coordinate of the south-west corner: -3072

# Floor heights per kind of square.
H_EMPTY = 0
H_WALL = STOREY // 2  # 64
H_CELL = STOREY  # 128
TOWER_SHAFT = round(0.95 * STOREY)  # 122
TOWER_ATTACHMENT = round(0.32 / 1.634 * STOREY)  # 25: deck + battlements (ausbau.js:50,56,66)
TOWER_TOP = round(0.95 * STOREY + 0.32 / 1.634 * STOREY)  # 147: shaft + deck + battlements

# Ceiling: one height for the whole map, well above the highest building (147).
CEILING = 4 * STOREY  # 512

# The renderer stores positions as 16.16 fixed point; the highest sector floor
# the map may ever get must stay below the ceiling (otherwise lines become solid
# and the renderer limits derived in COSMERGON.md no longer hold).
MAX_FLOOR = TOWER_TOP

EYE_HEIGHT = 41  # Doom's default view height above the floor

LIGHT = 200

# Texture and flat names (all present in freedoom1.wad, checked by tests).
TEX_LOWER = "STARTAN3"  # 128 x 128, used on the lower part of every cell edge
TEX_BORDER = "STONE3"  # 128 x 128, outer wall
FLAT_FLOOR = "FLOOR4_8"
FLAT_SKY = "F_SKY1"

LEVEL_NAME = "E1M1"


def sector_index(x: int, y: int) -> int:
    """Sector (and subsector) index of the cell in column x, row y."""
    return y * GRID + x
