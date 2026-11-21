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
- `doomgeneric/pov_sky.c`, `tools/sky_art.py`, `tools/theme_day.py`, `tools/sky_samples.py`, `tests/test_sky.py`,
  `tests/test_world.py`: the sky as a place in the world: time of day, clouds with depth, neighbour cubes, haze ("The sky").
- `tools/measure_ink.py`, `tools/measure_far.py`, `tests/test_ink.py`: stroke thickness, reach of the floor strokes and the
  calm of the far floor ("Themes").
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
| `clouds <seconds>` | the world time of the clouds; only a theme with a sky reacts | integer 0..10,000,000 |
| `world <cube_x> <cube_y> <cube_z> <level> <dim>`, `cube <id> <cube_x> <cube_y> <cube_z> <dim>`, `nocube <id>` | where the field lies in the world and the neighbour cubes ("The sky") | see there |
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
    vents, hatch, porthole, window rows, pipes, ducts, ladders, labels, hazard marks, lamps, dials, hatched recesses,
    rails, grilles, spalls, stains);
    own = the same family in the accent colour with a framed plate and a diamond in every variant, on the top too;
    wall = ashlar blocks in two or three courses under a coping band (slits, gratings, plaques); tower = a shaft
    with a cornice, plate courses with staggered joints, window rows with sills, bands in their own colour, a pipe or
    ladder and a framed double door at the foot (the lowest 19 units show the top rows of the texture again: a
    plinth). Ground = plates (tinted, a few light), wide joints (some through the whole cell), covers, hatches,
    channels, hatching along a joint, cracks, stains, and litter with a contour (paper, crates, cans, rubble).
  - Colours: a role has at most three stages (surface, shade, fleck) plus navy for the lines; no grey, no gradient.
    A fleck is an index of the same outline class as its surface: no outline around it (`theme_lump`). The tower has a
    strong colour of its own (violet, bands in yellow); the own cell keeps its framed diamond.
  - Strokes are navy twin indices of the colour they lie on, three widths drawn into the texture: fine (1 texel), core
    (2 texels, medium things: vents, frames of small parts) and wide (4 texels = 2 units: joints between plates, frames
    of windows and doors, courses). Each folds into the surface in the COLORMAP (`FOLD_Q` in `make_theme.py`; a row is
    about 1280 / distance below the start row): fine 80 units (floor) / 160 (walls), core 128 / 320, wide 640 / 640.
    Small flecks (small stains, scraps, window panes) use a second index that the COLORMAP maps to the surface from 128
    (floor) and 320 (walls) units on, so that no speck flickers when the camera moves. The tints of the ground
    (`I_GROUND_SHADE`, `I_GROUND_LIGHT`) fold into the ground from 427 units (`FAR_Q`): far away the floor is one calm
    plane, only big plates keep their tint to there (a tint on a plate under 100 texels uses the small index).
  - **Thin lines near, long lines far (the thinning pass).** A texel is up to 5 points near a block, so a stroke
    drawn into the texture would be thicker than the outline (measured before: median 2 / 2 / 2 points at 672 wide and
    5 / 3 / 3 at 1280 at 64 / 128 / 256 units, `tools/measure_ink.py`). `ink_pass` (`pov_control.c`, lump `POVINK`)
    runs on the finished picture before the outline pass and keeps of every stroke only the width of the outline (1
    point, 2 from 901 wide): the top rows of a horizontal stroke, the left columns of an upright or slanted one, both
    where strokes cross; the other points are set back to the colour under the stroke (`POVINK` lists, per stroke
    index, that colour). After: median and 99th percentile 1 point at 672 and 2 at 1280 at every distance. Because
    the width in the picture no longer decides the weight, a stroke can be drawn wide, and a wide stroke is a line that
    stays about a point wide to 640 units. Floor strokes that run across the view and are no thicker than the outline
    are dropped whole (a joint across the view is thinner than a point row beyond about 115 units: it would come and go
    with every step of the camera); so are single specks. Only strokes that run into the depth reach far (1559 floor
    stroke points between 150 and 400 units over three viewpoints at 672 x 324, before: none). A theme without `POVINK`
    draws as before.
  - Why 2 texels to the unit: measured at 672 x 324 a unit is 2.62 points at 128 units, 1.30 at 256; at 1280 x 640 it
    is 4.99 and 2.49. One texel a unit would make a wide stroke thinner than a point from 128 units on at 672. The
    joints on a cell edge of the ground are decided by `ground_edges` (`pov_control.c`): a joint runs along a line of
    cells (four share the decision) and a zone of 4 x 4 cells says how many lines it has: calm zones and dense ones.
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
  both sizes, the overview of A/B/C and the texture sheets). Tests: `python3 -m unittest tests.test_theme tests.test_ink`.

## The sky (package P7)

A theme with the lumps `POVSKY`, `POVWLD`, `POVCLS`, `POVSTR` draws its own sky, point by point in the size of the
picture (`pov_sky.c`, called from `R_DrawPlanes`, in place of the texture column). Without them (no theme, or an older
theme) the sky is the IWAD's or the theme's texture as before; without a theme nothing changes (the hashes of
`81fb3a0`, `a38a6b4` and `7b88364` are a test).

### Why not a bigger texture, and why not an angle layer
The first sky was a 1024 x 128 texture (the sun an ellipse: 119 x 83 points at 672 x 324, 226 x 166 at 1280 x 640 at
`a38a6b4`). The second one painted clouds into a layer of (azimuth, tan elevation) and projected it flat: the flat
base of a cloud leaned towards the edge of the picture and all clouds looked equally far ("they tip to the middle").
Now every cloud is a body at a place in the world and the picture is a perspective of that world.
A point of the picture looks along `(u, v, 1)` with `u, v` in units of `f = width / 2`; azimuth is
`viewangle + xtoviewangle[x]`, `tan(elevation) = v / sqrt(1 + u^2)`. Rows and columns step alike: a disc is round at every
shape, and nothing depends on a texture's resolution.

### The world the field lies in
A cell is a cube of 4 m (128 units, 32 units a metre). A field is one plane of a cube; a cube has N x N x N cells (the
main world N = 128: 512 m a side, 128 fields). The cubes of a room stand at whole grid positions `(cube_x, cube_y, cube_z)`
with a gap: one grid step is 2.5 cube widths (1.5 widths of air; 1280 m for N = 128). All cubes share ONE sky.

New control lines (all checked like every line; without a theme with a sky they change nothing):

| Line | Meaning | Limits |
|---|---|---|
| `world <cube_x> <cube_y> <cube_z> <level> <dim>` | where the field lies: the grid position of its cube, the level of the field in the cube, the cube's dimension in cells. Default `0 0 0 0 128` | positions integers within +-10,000; dim 8..1024; level 0..dim-1 |
| `cube <id> <cube_x> <cube_y> <cube_z> <dim>` | a neighbour cube at its grid position (places or moves it) | id 0..63, as above |
| `nocube <id>` | removes a neighbour cube (unknown id: nothing happens) | id 0..63 |
| `clouds <seconds>` | the WORLD TIME of the clouds (they move with the wind in the world) | 0..10,000,000 |
| `daytime <minutes>` | time of day, see below | 0..1439 |

The camera's place in the world is `world` + `origin` + `cam`: `x = cube_x * step + (origin_x + cam_x) * 128`, same for y,
`z = cube_z * step + level * 128 + eye height` (step = 2.5 * dim * 128 units; `origin` is the field coordinate of the
window's cell 0, 0 in cells; the eye is `viewz`). Two programs with the same world time at other places see the same sky
from their places (a test: cube (1,0,0) with `origin 0` is cube (0,0,0) with `origin 320`, 320 cells = one step: the sky
above the border wall is identical, point for point). `cube` lines are one line each, so a change is atomic; a bridge
sends the neighbours it knows once (up to 64) and `nocube` for those that go. The bridge sends `world` once and again when
the field's level changes, `clouds` once at the start (the world time; live mode adds the engine clock).

### Clouds (lumps `POVWLD`, `POVCLS`)
Upright bodies turned to the viewer at world positions `(x, y, height of the base)` on a periodic tile of 16 km (the nearest
image is taken, so the sky is the same everywhere); 220 clouds in four layers of base height 450, 650, 900 and 1250 m (+-50) above
the lowest cube, 65 percent of them clustered (sigma 1.8 km) over the middle where the cubes stand, the rest all round; width
250..650 m times 1.0 to 1.9 by layer, no two of a layer overlapping. The perspective is the planar one: size in points
`f * width / depth` (depth = distance along the view), centre `cx + f * lateral / depth`, base row
`cy - f * (height - eye height) / depth`. The lower edge is a row of the picture at every place and angle. A cloud is a
picture (sprite) of 1024 x 320 texels with three smaller copies (512, 256, 128 wide, every second column and row), picked
so that a texel is not smaller than a point; 8 shapes (5 with 6 to 9 bumps for the big ones, 3 with 3 or 4 for those under
330 m wide: calm silhouettes for the small, far ones), flat fill, one shade tone on the lower right edge. A cloud nearer than its width
would be wider than 1500 points (a texel of 1.5 points: no steps at 1280) is not drawn. The wind is the same for every
cloud, 4 m/s to the east, in the WORLD: near clouds cross the picture faster than far ones (the parallax is the geometry).
The outline is drawn by the outline pass (1 point, 2 from 901 wide); clouds and cubes are rank 0 (the line is on their
own side, in the haze colour of their distance, see below), the sky rank 1.
Depth: every sky point has a depth (a float row per column): a cloud and a cube are drawn in any order and the nearer
wins, so clouds pass in front of a cube and disappear behind it; the sun, moon and stars are behind everything.
Limit (not smoothed): a cloud closer than the width limit pops in and out. From the low levels this is out of the picture (the
lowest layer is 400 m or more over the eye, over 40 degrees at 400 m); for an eye as high as the cloud layers (levels above
about 100 look at the lowest layer from the side) a passing cloud can pop at the sides of the picture.

### Neighbour cubes
A box at its place (corner at `cube * step`, edge `dim * 128` units), drawn per column: the horizontal ray against the
footprint gives the face it enters through (x: tone 1, y: tone 2) and its distance, the vertical extent follows from the
heights `(z - eye) / distance`. Only what is above the horizon is drawn (the floor of the field is below it), so the top
face is never seen, the underside is (a cube above the eye). Level lines: a power of two of horizontal lines on the face,
as many as stay 12 points apart (a face at 1000 m on a 512 m cube: 16 levels at 1280 wide, 8 at 672; none when they would be closer than that),
drawn as the darker tone of the same face (no extra outline). Perspective: a 512 m cube whose face is 1020 m away is 28
degrees wide and (from level 0) reaches the top of the picture (26.6 degrees), a test compares edges and top with the corners (within 3 points at
320, 672 and 1280 wide). The border wall of the window (512 units, 24 cells from the middle: about 8.7 degrees) hides the lower
part; the higher the level, the less is left: from level 60 (240 m) a neighbour rises 14.9 degrees, so about 6 degrees over the wall;
from level 115 (460 m) nothing shows over the wall. The samples show levels 5, 60 and 115.

### Haze ("Luftperspektive", not fog)
Style limit (less glow and fog, more surface): no soft volumes, no gradient, no blur. Flat
steps towards the colour of the horizon, lines get lighter, near things stay as they are. The theme has one value, `fog`:
0 off, 1 light (the default), 2 clear (the samples `dunst-*` show all three).
- **The field** (ground, walls, tops, bands, the border wall): three steps by distance through the COLORMAP rows
  `row_s - 1`, `row_s` and `row_s + 1` (`row_s` the start row of the surface's orientation): from 640, 1280 and 3000 units
  (the strokes are folded before 640 units, so no stroke has a haze colour). Share towards the horizon colour: 0.12, 0.26, 0.42
  times `fog` (at most 0.95). The rows beyond `row_s` are new: upstream's light tables end at 2048 units, so for a
  theme `MAXLIGHTZ` is 256 and a flat beyond `POVFOG` distance (3000) and a wall whose normalised scale is below 160 * 65536 / 3000
  take the next row (`pov_fog_j`, `R_FogRow`, `r_main.c`, `r_segs.c`); the entries that existed keep their level (80 / (j + 1)
  is 0 from j = 80 on), so without a theme the pictures are byte for byte the old ones. A surface and its fleck stage share one
  hazed index (a face's second tone is gone far away, like the ground tints), 16 groups x 3 steps = 48 palette indices
  (`theme_art.FOG_GROUPS`). The border wall (one texture for four sides, so no orientation) is always at the last step, the
  far horizon.
- **Lines** (`POVFOG`: per colour index the index of a line drawn on it): a line on a hazed point is a hazed navy (six
  steps, 0.15 .. 0.85), so lines get lighter, not thicker. The lines of clouds and cubes follow the haze of their distance.
- **Clouds and cubes** by their distance in metres: clouds at 1800, 3200, 5000 (shares 0, 0.3, 0.5, 0.7), cubes at 1000, 2000,
  3500 (0.45, 0.6, 0.72, 0.85: the nearest cube is already 1020 m away): they stand pale in the haze.
- The haze colour is the sky's horizon colour of the time of day (it is part of each key palette).
- **Contrast, derived** (`tests.test_world.Haze`): the roles of a step are the roles mixed with the same horizon colour by the
  same share, so the difference of two is `(1 - share)` times the difference at step 0; the bound at each of the 11 key
  palettes and each step is the day's weakest pair times the section's light factor times `(1 - share)`, less sqrt(3); for
  `fog` 1 and 2 in all three themes.
Palette budget: 172..251 of 256 (48 field, 6 clouds, 6 hazed navies, 20 cubes).

### The sky's own layers (back to front)
Bands (16 flat colours of 3 degrees), stars (240, fixed to the world, 1 to 2 points, only at night), the sun (06:00 to 19:00) or the
moon (19:00 to 06:00, a crescent); then cubes and clouds with depth. Sun and moon: a disc of angular radius 4.5 / 3.6 degrees
at `(cx - f tan(d), cy - f tan(el) / cos(d))`, radius `f tan(r)` points, round at every shape (320 x 200, 672 x 324, 1280 x 640,
1280 x 800 are a test); the arc is simple, not astronomy: elevation `21 sin(pi p)` (higher is never in the picture: no pitch,
a half angle of 25.7 degrees at 672 x 324), azimuth east at the rise through south to west at the set. The border wall hides
everything under 8.7 degrees: the sun is over it from about 07:45 to 17:15, the moon from about 20:30 to 04:30.

### Clouds drift without load
Wind 4 m/s: a cloud 1000 m away crosses 0.23 degrees a second, the nearest ones about three times that. The cloud time is
the world time: blocking mode (headless, tests) the last `clouds` line (default 0), so a picture depends only on the input; live
mode adds the engine clock. Live mode redraws when ANY visible cloud has moved a whole point on the picture since the last
picture (`POV_SkyDirty`: one projection per cloud and tick, 220 a tick), so the nearest cloud sets the rate (the next layer
sets it when the nearest has left). Measured (headless live, 10 s, default place, four directions): **0.4 to 0.8 pictures a
second at 320 x 200, 0.7 to 1.1 at 672 x 324, 1.9 to 3.3 at 1280 x 800** (computed from the clouds and the geometry in
`tests.test_sky.Live`).

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
    python3 tools/theme_samples.py --sky      # out/muster-himmel/: A and B, 672x324 and 1280x640 (tools/sky_samples.py)

`tageslauf-<A|B>-<size>.png` (06:00 08:00 12:00 16:00 18:30 20:00 23:00 03:00, the view towards the sun or moon, eight
neighbour cubes, labelled), `rundblick-...` (four directions at 16:00, none of the cubes to the south), `wolkenzug-...`
(five pictures 10 s apart from a world time at which a cloud nearer than the east cube crosses it), `gang-...` (the camera
goes 5 steps across the field, 40 m apart), `dunst-...` (`fog` 0, 1, 2), `ebenen-...` (levels 5, 60, 115), and every picture of
the day alone (`einzel-...-<hhmm>.png`). The scene is a sparse field around the eye (24.5, 24.5), the window at cells 40..88 of
the field (the middle of its cube), the cube at (0, 0, 0). `theme_samples.berlin_minutes()` gives the Berlin minutes.

### Measured (`tools/measure_size.py` and a sky-heavy scene: an empty field with a wall, the camera turning)
ms a picture, 400 pictures, 3 runs, before (`7b88364`) / after (the machine is noisy: +-0.2 ms between runs):

| Size | Scene | Before | After |
|---|---|---|---|
| 672 x 324 | wueste, the usual scene | 4.37 | 4.63 |
| 1280 x 800 | wueste, the usual scene | 16.49 | 17.94 |
| 672 x 324 | sky-heavy | 3.84 | 4.17 (with 8 cubes 4.59) |
| 1280 x 800 | sky-heavy | 15.48 | 17.08 (with 8 cubes 18.66) |

Without a theme nothing changed (0.54 / 1.11 / 4.38). The clouds cost about +6 to +10 percent a picture, 8 neighbour cubes
about +10 percent more. Memory at 1280 x 800: 34.1 MB resident against 32.4 MB; the sprite lump is 3.5 MB (a theme file 8.0 MB against 6.6),
the zone has 17.95 MB free of 24 (19.34 before).

### Tests
    python3 -m unittest tests.test_sky tests.test_world
`test_sky`: the time of day (lines, palettes, contrast), the sun round, live drift, outline. `test_world`: the lines, clouds
against the perspective (size, place, lower edge a row in 3 shapes x 2 directions x 3 places, size by distance, parallax by a
step and by the wind), one sky for all cubes, cubes against their corners, depth order, the haze in flat steps, the haze contrast.

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
