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
| `MAXVISSPRITES` | r_things.h:25, r_things.c:322 | 128 | 256 | one vissprite per thing in view; the control channel (P3) has at most 256 things (ids 0..255), the player is never linked into a sector | extra sprites dropped (quietly) | `I_Error` |
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

## Control channel (package P3)

With `-pov-control` the engine only displays. The level (the fixed map) is loaded once; after that no
game tic runs: no thinkers, no input, no monsters, no status bar, no weapon, no menu, no wipe
(`pov_control.c`, switched in `d_main.c` under `POV_VIEW_ONLY`). Without the switch the build behaves
as before.

### Lines

Text lines on stdin, fields separated by blanks or tabs, at most 255 bytes, printable ASCII, LF or CRLF.
Coordinates are in cells of the 48 x 48 window: x to the east, y to the north, (0, 0) is the south-west
corner; angles in degrees, 0 = east, counter-clockwise.

| Line | Meaning | Limits |
|---|---|---|
| `cell <x> <y> <kind>` | kind of one cell: `empty`, `cell`, `wall`, `tower` | x, y integers 0..47 |
| `row <y> <48 characters>` | a whole row, west to east: `.` empty, `#` cell, `=` wall, `T` tower | exactly 48 characters |
| `thing <id> <kind> <x> <y> <angle>` | places or moves a thing: `marauder`, `loot` | id 0..255; 0 <= x, y < 48; angle within +-1,000,000 |
| `gone <id>` | removes a thing (unknown id: nothing happens) | id 0..255 |
| `cam <x> <y> <angle>` | camera; the eye is 41 units above the floor of the cell it stands in | as `thing` |
| `light <level>` | light level of all sectors | 0..255 |
| `next [n]` | draw n frames (default 1) with the state reached so far | 1..1,000,000 |
| `quit` | end | |

A line that is not exactly one of these is rejected as a whole, counted, and changes nothing; the first
20 reasons go to stderr. At the end stderr carries `control: lines=<n> rejected=<m>`. No input ends the
program with an error: tests feed 20,000 random valid lines, every class of invalid line, and noise
(`tests/test_control.py`, also under AddressSanitizer and UBSan).

The plan named `floor <x> <y> <height>`. Built is `cell` with a kind: the kind fixes height, wall texture
and floor flat together (table `s_kind` in `pov_control.c`), so a writer cannot send a height the limits
were not derived for. Heights equal `tools/pov_measures.py` (the test compares both files).

### Reading

Blocking (default): the engine reads until `next`, `quit` or end of input, so the frames depend only on
the input (same input, same bytes; chunking of the pipe does not matter). Live (`POV_CONTROL_LIVE=1`):
reading never blocks, a frame is drawn every tick; this is how a window platform reads. The platform
supplies `DG_ControlRead()`.

### Headless output

With `-pov-control` the headless build writes every frame (`POV_EVERY` default 1) and has no frame limit.
A frame is 768 kB: a run with thousands of frames needs `POV_EVERY` or `POV_FRAMES`. On 2026-11-20 two
such runs wrote 3.8 GB into a RAM-backed `/tmp` and the machine killed the session; the long test now
writes every 64th frame.

### Upstream changes

`d_main.c` (tick and start), `r_things.c` (no weapon; vissprite overflow is an error; 64-bit compare in
`R_ProjectSprite`, an overflow of `tz << 2` found by UBSan), `r_things.h` (limit 256). Each is marked
`// cosmergon-pov:`.

### Tests

    python3 -m unittest tests.test_control
    make -C doomgeneric -f Makefile.headless SANITIZE=1
    POV_SANITIZED=1 POV_BIN=$PWD/doomgeneric/cosmergon-pov-headless-sanitize python3 -m unittest tests.test_control

## The window (package P4)

`doomgeneric_pov.c` (SDL2, no sound, no SDL2_mixer), built with `make -f Makefile.pov` where SDL2 is
installed (the device; `sdl2-compat` works). The engine's objects are listed once in `pov_sources.mk`
for both makefiles; `pov_stdin.c` reads the control input for both platform layers.

- Only `-pov-control`; no keyboard, no mouse, no dialog. App id / window class `com.cosmergon.pov`.
- Without `-iwad` the program takes `freedoom1.wad` and `cosmergon.wad` from the folder it lies in.
- `POV_FPS` steps a second (default 35). A step draws only when a line changed something, once at
  the start, and shows the last picture again when the window is uncovered or resized.
- At the end stderr carries frames, work per frame, the slowest frame and the share spent handing
  the picture to the window system.

### Measured on the device (2026-11-20, 4 cores, 1440 x 900 at 60 Hz, Hyprland 0.56.2, window 640 x 400)

Percent of one core, CPU time from `/proc/<pid>/stat`. The compositor alone, without the window: 4.80
(600 s). Scene: `tools/pov_walk.py` (a third of the squares built on, 8 marauders, camera walking).

| Run | Pictures a second | Program | Compositor | Added by the window |
|---|---|---|---|---|
| 600 s, every step drawn | 35 | 21.65 | 9.52 | 26.4 |
| 45 s, every step drawn | 20 | 12.21 | 7.57 | 15.0 |
| 45 s, every step drawn | 12 | 7.43 | 6.88 | 9.5 |
| 45 s, every step drawn, software renderer | 35 | 23.38 | 9.50 | 28.1 |
| 45 s, drawn on change, writer at 35 lines a second | 35 | 21.26 | 9.52 | 26.0 |
| 45 s, drawn on change, writer at 8 | 8 | 4.45 | 6.24 | 5.9 |
| 45 s, drawn on change, writer at 5 | 5 | 3.31 | 5.69 | 4.2 |

A picture costs about 6 ms, half of it the engine, half the hand-over to the window system; the slowest
of 20,997 pictures took 16.9 ms, 10 took longer than half a step (14.3 ms). The cost is the number of
pictures: that is why a step without a change draws nothing. The dashboard's view steps 5 to 8 times a
second. Tools: `tools/measure_device.sh`, `tools/probe_device.sh`.

## Themes (looks)

A theme is a PWAD made by `tools/make_theme.py` (themes are data in its `THEMES` table): palette, no
dimming with distance, flat wall textures per kind and direction, floors, a sky, and a `POVTHEME` lump
(outline switch, light level, class and rank per colour index). Without a theme nothing changes.

    python3 tools/make_theme.py gelbestadt -o assets/theme-gelbestadt.wad
    doomgeneric/cosmergon-pov-headless -iwad assets/freedoom/freedoom1.wad -file assets/cosmergon.wad \
        -pov-theme assets/theme-gelbestadt.wad -pov-control -warp 1 1 < scene.txt

- `-pov-theme <file>` adds the PWAD after the map; its lumps win. Its own `F_START..F_END` replaces the
  IWAD's flat range (so only the six flats of the theme exist) and its `TEXTURE1`/`PNAMES` replace the
  IWAD's textures; the IWAD's `TEXTURE2` is replaced by an empty one.
- The theme's colours are shown exactly (no gamma table, `pov_gamma_off` in `i_video.c`).
- Outline pass (`pov_control.c`, `outline_pass`): on the finished 8-bit picture (320 x 200, shown at 2 x),
  one pixel in the outline colour where two neighbours are different surfaces, on the side of the lower
  rank (a surface keeps its area). Sky gradient indices are one class: no lines in the sky. Wall pixels
  carry the id of their wall plane (`pov_wall_id`, `r_segs.c`/`r_draw.c`): collinear cell edges are one
  plane, two planes at different distances get a line even where their colour is equal.
- Joints (floor tiles, slab seams, hatches) are drawn into the textures with "twin" colour indices; the
  COLORMAP of the farther light rows maps a twin to its surface colour, so joints vanish with distance
  (see the header of `tools/make_theme.py`; the theme sets the light level of all sectors).
- Kind `own` (row character `O`): a cell of the viewer's own, same height as `cell`.
- Sprites (things) are still the IWAD's and are wrong in a theme's palette: samples show no things.
- Upstream fixes needed by a theme (marked `// cosmergon-pov:`): `p_spec.c` (an animated flat that the
  theme's flat range does not hold made `flattranslation[]` writes land in the zone and corrupt lumps),
  `p_switch.c` (switch textures missing from a theme are skipped).
- Samples: `python3 tools/theme_samples.py` writes `out/muster/` (nine pictures, the comparison and the
  overview). Tests: `python3 -m unittest tests.test_theme`.
