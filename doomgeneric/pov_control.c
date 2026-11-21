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

// Things: the sprite of each kind (frame A, the 8 rotations show the facing).
static const struct
{
    const char *name;
    spritenum_t sprite;
} s_thing_kind[] = {
    { "marauder", SPR_TROO },
    { "loot",     SPR_BPAK },
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
static unsigned long s_pending = 0;      // frames still to draw for `next`
static unsigned long s_lines = 0;
static unsigned long s_rejected = 0;
static int s_summary_done = 0;

static unsigned char s_kind_of[POVC_CELLS];
static short s_texnum[K_COUNT][2];   // [kind][0 = edge facing east/west, 1 = north/south]
static short s_flatnum[K_COUNT];
static short s_facing[POVC_CELLS][4];    // side index of the cell's sidedef facing east/west/north/south

typedef struct
{
    int    used;
    int    linked;
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

// Sets the kind of one cell: its floor height and flat, and the lower texture on the sidedef of
// each neighbour that faces it. The wall texture of a step is the lower texture of the sidedef
// on the LOWER side (r_segs.c R_StoreWallRange: the seg's own sidedef, drawn when the back floor
// is higher). So the texture seen from outside a cell of kind K sits on the neighbour's side.
static void set_kind(int cell, int kind)
{
    int d;
    sector_t *sector = &sectors[cell];

    s_kind_of[cell] = (unsigned char)kind;
    sector->floorheight = s_kind[kind].height * FRACUNIT;
    sector->floorpic = s_flatnum[kind];
    for (d = 0; d < 4; d++)
    {
        int other = neighbour(cell, d);

        if (other >= 0)
        {
            sides[s_facing[other][opposite(d)]].bottomtexture = s_texnum[kind][d >> 1];
        }
    }
    s_dirty = 1;
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
    t->mo.sprite = s_thing_kind[kind].sprite;
    t->mo.frame = 0;
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
            t->mo.z = t->mo.subsector->sector->floorheight;
        }
    }
    p->mo->z = p->mo->subsector->sector->floorheight;
    p->viewz = p->mo->z + POV_EYE * FRACUNIT;
}

// ---------------------------------------------------------------------------------------
// Parser: one line -> one validated command. Nothing is applied before the whole line is valid.
// ---------------------------------------------------------------------------------------
typedef enum { OP_CELL, OP_ROW, OP_THING, OP_GONE, OP_CAM, OP_LIGHT, OP_NEXT, OP_QUIT } op_t;

typedef struct
{
    op_t   op;
    int    a, b;                       // cell x/y, row y, id, light, next n
    int    kind;
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
static unsigned char s_class[256];
static unsigned char s_rank[256];
static unsigned char *s_shot = NULL;       // copy of the picture the outline is derived from

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
    for (i = 0; i < numsectors; i++)
    {
        sectors[i].lightlevel = data[7];
    }
    memcpy(s_class, data + 8, 256);
    memcpy(s_rank, data + 264, 256);
    if (s_outline_on)
    {
        static unsigned short idmem[SCREENWIDTH * SCREENHEIGHT];
        static unsigned char shotmem[SCREENWIDTH * SCREENHEIGHT];

        pov_idbuf = idmem;
        s_shot = shotmem;
    }
}

static int is_edge(int p, int q)
{
    unsigned char a = s_shot[p], b = s_shot[q];
    int ia = pov_idbuf[p], ib = pov_idbuf[q];

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

// Lines on the finished picture (8 bit, before the palette): one pixel, on the side of the
// lower rank, so a surface keeps its full area and the line sits outside of it.
static void outline_pass(void)
{
    int x, y;

    memcpy(s_shot, I_VideoBuffer, SCREENWIDTH * SCREENHEIGHT);
    for (y = 0; y < SCREENHEIGHT; y++)
    {
        for (x = 0; x < SCREENWIDTH; x++)
        {
            int p = y * SCREENWIDTH + x;
            int hit = 0;

            if (x + 1 < SCREENWIDTH) hit |= is_edge(p, p + 1);
            if (x > 0) hit |= is_edge(p, p - 1);
            if (y + 1 < SCREENHEIGHT) hit |= is_edge(p, p + SCREENWIDTH);
            if (y > 0) hit |= is_edge(p, p - SCREENWIDTH);
            if (hit)
            {
                I_VideoBuffer[p] = s_outline_index;
            }
        }
    }
}

static void init_world(void)
{
    int i, d, k;
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
    for (k = 0; k < K_COUNT; k++)
    {
        s_texnum[k][0] = tex_num(s_theme_on ? s_kind[k].theme_x : s_kind[k].lower);
        s_texnum[k][1] = tex_num(s_theme_on ? s_kind[k].theme_y : s_kind[k].lower);
        s_flatnum[k] = flat_num(s_kind[k].flat);
    }
    // Whatever pattern the map was generated with: start with everything empty.
    for (i = 0; i < POVC_CELLS; i++)
    {
        set_kind(i, K_EMPTY);
    }

    // The player: keeps no sector link (never drawn), no blockmap link, never moves by itself.
    mo = players[consoleplayer].mo;
    P_UnsetThingPosition(mo);
    mo->flags |= MF_NOSECTOR | MF_NOBLOCKMAP;
    mo->momx = mo->momy = mo->momz = 0;
    P_SetThingPosition(mo);
    camera_place(to_fixed_world(POVC_GRID / 2.0 + 0.5), to_fixed_world(POVC_GRID / 2.0 + 0.5), 0);
    players[consoleplayer].extralight = 0;
    players[consoleplayer].fixedcolormap = 0;

    // Full screen 3D view, no status bar. The palette is set once (nothing else does it here).
    R_SetViewSize(11, 0);
    I_SetPalette(W_CacheLumpName("PLAYPAL", PU_CACHE));
    s_dirty = 1;        // live mode: the first picture is drawn without waiting for a line
    s_ready = 1;
}

extern boolean setsizeneeded;
void R_ExecuteSetViewSize(void);

static void render_frame(void)
{
    commit();
    if (setsizeneeded)
    {
        R_ExecuteSetViewSize();
    }
    if (s_outline_on)
    {
        memset(pov_idbuf, 0, SCREENWIDTH * SCREENHEIGHT * sizeof(*pov_idbuf));
        // the renderer leaves single pixels at some wall joints uncovered (upstream); they would
        // show the previous picture. Start from the outline colour: such a pixel becomes line.
        memset(I_VideoBuffer, s_outline_index, SCREENWIDTH * SCREENHEIGHT);
    }
    R_RenderPlayerView(&players[consoleplayer]);
    if (s_outline_on)
    {
        outline_pass();
    }
    s_dirty = 0;
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

    pump();
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
