// Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
//
// This program is free software; you can redistribute it and/or
// modify it under the terms of the GNU General Public License
// as published by the Free Software Foundation; either version 2
// of the License, or (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
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
//   POV_LIVE_MS       live mode: a tick is due every this many real milliseconds (default 10). The clock of the
//                     program is then the monotonic clock (as in the window program): a pause is only the wait
//                     until the next tick is due, so a slow sleep or a slow tick never stretches the program's time
//   POV_WINDOW        with -pov-control: <w>x<h>, the size of a window that this run pretends to have: the
//                     picture is chosen as the window platform does (POV_ControlFitSize: the window's own size
//                     inside the limits, above them the largest picture of its shape). Test hook; -pov-size wins.

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
static int s_live_clock = 0;            // live mode: DG_GetTicksMs is the monotonic clock, not counted pauses
static int s_started = 0;               // s_start is set (DG_Init ran)
static double s_next_tick_ms = 0.0;     // live: the clock reading at which the next tick is due
static unsigned long s_ticks = 0;       // calls of doomgeneric_Tick
static struct timespec s_start;
// Time spent drawing, without writing the frame: from the end of the previous DG_DrawFrame (or
// the start of the first step) to the call of this one. Includes reading control lines, the
// renderer, the outline pass and the conversion to RGB (what the window layer also does).
static double s_work_total_ms = 0.0;
static double s_work_worst_ms = 0.0;
static double s_work_mark_ms = -1.0;
static unsigned long s_work_frames = 0;

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
    row = malloc((size_t)DG_OutW * 3);
    if (row == NULL)
    {
        fprintf(stderr, "headless: out of memory\n");
        exit(1);
    }
    // cosmergon-pov: the picture in the buffer is DG_OutW x DG_OutH, tightly packed
    fprintf(file, "P6\n%d %d\n255\n", DG_OutW, DG_OutH);
    for (y = 0; y < DG_OutH; y++)
    {
        for (x = 0; x < DG_OutW; x++)
        {
            // pixel_t is 0x00RRGGBB (red offset 16, see i_video.c)
            uint32_t pixel = DG_ScreenBuffer[y * DG_OutW + x];

            row[x * 3 + 0] = (pixel >> 16) & 0xFF;
            row[x * 3 + 1] = (pixel >> 8) & 0xFF;
            row[x * 3 + 2] = pixel & 0xFF;
        }
        if (fwrite(row, 3, DG_OutW, file) != (size_t)DG_OutW)
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
    const char *window;

    s_control = POV_ControlEnabled();
    s_every = env_ulong("POV_EVERY", s_control ? 1 : 35);
    s_max_frames = env_ulong("POV_FRAMES", s_control ? ULONG_MAX : 700);
    if (s_control)
    {
        const char *live = getenv("POV_CONTROL_LIVE");

        POV_ControlSetLive(live != NULL && strcmp(live, "1") == 0);
        s_live_ms = env_ulong("POV_LIVE_MS", 10);
        window = getenv("POV_WINDOW");
        if (window != NULL && *window != '\0')
        {
            int w = 0, h = 0;
            char tail = 0;

            if (sscanf(window, "%dx%d%c", &w, &h, &tail) != 2)
            {
                fprintf(stderr, "headless: POV_WINDOW must be <w>x<h>, got '%s'\n", window);
                exit(2);
            }
            fprintf(stderr, "headless: window %d x %d -> %s\n", w, h,
                    POV_ControlFitSize(w, h) == 0 ? "not followed" : "followed");
        }
    }
    s_live_clock = s_control && POV_ControlIsLive();
    clock_gettime(CLOCK_MONOTONIC, &s_start);
    s_started = 1;
}

static void finish(void)
{
    double ms = elapsed_ms();

    // control mode: the last drawn frame is always written (live mode draws far more than it writes)
    if (s_control && s_frames > 0 && s_frames % s_every != 0)
    {
        write_frame(s_frames);
    }

    fprintf(stderr, "headless: frames=%lu real_ms=%.1f ms_per_frame=%.3f ticks=%lu ticks_per_s=%.1f live=%d\n",
            s_frames, ms, s_frames > 0 ? ms / (double)s_frames : 0.0, s_ticks,
            ms > 0.0 ? (double)s_ticks * 1000.0 / ms : 0.0, s_live_clock);
    fprintf(stderr, "headless: size=%dx%d work_ms=%.3f worst_ms=%.3f (per frame, without writing the frames)\n",
            DG_OutW, DG_OutH, s_work_frames > 0 ? s_work_total_ms / (double)s_work_frames : 0.0,
            s_work_worst_ms);
    fprintf(stderr, "headless: highwater drawsegs=%d visplanes=%d openings=%d solidsegs=%d vissprites=%d\n",
            pov_hw_drawsegs, pov_hw_visplanes, pov_hw_openings, pov_hw_solidsegs, pov_hw_vissprites);
    fprintf(stderr, "headless: zone_free_or_purgable_bytes=%d\n", Z_FreeMemory());
    POV_ControlSummary(stderr);
    exit(0);
}

void DG_DrawFrame(void)
{
    double entered = elapsed_ms();

    if (s_work_mark_ms >= 0.0)
    {
        double work = entered - s_work_mark_ms;

        s_work_total_ms += work;
        s_work_frames++;
        if (work > s_work_worst_ms)
        {
            s_work_worst_ms = work;
        }
    }
    s_frames++;
    if (!s_live_clock)
    {
        s_virtual_ms += POV_MS_PER_FRAME;
    }
    if (s_frames % s_every == 0)
    {
        write_frame(s_frames);
    }
    s_work_mark_ms = elapsed_ms();
    if (s_frames >= s_max_frames)
    {
        finish();
    }
}

static void sleep_real_ms(double ms)
{
    struct timespec pause;

    if (ms <= 0.0)
    {
        return;
    }
    pause.tv_sec = (time_t)(ms / 1000.0);
    pause.tv_nsec = (long)((ms - (double)pause.tv_sec * 1000.0) * 1e6);
    nanosleep(&pause, NULL);
}

void DG_SleepMs(uint32_t ms)
{
    if (s_live_clock)
    {
        sleep_real_ms((double)ms);      // the clock is the real one: waiting takes the time it says
        return;
    }
    s_virtual_ms += ms;
}

uint32_t DG_GetTicksMs(void)
{
    if (s_live_clock && s_started)
    {
        return (uint32_t)elapsed_ms();
    }
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
        s_ticks++;
        if (s_live_clock)
        {
            // live: a tick is due every POV_LIVE_MS on the monotonic clock, whether it drew or not. The pause
            // is only the wait until then; a tick that ran late is followed at once (no burst: the schedule
            // restarts from now when more than one period behind).
            double now = elapsed_ms();

            s_next_tick_ms += (double)s_live_ms;
            if (s_next_tick_ms < now - (double)s_live_ms)
            {
                s_next_tick_ms = now;
            }
            sleep_real_ms(s_next_tick_ms - now);
        }
    }
    return 0;
}
