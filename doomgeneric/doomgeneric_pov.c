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
// cosmergon-pov: the window (SDL2). It only shows what the control channel says
// (pov_control.h, COSMERGON.md): no keyboard, no mouse, no sound, no dialog.
//
// The engine draws in the size of the window itself, one point per pixel (COSMERGON.md, "Picture
// size"): at the start and after every resize (SDL window event) the renderer's output size is
// handed to POV_ControlFitSize. A size above 1280 x 800 in one or both axes gets the largest picture of the
// window's shape inside the limits (said once on stderr, counted), which SDL stretches to the window. A size
// below 160 x 100, or a shape no picture inside the limits has, is not followed (said once, counted): the last
// picture stays and is stretched.
//
// Always started with -pov-control; the control input is read without blocking, POV_FPS steps
// a second (default 35, Doom's own rate), and a step draws only when something changed.
//
// Environment:
//   POV_FPS      steps a second, 1..120 (default 35)
//   POV_WIDTH, POV_HEIGHT   first size of the window in pixels (default 640 x 400; at most 1280 x 800)
//   POV_SOFTWARE  set: SDL's software renderer instead of the accelerated one (for measuring)
//
// At the end stderr carries the measures of the run (frames, time per frame without the
// pause, the slowest frame, how many took longer than half a step).

#include <limits.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <SDL.h>

#include "doomgeneric.h"
#include "pov_control.h"

#define POV_APP_ID "com.cosmergon.pov"

static SDL_Window *s_window = NULL;
static SDL_Renderer *s_renderer = NULL;
static SDL_Texture *s_texture = NULL;
static volatile sig_atomic_t s_stop = 0;
static int s_uncovered = 0;             // the window system asks for the picture again
static int s_resized = 0;               // the window's size may have changed
static int s_tex_w = 0, s_tex_h = 0;    // size of s_texture
static unsigned long s_size_followed = 0;
static unsigned long s_size_rejected = 0;
static unsigned long s_size_fitted = 0;
static int s_last_rejected_w = 0, s_last_rejected_h = 0;

static unsigned long s_frames = 0;
static uint64_t s_work_ticks = 0;       // performance counter ticks spent in steps (without the pause)
static uint64_t s_worst_ticks = 0;
static uint64_t s_show_ticks = 0;       // of the work: handing the picture to the window system
static unsigned long s_over_half = 0;   // steps that took longer than half the interval
static uint64_t s_started = 0;

static long env_long(const char *name, long fallback, long lo, long hi)
{
    const char *text = getenv(name);
    char *end = NULL;
    long value;

    if (text == NULL || *text == '\0')
    {
        return fallback;
    }
    value = strtol(text, &end, 10);
    if (*end != '\0' || value < lo || value > hi)
    {
        fprintf(stderr, "pov: %s must be an integer %ld..%ld\n", name, lo, hi);
        exit(2);
    }
    return value;
}

static void on_signal(int number)
{
    (void)number;
    s_stop = 1;
}

static void die(const char *what)
{
    fprintf(stderr, "pov: %s: %s\n", what, SDL_GetError());
    exit(1);
}

// Hands the window's size in pixels (the renderer's output, so a scaled display counts in real
// pixels) to the engine. Called at the start and after a resize event.
static void follow_window(void)
{
    int w = 0, h = 0, fit;

    s_resized = 0;
    if (SDL_GetRendererOutputSize(s_renderer, &w, &h) != 0)
    {
        die("SDL_GetRendererOutputSize");
    }
    fit = POV_ControlFitSize(w, h);
    if (fit == 1)
    {
        s_size_followed++;
        return;
    }
    if (fit == 2)
    {
        s_size_fitted++;
        if (w != s_last_rejected_w || h != s_last_rejected_h)
        {
            s_last_rejected_w = w;
            s_last_rejected_h = h;
            fprintf(stderr, "pov: window %d x %d is above %d x %d: the picture is %d x %d "
                    "(the window's shape, stretched to the window)\n",
                    w, h, POV_MAX_W, POV_MAX_H, pov_view_w, pov_view_h);
        }
        return;
    }
    s_size_rejected++;
    if (w != s_last_rejected_w || h != s_last_rejected_h)
    {
        s_last_rejected_w = w;
        s_last_rejected_h = h;
        fprintf(stderr, "pov: window %d x %d is outside %d x %d .. %d x %d, not followed "
                "(the last picture is stretched to the window)\n",
                w, h, POV_MIN_W, POV_MIN_H, POV_MAX_W, POV_MAX_H);
    }
}

void DG_Init(void)
{
    int width = (int)env_long("POV_WIDTH", 640, POV_MIN_W, POV_MAX_W);
    int height = (int)env_long("POV_HEIGHT", 400, POV_MIN_H, POV_MAX_H);

    // The window's identity for the compositor's rules. Wayland takes it from the app id,
    // X11 from the class; older SDL2 reads the environment, newer ones the hint.
    setenv("SDL_VIDEO_WAYLAND_WMCLASS", POV_APP_ID, 1);
    setenv("SDL_VIDEO_X11_WMCLASS", POV_APP_ID, 1);
    SDL_SetHint("SDL_APP_ID", POV_APP_ID);
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "0");    // nearest: the pixels stay pixels
    SDL_SetHint(SDL_HINT_NO_SIGNAL_HANDLERS, "1");

    if (SDL_Init(SDL_INIT_VIDEO) != 0)
    {
        die("SDL_Init");
    }
    s_window = SDL_CreateWindow("cosmergon-pov", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED,
                                width, height, SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE);
    if (s_window == NULL)
    {
        die("SDL_CreateWindow");
    }
    if (getenv("POV_SOFTWARE") == NULL)
    {
        s_renderer = SDL_CreateRenderer(s_window, -1, SDL_RENDERER_ACCELERATED);
    }
    if (s_renderer == NULL)
    {
        s_renderer = SDL_CreateRenderer(s_window, -1, SDL_RENDERER_SOFTWARE);
    }
    if (s_renderer == NULL)
    {
        die("SDL_CreateRenderer");
    }
    // the texture is made in DG_DrawFrame, in the size of the picture
    SDL_ShowCursor(SDL_DISABLE);
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGPIPE, SIG_IGN);
    POV_ControlSetLive(1);
    follow_window();
}

static void show(void)
{
    SDL_RenderClear(s_renderer);
    SDL_RenderCopy(s_renderer, s_texture, NULL, NULL);
    SDL_RenderPresent(s_renderer);
}

void DG_DrawFrame(void)
{
    uint64_t before = SDL_GetPerformanceCounter();

    if (s_texture == NULL || s_tex_w != DG_OutW || s_tex_h != DG_OutH)
    {
        // new size of the picture: a new texture of exactly that size (not per frame)
        if (s_texture != NULL)
        {
            SDL_DestroyTexture(s_texture);
        }
        s_texture = SDL_CreateTexture(s_renderer, SDL_PIXELFORMAT_RGB888, SDL_TEXTUREACCESS_STREAMING,
                                      DG_OutW, DG_OutH);
        if (s_texture == NULL)
        {
            die("SDL_CreateTexture");
        }
        s_tex_w = DG_OutW;
        s_tex_h = DG_OutH;
    }
    SDL_UpdateTexture(s_texture, NULL, DG_ScreenBuffer, DG_OutW * (int)sizeof(uint32_t));
    show();
    s_uncovered = 0;
    s_show_ticks += SDL_GetPerformanceCounter() - before;
    s_frames++;
}

void DG_SleepMs(uint32_t ms)
{
    SDL_Delay(ms);
}

uint32_t DG_GetTicksMs(void)
{
    return SDL_GetTicks();
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

static void finish(void)
{
    double per_ms = 1000.0 / (double)SDL_GetPerformanceFrequency();
    double real_ms = (double)(SDL_GetPerformanceCounter() - s_started) * per_ms;
    SDL_RendererInfo info;

    memset(&info, 0, sizeof(info));
    SDL_GetRendererInfo(s_renderer, &info);
    fprintf(stderr, "pov: frames=%lu real_ms=%.0f work_ms_per_frame=%.3f worst_ms=%.3f over_half_step=%lu\n",
            s_frames, real_ms, s_frames > 0 ? (double)s_work_ticks * per_ms / (double)s_frames : 0.0,
            (double)s_worst_ticks * per_ms, s_over_half);
    fprintf(stderr, "pov: show_ms_per_frame=%.3f (part of the work)\n",
            s_frames > 0 ? (double)s_show_ticks * per_ms / (double)s_frames : 0.0);
    fprintf(stderr, "pov: video=%s renderer=%s\n", SDL_GetCurrentVideoDriver(), info.name ? info.name : "?");
    fprintf(stderr, "pov: picture size %d x %d, window sizes followed=%lu fitted=%lu not followed=%lu\n",
            DG_OutW, DG_OutH, s_size_followed, s_size_fitted, s_size_rejected);
    POV_ControlSummary(stderr);
    SDL_Quit();
    exit(0);
}

static void drain_events(void)
{
    SDL_Event event;

    while (SDL_PollEvent(&event))
    {
        if (event.type == SDL_QUIT)
        {
            s_stop = 1;
        }
        else if (event.type == SDL_WINDOWEVENT
                 && (event.window.event == SDL_WINDOWEVENT_EXPOSED
                     || event.window.event == SDL_WINDOWEVENT_SIZE_CHANGED))
        {
            s_uncovered = 1;
            if (event.window.event == SDL_WINDOWEVENT_SIZE_CHANGED)
            {
                s_resized = 1;
            }
        }
    }
}

// Without -iwad the program takes its two data files from the folder it lies in itself
// (freedoom1.wad and cosmergon.wad), so that a caller needs to know no file names.
static char **own_data_args(int argc, char **argv, int *count)
{
    static char dir[PATH_MAX], iwad[PATH_MAX + 32], map[PATH_MAX + 32];
    static char *args[64];
    ssize_t len = readlink("/proc/self/exe", dir, sizeof(dir) - 1);
    char *slash;
    int i;

    if (len <= 0 || argc > 59)
    {
        fprintf(stderr, "pov: cannot find the program's own folder; give -iwad and -file\n");
        exit(2);
    }
    dir[len] = '\0';
    slash = strrchr(dir, '/');
    if (slash == NULL)
    {
        fprintf(stderr, "pov: cannot find the program's own folder; give -iwad and -file\n");
        exit(2);
    }
    *slash = '\0';
    snprintf(iwad, sizeof(iwad), "%s/freedoom1.wad", dir);
    snprintf(map, sizeof(map), "%s/cosmergon.wad", dir);
    for (i = 0; i < argc; i++)
    {
        args[i] = argv[i];
    }
    args[i++] = "-iwad";
    args[i++] = iwad;
    args[i++] = "-file";
    args[i++] = map;
    args[i] = NULL;
    *count = i;
    return args;
}

int main(int argc, char **argv)
{
    long fps = env_long("POV_FPS", 35, 1, 120);
    uint64_t freq, step, half, next;
    int i, control = 0, iwad = 0;

    for (i = 1; i < argc; i++)
    {
        if (strcmp(argv[i], "-pov-size") == 0)
        {
            fprintf(stderr, "pov: -pov-size is for the build without a window; this one follows its window\n");
            return 2;
        }
        control = control || strcmp(argv[i], "-pov-control") == 0;
        iwad = iwad || strcmp(argv[i], "-iwad") == 0;
    }
    if (!control)
    {
        fprintf(stderr, "pov: this program only runs with -pov-control\n");
        return 2;
    }
    if (!iwad)
    {
        argv = own_data_args(argc, argv, &argc);
    }
    doomgeneric_Create(argc, argv);
    freq = SDL_GetPerformanceFrequency();
    step = freq / (uint64_t)fps;
    half = step / 2;
    s_started = SDL_GetPerformanceCounter();
    next = s_started + step;
    for (;;)
    {
        uint64_t before, spent, now;

        drain_events();
        if (s_stop || POV_ControlDone())
        {
            finish();
        }
        if (s_resized)
        {
            follow_window();        // the next tick draws in the new size (the request marks it changed)
        }
        before = SDL_GetPerformanceCounter();
        doomgeneric_Tick();
        if (s_uncovered && s_frames > 0)
        {
            // nothing changed in the world, but the window was uncovered or resized
            show();
            s_uncovered = 0;
        }
        spent = SDL_GetPerformanceCounter() - before;
        s_work_ticks += spent;
        if (spent > s_worst_ticks)
        {
            s_worst_ticks = spent;
        }
        if (spent > half)
        {
            s_over_half++;
        }
        now = SDL_GetPerformanceCounter();
        if (now < next)
        {
            SDL_Delay((uint32_t)((next - now) * 1000 / freq));
            next += step;
        }
        else
        {
            next = now + step;      // late: do not try to catch up
        }
    }
    return 0;
}
