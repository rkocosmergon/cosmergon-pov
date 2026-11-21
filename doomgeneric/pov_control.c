// cosmergon-pov: control channel (see pov_control.h and COSMERGON.md).
//
// The level is loaded once (the fixed 48 x 48 map). After that no game tic runs any more:
// no thinkers, no player logic, no specials. This file turns text lines into changes of
// sector floors, side textures, a pool of display-only things and the player's position,
// and draws the view with R_RenderPlayerView() only (no status bar, no HUD, no menu).

#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "doomdef.h"
#include "doomstat.h"
#include "d_loop.h"
#include "g_game.h"
#include "i_system.h"
#include "i_video.h"
#include "info.h"
#include "m_argv.h"
#include "m_fixed.h"
#include "p_local.h"
#include "p_mobj.h"
#include "r_data.h"
#include "r_draw.h"
#include "r_main.h"
#include "r_state.h"
#include "tables.h"
#include "w_wad.h"
#include "z_zone.h"

#include "pov_control.h"
#include "pov_sky.h"

// ---------------------------------------------------------------------------------------
// Measures. Must equal tools/pov_measures.py (tests/test_control.py compares them).
// ---------------------------------------------------------------------------------------
#define POV_H_EMPTY   0
#define POV_H_WALL    64
#define POV_H_CELL    128
#define POV_H_TOWER   147
#define POV_EYE       41            // eye height above the floor of the cell the camera is in
#define POV_CELL_SIZE 128           // units
#define POV_ORIGIN    (-3072)       // world coordinate of the south-west corner of the window

enum { K_EMPTY = 0, K_CELL, K_WALL, K_TOWER, K_OWN, K_COUNT };

// Look of each kind. `lower` is the lower wall texture seen on the four edges of a cell of this
// kind, `flat` its floor (top face). All names exist in freedoom1.wad (tests check this).
// Texture heights are 128 so that a step of up to 147 units stays inside one texture repeat.
// With a theme (a PWAD with a POVTHEME lump) the walls take `theme_x` on the two edges that face
// east or west and `theme_y` on those that face north or south (two shades of one role, so the
// edges of a block show); the flats keep their names (the theme's own flat range holds them).
static const struct
{
    const char *name;
    const char *lower;
    const char *flat;
    int         height;
    const char *theme_x;
    const char *theme_y;
} s_kind[K_COUNT] = {
    { "empty", "STARTAN3", "FLOOR4_8", POV_H_EMPTY, "PEX", "PEY" },   // the state of the generated map
    { "cell",  "A-CAMO1",  "GRASS1",   POV_H_CELL,  "PCX", "PCY" },
    { "wall",  "A-BRICK1", "FLAT10",   POV_H_WALL,  "PWX", "PWY" },
    { "tower", "STONE2",   "FLAT5_4",  POV_H_TOWER, "PTX", "PTY" },
    { "own",   "A-CAMO2",  "GRASS2",   POV_H_CELL,  "POX", "POY" },   // a cell of the viewer's own
};

// Things: the sprite and frame of each kind, and how high its origin floats above the floor of its cell
// (units). A sprite with 8 rotations shows the facing; one with a single look (rotation 0: BPAK, the
// TROO death frame) does not turn. The sprites are the IWAD's and stand in until the game's own figures
// exist; the lumps used are checked by tests/test_kinds.py.
//   marauder  TROO A  the imp, 48 x 60 units (body radius 0.6 m)
//   monster   BOSS A  the baron, 49 x 69, horned and broad (radius 0.9 m, the largest body)
//   bird      HEAD A  the cacodemon, a round flier 63 x 66; it floats: origin 40 above the floor, so its
//                     lowest point (5 under the origin) is 35 clear of the ground, about the eye (41), and
//                     its top (61 over the origin) is 101, under the 128 of a cell
//   corpse    TROO M  the last frame of the death (12): lies on the floor, one look from every side
//   loot      BPAK A  a backpack
static const struct
{
    const char *name;
    spritenum_t sprite;
    int         frame;
    int         lift;
} s_thing_kind[] = {
    { "marauder", SPR_TROO, 0,  0 },
    { "loot",     SPR_BPAK, 0,  0 },
    { "monster",  SPR_BOSS, 0,  0 },
    { "bird",     SPR_HEAD, 0, 40 },
    { "corpse",   SPR_TROO, 12, 0 },
};
#define THING_KINDS ((int)(sizeof(s_thing_kind) / sizeof(s_thing_kind[0])))

// ---------------------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------------------
static int s_live = 0;
static int s_ready = 0;
static int s_done = 0;
static int s_quit = 0;
static int s_input_done = 0;             // end of input reached, no line left
static int s_dirty = 0;                  // changed since the last drawn frame
static int s_live_t0 = 0;                // I_GetTimeMS at the start (the clouds' live clock)
static unsigned long s_pending = 0;      // frames still to draw for `next`
static unsigned long s_lines = 0;
static unsigned long s_rejected = 0;
static int s_summary_done = 0;

static unsigned char s_kind_of[POVC_CELLS];     // the kind a cell has been given (its target; the floor may still travel)

// Rise and sink (COSMERGON.md, "Rise and sink"): a floor never jumps, except when the window is set anew.
// A moving cell has a start height, a target height, a start step and a length in steps. The clock counts
// engine steps (35 a second): one drawn frame in blocking mode, the wall clock in live mode.
#define POV_RISE_MAX_MS     10000       // -pov-rise limit
#define POV_RISE_DEFAULT_MS 1200        // the iso client's cell animation
#define POV_STEPS_PER_SEC   35
#define POV_SNAP_LIVE_STEPS 18          // live: a reset window is filled within this many steps (~0.5 s)
static int s_rise_steps = 0;            // steps of a travel of POV_H_CELL units; 0 = no animation
static unsigned long s_step = 0;        // the clock
static unsigned s_clock_ms = 0;         // live: I_GetTimeMS at the last clock update
static unsigned s_clock_frac = 0;       // live: milliseconds * 35 not yet turned into a step
static fixed_t s_rise_from[POVC_CELLS];
static fixed_t s_rise_to[POVC_CELLS];
static unsigned long s_rise_t0[POVC_CELLS];
static int s_rise_len[POVC_CELLS];
static short s_moving[POVC_CELLS];      // the cells that travel (the only ones looked at in a step)
static short s_moving_at[POVC_CELLS];  // position in s_moving, -1 = at rest
static int s_moving_n = 0;
static unsigned char s_look_of[POVC_CELLS];     // the kind whose look the cell wears now
static int s_trace = 0;                         // POV_RISE_TRACE set: one stderr line per frame and raised cell
static unsigned long s_trace_frame = 0;
// The "snap": while the window is set anew (the start, or `origin`) the cells it is filled with take their height
// at once. s_snap_todo marks the cells not yet written since the reset.
static int s_snap = 1;
static int s_snap_started = 0;
static unsigned long s_snap_step = 0;
static int s_snap_left = POVC_CELLS;
static unsigned char s_snap_todo[POVC_CELLS];
// Variants (a theme with a POVX lump, see theme_init): which look a cell wears is picked from its WORLD
// position, so it stays the same when the 48 x 48 window moves over the field (`origin` line).
#define POV_SLOTS 16
static short s_texnum[K_COUNT][POV_SLOTS][2];   // [kind][slot][0 = edge facing east/west, 1 = north/south]
static short s_flatnum[K_COUNT][POV_SLOTS][4];  // [kind][slot][edge bits: 1 = joint on the west edge, 2 = on the south edge]
static int s_origin_x = 0;               // world coordinates of cell 0, 0 of the window
static int s_origin_y = 0;
static short s_facing[POVC_CELLS][4];    // side index of the cell's sidedef facing east/west/north/south

typedef struct
{
    int    used;
    int    linked;
    int    kind;                        // index in s_thing_kind
    mobj_t mo;
} pov_thing_t;

static pov_thing_t s_things[POVC_MAX_THINGS];

// ---------------------------------------------------------------------------------------
// Mode switches
// ---------------------------------------------------------------------------------------
int POV_ControlEnabled(void)
{
    static int cached = -1;

    if (cached < 0)
    {
        cached = M_CheckParm("-pov-control") > 0;
    }
    return cached;
}

void POV_ControlSetLive(int live)
{
    s_live = live != 0;
}

int POV_ControlIsLive(void)
{
    return s_live;
}

int POV_ControlDone(void)
{
    return s_done;
}

void POV_ControlSummary(FILE *out)
{
    if (!POV_ControlEnabled() || s_summary_done)
    {
        return;
    }
    s_summary_done = 1;
    fprintf(out, "control: lines=%lu rejected=%lu\n", s_lines, s_rejected);
}

// ---------------------------------------------------------------------------------------
// Picture size (pov_view_w x pov_view_h, i_video.c). Without a choice the engine draws 320 x 200
// and the platform layer shows it twice as large (640 x 400), the way it always did. A choice (the
// `size` line, -pov-size, or the window's own size) draws exactly that many points, shown 1 : 1.
// ---------------------------------------------------------------------------------------
extern boolean setsizeneeded;

int POV_ControlRequestSize(int width, int height)
{
    if (width < POV_MIN_W || width > POV_MAX_W || height < POV_MIN_H || height > POV_MAX_H)
    {
        return 0;
    }
    if (width != pov_view_w || height != pov_view_h || pov_out_scale != 1)
    {
        pov_view_w = width;
        pov_view_h = height;
        pov_out_scale = 1;
        if (s_ready)
        {
            R_SetViewSize(11, 0);       // takes effect in the next frame (render_frame)
        }
        s_dirty = 1;
    }
    return 1;
}

// A platform layer that follows its window (doomgeneric_pov.c): the window's size in pixels. Inside the limits it is
// the picture size (as POV_ControlRequestSize). Above them in one or both axes the picture is the largest one that
// lies inside the limits and has the window's shape (the window shows it stretched, the points stay square to
// within half a point of rounding). Below the minimum, or a shape that no picture inside the limits has (a side
// would fall under its minimum), nothing changes. Returns 0 nothing taken, 1 taken as it is, 2 taken fitted.
int POV_ControlFitSize(int width, int height)
{
    long long w = width, h = height, fw, fh;

    if (w < POV_MIN_W || h < POV_MIN_H)
    {
        return 0;
    }
    if (w <= POV_MAX_W && h <= POV_MAX_H)
    {
        return POV_ControlRequestSize(width, height);
    }
    if (w * POV_MAX_H > h * POV_MAX_W)      // wider than the limits' shape: the width is the limit
    {
        fw = POV_MAX_W;
        fh = (h * POV_MAX_W + w / 2) / w;
    }
    else
    {
        fh = POV_MAX_H;
        fw = (w * POV_MAX_H + h / 2) / h;
    }
    if (fw < POV_MIN_W || fh < POV_MIN_H || fw > POV_MAX_W || fh > POV_MAX_H)
    {
        return 0;
    }
    return POV_ControlRequestSize((int)fw, (int)fh) ? 2 : 0;
}

// -pov-size <w>x<h>: exactly two whole numbers in range, else the program stops (a wrong command
// line is a mistake of the caller, not a line to skip).
static void size_from_command_line(void)
{
    int i = M_CheckParmWithArgs("-pov-size", 1);
    const char *text;
    char *end = NULL;
    long w, h;

    if (i <= 0)
    {
        return;
    }
    text = myargv[i + 1];
    errno = 0;
    w = strtol(text, &end, 10);
    if (errno != 0 || end == text || *end != 'x' || !isdigit((unsigned char)text[0]))
    {
        I_Error("pov-control: -pov-size needs <width>x<height>, got '%s'", text);
    }
    text = end + 1;
    h = strtol(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' || !isdigit((unsigned char)text[0]))
    {
        I_Error("pov-control: -pov-size needs <width>x<height>, got '%s'", myargv[i + 1]);
    }
    if (!POV_ControlRequestSize((int)(w > 100000 ? 100000 : w), (int)(h > 100000 ? 100000 : h)))
    {
        I_Error("pov-control: -pov-size %ldx%ld is outside %dx%d .. %dx%d", w, h,
                POV_MIN_W, POV_MIN_H, POV_MAX_W, POV_MAX_H);
    }
}

// ---------------------------------------------------------------------------------------
// World changes
// ---------------------------------------------------------------------------------------
static short tex_num(const char *name)
{
    char buf[16];

    snprintf(buf, sizeof(buf), "%s", name);
    return (short)R_TextureNumForName(buf);
}

static short flat_num(const char *name)
{
    char buf[16];

    snprintf(buf, sizeof(buf), "%s", name);
    return (short)R_FlatNumForName(buf);
}

// Direction d: 0 east (+x), 1 west, 2 north (+y), 3 south. Returns the neighbour or -1.
static int neighbour(int cell, int d)
{
    int x = cell % POVC_GRID;
    int y = cell / POVC_GRID;

    switch (d)
    {
    case 0: return x + 1 < POVC_GRID ? cell + 1 : -1;
    case 1: return x > 0 ? cell - 1 : -1;
    case 2: return y + 1 < POVC_GRID ? cell + POVC_GRID : -1;
    default: return y > 0 ? cell - POVC_GRID : -1;
    }
}

static int opposite(int d)
{
    return d ^ 1;
}

// Hash of a world cell, a salt tells the uses apart (murmur3 finaliser; the same on every machine).
static unsigned mix32(unsigned h)
{
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    h *= 0xC2B2AE35u;
    h ^= h >> 16;
    return h;
}

static unsigned cell_hash(int wx, int wy, unsigned salt)
{
    return mix32(mix32((unsigned)wx * 0x9E3779B1u + salt * 0x7FEB352Du) ^ ((unsigned)wy * 0x846CA68Bu + salt));
}

// The long joints of the ground sit on cell edges. A joint runs along a line of cells (four in a row share the
// decision, a zone of four by four cells says how many lines it has: calm zones and dense ones), with a gap
// now and then; whichever cell is next to an edge, it is the cell on the east / north side that draws it.
// Bit 1: a joint on the west edge, bit 2: on the south edge.
static int ground_edges(int wx, int wy)
{
    static const int lines_of_zone[8] = { 1, 1, 2, 3, 3, 4, 5, 6 };      // of 8 lines per zone, by the zone's hash
    const int zone = (int)(cell_hash(wx >> 2, wy >> 2, 103) >> 9 & 7);
    const int have = lines_of_zone[zone];
    int edges = 0;

    if ((int)(cell_hash(wx, wy >> 2, 102) >> 9 & 7) < have && (cell_hash(wx, wy, 100) >> 9 & 7) != 0)
    {
        edges |= 1;
    }
    if ((int)(cell_hash(wx >> 2, wy, 104) >> 9 & 7) < have && (cell_hash(wx, wy, 101) >> 9 & 7) != 0)
    {
        edges |= 2;
    }
    return edges;
}

// Gives one cell the look of a kind: its floor flat, and the lower texture on the sidedef of
// each neighbour that faces it. The wall texture of a step is the lower texture of the sidedef
// on the LOWER side (r_segs.c R_StoreWallRange: the seg's own sidedef, drawn when the back floor
// is higher). So the texture seen from outside a cell of kind K sits on the neighbour's side.
// The lower texture is pegged to the higher floor (no ML_DONTPEGBOTTOM on any line): its top row
// lies on the top edge of the cell, so a travelling cell carries its texture with it.
static void set_look(int cell, int kind)
{
    int d;
    sector_t *sector = &sectors[cell];

    const int wx = s_origin_x + cell % POVC_GRID;
    const int wy = s_origin_y + cell / POVC_GRID;
    int edges = 0;

    s_look_of[cell] = (unsigned char)kind;
    if (kind == K_EMPTY)
    {
        edges = ground_edges(wx, wy);
    }
    sector->floorpic = s_flatnum[kind][cell_hash(wx, wy, (unsigned)kind * 8 + 7) >> 8 & (POV_SLOTS - 1)][edges];
    for (d = 0; d < 4; d++)
    {
        int other = neighbour(cell, d);

        if (other >= 0)
        {
            unsigned slot = cell_hash(wx, wy, (unsigned)kind * 8 + (unsigned)d) >> 8 & (POV_SLOTS - 1);

            sides[s_facing[other][opposite(d)]].bottomtexture = s_texnum[kind][slot][d >> 1];
        }
    }
    s_dirty = 1;
}

static void moving_remove(int cell)
{
    int at = s_moving_at[cell];

    if (at >= 0)
    {
        int last = s_moving[--s_moving_n];

        s_moving[at] = (short)last;
        s_moving_at[last] = (short)at;
        s_moving_at[cell] = -1;
    }
}

// Ends the travel of a cell where it stands: the floor is at its target; a cell that sank to nothing
// now looks empty.
static void rise_finish(int cell)
{
    sectors[cell].floorheight = s_rise_to[cell];
    moving_remove(cell);
    if (s_kind_of[cell] == K_EMPTY)
    {
        set_look(cell, K_EMPTY);
    }
    s_dirty = 1;
}

// The cell takes its kind at once: no travel.
static void set_kind_now(int cell, int kind)
{
    moving_remove(cell);
    s_kind_of[cell] = (unsigned char)kind;
    sectors[cell].floorheight = s_kind[kind].height * FRACUNIT;
    set_look(cell, kind);
}

// Is the cell written in the snap (the window is being set anew)? Marks it as written.
static int snap_takes(int cell)
{
    if (!s_snap)
    {
        return 0;
    }
    if (!s_snap_started)
    {
        s_snap_started = 1;
        s_snap_step = s_step;
    }
    if (s_snap_todo[cell])
    {
        s_snap_todo[cell] = 0;
        if (--s_snap_left == 0)
        {
            s_snap = 0;
        }
    }
    return 1;
}

// The window is set anew (start, `origin`): everything stands where it goes, and the snap opens.
static void snap_open(void)
{
    int i;

    for (i = 0; i < POVC_CELLS; i++)
    {
        s_snap_todo[i] = 1;
    }
    s_snap_left = POVC_CELLS;
    s_snap = 1;
    s_snap_started = 0;
}

// Sets the kind of one cell (the lines `cell` and `row`). A cell whose height changes travels from the
// height it has now to the new one; one that already has the kind, or any cell in the snap, changes nothing
// on the way. A rising cell wears the look of its new kind from the first step; a cell that sinks to nothing
// keeps its look until it is down; a change between two raised kinds takes the new look at once and the
// height travels; a change between kinds of one height (cell and own) is at once.
static void set_kind(int cell, int kind)
{
    const fixed_t target = s_kind[kind].height * FRACUNIT;
    const fixed_t now = sectors[cell].floorheight;
    long long dist;
    int steps;

    if (snap_takes(cell) || s_rise_steps == 0)
    {
        set_kind_now(cell, kind);
        return;
    }
    if (kind == s_kind_of[cell])
    {
        return;
    }
    s_kind_of[cell] = (unsigned char)kind;
    if (target == now)
    {
        moving_remove(cell);
        set_look(cell, kind);
        return;
    }
    dist = target > now ? (long long)target - now : (long long)now - target;
    // the speed is the same for every kind (POV_H_CELL units in s_rise_steps), so a reversal takes the time of
    // the way that is left
    steps = (int)((dist * s_rise_steps + (long long)POV_H_CELL * FRACUNIT - 1) / ((long long)POV_H_CELL * FRACUNIT));
    if (steps < 1)
    {
        steps = 1;
    }
    s_rise_from[cell] = now;
    s_rise_to[cell] = target;
    s_rise_t0[cell] = s_step;
    s_rise_len[cell] = steps;
    if (s_moving_at[cell] < 0)
    {
        s_moving_at[cell] = (short)s_moving_n;
        s_moving[s_moving_n++] = (short)cell;
    }
    if (kind != K_EMPTY)
    {
        set_look(cell, kind);
    }
    s_dirty = 1;
}

// The floor of a travelling cell at the clock: smoothstep 3t^2 - 2t^3 in integers (t = k / n), exact at both
// ends, monotone, never outside [from, to].
static fixed_t rise_height(int cell)
{
    const unsigned long k_raw = s_step - s_rise_t0[cell];
    const long long n = s_rise_len[cell];
    const long long k = k_raw > (unsigned long)n ? n : (long long)k_raw;
    const long long delta = (long long)s_rise_to[cell] - s_rise_from[cell];

    return (fixed_t)(s_rise_from[cell] + delta * (k * k * (3 * n - 2 * k)) / (n * n * n));
}

// One step of every travelling cell. Nothing is looked at when nothing travels.
static void rise_update(void)
{
    int i = 0;

    while (i < s_moving_n)
    {
        int cell = s_moving[i];

        if (s_step - s_rise_t0[cell] >= (unsigned long)s_rise_len[cell])
        {
            rise_finish(cell);      // swaps the last travelling cell into slot i: look at i again
            continue;
        }
        sectors[cell].floorheight = rise_height(cell);
        i++;
    }
}

// Live clock: engine steps from the wall clock, whatever the rate of the loop.
static void rise_clock_live(void)
{
    unsigned now = (unsigned)I_GetTimeMS();

    s_clock_frac += (now - s_clock_ms) * POV_STEPS_PER_SEC;
    s_clock_ms = now;
    s_step += s_clock_frac / 1000;
    s_clock_frac %= 1000;
}

// -pov-rise <ms>: whole milliseconds 0..POV_RISE_MAX_MS, else the program stops.
static void rise_from_command_line(void)
{
    int i = M_CheckParmWithArgs("-pov-rise", 1);
    int ms = POV_RISE_DEFAULT_MS;

    if (i > 0)
    {
        const char *text = myargv[i + 1];
        char *end = NULL;
        long value;

        errno = 0;
        value = strtol(text, &end, 10);
        if (errno != 0 || end == text || *end != '\0' || !isdigit((unsigned char)text[0]) || value > POV_RISE_MAX_MS)
        {
            I_Error("pov-control: -pov-rise needs whole milliseconds 0..%d, got '%s'", POV_RISE_MAX_MS, text);
        }
        ms = (int)value;
    }
    s_rise_steps = ms == 0 ? 0 : (ms * POV_STEPS_PER_SEC + 500) / 1000;
    if (ms > 0 && s_rise_steps < 1)
    {
        s_rise_steps = 1;
    }
}

static fixed_t to_fixed_world(double cells)
{
    return (fixed_t)floor((POV_ORIGIN + cells * POV_CELL_SIZE) * 65536.0 + 0.5);
}

static angle_t to_bam(double degrees)
{
    double a = fmod(degrees, 360.0);
    double bam;

    if (a < 0.0)
    {
        a += 360.0;
    }
    if (a >= 360.0)
    {
        a = 0.0;
    }
    bam = a / 360.0 * 4294967296.0;
    if (bam >= 4294967296.0)
    {
        bam = 0.0;
    }
    return (angle_t)bam;
}

static void thing_unlink(pov_thing_t *t)
{
    if (t->linked)
    {
        P_UnsetThingPosition(&t->mo);
        t->linked = 0;
    }
}

static void thing_place(int id, int kind, fixed_t x, fixed_t y, angle_t angle)
{
    pov_thing_t *t = &s_things[id];

    thing_unlink(t);
    memset(&t->mo, 0, sizeof(t->mo));
    t->mo.x = x;
    t->mo.y = y;
    t->mo.angle = angle;
    t->kind = kind;
    t->mo.sprite = s_thing_kind[kind].sprite;
    t->mo.frame = s_thing_kind[kind].frame;
    t->mo.flags = MF_NOBLOCKMAP;     // only the sector list: the renderer finds it there
    P_SetThingPosition(&t->mo);
    t->linked = 1;
    t->used = 1;
    s_dirty = 1;
}

static void camera_place(fixed_t x, fixed_t y, angle_t angle)
{
    mobj_t *mo = players[consoleplayer].mo;

    P_UnsetThingPosition(mo);
    mo->x = x;
    mo->y = y;
    mo->angle = angle;
    P_SetThingPosition(mo);
    s_dirty = 1;
}

// Floors may have changed since a thing was placed: z follows the floor of its cell; the eye
// follows the floor of the cell the camera stands in.
static void commit(void)
{
    int i;
    player_t *p = &players[consoleplayer];

    for (i = 0; i < POVC_MAX_THINGS; i++)
    {
        pov_thing_t *t = &s_things[i];

        if (t->used)
        {
            t->mo.z = t->mo.subsector->sector->floorheight + s_thing_kind[t->kind].lift * FRACUNIT;
        }
    }
    p->mo->z = p->mo->subsector->sector->floorheight;
    p->viewz = p->mo->z + POV_EYE * FRACUNIT;
}

// ---------------------------------------------------------------------------------------
// Parser: one line -> one validated command. Nothing is applied before the whole line is valid.
// ---------------------------------------------------------------------------------------
typedef enum { OP_CELL, OP_ROW, OP_THING, OP_GONE, OP_CAM, OP_LIGHT, OP_NEXT, OP_SIZE, OP_ORIGIN, OP_DAYTIME, OP_CLOUDS, OP_WORLD, OP_CUBE, OP_NOCUBE, OP_QUIT } op_t;

typedef struct
{
    op_t   op;
    int    a, b;                       // cell x/y, row y, id, light, next n
    int    kind;
    int    w[4];                       // world: cube x, y, z, level; cube: x, y, z, dim
    double x, y, angle;
    unsigned char row[POVC_GRID];
} command_t;

static int parse_double(const char *tok, double *out)
{
    size_t len = strlen(tok);
    size_t i;
    char *end = NULL;
    double v;

    if (len == 0 || len > 24)
    {
        return 0;
    }
    for (i = 0; i < len; i++)
    {
        if (strchr("0123456789+-.eE", tok[i]) == NULL)
        {
            return 0;
        }
    }
    errno = 0;
    v = strtod(tok, &end);
    if (end != tok + len || errno != 0 || !isfinite(v))
    {
        return 0;
    }
    *out = v;
    return 1;
}

static int parse_int(const char *tok, long lo, long hi, int *out)
{
    size_t len = strlen(tok);
    size_t i;
    char *end = NULL;
    long v;

    if (len == 0 || len > 9)
    {
        return 0;
    }
    for (i = 0; i < len; i++)
    {
        if (!isdigit((unsigned char)tok[i]) && !(i == 0 && tok[i] == '-' && len > 1))
        {
            return 0;
        }
    }
    errno = 0;
    v = strtol(tok, &end, 10);
    if (end != tok + len || errno != 0 || v < lo || v > hi)
    {
        return 0;
    }
    *out = (int)v;
    return 1;
}

// Cell coordinate: a number, integral, 0..47.
static const char *parse_cell_coord(const char *tok, int *out)
{
    double v;

    if (!parse_double(tok, &v))
    {
        return "bad number";
    }
    if (v != floor(v) || v < 0.0 || v > (double)(POVC_GRID - 1))
    {
        return "cell coordinate must be an integer 0..47";
    }
    *out = (int)v;
    return NULL;
}

// Position in cells: 0 <= v < 48.
static const char *parse_pos(const char *tok, double *out)
{
    double v;

    if (!parse_double(tok, &v))
    {
        return "bad number";
    }
    if (v < 0.0 || v >= (double)POVC_GRID)
    {
        return "position out of range 0..<48";
    }
    *out = v;
    return NULL;
}

static const char *parse_angle(const char *tok, double *out)
{
    double v;

    if (!parse_double(tok, &v))
    {
        return "bad number";
    }
    if (fabs(v) > 1000000.0)
    {
        return "angle out of range";
    }
    *out = v;
    return NULL;
}

static int kind_from_char(char c)
{
    switch (c)
    {
    case '.': return K_EMPTY;
    case '#': return K_CELL;
    case '=': return K_WALL;
    case 'T': return K_TOWER;
    case 'O': return K_OWN;
    default: return -1;
    }
}

// `world <cube_x> <cube_y> <cube_z> <level> <dim>`: where the field lies in the world (COSMERGON.md, "The sky").
static const char *parse_world(char **tok, int ntok, command_t *c)
{
    int i;

    if (ntok != 6)
    {
        return "world needs <cube_x> <cube_y> <cube_z> <level> <dim>";
    }
    c->op = OP_WORLD;
    for (i = 0; i < 3; i++)
    {
        if (!parse_int(tok[1 + i], -POVC_MAX_CUBE_POS, POVC_MAX_CUBE_POS, &c->w[i]))
        {
            return "a cube position must be an integer within +-10,000";
        }
    }
    if (!parse_int(tok[5], POVC_DIM_MIN, POVC_DIM_MAX, &c->b))
    {
        return "dim must be an integer 8..1024 (cells a side of the cube)";
    }
    if (!parse_int(tok[4], 0, c->b - 1, &c->w[3]))
    {
        return "level must be an integer 0..dim-1";
    }
    return NULL;
}

// `cube <id> <cube_x> <cube_y> <cube_z> <dim>`: a neighbour cube at its grid position.
static const char *parse_cube(char **tok, int ntok, command_t *c)
{
    int i;

    if (ntok != 6)
    {
        return "cube needs <id> <cube_x> <cube_y> <cube_z> <dim>";
    }
    c->op = OP_CUBE;
    if (!parse_int(tok[1], 0, POVC_MAX_CUBES - 1, &c->a))
    {
        return "id must be an integer 0..63";
    }
    for (i = 0; i < 3; i++)
    {
        if (!parse_int(tok[2 + i], -POVC_MAX_CUBE_POS, POVC_MAX_CUBE_POS, &c->w[i]))
        {
            return "a cube position must be an integer within +-10,000";
        }
    }
    return parse_int(tok[5], POVC_DIM_MIN, POVC_DIM_MAX, &c->w[3]) ? NULL : "dim must be an integer 8..1024";
}

// Returns NULL when the line is a valid command (stored in *c) or the reason it is not.
static const char *parse_line(const unsigned char *line, size_t len, command_t *c)
{
    char buf[POVC_MAX_LINE + 1];
    char *tok[8];
    int ntok = 0;
    size_t i;
    char *p;
    const char *err;

    if (len > 0 && line[len - 1] == '\r')
    {
        len--;
    }
    if (len == 0)
    {
        return "empty line";
    }
    for (i = 0; i < len; i++)
    {
        unsigned char ch = line[i];

        if (!((ch >= 0x20 && ch <= 0x7E) || ch == '\t'))
        {
            return "byte outside printable ASCII";
        }
        buf[i] = (char)ch;
    }
    buf[len] = '\0';

    p = buf;
    for (;;)
    {
        while (*p == ' ' || *p == '\t')
        {
            *p++ = '\0';
        }
        if (*p == '\0')
        {
            break;
        }
        if (ntok == 8)
        {
            return "too many fields";
        }
        tok[ntok++] = p;
        while (*p != '\0' && *p != ' ' && *p != '\t')
        {
            p++;
        }
    }
    if (ntok == 0)
    {
        return "empty line";
    }

    memset(c, 0, sizeof(*c));
    if (strcmp(tok[0], "cell") == 0)
    {
        int k;

        if (ntok != 4)
        {
            return "cell needs <x> <y> <kind>";
        }
        c->op = OP_CELL;
        if ((err = parse_cell_coord(tok[1], &c->a)) != NULL || (err = parse_cell_coord(tok[2], &c->b)) != NULL)
        {
            return err;
        }
        for (k = 0; k < K_COUNT; k++)
        {
            if (strcmp(tok[3], s_kind[k].name) == 0)
            {
                c->kind = k;
                return NULL;
            }
        }
        return "unknown kind";
    }
    if (strcmp(tok[0], "row") == 0)
    {
        if (ntok != 3)
        {
            return "row needs <y> <48 characters>";
        }
        c->op = OP_ROW;
        if ((err = parse_cell_coord(tok[1], &c->a)) != NULL)
        {
            return err;
        }
        if (strlen(tok[2]) != POVC_GRID)
        {
            return "row needs exactly 48 characters";
        }
        for (i = 0; i < POVC_GRID; i++)
        {
            int k = kind_from_char(tok[2][i]);

            if (k < 0)
            {
                return "bad character in row (use . # = T O)";
            }
            c->row[i] = (unsigned char)k;
        }
        return NULL;
    }
    if (strcmp(tok[0], "thing") == 0)
    {
        int k;

        if (ntok != 6)
        {
            return "thing needs <id> <kind> <x> <y> <angle>";
        }
        c->op = OP_THING;
        if (!parse_int(tok[1], 0, POVC_MAX_THINGS - 1, &c->a))
        {
            return "id must be an integer 0..255";
        }
        c->kind = -1;
        for (k = 0; k < THING_KINDS; k++)
        {
            if (strcmp(tok[2], s_thing_kind[k].name) == 0)
            {
                c->kind = k;
            }
        }
        if (c->kind < 0)
        {
            return "unknown kind";
        }
        if ((err = parse_pos(tok[3], &c->x)) != NULL || (err = parse_pos(tok[4], &c->y)) != NULL
            || (err = parse_angle(tok[5], &c->angle)) != NULL)
        {
            return err;
        }
        return NULL;
    }
    if (strcmp(tok[0], "gone") == 0)
    {
        if (ntok != 2)
        {
            return "gone needs <id>";
        }
        c->op = OP_GONE;
        return parse_int(tok[1], 0, POVC_MAX_THINGS - 1, &c->a) ? NULL : "id must be an integer 0..255";
    }
    if (strcmp(tok[0], "cam") == 0)
    {
        if (ntok != 4)
        {
            return "cam needs <x> <y> <angle>";
        }
        c->op = OP_CAM;
        if ((err = parse_pos(tok[1], &c->x)) != NULL || (err = parse_pos(tok[2], &c->y)) != NULL
            || (err = parse_angle(tok[3], &c->angle)) != NULL)
        {
            return err;
        }
        return NULL;
    }
    if (strcmp(tok[0], "light") == 0)
    {
        if (ntok != 2)
        {
            return "light needs <0..255>";
        }
        c->op = OP_LIGHT;
        return parse_int(tok[1], 0, 255, &c->a) ? NULL : "light must be an integer 0..255";
    }
    if (strcmp(tok[0], "next") == 0)
    {
        if (ntok > 2)
        {
            return "next needs [n]";
        }
        c->op = OP_NEXT;
        c->a = 1;
        if (ntok == 2 && !parse_int(tok[1], 1, POVC_MAX_NEXT, &c->a))
        {
            return "next count must be an integer 1..1000000";
        }
        return NULL;
    }
    if (strcmp(tok[0], "size") == 0)
    {
        if (ntok != 3)
        {
            return "size needs <width> <height>";
        }
        c->op = OP_SIZE;
        if (!parse_int(tok[1], POV_MIN_W, POV_MAX_W, &c->a) || !parse_int(tok[2], POV_MIN_H, POV_MAX_H, &c->b))
        {
            return "size must be integers, width 160..1280, height 100..800";
        }
        return NULL;
    }
    if (strcmp(tok[0], "origin") == 0)
    {
        if (ntok != 3)
        {
            return "origin needs <x> <y>";
        }
        c->op = OP_ORIGIN;
        if (!parse_int(tok[1], -POVC_MAX_ORIGIN, POVC_MAX_ORIGIN, &c->a)
            || !parse_int(tok[2], -POVC_MAX_ORIGIN, POVC_MAX_ORIGIN, &c->b))
        {
            return "origin must be integers within +-1,000,000";
        }
        return NULL;
    }
    if (strcmp(tok[0], "daytime") == 0)
    {
        if (ntok != 2)
        {
            return "daytime needs <minutes>";
        }
        c->op = OP_DAYTIME;
        return parse_int(tok[1], 0, 1439, &c->a) ? NULL : "daytime must be an integer 0..1439 (minutes since midnight)";
    }
    if (strcmp(tok[0], "world") == 0)
    {
        return parse_world(tok, ntok, c);
    }
    if (strcmp(tok[0], "cube") == 0)
    {
        return parse_cube(tok, ntok, c);
    }
    if (strcmp(tok[0], "nocube") == 0)
    {
        if (ntok != 2)
        {
            return "nocube needs <id>";
        }
        c->op = OP_NOCUBE;
        return parse_int(tok[1], 0, POVC_MAX_CUBES - 1, &c->a) ? NULL : "id must be an integer 0..63";
    }
    if (strcmp(tok[0], "clouds") == 0)
    {
        if (ntok != 2)
        {
            return "clouds needs <seconds>";
        }
        c->op = OP_CLOUDS;
        return parse_int(tok[1], 0, POVC_MAX_CLOUDS, &c->a) ? NULL : "clouds must be an integer 0..10,000,000 (seconds)";
    }
    if (strcmp(tok[0], "quit") == 0)
    {
        if (ntok != 1)
        {
            return "quit takes no arguments";
        }
        c->op = OP_QUIT;
        return NULL;
    }
    return "unknown command";
}

// The colours of the time of day (a theme with a sky): set the palette again.
static void sky_palette(void)
{
    unsigned char pal[768];

    POV_SkyPalette(POV_SkyMinute(), pal);
    I_SetPalette(pal);
}

static void apply(const command_t *c)
{
    int i;

    switch (c->op)
    {
    case OP_CELL:
        set_kind(c->b * POVC_GRID + c->a, c->kind);
        break;
    case OP_ROW:
        for (i = 0; i < POVC_GRID; i++)
        {
            set_kind(c->a * POVC_GRID + i, c->row[i]);
        }
        break;
    case OP_THING:
        thing_place(c->a, c->kind, to_fixed_world(c->x), to_fixed_world(c->y), to_bam(c->angle));
        break;
    case OP_GONE:
        if (s_things[c->a].used)
        {
            thing_unlink(&s_things[c->a]);
            s_things[c->a].used = 0;
            s_dirty = 1;
        }
        break;
    case OP_CAM:
        camera_place(to_fixed_world(c->x), to_fixed_world(c->y), to_bam(c->angle));
        break;
    case OP_LIGHT:
        for (i = 0; i < numsectors; i++)
        {
            sectors[i].lightlevel = (short)c->a;
        }
        s_dirty = 1;
        break;
    case OP_NEXT:
        s_pending += (unsigned long)c->a;
        break;
    case OP_SIZE:
        POV_ControlRequestSize(c->a, c->b);
        break;
    case OP_ORIGIN:
        s_origin_x = c->a;
        s_origin_y = c->b;
        if (POV_SkyActive())
        {
            POV_SkySetOrigin(c->a, c->b);
            s_dirty = 1;
        }
        while (s_moving_n > 0)
        {
            rise_finish(s_moving[0]);       // a reset window: the heights stand at once
        }
        for (i = 0; i < POVC_CELLS; i++)
        {
            set_look(i, s_kind_of[i]);      // the variants follow the world position
        }
        snap_open();
        break;
    case OP_DAYTIME:
        if (POV_SkyActive())
        {
            POV_SkySetMinute(c->a);
            sky_palette();
            s_dirty = 1;
        }
        break;
    case OP_CLOUDS:
        if (POV_SkyActive())
        {
            POV_SkySetCloudBase(c->a * 1000.0);
            s_dirty = 1;
        }
        break;
    case OP_WORLD:
        if (POV_SkyActive())
        {
            POV_SkySetWorld(c->w[0], c->w[1], c->w[2], c->w[3], c->b);
            s_dirty = 1;
        }
        break;
    case OP_CUBE:
        if (POV_SkyActive())
        {
            POV_SkyCube(c->a, c->w[0], c->w[1], c->w[2], c->w[3]);
            s_dirty = 1;
        }
        break;
    case OP_NOCUBE:
        if (POV_SkyActive())
        {
            POV_SkyNoCube(c->a);
            s_dirty = 1;
        }
        break;
    case OP_QUIT:
        s_quit = 1;
        break;
    }
}

// ---------------------------------------------------------------------------------------
// Line assembly from the platform's bytes
// ---------------------------------------------------------------------------------------
static unsigned char s_rbuf[4096];
static int s_rpos = 0;
static int s_rlen = 0;
static int s_eof = 0;
static unsigned char s_line[POVC_MAX_LINE];
static size_t s_line_len = 0;
static int s_overlong = 0;

enum { LINE_NONE, LINE_READY, LINE_EOF };

// Fills s_line / s_line_len / s_overlong. A line longer than POVC_MAX_LINE keeps only its
// first bytes and is flagged: the caller rejects it whole.
static int next_line(int wait)
{
    for (;;)
    {
        while (s_rpos < s_rlen)
        {
            unsigned char ch = s_rbuf[s_rpos++];

            if (ch == '\n')
            {
                return LINE_READY;
            }
            if (s_line_len < POVC_MAX_LINE)
            {
                s_line[s_line_len++] = ch;
            }
            else
            {
                s_overlong = 1;
            }
        }
        if (s_eof)
        {
            // a last line without a newline still counts
            return (s_line_len > 0 || s_overlong) ? LINE_READY : LINE_EOF;
        }
        {
            int n = DG_ControlRead(s_rbuf, (int)sizeof(s_rbuf), wait);

            if (n < 0)
            {
                s_eof = 1;
                continue;
            }
            if (n == 0)
            {
                return LINE_NONE;
            }
            s_rpos = 0;
            s_rlen = n;
        }
    }
}

static void handle_line(void)
{
    command_t cmd;
    const char *err;

    s_lines++;
    err = s_overlong ? "line too long" : parse_line(s_line, s_line_len, &cmd);
    s_line_len = 0;
    s_overlong = 0;
    if (err != NULL)
    {
        s_rejected++;
        if (s_rejected <= POVC_MAX_MSGS)
        {
            fprintf(stderr, "control: line %lu rejected: %s\n", s_lines, err);
        }
        return;
    }
    apply(&cmd);
}

// Reads lines until a frame is due (`next`), `quit` or end of input. In blocking mode the read
// waits, so the result only depends on the input; in live mode it stops when nothing is there.
static void pump(void)
{
    while (s_pending == 0 && !s_quit)
    {
        int r = next_line(!s_live);

        if (r == LINE_NONE)
        {
            return;
        }
        if (r == LINE_EOF)
        {
            s_input_done = 1;
            return;
        }
        handle_line();
    }
}

// ---------------------------------------------------------------------------------------
// Start and frame
// ---------------------------------------------------------------------------------------
extern gameaction_t gameaction;

static int level_loaded(void)
{
    return gamestate == GS_LEVEL && gameaction == ga_nothing && gametic > 0
           && players[consoleplayer].mo != NULL;
}

// ---------------------------------------------------------------------------------------
// Theme (see COSMERGON.md, "Themes"). A PWAD with a POVTHEME lump:
//   bytes 0..3 "POVT", 4 version (1), 5 outline on (0/1), 6 outline colour index, 7 light level
//   of all sectors (it fixes which COLORMAP row belongs to which distance, tools/make_theme.py),
//   8..263 class per colour index,
//   264..519 rank per colour index. An outline pixel is set on the pixel of lower rank where two
//   neighbours have different classes (equal rank: the lower class); pixels of one wall plane
//   (pov_wall_id) count as one surface even where colour indices differ.
// ---------------------------------------------------------------------------------------
#define THEME_LUMP_SIZE 520

extern int pov_gamma_off;      // i_video.c
static int s_theme_on = 0;
static int s_outline_on = 0;
static unsigned char s_outline_index = 0;
static unsigned char s_outline_of[256];    // per colour index: the index of a line drawn on a point of it (haze, POVFOG)
static unsigned char s_is_outline[256];    // 1 for every index a line can have
static unsigned char s_class[256];
static unsigned char s_rank[256];
static unsigned char *s_shot = NULL;       // copy of the picture the outline is derived from
static int s_ink_on = 0;                   // lump POVINK: the strokes are thinned on the picture (ink_pass)
static unsigned char s_ink_repl[256];      // per colour index: what a thinned stroke point becomes (0: no stroke)
static unsigned char s_ink_floor[256];     // 1: a stroke on a floor

static void theme_init(void)
{
    int lump = W_CheckNumForName("POVTHEME");
    unsigned char *data;
    int i;

    s_theme_on = lump >= 0;
    if (!s_theme_on)
    {
        return;
    }
    if (W_LumpLength(lump) != THEME_LUMP_SIZE)
    {
        I_Error("pov-control: POVTHEME must be %d bytes, it has %d", THEME_LUMP_SIZE, W_LumpLength(lump));
    }
    data = W_CacheLumpNum(lump, PU_STATIC);
    if (memcmp(data, "POVT", 4) != 0 || data[4] != 1)
    {
        I_Error("pov-control: POVTHEME has the wrong magic or version");
    }
    pov_gamma_off = 1;
    s_outline_on = data[5] != 0;
    s_outline_index = data[6];
    memset(s_outline_of, s_outline_index, 256);
    memset(s_is_outline, 0, 256);
    s_is_outline[s_outline_index] = 1;
    for (i = 0; i < numsectors; i++)
    {
        sectors[i].lightlevel = data[7];
    }
    memcpy(s_class, data + 8, 256);
    memcpy(s_rank, data + 264, 256);
    if (s_outline_on)
    {
        static unsigned short idmem[POV_MAX_W * POV_MAX_H];
        static unsigned char shotmem[POV_MAX_W * POV_MAX_H];

        pov_idbuf = idmem;
        s_shot = shotmem;
    }
}

// The variants of a theme (lump POVX, optional; without it every kind has the one look named in s_kind):
//   0..3 "POVX", 4 version (1), 5 texel bits to the unit of the wall textures (0 or 1), 6 side of a
//   flat in bits (6 or 8), 7 flat texel bits to the unit (0..2);
//   then for the empty cell 16 slots of 4 flat names (8 bytes, zero padded; joint on west/south edge),
//   then for cell, wall, tower, own: 16 slots of 2 wall texture names (east/west, north/south)
//   followed by 16 flat names (the top face). A slot is picked from the world position of a cell
//   (set_kind); a theme repeats a look in several slots to make it more frequent.
#define POVX_LUMP_SIZE (8 + POV_SLOTS * 4 * 8 + 4 * (POV_SLOTS * 2 * 8 + POV_SLOTS * 8))

static short name_flat(const unsigned char *p)
{
    char buf[9];

    memcpy(buf, p, 8);
    buf[8] = '\0';
    return flat_num(buf);
}

static short name_tex(const unsigned char *p)
{
    char buf[9];

    memcpy(buf, p, 8);
    buf[8] = '\0';
    return tex_num(buf);
}

// The strokes of a theme (lump POVINK, optional): 0..3 "POVK", 4 version (1), 8..263 the index a thinned point of a
// stroke becomes (0: the index is no stroke), 264..519 1 for a stroke on a floor. See ink_pass.
#define POVINK_LUMP_SIZE 520

static void ink_init(void)
{
    int lump = W_CheckNumForName("POVINK");
    unsigned char *data;

    if (!s_theme_on || lump < 0)
    {
        return;
    }
    if (W_LumpLength(lump) != POVINK_LUMP_SIZE)
    {
        I_Error("pov-control: POVINK must be %d bytes, it has %d", POVINK_LUMP_SIZE, W_LumpLength(lump));
    }
    data = W_CacheLumpNum(lump, PU_STATIC);
    if (memcmp(data, "POVK", 4) != 0 || data[4] != 1)
    {
        I_Error("pov-control: POVINK has the wrong magic or version");
    }
    memcpy(s_ink_repl, data + 8, 256);
    memcpy(s_ink_floor, data + 264, 256);
    s_ink_on = 1;
}

// The haze of a theme (lump POVFOG, optional): 0..3 "POVF", 4 version (1), 6..7 the distance in units beyond which the
// field is one COLORMAP row further (flats and walls: pov_fog_j, pov_fog_scale), 8..263 per colour index the index of a
// line drawn on a point of it (a hazed navy on a hazed surface). See make_theme.py `povfog_lump`.
#define POVFOG_LUMP_SIZE 264

extern void R_InitLightTables(void);

static void fog_init(void)
{
    int lump = W_CheckNumForName("POVFOG");
    unsigned char *data;
    int i, units;

    if (!s_theme_on || lump < 0)
    {
        return;
    }
    if (W_LumpLength(lump) != POVFOG_LUMP_SIZE)
    {
        I_Error("pov-control: POVFOG must be %d bytes, it has %d", POVFOG_LUMP_SIZE, W_LumpLength(lump));
    }
    data = W_CacheLumpNum(lump, PU_STATIC);
    units = data[6] | (data[7] << 8);
    if (memcmp(data, "POVF", 4) != 0 || data[4] != 1 || units < 640)
    {
        I_Error("pov-control: POVFOG has the wrong magic, version or distance");
    }
    memcpy(s_outline_of, data + 8, 256);
    for (i = 0; i < 256; i++)
    {
        s_is_outline[s_outline_of[i]] = 1;
    }
    pov_fog_j = (units + 15) / 16 - 1;
    pov_fog_scale = (int)((160LL * 65536) / units);
    R_InitLightTables();          // the tables were built at start without the haze
}

static void variants_init(void)
{
    int k, s, e;
    int lump = W_CheckNumForName("POVX");
    const int have_x = s_theme_on && lump >= 0;
    const unsigned char *data, *q;
    static const int order[4] = { K_CELL, K_WALL, K_TOWER, K_OWN };

    // one look per kind (the original, without a theme: byte for byte the old pictures); a theme with
    // variants only needs the plain faces of the empty cell here
    for (k = 0; k < K_COUNT; k++)
    {
        short fl = 0;
        short tx, ty;

        if (have_x && k != K_EMPTY)
        {
            continue;
        }
        tx = tex_num(s_theme_on ? s_kind[k].theme_x : s_kind[k].lower);
        ty = tex_num(s_theme_on ? s_kind[k].theme_y : s_kind[k].lower);
        if (!have_x)
        {
            fl = flat_num(s_kind[k].flat);
        }
        for (s = 0; s < POV_SLOTS; s++)
        {
            s_texnum[k][s][0] = tx;
            s_texnum[k][s][1] = ty;
            for (e = 0; e < 4; e++)
            {
                s_flatnum[k][s][e] = fl;
            }
        }
    }
    if (!have_x)
    {
        return;
    }
    if (W_LumpLength(lump) != POVX_LUMP_SIZE)
    {
        I_Error("pov-control: POVX must be %d bytes, it has %d", POVX_LUMP_SIZE, W_LumpLength(lump));
    }
    data = W_CacheLumpNum(lump, PU_STATIC);
    if (memcmp(data, "POVX", 4) != 0 || data[4] != 1 || data[5] > 1 || (data[6] != 6 && data[6] != 8) || data[7] > 2)
    {
        I_Error("pov-control: POVX has the wrong magic, version or geometry");
    }
    pov_tex_dshift = data[5];
    pov_flat_bits = data[6];
    pov_flat_dshift = data[7];
    q = data + 8;
    for (s = 0; s < POV_SLOTS; s++)
    {
        for (e = 0; e < 4; e++, q += 8)
        {
            s_flatnum[K_EMPTY][s][e] = name_flat(q);
        }
    }
    for (k = 0; k < 4; k++)
    {
        int kind = order[k];

        for (s = 0; s < POV_SLOTS; s++, q += 16)
        {
            s_texnum[kind][s][0] = name_tex(q);
            s_texnum[kind][s][1] = name_tex(q + 8);
        }
        for (s = 0; s < POV_SLOTS; s++, q += 8)
        {
            for (e = 0; e < 4; e++)
            {
                s_flatnum[kind][s][e] = name_flat(q);
            }
        }
    }
}

static int is_edge(int p, int q)
{
    unsigned char a = s_shot[p], b = s_shot[q];
    int ia = pov_idbuf[p], ib = pov_idbuf[q];

    if (a == b && ia == ib)
    {
        return 0;       // the common case, and what the rules below give for it
    }
    if (ia != 0 && ib != 0 && ia != ib)
    {
        // two wall planes: the line goes on the one with the lower id (any fixed rule will do)
        return ia < ib;
    }
    if (s_class[a] == s_class[b])
    {
        return 0;
    }
    return s_rank[a] < s_rank[b] || (s_rank[a] == s_rank[b] && s_class[a] < s_class[b]);
}

// Width of the line in points: 1, or 2 from POV_OUTLINE_WIDE_FROM on (decided by looking at the
// samples, COSMERGON.md "Picture size"). At 320 points shown twice the line was 2 screen points.
#define POV_OUTLINE_WIDE_FROM 901
static int s_outline_width = 1;

// Strokes drawn into a texture are 1, 2 or 4 texels wide; a texel is up to several points near the viewer, so
// a stroke would be thicker than the outline. The thinning pass keeps of a stroke only `width` points (that of
// the outline, 1 or 2) and sets the others back to the colour under the stroke. Which edge it keeps follows the
// run lengths of a point (INK_CAP at most): a stroke that is longer across than up and down keeps its top rows,
// any other its left columns; where both runs are long (a crossing, a corner, a big block) a point is kept when
// either count is small. Floor strokes that run across the picture and are no thicker than the outline are
// dropped altogether (a joint across the view is thinner than a point row from some distance on and would come
// and go with every step of the camera; the whole run goes, judged by its thickest sampled point, so that no
// dashes are left): only strokes that run into the depth reach far. Only stroke indices are touched; the counts
// follow the picture as drawn, not the points already set back.
#define INK_CAP 24
static unsigned short s_ink_up[POV_MAX_W];

static int ink_at(const unsigned char *buf, int p)
{
    return s_ink_repl[buf[p]] != 0;
}

// Number of stroke points below (x, y) (up to `limit`), in the rows not yet visited.
static int ink_below(const unsigned char *buf, int x, int y, int w, int h, int limit)
{
    int k = 0;

    while (k < limit && y + 1 + k < h && ink_at(buf, (y + 1 + k) * w + x))
    {
        k++;
    }
    return k;
}

// Length of the run of stroke points that starts at x in this row (at most `limit`).
static int ink_run(const unsigned char *row, int x, int w, int limit)
{
    int n = 1;

    while (n < limit && x + n < w && ink_at(row, x + n))
    {
        n++;
    }
    return n;
}

// A floor stroke run that is across the view and no thicker than `width`: its thickest sampled point.
static int ink_run_is_sliver(int x, int y, int w, int h, int run, int width)
{
    int k;

    if (run < 3)
    {
        return 0;
    }
    for (k = 0; k < run; k += 4)
    {
        if (s_ink_up[x + k] + 1 + ink_below(I_VideoBuffer, x + k, y, w, h, width) > width)
        {
            return 0;
        }
    }
    return 1;
}

// A run of one or two stroke points on a floor with no stroke point in the rows above and below it (up_left: what
// the row above had at x - 1): a speck, which would only be noise far away.
static int ink_is_speck(int x, int y, int w, int h, int up_left, int run)
{
    int k;

    if (run > 2 || up_left || (x + run < w && s_ink_up[x + run]) || y + 1 >= h)
    {
        return 0;
    }
    for (k = -1; k <= run; k++)
    {
        if (x + k < 0 || x + k >= w)
        {
            continue;
        }
        if ((k >= 0 && k < run && s_ink_up[x + k]) || ink_at(I_VideoBuffer, (y + 1) * w + x + k))
        {
            return 0;
        }
    }
    return 1;
}

static int ink_keep(int up, int left, int vert, int horz, int width)
{
    if (vert >= INK_CAP && horz >= INK_CAP)
    {
        return up < width || left < width;
    }
    return vert < horz ? up < width : left < width;
}

static void ink_pass(void)
{
    const int w = pov_view_w, h = pov_view_h;
    const int width = w >= POV_OUTLINE_WIDE_FROM ? 2 : 1;
    int x, y;

    memset(s_ink_up, 0, sizeof(s_ink_up[0]) * (size_t)w);
    for (y = 0; y < h; y++)
    {
        unsigned char *row = I_VideoBuffer + (size_t)y * w;
        int left = 0, run = 0, sliver = 0, up_left = 0;

        for (x = 0; x < w; x++)
        {
            unsigned char v = row[x];
            unsigned char repl = s_ink_repl[v];
            int up = s_ink_up[x], vert, horz;

            if (repl == 0)
            {
                up_left = up;
                s_ink_up[x] = 0;
                left = 0;
                continue;
            }
            if (left == 0)
            {
                run = ink_run(row, x, w, 64);
                sliver = s_ink_floor[v] && (ink_run_is_sliver(x, y, w, h, run, width)
                                            || ink_is_speck(x, y, w, h, up_left, run));
            }
            vert = up + 1 + ink_below(I_VideoBuffer, x, y, w, h, INK_CAP);
            horz = left + ink_run(row, x, w, INK_CAP);
            if (sliver || !ink_keep(up, left, vert, horz, width))
            {
                row[x] = repl;
            }
            up_left = up;
            s_ink_up[x] = (unsigned short)(up < 60000 ? up + 1 : up);
            left++;
        }
    }
}

// Lines on the finished picture (8 bit, before the palette): one point, on the side of the
// lower rank, so a surface keeps its full area and the line sits outside of it. The picture is
// pov_view_w x pov_view_h bytes, tightly packed (stride = width, pov_stride).
static void outline_pass(void)
{
    static int line_points[POV_MAX_W * POV_MAX_H];      // the points set in the first pass
    static int grow_points[POV_MAX_W * POV_MAX_H];      // the points the second pass adds
    int x, y, k;
    int w = pov_view_w, h = pov_view_h;
    int lines = 0, grown = 0;

    memcpy(s_shot, I_VideoBuffer, (size_t)w * h);
    for (y = 0; y < h; y++)
    {
        for (x = 0; x < w; x++)
        {
            int p = y * w + x;
            int hit = 0;

            if (x + 1 < w) hit |= is_edge(p, p + 1);
            if (x > 0) hit |= is_edge(p, p - 1);
            if (y + 1 < h) hit |= is_edge(p, p + w);
            if (y > 0) hit |= is_edge(p, p - w);
            if (hit)
            {
                I_VideoBuffer[p] = s_outline_of[s_shot[p]];
                line_points[lines++] = p;
            }
        }
    }
    if (s_outline_width < 2)
    {
        return;
    }
    // Second point: next to a line point, a point of the same surface as the line point's original.
    // Marked in pov_idbuf (bit 15; wall ids are small) and listed first, applied afterwards, so that
    // the line grows by exactly one point. The work follows the length of the lines, not the picture.
    for (k = 0; k < lines; k++)
    {
        int q = line_points[k];
        int qx = q % w, qy = q / w;
        int n[4], m = 0, i;

        if (qx + 1 < w) n[m++] = q + 1;
        if (qx > 0) n[m++] = q - 1;
        if (qy + 1 < h) n[m++] = q + w;
        if (qy > 0) n[m++] = q - w;
        for (i = 0; i < m; i++)
        {
            int p = n[i];

            if (!s_is_outline[I_VideoBuffer[p]] && !(pov_idbuf[p] & 0x8000)
                && s_class[s_shot[q]] == s_class[s_shot[p]])
            {
                pov_idbuf[p] |= 0x8000;
                grow_points[grown++] = p;
            }
        }
    }
    for (k = 0; k < grown; k++)
    {
        I_VideoBuffer[grow_points[k]] = s_outline_of[s_shot[grow_points[k]]];
    }
}

static void init_world(void)
{
    int i, d;
    mobj_t *mo;

    if (numsectors != POVC_CELLS || numsubsectors != POVC_CELLS)
    {
        I_Error("pov-control: the map must be the 48 x 48 grid map (sectors %d, subsectors %d)",
                numsectors, numsubsectors);
    }
    for (i = 0; i < POVC_CELLS; i++)
    {
        for (d = 0; d < 4; d++)
        {
            s_facing[i][d] = -1;
        }
    }
    for (i = 0; i < numlines; i++)
    {
        line_t *line = &lines[i];
        int s0, s1, delta;

        if (line->sidenum[1] == -1)
        {
            continue;
        }
        s0 = (int)(sides[line->sidenum[0]].sector - sectors);
        s1 = (int)(sides[line->sidenum[1]].sector - sectors);
        delta = s1 - s0;
        d = delta == 1 ? 0 : delta == -1 ? 1 : delta == POVC_GRID ? 2 : delta == -POVC_GRID ? 3 : -1;
        if (d < 0 || neighbour(s0, d) != s1)
        {
            I_Error("pov-control: line %d joins sectors %d and %d, not neighbours of the grid", i, s0, s1);
        }
        s_facing[s0][d] = line->sidenum[0];
        s_facing[s1][opposite(d)] = line->sidenum[1];
    }
    for (i = 0; i < POVC_CELLS; i++)
    {
        subsector_t *ss;

        for (d = 0; d < 4; d++)
        {
            if (neighbour(i, d) >= 0 && s_facing[i][d] < 0)
            {
                I_Error("pov-control: cell %d has no sidedef towards direction %d", i, d);
            }
        }
        // the cell centre must lie in the subsector of the same number (index = y * 48 + x)
        ss = R_PointInSubsector(to_fixed_world(i % POVC_GRID + 0.5), to_fixed_world(i / POVC_GRID + 0.5));
        if (ss->sector != &sectors[i] || (int)(ss - subsectors) != i)
        {
            I_Error("pov-control: cell %d is not sector/subsector %d", i, i);
        }
    }
    theme_init();
    ink_init();
    variants_init();
    fog_init();
    POV_SkyLoad();
    // Whatever pattern the map was generated with: start with everything empty.
    for (i = 0; i < POVC_CELLS; i++)
    {
        s_moving_at[i] = -1;
        set_kind_now(i, K_EMPTY);
    }
    rise_from_command_line();
    s_trace = getenv("POV_RISE_TRACE") != NULL;
    snap_open();
    s_clock_ms = (unsigned)I_GetTimeMS();

    // The player: keeps no sector link (never drawn), no blockmap link, never moves by itself.
    mo = players[consoleplayer].mo;
    P_UnsetThingPosition(mo);
    mo->flags |= MF_NOSECTOR | MF_NOBLOCKMAP;
    mo->momx = mo->momy = mo->momz = 0;
    P_SetThingPosition(mo);
    camera_place(to_fixed_world(POVC_GRID / 2.0 + 0.5), to_fixed_world(POVC_GRID / 2.0 + 0.5), 0);
    players[consoleplayer].extralight = 0;
    players[consoleplayer].fixedcolormap = 0;

    // Full picture 3D view, no status bar. The palette is set once (nothing else does it here).
    size_from_command_line();
    R_SetViewSize(11, 0);
    if (POV_SkyActive())
    {
        sky_palette();
    }
    else
    {
        I_SetPalette(W_CacheLumpName("PLAYPAL", PU_CACHE));
    }
    s_live_t0 = I_GetTimeMS();
    s_dirty = 1;        // live mode: the first picture is drawn without waiting for a line
    s_ready = 1;
}

void R_ExecuteSetViewSize(void);

static unsigned long s_drawn_step = 0;   // the clock at the last frame

static void render_frame(void)
{
    if (s_live)
    {
        rise_clock_live();
    }
    else
    {
        s_step++;       // blocking: every frame is one step
    }
    s_drawn_step = s_step;
    rise_update();
    if (s_trace)
    {
        int c;

        // measure for tests/test_rise.py: the floor (16.16 units), target kind and look of every raised cell
        s_trace_frame++;
        for (c = 0; c < POVC_CELLS; c++)
        {
            if (sectors[c].floorheight != 0 || s_look_of[c] != K_EMPTY || s_kind_of[c] != K_EMPTY)
            {
                fprintf(stderr, "rise: frame=%lu cell=%d h=%d kind=%d look=%d\n", s_trace_frame, c,
                        (int)sectors[c].floorheight, (int)s_kind_of[c], (int)s_look_of[c]);
            }
        }
    }
    commit();
    if (setsizeneeded)
    {
        R_ExecuteSetViewSize();
    }
    if (s_outline_on)
    {
        size_t points = (size_t)pov_view_w * pov_view_h;

        s_outline_width = pov_view_w >= POV_OUTLINE_WIDE_FROM ? 2 : 1;
        memset(pov_idbuf, 0, points * sizeof(*pov_idbuf));
        // the renderer leaves single pixels at some wall joints uncovered (upstream); they would
        // show the previous picture. Start from the outline colour: such a pixel becomes line.
        memset(I_VideoBuffer, s_outline_index, points);
    }
    R_RenderPlayerView(&players[consoleplayer]);
    if (s_ink_on)
    {
        ink_pass();
    }
    if (s_outline_on)
    {
        outline_pass();
    }
    s_dirty = 0;
    // blocking: the window's snap ends with the first frame (a `next` ends a picture); live it ends in the
    // tick, when the filling has had its time (POV_ControlTick)
    if (!s_live)
    {
        s_snap = 0;
    }
    I_FinishUpdate();       // -> DG_DrawFrame
}

void POV_ControlTick(void)
{
    if (!s_ready)
    {
        int i;

        // the first game tics load the level; after that the game loop never runs again
        for (i = 0; i < 200 && !level_loaded(); i++)
        {
            I_StartFrame();
            TryRunTics();
        }
        if (!level_loaded())
        {
            I_Error("pov-control: the level did not load");
        }
        init_world();
        return;
    }

    if (s_live && POV_SkyActive())
    {
        // the clouds drift on the clock; a picture is due only when they moved a whole point
        POV_SkySetCloudLive((double)(I_GetTimeMS() - s_live_t0));
        if (POV_SkyDirty())
        {
            s_dirty = 1;
        }
    }
    if (s_live)
    {
        rise_clock_live();
        // the lines of one picture may arrive in two reads: the snap stays open for a while, never longer
        if (s_snap && s_snap_started && s_step - s_snap_step >= POV_SNAP_LIVE_STEPS)
        {
            s_snap = 0;
        }
    }
    pump();
    if (s_live && s_moving_n > 0 && s_step != s_drawn_step)
    {
        s_dirty = 1;        // something travels and the clock moved: the next picture
    }
    if (s_quit)
    {
        s_done = 1;
        return;
    }
    if (s_input_done && s_pending == 0)
    {
        if (s_live && s_dirty)
        {
            render_frame();     // the last changes get one frame before the end
        }
        s_done = 1;
        return;
    }
    if (s_pending > 0)
    {
        s_pending--;
        render_frame();
    }
    else if (s_live && s_dirty)
    {
        // live: a picture only when something changed. What costs is drawing, so the cost
        // follows the writer's rate and a still world costs nothing (measured, COSMERGON.md).
        render_frame();
    }
}
