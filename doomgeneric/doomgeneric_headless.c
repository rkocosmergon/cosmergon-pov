// doomgeneric platform layer without any window, sound or input.
// Frames are written as binary PPM (P6) files. The clock is virtual, so a run
// is deterministic and as fast as the CPU allows.
//
// Environment:
//   POV_OUT     directory for the frames (required, must exist and be writable)
//   POV_EVERY   write every n-th drawn frame (default 35; with -pov-control 1)
//   POV_FRAMES  stop cleanly after this many drawn frames (default 700; with -pov-control no limit)
//   POV_CONTROL_LIVE  with -pov-control: 1 = never block on stdin, draw a frame in every tick
//                     in which something changed
//                     (the way a window platform reads); unset/0 = block until `next`/`quit`/EOF
//   POV_LIVE_MS       live mode: real milliseconds slept per tick (default 10)

#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "doomgeneric.h"
#include "pov_control.h"
#include "z_zone.h"

// cosmergon-pov: high water marks of the renderer's fixed arrays (r_plane.c)
extern int pov_hw_drawsegs, pov_hw_visplanes, pov_hw_openings, pov_hw_solidsegs;

// Virtual milliseconds added per drawn frame (one game tic is 1000/35 ms).
#define POV_MS_PER_FRAME 29

static uint32_t s_virtual_ms = 0;
static unsigned long s_frames = 0;
static unsigned long s_every = 35;
static unsigned long s_max_frames = 700;
static const char *s_out_dir = NULL;
static int s_control = 0;
static unsigned long s_live_ms = 10;
static struct timespec s_start;

static unsigned long env_ulong(const char *name, unsigned long fallback)
{
    const char *text = getenv(name);
    char *end = NULL;
    unsigned long value;

    if (text == NULL || *text == '\0')
    {
        return fallback;
    }
    errno = 0;
    value = strtoul(text, &end, 10);
    if (errno != 0 || *end != '\0' || value == 0)
    {
        fprintf(stderr, "headless: %s must be a positive integer, got '%s'\n", name, text);
        exit(2);
    }
    return value;
}

static double elapsed_ms(void)
{
    struct timespec now;

    clock_gettime(CLOCK_MONOTONIC, &now);
    return (now.tv_sec - s_start.tv_sec) * 1000.0 + (now.tv_nsec - s_start.tv_nsec) / 1e6;
}

static void write_frame(unsigned long number)
{
    char path[4096];
    FILE *file;
    unsigned char *row;
    int x, y;

    if (snprintf(path, sizeof(path), "%s/frame-%06lu.ppm", s_out_dir, number) >= (int)sizeof(path))
    {
        fprintf(stderr, "headless: output path too long\n");
        exit(1);
    }
    file = fopen(path, "wb");
    if (file == NULL)
    {
        fprintf(stderr, "headless: cannot write %s: %s\n", path, strerror(errno));
        exit(1);
    }
    row = malloc((size_t)DOOMGENERIC_RESX * 3);
    if (row == NULL)
    {
        fprintf(stderr, "headless: out of memory\n");
        exit(1);
    }
    fprintf(file, "P6\n%d %d\n255\n", DOOMGENERIC_RESX, DOOMGENERIC_RESY);
    for (y = 0; y < DOOMGENERIC_RESY; y++)
    {
        for (x = 0; x < DOOMGENERIC_RESX; x++)
        {
            // pixel_t is 0x00RRGGBB (red offset 16, see i_video.c)
            uint32_t pixel = DG_ScreenBuffer[y * DOOMGENERIC_RESX + x];

            row[x * 3 + 0] = (pixel >> 16) & 0xFF;
            row[x * 3 + 1] = (pixel >> 8) & 0xFF;
            row[x * 3 + 2] = pixel & 0xFF;
        }
        if (fwrite(row, 3, DOOMGENERIC_RESX, file) != (size_t)DOOMGENERIC_RESX)
        {
            fprintf(stderr, "headless: write error on %s\n", path);
            exit(1);
        }
    }
    free(row);
    if (fclose(file) != 0)
    {
        fprintf(stderr, "headless: close error on %s: %s\n", path, strerror(errno));
        exit(1);
    }
}

void DG_Init(void)
{
    s_out_dir = getenv("POV_OUT");
    if (s_out_dir == NULL || *s_out_dir == '\0')
    {
        fprintf(stderr, "headless: POV_OUT is not set\n");
        exit(2);
    }
    {
        struct stat info;

        if (stat(s_out_dir, &info) != 0 || !S_ISDIR(info.st_mode) || access(s_out_dir, W_OK | X_OK) != 0)
        {
            fprintf(stderr, "headless: POV_OUT '%s' is not a writable directory\n", s_out_dir);
            exit(2);
        }
    }
    s_control = POV_ControlEnabled();
    s_every = env_ulong("POV_EVERY", s_control ? 1 : 35);
    s_max_frames = env_ulong("POV_FRAMES", s_control ? ULONG_MAX : 700);
    if (s_control)
    {
        const char *live = getenv("POV_CONTROL_LIVE");

        POV_ControlSetLive(live != NULL && strcmp(live, "1") == 0);
        s_live_ms = env_ulong("POV_LIVE_MS", 10);
    }
    clock_gettime(CLOCK_MONOTONIC, &s_start);
}

static void finish(void)
{
    double ms = elapsed_ms();

    // control mode: the last drawn frame is always written (live mode draws far more than it writes)
    if (s_control && s_frames > 0 && s_frames % s_every != 0)
    {
        write_frame(s_frames);
    }

    fprintf(stderr, "headless: frames=%lu real_ms=%.1f ms_per_frame=%.3f\n",
            s_frames, ms, s_frames > 0 ? ms / (double)s_frames : 0.0);
    fprintf(stderr, "headless: highwater drawsegs=%d visplanes=%d openings=%d solidsegs=%d vissprites=%d\n",
            pov_hw_drawsegs, pov_hw_visplanes, pov_hw_openings, pov_hw_solidsegs, pov_hw_vissprites);
    fprintf(stderr, "headless: zone_free_or_purgable_bytes=%d\n", Z_FreeMemory());
    POV_ControlSummary(stderr);
    exit(0);
}

void DG_DrawFrame(void)
{
    s_frames++;
    s_virtual_ms += POV_MS_PER_FRAME;
    if (s_frames % s_every == 0)
    {
        write_frame(s_frames);
    }
    if (s_frames >= s_max_frames)
    {
        finish();
    }
}

void DG_SleepMs(uint32_t ms)
{
    s_virtual_ms += ms;
}

uint32_t DG_GetTicksMs(void)
{
    return s_virtual_ms;
}

int DG_GetKey(int *pressed, unsigned char *key)
{
    (void)pressed;
    (void)key;
    return 0;
}

void DG_SetWindowTitle(const char *title)
{
    (void)title;
}

int main(int argc, char **argv)
{
    doomgeneric_Create(argc, argv);
    for (;;)
    {
        if (POV_ControlDone())
        {
            finish();
        }
        doomgeneric_Tick();
        if (s_control && POV_ControlIsLive())
        {
            // live: one tick every POV_LIVE_MS, whether it drew or not
            struct timespec pause = { (time_t)(s_live_ms / 1000), (long)(s_live_ms % 1000) * 1000000L };

            nanosleep(&pause, NULL);
        }
    }
    return 0;
}
