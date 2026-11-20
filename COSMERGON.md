# cosmergon-pov

Fork of [ozkl/doomgeneric](https://github.com/ozkl/doomgeneric), upstream commit
`e257a09527062bfb986b6e5e0780839b6cbd5b71` (2026-10-11). Remote `upstream` points there.
License: GPL-2.0 (see `LICENSE`, unchanged).

## What this fork adds

- `doomgeneric/doomgeneric_headless.c`: platform layer without window, sound or input.
  Virtual clock (deterministic, as fast as the CPU allows), frames written as PPM (P6).
- `doomgeneric/Makefile.headless`: build without SDL and sound, output `cosmergon-pov-headless`.
- `scripts/download-freedoom.sh`: pinned, SHA-256 checked Freedoom download.
- `tools/ppm2png.py`: PPM to PNG (standard library only).
- `tests/test_headless.sh`: smoke test.
- One upstream change: `doomgeneric/i_system.c` skips the zenity error dialog when
  `POV_NO_ERROR_DIALOG` is defined (set in `Makefile.headless`). The message still goes to stderr.

## Build and run

    bash scripts/download-freedoom.sh
    make -C doomgeneric -f Makefile.headless
    mkdir -p out
    POV_OUT=out POV_EVERY=35 POV_FRAMES=1400 \
      doomgeneric/cosmergon-pov-headless -iwad assets/freedoom/freedoom1.wad
    python3 tools/ppm2png.py out/frame-000035.ppm out/frame-000035.png

Environment: `POV_OUT` (required output directory), `POV_EVERY` (default 35), `POV_FRAMES` (default 700).

## Test

    bash tests/test_headless.sh

## Freedoom

Game data is [Freedoom](https://freedoom.github.io/) 0.13.0, licensed under the BSD 3-clause
license (`assets/freedoom/COPYING.txt` after download). The IWAD is not part of this repository.
No original Doom data is used.

## The fixed map (package P2)

One map `E1M1` in `assets/cosmergon.wad` (PWAD, not committed, generated), 48 x 48 grid cells.

- **Sector index = y * 48 + x** (x east, y north, both 0..47). Subsector index = sector index.
  Sector, subsector and cell number are the same number; the sector's floor height is the cell's height.
- Cell edge 128 units = 4 m (32 units per metre). Map spans -3072..3072 in x and y. Cell (x, y) covers
  x from -3072 + 128 x to -3072 + 128 (x + 1), same for y. All coordinates are 16-bit safe.
- Every cell edge is a two-sided line with the lower texture (`STARTAN3`) on both sides, upper and middle
  are `-`. The outer border is one-sided with `STONE3`. Floor flat `FLOOR4_8`, ceiling `F_SKY1`,
  light 200, ceiling 512 for every sector. One thing: the player start.
- Line index and side index are not a stable interface; use the sector index.
- `tools/pov_measures.py` holds the heights (`H_EMPTY` 0, `H_WALL` 64, `H_CELL` 128, `TOWER_SHAFT` 122,
  `TOWER_TOP` 147, `CEILING` 512, `EYE_HEIGHT` 41) with the source of each proportion. Floors must stay
  between 0 and `MAX_FLOOR` (147): a floor at or above the ceiling would make cell edges solid, and the
  limits below assume that only the outer border is solid.
- BSP: built directly from the grid (split the longer side in the middle along grid lines, a leaf is one
  cell with its four segs). Root is the last node. Blockmap: block size 128 = cell size, a line is listed in
  every block in which it has a stretch of positive length. REJECT is all zero.

### Generate and load

    python3 tools/make_map.py [--pattern flat|checker|full|random|stairs] [--seed N] \
        [--start X,Y,ANGLE] [--start-floor H] [-o assets/cosmergon.wad]
    POV_OUT=out POV_EVERY=70 POV_FRAMES=70 \
      doomgeneric/cosmergon-pov-headless -iwad assets/freedoom/freedoom1.wad \
        -file assets/cosmergon.wad -warp 1 1 </dev/null

`-warp 1 1` goes straight to the map (no title, no demo). The headless build never does the screen melt
(`POV_NO_WIPE`), so the first written frame already shows the map.

- `flat` (all heights 0) is the delivery state; the other patterns burn test heights into the sectors:
  `checker` (alternating 128 and 0), `full` (all 128), `random` (every height 0..147, seeded, a stress case),
  `stairs` (steps of 16 rising along x, restarting every 10 cells).
- `--start X,Y,ANGLE`: cell coordinates (0..48, default `24.5,24.5`, the centre of cell 24,24) and degrees,
  0 = east, 90 = north. The engine rounds the angle to multiples of 45, so other angles are refused.
- **The start cell is empty in every pattern** (`full` would otherwise put the player inside a block).
  Its floor is `--start-floor` (default 0). A start floor of 128 or more lets the eye (floor + 41) see the
  tops of 128-high cells.
- Heights burnt in are only for tests; P3 changes sector floors at run time.

### Renderer limits

The engine is built with fixed arrays. Overflow behaviour "before" is upstream. "After" is this fork:
every overflow ends in `I_Error` with a clear message before anything is written past an array. Upstream
values are kept behind `make -f Makefile.headless UPSTREAM_LIMITS=1` (own directory `build-headless-upstream`,
binary `cosmergon-pov-headless-upstream`); the raised values are in `r_defs.h` and `i_system.c`.
Highwater marks of one run are printed at exit (`headless: highwater ...`).

| Limit | Where (upstream) | Old | New | Derivation | Overflow before | Overflow now |
|---|---|---|---|---|---|---|
| `MAXDRAWSEGS` | r_defs.h:51, check r_segs.c:383 | 256 | 9408 | 4704 lines (2*48*49); of each line's two segs at most one faces the viewer, so at most 4704 stored; factor 2 allows one split per seg (the only solid lines are the 192 border segs) | wall silently dropped (wrong picture) | `I_Error` |
| `MAXVISPLANES` | r_plane.c:45, checks :238 and :374 | 128 | 23424 | `R_Subsector` finds at most 2 planes per subsector (2*2304) plus `R_CheckPlane` duplicates at most 2 per drawseg (2*9408) | `R_FindPlane`: `I_Error`; `R_CheckPlane` (r_plane.c:306): no check, wrote past the array | `I_Error` in both |
| `MAXOPENINGS` | r_plane.c:52, check :378 | 20480 (`SCREENWIDTH*64`) | 121600 | a screen column is covered by at most 95 lines (47 + 47 inner + 1 border) x2 for rounding of column borders at shared vertices x2 for the top and bottom clip array copied per drawseg: `SCREENWIDTH*380` | checked only at the end of the frame, after writing past the array | `I_Error` before each write (r_segs.c, `POV_NeedOpenings`) |
| `MAXSEGS` (solidsegs) | r_bsp.c:81 | 32 | 162 | posts are separated by at least one column: at most 160, plus 2 sentinels (`SCREENWIDTH/2 + 2`) | no check, wrote past the array | `I_Error` (r_bsp.c, insertion) |
| zone memory | i_system.c:58-59 | 6 MiB | 9 MiB | 6 MiB upstream plus this map's level data, which stays in the zone: 2.29 MiB (vertexes 19208, segs 516096, subsectors 36864, sectors 294912, lines 413952, sides 221184, nodes 119756, blockmap 27656 + links 18432, reject 663552, line lists 73728 bytes; struct sizes from `sizeof` in this build) | `Z_Malloc` ends in `I_Error` | unchanged (`I_Error`); `MIN_RAM` = `DEFAULT_RAM`, so a failed allocation says so |
| `MAXVISSPRITES` | r_things.h:25, r_things.c:322 | 128 | 128 | one thing (the player, which is not drawn) | extra sprites dropped (graceful) | unchanged; not reachable |
| `MAXSPECIALCROSS`, `MAXINTERCEPTS` | p_local.h:155,219 | | | no special lines, no shooting, no input | | not reachable |
| `short` blockmap offsets | p_setup.c:84 (signed) | 32767 | | the lump has 13828 shorts; the generator refuses more than 32767 | | generator error |
| fixed-point distance | r_main.c `SlopeDiv` (`num<<3` in 32 bits) | | | deltas must stay below 8192 units; the map is 6144 wide | | not reachable |

High water of the worst measured views (`tests/test_map_render.sh`, 70 frames each): drawsegs 4474 (checker,
corner view over the diagonal), visplanes 1152 (same), openings 20593 (same; the old 20480 is too small by
113), solidsegs 3. Memory in use after 700 frames: 3.3 MB non-purgeable of 9 MiB.

Other upstream changes in this package: `d_main.c` (`POV_NO_WIPE`), `r_plane.h` (declarations),
`doomgeneric_headless.c` (prints the high water marks). Each is marked `// cosmergon-pov:`.

### Tests

    python3 -m unittest tests.test_make_map      # generator, standard library only
    bash tests/test_map_render.sh                # engine: every pattern x 3 views, plus the old-limits counter-check
    POV_PNG=1 bash tests/test_map_render.sh      # also writes out/map-<pattern>-<view>.png
