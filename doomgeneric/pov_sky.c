// cosmergon-pov: the sky of a theme. See pov_sky.h and COSMERGON.md ("The sky").
//
// The sky is a sphere around the viewer, drawn point by point in the size of the picture, so that its
// look does not depend on a texture's resolution (the old 1024 x 128 texture made the sun an ellipse
// and its edge show steps):
//   - a point of the picture looks along (u, v, 1): u = x offset / f, v = y offset / f, f = width / 2
//     (the angle of view is 90 degrees across); azimuth = viewangle + xtoviewangle[x], tan(elevation) =
//     v / sqrt(1 + u * u). Rows and columns of one point step alike, which is what makes a disc round.
//   - background: bands of elevation (lump POVSKY: count, degrees a band), flat colours;
//   - stars (night only): bit 4 of the cloud layer, fixed to the world;
//   - sun (day) or moon (night): a disc of fixed angular size at the position the time of day gives;
//   - clouds: the layer POVCLD, 4096 columns around the circle, 512 rows of tan(elevation) * 651.9
//     (1 texel a point at 1280 wide, finer than the picture below that), drifting around the circle.

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

#define SKY_W        4096
#define SKY_H        512
#define SKY_COLSHIFT 20                          // angle_t (32 bit) >> 20 = column of 4096
#define SKY_RPT      (SKY_W / (2.0 * M_PI))      // texels per unit of tan(elevation)
#define SKY_MAX_KEYS 32
#define SKY_MAX_BANDS 32

// The time of day (the same numbers are in tools/sky_art.py, which the tests compare).
#define SUN_RISE      360        // minutes: 06:00
#define SUN_SET       1140       // 19:00; the moon runs from 19:00 to 06:00
#define MOON_SPAN     660
#define SKY_EL_MAX    21.0       // highest elevation of sun and moon, degrees (higher is never in the picture)
#define SUN_RADIUS    4.5        // angular radius, degrees
#define MOON_RADIUS   3.6
// Cloud drift: 0.25 degrees a second = 2844 columns in 1000 seconds.
#define DRIFT_COLS_PER_KS 2844.4

static int s_on = 0;
static const unsigned char *s_cloud = NULL;      // [column * SKY_H + row]
static const unsigned char *s_pal = NULL;        // key palettes, 768 bytes each
static int s_nkeys = 0, s_nbands = 0;
static int s_key_min[SKY_MAX_KEYS], s_key_stars[SKY_MAX_KEYS];
static int s_band_deg10 = 30;
static unsigned char s_i_sun, s_i_moon, s_i_cloud, s_i_shade, s_i_star, s_i_band0;
static unsigned char s_bandtab[SKY_H];
static int s_minute = 720;
static double s_cloud_base_ms = 0, s_cloud_live_ms = 0;

// per picture
static int s_body = 0;                           // 0 none, 1 sun, 2 moon
static int s_stars = 0;
static long s_drift_cols = 0;
static double s_stepd[POV_MAX_W];                // texture rows a point down, per column
static int s_ccol[POV_MAX_W];                    // texture column of the clouds
static int s_scol[POV_MAX_W];                    // texture column of the stars
static int s_b0[POV_MAX_W], s_b1[POV_MAX_W];     // rows of the body, inclusive; b0 > b1: none
static int s_k0[POV_MAX_W], s_k1[POV_MAX_W];     // rows cut out of the body (the moon's crescent)

int POV_SkyActive(void) { return s_on; }
int POV_SkyMinute(void) { return s_minute; }

static const unsigned char *lump_data(const char *name, int size)
{
    int lump = W_CheckNumForName((char *)name);

    if (lump < 0)
    {
        return NULL;
    }
    if (W_LumpLength(lump) != size)
    {
        I_Error("pov-sky: lump %s must have %d bytes, it has %d", name, size, W_LumpLength(lump));
    }
    return W_CacheLumpNum(lump, PU_STATIC);
}

int POV_SkyLoad(void)
{
    int lump = W_CheckNumForName("POVSKY");
    const unsigned char *h;
    int i, b, size;

    s_on = 0;
    if (lump < 0)
    {
        return 0;
    }
    h = W_CacheLumpNum(lump, PU_STATIC);
    if (W_LumpLength(lump) < 16 || memcmp(h, "POVS", 4) != 0 || h[4] != 1)
    {
        I_Error("pov-sky: POVSKY has the wrong magic or version");
    }
    s_nbands = h[5];
    s_nkeys = h[6];
    s_band_deg10 = h[7];
    s_i_sun = h[8]; s_i_moon = h[9]; s_i_cloud = h[10]; s_i_shade = h[11]; s_i_star = h[12]; s_i_band0 = h[13];
    size = 16 + 4 * s_nkeys;
    if (s_nbands < 1 || s_nbands > SKY_MAX_BANDS || s_nkeys < 2 || s_nkeys > SKY_MAX_KEYS
        || s_band_deg10 < 1 || W_LumpLength(lump) != size)
    {
        I_Error("pov-sky: POVSKY has a wrong count or size");
    }
    for (i = 0; i < s_nkeys; i++)
    {
        s_key_min[i] = h[16 + 4 * i] | (h[17 + 4 * i] << 8);
        s_key_stars[i] = h[18 + 4 * i];
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
    s_cloud = lump_data("POVCLD", SKY_W * SKY_H);
    if (s_pal == NULL || s_cloud == NULL)
    {
        I_Error("pov-sky: lumps POVCLD and PLAYPAL (one palette a key) are needed");
    }
    for (b = 0; b < SKY_H; b++)
    {
        int band = (int)(atan(b / SKY_RPT) * 1800.0 / M_PI / s_band_deg10);

        s_bandtab[b] = (unsigned char)(s_i_band0 + (band >= s_nbands ? s_nbands - 1 : band));
    }
    s_on = 1;
    return 1;
}

void POV_SkySetMinute(int minute) { s_minute = minute; }
void POV_SkySetCloudBase(double ms) { s_cloud_base_ms = ms; }
void POV_SkySetCloudLive(double ms) { s_cloud_live_ms = ms; }

// Same rounding in tools/sky_art.py (palette_at): t in 0..256, (a * (256 - t) + b * t + 128) >> 8.
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

// Whole points the clouds have drifted at this width: f points a radian, 0.25 degrees a second.
long POV_SkyDriftPoints(int view_w)
{
    double ms = s_cloud_base_ms + s_cloud_live_ms;
    double cols = ms * (DRIFT_COLS_PER_KS / 1.0e6);

    return (long)floor(cols * (2.0 * M_PI) * (view_w / 2.0) / SKY_W);
}

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

static void body_tables(void)
{
    double el, az, radius, f = projection / 65536.0, cx = centerxfrac / 65536.0, cy = centeryfrac / 65536.0;
    double delta, sx, sy, r, ccx, ccy, cr;
    int x, kind;

    body_place(s_minute, &kind, &el, &az, &radius);
    delta = (az - viewangle * (360.0 / 4294967296.0)) * (M_PI / 180.0);
    delta = remainder(delta, 2.0 * M_PI);
    s_body = (fabs(delta) < 85.0 * M_PI / 180.0) ? kind : 0;
    if (!s_body)
    {
        return;
    }
    r = f * tan(radius * M_PI / 180.0);
    sx = cx - f * tan(delta);
    sy = cy - f * tan(el * M_PI / 180.0) / cos(delta);
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

void POV_SkyBegin(void)
{
    double f = projection / 65536.0;
    long px = POV_SkyDriftPoints(viewwidth);
    int x;

    // the clouds move by whole points: the texture offset follows the points, not the clock
    s_drift_cols = (long)floor(px * SKY_W / (2.0 * M_PI * f) + 0.5);
    s_stars = stars_at(s_minute);
    for (x = 0; x < viewwidth; x++)
    {
        double u = ((x + 0.5) - centerxfrac / 65536.0) / f;
        int c = (int)((viewangle + xtoviewangle[x]) >> SKY_COLSHIFT);

        s_stepd[x] = SKY_RPT / (f * sqrt(1.0 + u * u));
        s_scol[x] = c & (SKY_W - 1);
        s_ccol[x] = (int)((c + s_drift_cols) & (SKY_W - 1));
    }
    body_tables();
}

void POV_SkyColumn(int x, int yl, int yh)
{
    byte *dest = ylookup[yl] + columnofs[x];
    double cy = centeryfrac / 65536.0;
    int step = (int)(s_stepd[x] * 65536.0);
    int rfix = (int)((cy - (yl + 0.5)) * s_stepd[x] * 65536.0);
    const unsigned char *cc = s_cloud + (size_t)s_ccol[x] * SKY_H;
    const unsigned char *sc = s_cloud + (size_t)s_scol[x] * SKY_H;
    int y;

    for (y = yl; y <= yh; y++, dest += pov_stride, rfix -= step)
    {
        int rr = rfix >> 16;
        int ri = rr < 0 ? 0 : (rr >= SKY_H ? SKY_H - 1 : rr);
        byte col = s_bandtab[ri];

        int in_body = s_body && y >= s_b0[x] && y <= s_b1[x] && !(y >= s_k0[x] && y <= s_k1[x]);

        if (in_body)
        {
            col = s_body == 1 ? s_i_sun : s_i_moon;
        }
        else if (s_stars && rr >= 0 && rr < SKY_H && (sc[rr] & 16))
        {
            col = s_i_star;
        }
        if (rr >= 0 && rr < SKY_H && (cc[rr] & 3))
        {
            col = (cc[rr] & 3) == 1 ? s_i_cloud : s_i_shade;
        }
        *dest = col;
    }
}
