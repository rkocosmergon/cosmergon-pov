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
- `tools/theme_art.py`, `tools/make_theme.py`, `tools/theme_samples.py`: the themes and their samples ("Themes").
- `doomgeneric/pov_sky.c`, `tools/sky_art.py`, `tools/theme_day.py`, `tests/test_sky.py`: the sky with the time of day and
  drifting clouds ("The sky").
- `tests/test_headless.sh`: smoke test.
- `tests/test_size.py`, `tools/measure_size.py`: picture size (package P5, "Picture size" below).
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
| `MAXDRAWSEGS` | r_defs.h:51, check r_segs.c:383 | 256 | 9408 (independent of the picture width) | 4704 lines (2*48*49); of each line's two segs at most one faces the viewer, so at most 4704 stored; factor 2 allows one split per seg (the only solid lines are the 192 border segs) | wall silently dropped (wrong picture) | `I_Error` |
| `MAXVISPLANES` | r_plane.c:45, checks :238 and :374 | 128 | 23424 (independent of the picture width; each plane now holds two 16 bit rows of 1280 entries, 5.1 kB: the array is 120 MB of address space, only the planes in use are touched) | `R_Subsector` finds at most 2 planes per subsector (2*2304) plus `R_CheckPlane` duplicates at most 2 per drawseg (2*9408) | `R_FindPlane`: `I_Error`; `R_CheckPlane` (r_plane.c:306): no check, wrote past the array | `I_Error` in both |
| `MAXOPENINGS` | r_plane.c:52, check :378 | 20480 (`SCREENWIDTH*64`) | 486400 (was 121600 for 320 wide) | a screen column is covered by at most 95 lines (47 + 47 inner + 1 border) x2 for rounding of column borders at shared vertices x2 for the top and bottom clip array copied per drawseg: 380 per column, times the widest picture `POV_MAX_W` 1280 (the bound is per column, so it scales with the width and with nothing else) | checked only at the end of the frame, after writing past the array | `I_Error` before each write (r_segs.c, `POV_NeedOpenings`) |
| `MAXSEGS` (solidsegs) | r_bsp.c:81 | 32 | 642 (was 162) | posts are separated by at least one column: at most `POV_MAX_W/2` = 640, plus 2 sentinels | no check, wrote past the array | `I_Error` (r_bsp.c, insertion) |
| zone memory | i_system.c:58-59 | 6 MiB | 24 MiB (9 until the themes with variants) | 6 MiB upstream plus this map's level data, which stays in the zone: 2.29 MiB (vertexes 19208, segs 516096, subsectors 36864, sectors 294912, lines 413952, sides 221184, nodes 119756, blockmap 27656 + links 18432, reject 663552, line lists 73728 bytes; struct sizes from `sizeof` in this build); a theme with variants adds 64 wall textures of 256 x 256 (a 64 KiB composite and two 34 KiB patches each, 8.5 MiB) and 52 flats of 64 KiB (3.4 MiB), purgeable but kept while in view | `Z_Malloc` ends in `I_Error` | unchanged (`I_Error`); `MIN_RAM` = `DEFAULT_RAM`, so a failed allocation says so |
| `MAXVISSPRITES` | r_things.h:25, r_things.c:322 | 128 | 256 | one vissprite per thing in view; the control channel (P3) has at most 256 things (ids 0..255), the player is never linked into a sector | extra sprites dropped (quietly) | `I_Error` |
| `MAXSPECIALCROSS`, `MAXINTERCEPTS` | p_local.h:155,219 | | | no special lines, no shooting, no input | | not reachable |
| `short` blockmap offsets | p_setup.c:84 (signed) | 32767 | | the lump has 13828 shorts; the generator refuses more than 32767 | | generator error |
| fixed-point distance | r_main.c `SlopeDiv` (`num<<3` in 32 bits) | | | deltas must stay below 8192 units; the map is 6144 wide | | not reachable |

High water of the worst measured views (`tests/test_map_render.sh`, 70 frames each): drawsegs 4474 (checker,
corner view over the diagonal), visplanes 1152 (same), openings 20593 (same; the old 20480 is too small by
113), solidsegs 3. Memory in use after 700 frames: 3.3 MB non-purgeable of 9 MiB. At the widest picture
(1280 x 800, both parities of the checker field, six views, `tests/test_size.py`): drawsegs 4582 of 9408,
visplanes 1152 of 23424, openings 83635 of 486400, solidsegs 3 of 642 (the openings grow with the width,
65 per column against the bound of 380).

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
| `size <w> <h>` | picture size in points for the next frames, shown 1 : 1 (see "Picture size") | w integer 160..1280, h integer 100..800 |
| `daytime <minutes>` | time of day in the sender's local time, minutes since midnight; only a theme with a sky reacts ("The sky"); default 720 (noon) | integer 0..1439 |
| `clouds <seconds>` | the cloud clock: where the clouds are, seconds since their start position; only a theme with a sky reacts | integer 0..10,000,000 |
| `origin <x> <y>` | world coordinates of cell 0, 0 of the window (default 0 0); the look of a cell follows its world position (see "Themes"). The cell lines keep using window coordinates | x, y integers within +-1,000,000 |
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
A frame is 768 kB (3 MB at 1280 x 800): a run with thousands of frames needs `POV_EVERY` or `POV_FRAMES`. On 2026-11-20 two
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
- The picture has the size of the window, one point a pixel, and follows a resize ("Picture size").

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
- Outline pass (`pov_control.c`, `outline_pass`): on the finished 8-bit picture (its own size, one point a
  pixel; at the default 320 x 200 shown at 2 x), one point in the outline colour where two neighbours are different surfaces, on the side of the lower
  rank (a surface keeps its area). Sky gradient indices are one class: no lines in the sky. Wall pixels
  carry the id of their wall plane (`pov_wall_id`, `r_segs.c`/`r_draw.c`): collinear cell edges are one
  plane, two planes at different distances get a line even where their colour is equal.
- **Surfaces with life (package P6).** Every kind has several looks and the floor too; the pictures are drawn by
  `tools/theme_art.py` (standard library, deterministic, nothing outside) and are the same in every theme (made of
  palette indices; the theme only gives them colours). A wall texture is 256 x 256 texels over a cell edge of 128
  units, a floor flat 256 x 256 over one cell: two texels to the unit (`pov_tex_dshift`, `pov_flat_dshift`, lump `POVX`).
  - Variants: cell sides 10, own sides 8, wall sides 8, tower sides 6 (each in the east/west and the north/south
    shade), ground 8 interiors x 4 edge states (a joint on the west edge, on the south edge, both, none), tops of
    cell 6, own 4, wall 5, tower 4. A kind lists 16 weighted slots (`POVX`): the calm looks occur twice, the dense ones
    once, so most faces are quiet and a few are nests.
  - Choice: hash of the WORLD position of the cell (`origin` + window coordinates), the kind and the side
    (`cell_hash`, murmur3 finaliser, `pov_control.c`): the four sides of a block may differ. An edge of the ground
    has a joint or not by the hash of the edge, whichever cell is next to it. `origin <x> <y>` moves the world
    position of the window (the SDK shifts the window by whole cells and sends the lines again): the looks of all
    cells are assigned again; a cell keeps its look wherever it lies in the window (`tests.test_theme.Variants`).
  - Forms (second channel for colour blindness): cell = machine/building block (plate joints, tinted plates, rivets,
    vents, hatch, porthole, window rows, pipes, ducts, ladders, labels, hazard marks, lamps, dials, spalls, stains);
    own = the same family in the accent colour with a framed plate and a diamond in every variant, on the top too;
    wall = ashlar blocks in two or three courses under a coping band (slits, gratings, plaques); tower = a shaft
    with a cornice, bands in their own colour, slits and a framed double door at the foot (the lowest 19 units show
    the top rows of the texture again: a plinth). Ground = plates (tinted, a few light), joints, covers, hatches,
    gutters, cracks, stains, scraps of paper, rubble.
  - Colours: a role has at most three stages (surface, shade, fleck) plus navy for the lines; no grey, no gradient.
    A fleck is an index of the same outline class as its surface: no outline around it (`theme_lump`).
  - Lines are navy twin indices of the colour they lie on, three kinds, each folds into the surface in the COLORMAP
    (`FOLD_Q` in `make_theme.py`; a row is about 1280 / distance below the start row): the core line (one texel, half a
    unit) is drawn up to 128 units on the floor and 320 on walls; the halo (a second texel) is navy only between 80
    and 128 units (floor) and 160 and 320 (walls), so far away the coarse lines are two texels (one unit) and keep
    about the weight of the outline; fine things (rivets, scraps, cracks) fold at 80 and 160 units. Small flecks
    (small stains, scraps) use a second index that the COLORMAP maps to the surface from 128 (floor) and 320
    (walls) units on, so that no speck flickers when the camera moves.
  - Why 2 texels to the unit: measured at 672 x 324 a unit is 2.62 points at 128 units, 1.30 at 256; at 1280 x 640 it
    is 4.99 and 2.49 (`out/muster-detail`, see the report in the commit message). One texel a unit made a detail
    line 2.6 points thick near a block at 672 wide (the outline is 1 point); two texels give 1.3, and 2.5 points at
    1280 (outline 2). Four would be below a point from 128 units on at 672 and cost four times the memory.
  - Engine: `R_DrawColumnTall` (rows masked with 255) for walls, `R_DrawSpanFine` takes the flat geometry from
    `pov_flat_bits` / `pov_flat_dshift`; `r_segs.c` scales the texture column, the row start and the step by
    `pov_tex_dshift`. Without a theme, or with a theme without `POVX`, nothing changes (hashes of the pictures of
    `81fb3a0` are a test).
- Kind `own` (row character `O`): a cell of the viewer's own, same height as `cell`.
- Sprites (things) are still the IWAD's and are wrong in a theme's palette: samples show no things.
- Upstream fixes needed by a theme (marked `// cosmergon-pov:`): `p_spec.c` (an animated flat that the
  theme's flat range does not hold made `flattranslation[]` writes land in the zone and corrupt lumps),
  `p_switch.c` (switch textures missing from a theme are skipped).
- Samples: `python3 tools/theme_samples.py` writes `out/muster/` (nine pictures, the comparison and the
  overview); `--size 672x324` the same in that size with the size in every file name, `--fine` writes
  672 x 324 and 1280 x 640 to `out/muster-fein/`, `--detail` writes `out/muster-detail/` (six viewpoints in A and B,
  both sizes, the overview of A/B/C and the texture sheets). Tests: `python3 -m unittest tests.test_theme`.

## The sky (package P7)

A theme with the lumps `POVSKY` and `POVCLD` draws its own sky, point by point in the size of the picture
(`pov_sky.c`, called from `R_DrawPlanes`, in place of the texture column). Without them (no theme, or an older
theme) the sky is the IWAD's or the theme's texture as before; without a theme nothing changes (the hashes of
`81fb3a0` and `a38a6b4` are a test).

### Why not a bigger texture
The old sky was a 1024 x 128 texture, 256 texels across the 90 degrees: at 1280 wide 5 points a texel across but
3.2 down (and 1.6 : 1.0 at 672 x 324): the sun was an ellipse (measured, `a38a6b4`, bounding box of the sun's
points: 119 x 83 at 672 x 324, 226 x 166 at 1280 x 640, 56 x 57 at 320 x 200, 226 x 228 at 1280 x 800) and its edge
showed texel steps. A bigger texture would only move the ratio. Root: a point looks along `(u, v, 1)` with
`u, v` in units of `f = width / 2`; azimuth is `viewangle + xtoviewangle[x]`, `tan(elevation) = v / sqrt(1 + u^2)`.
Rows and columns step alike, so a disc is round at every shape, and nothing depends on a texture's resolution.

### Layers (back to front)
1. **Bands** of elevation, 16 flat colours of 3.0 degrees (`POVSKY`: palette index of band 0 at the horizon,
   count, degrees): the calm stepped gradient. No outline between them (one class).
2. **Stars** (night only, `stars` flag of the keys): bit 4 of the cloud layer, fixed to the world, 3 x 3 texels
   (at least one point at 672 wide, where a point is 1.9 texels: 3 >= ceil(1.9)); colour index in the sky class
   (no outline).
3. **Sun** (06:00 to 19:00) or **moon** (19:00 to 06:00): a disc of angular radius 4.5 / 3.6 degrees, centre
   `(cx - f tan(d), cy - f tan(el) / cos(d))` for the azimuth difference `d` to the view (hidden at 85 degrees or
   more), radius `f tan(r)` points. The arc is simple, not astronomy: elevation `21 sin(pi p)` degrees (`p` the
   share of the arc), azimuth 0 (east) at the rise through 270 (south) to 180 (west) at the set; the same arc for
   the moon. 21 degrees because the picture has no pitch: its half angle is 25.7 degrees at 672 x 324 (26.6 at
   1280 x 640, 32 at 1280 x 800), a higher body would never be seen. The sky is bound to the WORLD: the sun is in
   one direction only. The moon is a crescent (the disc less a disc up and to the right).
   The border wall of the window (512 units, 24 cells away from the middle) hides everything under about 8.7
   degrees: the sun is above it only from about 07:45 to 17:15 and the moon from about 20:30 to 04:30 (computed from the
   arc: the sun is hidden at 06:00, 18:30 and the moon at 20:00; the samples show sky colours there, not the body).
4. **Clouds**: layer `POVCLD`, 4096 columns around the circle (angle >> 20) by 512 rows of `tan(elevation) * 651.9`
   (a column of rows is walked with a fixed-point step per point, as a wall column), one byte a texel: 1 fill, 2
   shade tone on the lower right edge, +16 star. Comic clouds (`tools/sky_art.py`: round bumps over a flat base, flatter
   near the horizon, bigger higher up, in clusters and strays, 26 of them, same for every theme). Density: 651.9
   texels a radian against `f` points a radian: 1.02 texels a point at the middle of 1280 wide (0.51 at 45
   degrees off the middle, where the projection stretches: 2 points a texel), 1.94 at 672, 4.1 at 320.
   The outline (1 point, 2 from 901 wide) is drawn by the outline pass on the finished picture, so the line has
   the weight of every other line and no texel steps. Classes (`POVTHEME`): bands and stars 0, sun and moon 5, clouds
   6: the pass puts the line on the lower class, outside a disc and outside a cloud, and where a cloud covers the sun
   the line is on the sun's side. Nothing is doubled (looked at: a cloud across the sun at 672 and 1280 wide).

### Clouds drift without load
Rate: 0.25 degrees a second (one turn of the circle in 24 minutes; across the 90 degrees of the picture in 6
minutes), "one notices it when looking": 0.70 points a second at 320 wide, 1.47 at 672, 2.79 at 1280. The clouds
move in WHOLE POINTS (`POV_SkyDriftPoints = floor(columns * 2 pi f / 4096)`; the texture offset is the points
turned back into columns, so the picture is a function of the points); live mode draws only when that number changed:
**1.5 pictures a second at 672 wide, 2.8 at 1280 wide, 0.7 at 320** (measured live, 5 s: tests.test_sky.Live), at
4 to 16 ms a picture (see Measured below): a few tenths of a percent of a core. The clock is deterministic:
- blocking mode (headless, tests): the clouds stand where the last `clouds <seconds>` line put them (default 0);
  the picture depends only on the input;
- live mode: that base plus the engine's clock (`I_GetTimeMS`, a window: real time, the headless live mode: a tick
  of `POV_LIVE_MS` virtual milliseconds).

### The time of day (the bridge's part)
The program has no clock and no time zone knowledge. The sender (the SDK's bridge) sends **`daytime <minutes>`** with
the local time it chose (default Europe/Berlin, the user may choose another zone), minutes since midnight 0..1439.
**Once a minute is enough** (and once at the start); the palette is mixed for that minute. Optionally `clouds
<seconds>` at the start. Without the line the time is 720 (noon, the day palette). A line that is not an integer in
range is rejected like any bad line.

Way: **one palette per key of the day in `PLAYPAL`** (Doom's own mechanism, `I_SetPalette`) **and an integer mix of the
two keys around the minute** in the engine (`POV_SkyPalette`, `tools/theme_day.palette_at` is the same arithmetic;
a test compares the two against the picture). Keys (minutes): 0, 270 night; 360 dawn; 450 morning; 600 and 960 day;
1080 evening; 1130 sunset; 1200 dusk; 1275 and 1440 night: 11 palettes, 8.4 kB. Why this and not one palette per
minute: 1440 palettes would be 1.1 MB a theme for the same result; and not 14 fixed palettes: a step of 14 sections
shows. How many steps: the largest change of one colour channel between two minutes is 3 of 255 levels (dusk, the
fastest) in each of the three themes, 1 to 2 in most of the day (`tests.test_sky`, bound 4); the sender's rate (a
minute) is the limit, a faster sender would need no more palettes (the mix has 256 steps per segment).
Whether 3 levels a minute are visible to the eye is not tested (only looked at: not noticeable in a sheet).

The light of a section (`tools/theme_day.py`): the world's colours are multiplied (night 0.68 / 0.78 / 1.0 with a
bluish haze of 14 percent, dusk violet, sunset and dawn warm, morning and evening slightly warm, day 1), the sky
bands, the sun, the clouds and the moon change colour. The roles (ground, border, cell, own, wall, tower) keep
their character: a multiply keeps ratios, hues stay apart. The night is blue and bright, not dark: the mean Lab
lightness of the six roles is 58 of 77 at noon (wueste), the stars and the moon are light on a mid blue.

**Contrast, derived not set** (`tests.test_sky.Palette`, every minute, three themes): the difference of two
colours (RGB) is multiplied per channel by `(1 - haze) * mul`, so its length falls to at most the smallest such
factor times the day's; the bound is the DAY state's weakest pair of the six roles times the weaker factor of the
two keys around the minute, less sqrt(3) for the rounding to whole values. Measured RGB distance of the weakest
pair: day 51.0 (wueste), 37.9 (gelbestadt), 33.9 (blaustadt); lowest over the day 40.1, 28.8, 22.9. Lab (dE76)
of the weakest pair on the hour: 12.9 to 16.7 (A), 9.2 to 11.9 (B), 4.8 to 7.4 (C: ground and tower are pale
blue-grey at night, 4.8; the theme C was weak in the day too, 7.2).

### Samples
    python3 tools/theme_samples.py --sky      # out/muster-himmel/: A and B, 672x324 and 1280x640

`tageslauf-<A|B>-<size>.png` (06:00 08:00 12:00 16:00 18:30 20:00 23:00 03:00, the view towards the sun or moon,
labelled), `rundblick-...` (four directions at 16:00), `wolkenzug-...` (five pictures 10 s apart), and every
picture of the day alone (`einzel-...-<hhmm>.png`). The scene is a sparse field around the eye (24.5, 24.5).
`theme_samples.berlin_minutes()` gives the Berlin minutes for a tool that wants "now" (the program does not).

### Measured (`tools/measure_size.py`, as above; and an empty field with a wall, the camera turning, sky-heavy)
ms a picture, 400 pictures, 3 runs, before (`a38a6b4`) / after:

| Size | Scene | Mean before | Mean after | Slowest before | Slowest after |
|---|---|---|---|---|---|
| 672 x 324 | wueste, the usual scene | 4.10 | 4.19 | 11.61 | 7.26 |
| 1280 x 800 | wueste, the usual scene | 16.47 | 15.80 | 112.46 | 22.95 |
| 672 x 324 | wueste, sky-heavy | 3.65 | 3.86 | 6.71 | 7.00 |
| 1280 x 800 | wueste, sky-heavy | 14.68 | 15.19 | 18.87 | 25.39 |

(the slowest values are single outliers of this machine and differ between runs; the means are the measure.) Without
a theme nothing changed (0.54 / 1.12 / 4.38). Memory at 1280 x 800: 34.7 MB resident against 31.7 (the 2 MB cloud
layer and the 11 palettes), the zone has 19.3 MB free of 24.

### Tests
    python3 -m unittest tests.test_sky     # the lines, no theme = no change, the sun round in four shapes,
                                           # drift only in sky points, every palette at 25 times of the day,
                                           # contrast bound, step of a minute, live drift, outline
(sanitizer: as above; the known upstream class of `r_plane.c` in `tests/test_control.py` moved with the lines.)

## Picture size (package P5)

The renderer draws in the size of the window, one point a pixel, square points, from 160 x 100 up to
1280 x 800. Without a choice nothing changes: 320 x 200, shown 2 x as 640 x 400, byte for byte the old
pictures (checked against the previous build for the three themes and none, with and without things, 7
views: identical hashes).

    doomgeneric/cosmergon-pov-headless ... -pov-control -pov-size 672x324   # fixed at the start
    size 672 324                                                            # a control line, any time
    # the window build (doomgeneric_pov.c) takes the size of its window at the start and after every resize

- **Way:** the arrays of the renderer and `I_VideoBuffer` are sized for 1280 x 800 (`POV_MAX_W/H`, i_video.h);
  the picture is `pov_view_w x pov_view_h`, tightly packed at the start of the buffer, its row distance
  is the run time variable `pov_stride` (= its width with `-pov-control`, 320 otherwise; r_draw.c,
  `R_InitBuffer`). `R_ExecuteSetViewSize` (the way Doom changes its view size) rebuilds the tables on a
  change, in the next frame. Doom's own user interface keeps `SCREENWIDTH` x `SCREENHEIGHT` = 320 x 200
  (not reached with `-pov-control`; without the switch the old demo mode runs as before). No memory is
  asked for per frame: everything is static, sized for the maximum.
- **Limits of the size:** 160 x 100 .. 1280 x 800. Upper: the arrays and 1 MB of buffer, the highest
  numbers in the fixed-point arithmetic (below) and 3 MB for a picture; 1280 x 800 is what the device's
  window can reach with room to spare and keeps the angle table (8192 fine angles, 2048 across the 90
  degrees) at about one fine angle per point at the picture's edge: wider would be coarser than a point.
  Lower: 160 x 100 is half of Doom's own, the smallest picture in which a cell is still a block.
  A size outside is rejected: a `size` line like any bad line (counted, nothing changes), `-pov-size`
  stops the program with a message, the window does not follow it (says so once on stderr, counts, and
  SDL stretches the last picture).
- **Shape and angle:** the horizontal angle stays 90 degrees (`FIELDOFVIEW`), the vertical one is what the
  shape gives. Doom's projection already uses one scale for both directions (`FixedMul(world, rw_scale)`
  and `centerxfrac`), so the points are square; there is no 1.2 factor in the renderer (it lived only in
  the CRT's screen). `tests/test_size.py` measures it: a cell of 128 x 128 x 128 units seen straight on
  from 256 and 384 units has the same width and height in points (within 2) in 7 shapes (672 x 324,
  1280 x 640, 1280 x 800, 200 x 800, 160 x 100, 320 x 200, 900 x 300) and the expected position (eye line
  at row h / 2). An odd width is covered to its last column (`centerxfrac` is half the width in 16.16;
  upstream cut it to a whole number and left the last column undrawn: found by comparing a size change
  against a fresh run). An odd height puts the horizon half a point above the middle.
- **What follows the size in the renderer** (every change marked `// cosmergon-pov:` and equal to upstream
  at 320 x 200):
  - visplane rows are 16 bit (`top`/`bottom`, empty = `POV_VP_EMPTY` 0xffff; upstream byte, 0..254, too
    small for 800 rows);
  - the largest scale of a wall (upstream 64 points a unit) and the nearest thing (upstream 4 units)
    scale with `viewwidth / 320` (`pov_max_wall_scale`, `pov_minz`), so the fixed-point numbers derived from
    a scale (tops and bottoms, texture steps, a sprite's top) stay in the range they have at 320;
  - the light: a wall's or thing's light index uses the scale normalised to 320 (`R_LightIndex`), the
    floor's light uses 320 / 2 in `R_InitLightTables`: light by distance, whatever the size;
  - the sky (**without a theme**; with a theme the sky is drawn per point, see "The sky" below and ignore the
    sun remarks here, which are SUPERSEDED by it): its 100 rows above the horizon always cover the upper half of the picture
    (`pov_sky_iscale` = 200 / viewheight texels a row; upstream `pspriteiscale` follows the width, and in
    a tall picture the sky would run out and tile). The sky texture is 1024 x 128 and is enlarged by the
    picture: the sun is an ellipse of width : height = (w / 256) : (h / 200), 1.25 at 1280 x 800 and 1.6 at
    672 x 324, and its edge shows the steps of the texture;
  - spans wider than 320 points use `R_DrawSpanFine` (full 16.16 position): the old 6.10 bit step is
    cut to 1/1024 texel, which over 1280 points drifts a texel or more (about 12 points of a floor joint at
    the bottom edge);
  - range checks of the column and span drawers are against the picture, not the buffer.
- **Outline:** 1 point from 160 to 900 wide, 2 points above (`POV_OUTLINE_WIDE_FROM` 901): looked at in
  `out/muster-fein`, 1 point is delicate at 1280 (0.16 percent of the height) and the same weight as the
  old line at 672 x 324 (0.31 percent); 2 points at 1280 x 640 have it. The second point grows into the
  surface the first one lies in (same class), so the line stays outside the faces.
- **Themes:** (the numbers below are from before package P6; for the lines of the variants see "Themes")
  joints are 1 texel; they vanish at 1280 / (q + 1) units (`FOLD_Q`: floor 7 = 160 units, walls
  3 = 320). A 1 texel line across the view (a floor joint) is thinner than one row beyond
  sqrt(eye height * w / 2) units (41 units: 117 at 672 wide); beyond that it breaks into dashes
  (looked at: fold 213 shows dashes at 672, 160 is clean). Wall seams are wider than a point up to
  w / 2 units. With the old 2 texel joints at 320 and a theme made by this generator, the joints are
  thin there; the default size without a theme is unchanged.

### Measured (`python3 tools/measure_size.py`, 400 pictures, 3 runs, this machine, ms per picture
without writing it: control lines, renderer, outline, conversion to RGB)

| Size | Theme | Mean | Slowest | Mean before P6 | Slowest before P6 |
|---|---|---|---|---|---|
| 320 x 200 (default, shown 640 x 400) | none | 0.55 | 2.44 | 0.54 | 2.41 |
| 320 x 200 | wueste | 1.78 | 4.41 | 1.13 | 3.17 |
| 672 x 324 | none | 1.12 | 3.02 | 1.10 | 2.79 |
| 672 x 324 | wueste | 4.03 | 7.49 | 3.01 | 5.85 |
| 1280 x 800 | none | 4.41 | 8.39 | 4.44 | 7.48 |
| 1280 x 800 | wueste | 15.47 | 25.06 | 13.69 | 23.59 |

(Re-measured 2026-11-21 with the scene of before, `scene(rich=False)`, `tools/measure_size.py`; the themed pictures cost
more by the 256 texel textures and the span drawer's wider flats; without a theme the fast span loop of before is
kept, `R_DrawSpanFine`.)

The step at 35 a second is 28.6 ms. Memory: 134 MB of address space (the visplane array), 22 MB resident
at 1280 x 800.

### Tests

    python3 -m unittest tests.test_size      # option, `size` line, aspect, limits at 1280 x 800, loud overflow
    POV_SANITIZED=1 POV_BIN=$PWD/doomgeneric/cosmergon-pov-headless-sanitize python3 -m unittest tests.test_size

The window build is not tested here (SDL2 was not installed; the file passes `gcc -fsyntax-only` against a
stub of the SDL2 declarations it uses and has not run).
