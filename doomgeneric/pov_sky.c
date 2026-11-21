// cosmergon-pov: the sky of a theme. See pov_sky.h and COSMERGON.md ("The sky").
//
// The sky is drawn point by point in the size of the picture (no texture of the sky: the old 1024 x 128 one made
// the sun an ellipse). A point of the picture looks along (u, v, 1): u = x offset / f, v = y offset / f, f =
// width / 2 (the angle of view is 90 degrees across); azimuth = viewangle + xtoviewangle[x], tan(elevation) =
// v / sqrt(1 + u * u). Rows and columns step alike, which is what makes a disc round.
//
// Back to front: bands of elevation, stars, the sun (day) or moon (night); then the THINGS OF THE WORLD, with a
// depth per point: clouds (upright pictures turned to the viewer, at world positions, perspective by their
// distance) and the neighbour cubes (boxes at their grid positions). A point takes the nearer of two things, so a
// cloud passes in front of a cube or behind it. Everything stands in the world: the eye is the position of the
// camera in the world (the `world` line, `origin` and `cam`), the time of the clouds is the world time.

#include <math.h>
#include <string.h>

#include "i_system.h"
#include "i_video.h"
#include "m_fixed.h"
#include "r_local.h"
#include "w_wad.h"
#include "z_zone.h"

#include "pov_sky.h"

extern byte *ylookup[];       // r_draw.c
extern int columnofs[];

#define BAND_ROWS    512                         // the bands are a table of rows of tan(elevation) * BAND_RPT
#define BAND_RPT     651.9
#define SKY_MAX_KEYS 32
#define SKY_MAX_BANDS 32
#define MAX_CLOUDS   1024
#define MAX_STARS    512
#define MAX_SHAPES   16
#define MAX_MIPS     6
#define MAX_CUBES    64
#define UNITS_M      32.0                        // units a metre (a cell of 128 units is 4 m)
#define ORIGIN_X     (-3072.0)                   // map coordinate of the window's south-west corner (pov_control.c)

// The time of day (the same numbers are in tools/sky_art.py, which the tests compare).
#define SUN_RISE      360        // minutes: 06:00
#define SUN_SET       1140       // 19:00; the moon runs from 19:00 to 06:00
#define MOON_SPAN     660
#define SKY_EL_MAX    21.0       // highest elevation of sun and moon, degrees (higher is never in the picture)
#define SUN_RADIUS    4.5        // angular radius, degrees
#define MOON_RADIUS   3.6
// Distances (metres) at which a cloud or a cube goes one step further into the haze.
static const double s_cloud_haze_m[3] = { 1800.0, 3200.0, 5000.0 };
static const double s_cube_haze_m[3] = { 1000.0, 2000.0, 3500.0 };
#define CLOUD_MIN_PW  3.0        // a cloud narrower than this (points) is not drawn
#define CLOUD_MAX_PW  1500.0     // wider than this a texel is more than 1.5 points: not drawn (a cloud overhead)
#define CUBE_LINE_PX  12.0       // the levels of a cube are drawn where they are at least this far apart (points)

typedef struct { int x, y, z, w; unsigned char shape; } cloud_t;
typedef struct { int used, cx, cy, cz, dim; } cube_t;

static int s_on = 0;
static const unsigned char *s_pal = NULL;        // key palettes, 768 bytes each
static int s_nkeys = 0, s_nbands = 0;
static int s_key_min[SKY_MAX_KEYS], s_key_stars[SKY_MAX_KEYS];
static int s_band_deg10 = 30;
static unsigned char s_i_sun, s_i_moon, s_i_star, s_i_band0;
static unsigned char s_i_cloud[4][2], s_i_cube[4][5];
static unsigned char s_bandtab[BAND_ROWS];
static int s_minute = 720;
static double s_cloud_base_ms = 0, s_cloud_live_ms = 0;

// the world
static int s_wcx = 0, s_wcy = 0, s_wcz = 0, s_wlevel = 0, s_wdim = 128;
static int s_origin_x = 0, s_origin_y = 0;
static cube_t s_cubes[MAX_CUBES];

// the clouds (lumps POVWLD, POVCLS) and the stars (POVSTR)
static cloud_t s_cl[MAX_CLOUDS];
static int s_ncl = 0;
static double s_period = 1.0, s_wind_x = 0.0, s_wind_y = 0.0;
static const unsigned char *s_spr = NULL;
static int s_nshapes = 0, s_nmips = 0, s_spr_w = 1, s_spr_h = 1;
static long s_spr_off[MAX_SHAPES][MAX_MIPS];
static unsigned short s_star_az[MAX_STARS], s_star_el[MAX_STARS];
static int s_nstars = 0;

// per picture
typedef struct
{
    double ex, ey, ez, fx, fy, rx, ry, f, cx, cy;   // eye, forward and right (world xy), the projection
} frame_t;
typedef struct
{
    double depth, x0, pw, yb, ph;
    int x0i, x1i, mip, shape, fog;
} vcloud_t;
typedef struct
{
    double rx0, rx1, ry0, ry1, dzb, dzt, width;      // relative to the eye
} vcube_t;

static frame_t s_fr;
static int s_frame_ok = 0;
static vcloud_t s_vis[MAX_CLOUDS];
static int s_nvis = 0;
static double s_cx_drawn[MAX_CLOUDS];            // screen x of each cloud in the picture drawn last (NaN: not shown)
static vcube_t s_vcube[MAX_CUBES];
static int s_nvcube = 0;
static int s_body = 0;                           // 0 none, 1 sun, 2 moon
static int s_stars_on = 0;
static int s_star_size = 1;
static float s_depth[POV_MAX_H];
static double s_stepd[POV_MAX_W];                // band rows a point down, per column
static int s_b0[POV_MAX_W], s_b1[POV_MAX_W];     // rows of the body, inclusive; b0 > b1: none
static int s_k0[POV_MAX_W], s_k1[POV_MAX_W];     // rows cut out of the body (the moon's crescent)
static int s_star_head[POV_MAX_W];               // per column: first of the stars in it (index into s_star_y)
static int s_star_y[MAX_STARS * 3], s_star_next[MAX_STARS * 3];
static int s_nstar_entries = 0;

int POV_SkyActive(void) { return s_on; }
int POV_SkyMinute(void) { return s_minute; }

static const unsigned char *lump_data(const char *name, int size)
{
    int lump = W_CheckNumForName((char *)name);

    if (lump < 0)
    {
        return NULL;
    }
    if (size >= 0 && W_LumpLength(lump) != size)
    {
        I_Error("pov-sky: lump %s must have %d bytes, it has %d", name, size, W_LumpLength(lump));
    }
    return W_CacheLumpNum(lump, PU_STATIC);
}

static int lump_len(const char *name)
{
    return W_LumpLength(W_GetNumForName((char *)name));
}

static int le32(const unsigned char *p)
{
    return (int)(p[0] | (p[1] << 8) | (p[2] << 16) | ((unsigned)p[3] << 24));
}

static void load_header(void)
{
    const unsigned char *h = lump_data("POVSKY", -1);
    int i;

    if (memcmp(h, "POVS", 4) != 0 || h[4] != 2)
    {
        I_Error("pov-sky: POVSKY has the wrong magic or version");
    }
    s_nbands = h[5];
    s_nkeys = h[6];
    s_band_deg10 = h[7];
    s_i_sun = h[8]; s_i_moon = h[9]; s_i_star = h[10]; s_i_band0 = h[11];
    memcpy(s_i_cloud, h + 12, 8);
    memcpy(s_i_cube, h + 20, 20);
    if (s_nbands < 1 || s_nbands > SKY_MAX_BANDS || s_nkeys < 2 || s_nkeys > SKY_MAX_KEYS || s_band_deg10 < 1
        || lump_len("POVSKY") != 40 + 4 * s_nkeys)
    {
        I_Error("pov-sky: POVSKY has a wrong count or size");
    }
    for (i = 0; i < s_nkeys; i++)
    {
        s_key_min[i] = h[40 + 4 * i] | (h[41 + 4 * i] << 8);
        s_key_stars[i] = h[42 + 4 * i];
        if (i > 0 && s_key_min[i] <= s_key_min[i - 1])
        {
            I_Error("pov-sky: the key minutes must rise");
        }
    }
    if (s_key_min[0] != 0 || s_key_min[s_nkeys - 1] != 1440)
    {
        I_Error("pov-sky: the keys must run from minute 0 to 1440");
    }
    s_pal = lump_data("PLAYPAL", 768 * s_nkeys);
}

static void load_world(const unsigned char *w)
{
    float wx, wy;
    int i;

    s_period = le32(w + 8);
    memcpy(&wx, w + 12, 4);
    memcpy(&wy, w + 16, 4);
    s_wind_x = wx;
    s_wind_y = wy;
    s_ncl = le32(w + 20);
    if (s_ncl < 0 || s_ncl > MAX_CLOUDS || lump_len("POVWLD") != 24 + 20 * s_ncl || s_period < 1.0)
    {
        I_Error("pov-sky: POVWLD has a wrong count or size");
    }
    for (i = 0; i < s_ncl; i++)
    {
        const unsigned char *r = w + 24 + 20 * i;

        s_cl[i].x = le32(r); s_cl[i].y = le32(r + 4); s_cl[i].z = le32(r + 8); s_cl[i].w = le32(r + 12);
        s_cl[i].shape = r[16];
        if (s_cl[i].w < 1)
        {
            I_Error("pov-sky: a cloud has no width");
        }
    }
}

static void load_sprites(const unsigned char *c)
{
    long len = 0;
    int k, m;

    s_nshapes = c[5];
    s_nmips = c[6];
    s_spr_w = c[8] | (c[9] << 8);
    s_spr_h = c[10] | (c[11] << 8);
    if (s_nshapes < 1 || s_nshapes > MAX_SHAPES || s_nmips < 1 || s_nmips > MAX_MIPS || s_spr_w < 1 || s_spr_h < 1)
    {
        I_Error("pov-sky: POVCLS has a wrong count");
    }
    s_spr = c + 12;
    for (k = 0; k < s_nshapes; k++)
    {
        for (m = 0; m < s_nmips; m++)
        {
            s_spr_off[k][m] = len;
            len += (long)(s_spr_w >> m) * (s_spr_h >> m);
        }
    }
    if (lump_len("POVCLS") != 12 + len)
    {
        I_Error("pov-sky: POVCLS has a wrong size");
    }
}

static void load_clouds(void)
{
    const unsigned char *w = lump_data("POVWLD", -1), *c = lump_data("POVCLS", -1);
    const unsigned char *s = lump_data("POVSTR", -1);
    int i;

    if (w == NULL || c == NULL || s == NULL || memcmp(w, "POVW", 4) != 0 || memcmp(c, "POVC", 4) != 0
        || memcmp(s, "POVR", 4) != 0 || w[4] != 1 || c[4] != 1)
    {
        I_Error("pov-sky: lumps POVWLD, POVCLS and POVSTR (version 1) are needed");
    }
    load_world(w);
    load_sprites(c);
    s_nstars = le32(s + 8);
    if (s_nstars < 0 || s_nstars > MAX_STARS || lump_len("POVSTR") != 12 + 4 * s_nstars)
    {
        I_Error("pov-sky: POVSTR has a wrong count or size");
    }
    for (i = 0; i < s_nstars; i++)
    {
        s_star_az[i] = (unsigned short)(s[12 + 4 * i] | (s[13 + 4 * i] << 8));
        s_star_el[i] = (unsigned short)(s[14 + 4 * i] | (s[15 + 4 * i] << 8));
    }
}

int POV_SkyLoad(void)
{
    int b;

    s_on = 0;
    if (W_CheckNumForName("POVSKY") < 0)
    {
        return 0;
    }
    load_header();
    load_clouds();
    for (b = 0; b < BAND_ROWS; b++)
    {
        int band = (int)(atan(b / BAND_RPT) * 1800.0 / M_PI / s_band_deg10);

        s_bandtab[b] = (unsigned char)(s_i_band0 + (band >= s_nbands ? s_nbands - 1 : band));
    }
    s_on = 1;
    return 1;
}

void POV_SkySetMinute(int minute) { s_minute = minute; }
void POV_SkySetCloudBase(double ms) { s_cloud_base_ms = ms; }
void POV_SkySetCloudLive(double ms) { s_cloud_live_ms = ms; }
void POV_SkySetWorld(int cx, int cy, int cz, int level, int dim)
{
    s_wcx = cx; s_wcy = cy; s_wcz = cz; s_wlevel = level; s_wdim = dim;
}
void POV_SkySetOrigin(int ox, int oy) { s_origin_x = ox; s_origin_y = oy; }
void POV_SkyCube(int id, int cx, int cy, int cz, int dim)
{
    s_cubes[id].used = 1; s_cubes[id].cx = cx; s_cubes[id].cy = cy; s_cubes[id].cz = cz; s_cubes[id].dim = dim;
}
void POV_SkyNoCube(int id) { s_cubes[id].used = 0; }

// Same rounding in tools/theme_day.py (palette_at): t in 0..256, (a * (256 - t) + b * t + 128) >> 8.
void POV_SkyPalette(int minute, unsigned char *out)
{
    int i, k = 0, t, span;

    while (k + 2 < s_nkeys && minute >= s_key_min[k + 1])
    {
        k++;
    }
    span = s_key_min[k + 1] - s_key_min[k];
    t = ((minute - s_key_min[k]) * 256 + span / 2) / span;
    for (i = 0; i < 768; i++)
    {
        out[i] = (unsigned char)((s_pal[768 * k + i] * (256 - t) + s_pal[768 * (k + 1) + i] * t + 128) >> 8);
    }
}

static int stars_at(int minute)
{
    int k = 0;

    while (k + 2 < s_nkeys && minute >= s_key_min[k + 1])
    {
        k++;
    }
    return s_key_stars[k] || s_key_stars[k + 1];
}

// ---------------------------------------------------------------------------------------
// The eye in the world, and the clouds as seen from it
// ---------------------------------------------------------------------------------------
static void frame_setup(frame_t *fr)
{
    double step = 2.5 * s_wdim * 128.0, th = viewangle * (2.0 * M_PI / 4294967296.0);

    fr->ex = s_wcx * step + s_origin_x * 128.0 + (viewx / 65536.0 - ORIGIN_X);
    fr->ey = s_wcy * step + s_origin_y * 128.0 + (viewy / 65536.0 - ORIGIN_X);
    fr->ez = s_wcz * step + s_wlevel * 128.0 + viewz / 65536.0;
    fr->fx = cos(th);
    fr->fy = sin(th);
    fr->rx = sin(th);
    fr->ry = -cos(th);
    fr->f = projection / 65536.0;
    fr->cx = centerxfrac / 65536.0;
    fr->cy = centeryfrac / 65536.0;
}

// Where cloud i is at world time t (seconds): screen centre x, row of its base, width and height in points, depth
// (forward, units) and distance (units). Returns 0 when it is behind the eye or cannot show.
static int cloud_geom(const frame_t *fr, int i, double t, vcloud_t *v, double *xc, double *rho)
{
    double dx = remainder(s_cl[i].x + s_wind_x * t - fr->ex, s_period);
    double dy = remainder(s_cl[i].y + s_wind_y * t - fr->ey, s_period);
    double dz = s_cl[i].z - fr->ez;
    double depth = dx * fr->fx + dy * fr->fy, lat = dx * fr->rx + dy * fr->ry, pw;

    if (depth <= 0.0)
    {
        return 0;
    }
    pw = fr->f * s_cl[i].w / depth;
    if (pw < CLOUD_MIN_PW || pw > CLOUD_MAX_PW)
    {
        return 0;
    }
    *xc = fr->cx + fr->f * lat / depth;
    *rho = sqrt(dx * dx + dy * dy + dz * dz);
    v->depth = depth;
    v->pw = pw;
    v->x0 = *xc - pw / 2.0;
    v->ph = pw * s_spr_h / s_spr_w;
    v->yb = fr->cy - fr->f * dz / depth;
    v->shape = s_cl[i].shape;
    return 1;
}

static int haze_step(double rho_units, const double *thresholds_m)
{
    int s = 0;

    while (s < 3 && rho_units / UNITS_M >= thresholds_m[s])
    {
        s++;
    }
    return s;
}

static int cloud_shown(const vcloud_t *v)
{
    return v->x0 + v->pw >= 0.0 && v->x0 < viewwidth && v->yb > 0.0 && v->yb - v->ph < centeryfrac / 65536.0;
}

static void clouds_begin(const frame_t *fr, double t)
{
    int i;

    s_nvis = 0;
    for (i = 0; i < s_ncl; i++)
    {
        vcloud_t v;
        double xc, rho;

        s_cx_drawn[i] = NAN;
        if (!cloud_geom(fr, i, t, &v, &xc, &rho) || !cloud_shown(&v))
        {
            continue;
        }
        s_cx_drawn[i] = xc;
        v.mip = (int)floor(log2((double)s_spr_w / v.pw));
        v.mip = v.mip < 0 ? 0 : (v.mip >= s_nmips ? s_nmips - 1 : v.mip);
        v.fog = haze_step(rho, s_cloud_haze_m);
        v.x0i = (int)floor(v.x0);
        v.x1i = (int)floor(v.x0 + v.pw);
        s_vis[s_nvis++] = v;
    }
}

// True when a cloud has moved a whole point since the picture drawn last: only then is a new picture due.
int POV_SkyDirty(void)
{
    double t = (s_cloud_base_ms + s_cloud_live_ms) / 1000.0;
    int i;

    if (!s_on || !s_frame_ok)
    {
        return 0;
    }
    for (i = 0; i < s_ncl; i++)
    {
        vcloud_t v;
        double xc, rho;
        int shown = cloud_geom(&s_fr, i, t, &v, &xc, &rho) && cloud_shown(&v);

        if (shown != !isnan(s_cx_drawn[i]) || (shown && fabs(xc - s_cx_drawn[i]) >= 1.0))
        {
            return 1;
        }
    }
    return 0;
}

// ---------------------------------------------------------------------------------------
// Cubes
// ---------------------------------------------------------------------------------------
static void cubes_begin(const frame_t *fr)
{
    int i;
    double step = 2.5 * s_wdim * 128.0;

    s_nvcube = 0;
    for (i = 0; i < MAX_CUBES; i++)
    {
        vcube_t *c = &s_vcube[s_nvcube];
        double w;

        if (!s_cubes[i].used)
        {
            continue;
        }
        w = s_cubes[i].dim * 128.0;
        c->rx0 = s_cubes[i].cx * step - fr->ex;
        c->rx1 = c->rx0 + w;
        c->ry0 = s_cubes[i].cy * step - fr->ey;
        c->ry1 = c->ry0 + w;
        c->dzb = s_cubes[i].cz * step - fr->ez;
        c->dzt = c->dzb + w;
        c->width = w;
        s_nvcube++;
    }
}

// The slab test of the horizontal ray (eye at 0, direction d) with the footprint: entry and exit, and the axis the
// ray enters through (0 x, 1 y). Returns 0 for a miss.
static int ray_box(const vcube_t *c, double dx, double dy, double *tin, double *tout, int *axis)
{
    double lo = -1e30, hi = 1e30, a, b, t;
    int ax = 0;

    if (fabs(dx) < 1e-12)
    {
        if (c->rx0 > 0 || c->rx1 < 0)
        {
            return 0;
        }
    }
    else
    {
        a = c->rx0 / dx;
        b = c->rx1 / dx;
        lo = a < b ? a : b;
        hi = a < b ? b : a;
    }
    if (fabs(dy) < 1e-12)
    {
        if (c->ry0 > 0 || c->ry1 < 0)
        {
            return 0;
        }
    }
    else
    {
        a = c->ry0 / dy;
        b = c->ry1 / dy;
        t = a < b ? a : b;
        if (t > lo) { lo = t; ax = 1; }
        t = a < b ? b : a;
        if (t < hi) { hi = t; }
    }
    *tin = lo;
    *tout = hi;
    *axis = ax;
    return lo < hi && hi > 0 && lo > 0;
}

// Number of levels drawn on a face seen at forward distance lam: a power of two, as many as stay CUBE_LINE_PX apart.
static int cube_levels(const vcube_t *c, double lam)
{
    double room = s_fr.f * c->width / (CUBE_LINE_PX * lam);
    int n = 1;

    while (n * 2 <= room && n < 32)
    {
        n *= 2;
    }
    return n < 2 ? 0 : n;
}

static void cube_column(const vcube_t *c, int x, int yl, int yh, byte *base)
{
    double u = ((x + 0.5) - s_fr.cx) / s_fr.f;
    double dx = s_fr.fx + u * s_fr.rx, dy = s_fr.fy + u * s_fr.ry, lin, lout, vt, vb;
    int axis, y, fog, nb;

    if (!ray_box(c, dx, dy, &lin, &lout, &axis) || (vt = c->dzt / lin) <= 0.0)
    {
        return;
    }
    vb = c->dzb / lin;
    fog = haze_step(lin * sqrt(dx * dx + dy * dy), s_cube_haze_m);
    nb = cube_levels(c, lin);
    for (y = yl; y <= yh; y++)
    {
        double v = (s_fr.cy - (y + 0.5)) / s_fr.f, depth = lin;
        int tone;

        if (v > vt)
        {
            continue;
        }
        if (v >= vb)
        {
            tone = axis == 0 ? 0 : 2;
            if (nb && floor((c->dzb + lin * v) * nb / c->width) != floor((c->dzb + lin * (v + 1.0 / s_fr.f)) * nb / c->width))
            {
                tone++;                 // a level line: the darker tone of the same face
            }
        }
        else if (c->dzb > 0.0 && v >= c->dzb / lout)
        {
            tone = 4;
            depth = c->dzb / v;
        }
        else
        {
            continue;
        }
        if (depth < s_depth[y])
        {
            s_depth[y] = (float)depth;
            base[(y - yl) * pov_stride] = s_i_cube[fog][tone];
        }
    }
}

// ---------------------------------------------------------------------------------------
// Clouds: one column of a cloud's picture
// ---------------------------------------------------------------------------------------
static void cloud_column(const vcloud_t *c, int x, int yl, int yh, byte *base)
{
    int wm = s_spr_w >> c->mip, hm = s_spr_h >> c->mip;
    int tcol = (int)(((x + 0.5) - c->x0) / c->pw * wm);
    const unsigned char *col;
    double rstep = hm / c->ph;
    int ya = (int)ceil(c->yb - c->ph - 0.5), yz = (int)floor(c->yb - 0.5), y;

    if (tcol < 0 || tcol >= wm)
    {
        return;
    }
    col = s_spr + s_spr_off[c->shape][c->mip] + (long)tcol * hm;
    ya = ya < yl ? yl : ya;
    yz = yz > yh ? yh : yz;
    for (y = ya; y <= yz; y++)
    {
        int tr = (int)((c->yb - (y + 0.5)) * rstep);

        if (tr >= 0 && tr < hm && col[tr] && c->depth < s_depth[y])
        {
            s_depth[y] = (float)c->depth;
            base[(y - yl) * pov_stride] = s_i_cloud[c->fog][col[tr] == 1 ? 0 : 1];
        }
    }
}

// ---------------------------------------------------------------------------------------
// Sun, moon, stars
// ---------------------------------------------------------------------------------------
// Sun (day) or moon (night): where, in degrees. East is angle 0, south 270 (-90), west 180 (-180).
static void body_place(int minute, int *kind, double *el, double *az, double *radius)
{
    double p;

    if (minute >= SUN_RISE && minute < SUN_SET)
    {
        *kind = 1;
        p = (minute - SUN_RISE) / (double)(SUN_SET - SUN_RISE);
        *radius = SUN_RADIUS;
    }
    else
    {
        *kind = 2;
        p = (minute >= SUN_SET ? minute - SUN_SET : minute + 1440 - SUN_SET) / (double)MOON_SPAN;
        *radius = MOON_RADIUS;
    }
    *el = SKY_EL_MAX * sin(M_PI * p);
    *az = -180.0 * p;
}

// Rows [lo, hi] (point centres) of the disc at (sx, sy) with radius r in column x; hi < lo: none.
static void disc_rows(double sx, double sy, double r, int x, int *lo, int *hi)
{
    double dx = (x + 0.5) - sx;

    *lo = 1;
    *hi = 0;
    if (dx * dx < r * r)
    {
        double dy = sqrt(r * r - dx * dx);

        *lo = (int)ceil(sy - dy - 0.5);
        *hi = (int)floor(sy + dy - 0.5);
    }
}

static void body_tables(const frame_t *fr)
{
    double el, az, radius, delta, sx, sy, r, ccx, ccy, cr;
    int x, kind;

    body_place(s_minute, &kind, &el, &az, &radius);
    delta = remainder((az - viewangle * (360.0 / 4294967296.0)) * (M_PI / 180.0), 2.0 * M_PI);
    s_body = (fabs(delta) < 85.0 * M_PI / 180.0) ? kind : 0;
    if (!s_body)
    {
        return;
    }
    r = fr->f * tan(radius * M_PI / 180.0);
    sx = fr->cx - fr->f * tan(delta);
    sy = fr->cy - fr->f * tan(el * M_PI / 180.0) / cos(delta);
    ccx = sx + 0.55 * r;           // the moon's crescent: the disc less a disc up and to the right
    ccy = sy - 0.20 * r;
    cr = 0.88 * r;
    for (x = 0; x < viewwidth; x++)
    {
        disc_rows(sx, sy, r, x, &s_b0[x], &s_b1[x]);
        s_k0[x] = 1;
        s_k1[x] = 0;
        if (kind == 2)
        {
            disc_rows(ccx, ccy, cr, x, &s_k0[x], &s_k1[x]);
        }
    }
}

// The stars of this picture, put into per-column lists: fixed to the world, a square of a point or two.
static void stars_begin(const frame_t *fr)
{
    int i, x, size = (int)(fr->f / 320.0 + 0.5);

    memset(s_star_head, -1, sizeof(int) * (size_t)viewwidth);
    s_nstar_entries = 0;
    s_star_size = size < 1 ? 1 : size;
    if (!s_stars_on)
    {
        return;
    }
    for (i = 0; i < s_nstars; i++)
    {
        double az = s_star_az[i] * (360.0 / 65536.0), el = s_star_el[i] * (90.0 / 65536.0);
        double delta = remainder((az - viewangle * (360.0 / 4294967296.0)) * (M_PI / 180.0), 2.0 * M_PI);
        int sx, sy;

        if (fabs(delta) >= 85.0 * M_PI / 180.0)
        {
            continue;
        }
        sx = (int)floor(fr->cx - fr->f * tan(delta));
        sy = (int)floor(fr->cy - fr->f * tan(el * M_PI / 180.0) / cos(delta));
        for (x = sx; x < sx + s_star_size; x++)
        {
            if (x >= 0 && x < viewwidth && s_nstar_entries < MAX_STARS * 3)
            {
                s_star_y[s_nstar_entries] = sy;
                s_star_next[s_nstar_entries] = s_star_head[x];
                s_star_head[x] = s_nstar_entries++;
            }
        }
    }
}

void POV_SkyBegin(void)
{
    int x;

    frame_setup(&s_fr);
    s_frame_ok = 1;
    s_stars_on = stars_at(s_minute);
    for (x = 0; x < viewwidth; x++)
    {
        double u = ((x + 0.5) - s_fr.cx) / s_fr.f;

        s_stepd[x] = BAND_RPT / (s_fr.f * sqrt(1.0 + u * u));
    }
    body_tables(&s_fr);
    stars_begin(&s_fr);
    clouds_begin(&s_fr, (s_cloud_base_ms + s_cloud_live_ms) / 1000.0);
    cubes_begin(&s_fr);
}

// Bands and the body of one column.
static void base_column(int x, int yl, int yh, byte *dest)
{
    double cy = centeryfrac / 65536.0;
    int step = (int)(s_stepd[x] * 65536.0);
    int rfix = (int)((cy - (yl + 0.5)) * s_stepd[x] * 65536.0);
    int y;

    for (y = yl; y <= yh; y++, dest += pov_stride, rfix -= step)
    {
        int rr = rfix >> 16;
        byte col = s_bandtab[rr < 0 ? 0 : (rr >= BAND_ROWS ? BAND_ROWS - 1 : rr)];

        if (s_body && y >= s_b0[x] && y <= s_b1[x] && !(y >= s_k0[x] && y <= s_k1[x]))
        {
            col = s_body == 1 ? s_i_sun : s_i_moon;
        }
        *dest = col;
    }
}

static void stars_column(int x, int yl, int yh, byte *base)
{
    int e, k;

    for (e = s_star_head[x]; e >= 0; e = s_star_next[e])
    {
        for (k = 0; k < s_star_size; k++)
        {
            int y = s_star_y[e] + k;
            byte *p;

            if (y < yl || y > yh)
            {
                continue;
            }
            p = base + (y - yl) * pov_stride;
            if (*p >= s_i_band0 && *p < s_i_band0 + s_nbands)       // only on the plain sky, not on the sun or moon
            {
                *p = s_i_star;
            }
        }
    }
}

void POV_SkyColumn(int x, int yl, int yh)
{
    byte *base = ylookup[yl] + columnofs[x];
    int i, y;

    base_column(x, yl, yh, base);
    stars_column(x, yl, yh, base);
    for (y = yl; y <= yh; y++)
    {
        s_depth[y] = 1e30f;
    }
    for (i = 0; i < s_nvcube; i++)
    {
        cube_column(&s_vcube[i], x, yl, yh, base);
    }
    for (i = 0; i < s_nvis; i++)
    {
        if (x >= s_vis[i].x0i && x <= s_vis[i].x1i)
        {
            cloud_column(&s_vis[i], x, yl, yh, base);
        }
    }
}
