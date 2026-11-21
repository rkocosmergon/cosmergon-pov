// cosmergon-pov: control channel. The engine only DISPLAYS a world that another program
// drives with text lines on stdin (see COSMERGON.md, "Control channel").
//
// The parser and the world state live in pov_control.c. How bytes arrive (blocking until the
// next `next`, or non blocking) is a choice of the platform layer: DG_ControlRead().

#ifndef POV_CONTROL_H
#define POV_CONTROL_H

#include <stdio.h>

#include "i_video.h"      // POV_MIN_W .. POV_MAX_H

// Hard limits of the protocol (checked by the parser, derived in COSMERGON.md).
#define POVC_GRID       48          // cells per side of the window
#define POVC_CELLS      (POVC_GRID * POVC_GRID)
#define POVC_MAX_THINGS 256         // ids 0..255
#define POVC_MAX_LINE   255         // bytes per line, without the newline
#define POVC_MAX_NEXT   1000000     // frames per `next`
#define POVC_MAX_ORIGIN 1000000     // `origin`: world coordinate of cell 0, 0, within +-this
#define POVC_MAX_CLOUDS 10000000    // `clouds`: seconds on the cloud clock
#define POVC_MAX_MSGS   20          // rejection messages on stderr

// True when the command line has -pov-control. Everything below is inert without it.
int POV_ControlEnabled(void);

// Platform choice, call before the first tick. live = 0: reading blocks until `next`,
// `quit` or end of input (deterministic). live = 1: reading never blocks, a frame is drawn
// in every tick in which something changed (and once at the start).
void POV_ControlSetLive(int live);
int POV_ControlIsLive(void);

// Picture size in points (COSMERGON.md, "Picture size"): 160..1280 x 100..800. Returns 1 when taken
// (the next frame has that size and is shown 1 : 1), 0 when outside the range (nothing changes).
// Used by the `size` line and by a platform layer that follows its window.
int POV_ControlRequestSize(int width, int height);

// One iteration of the main loop (called by doomgeneric_Tick in place of the game loop).
void POV_ControlTick(void);

// True once `quit` or end of input was reached and nothing is left to draw.
int POV_ControlDone(void);

// Prints "control: lines=<n> rejected=<m>" (once).
void POV_ControlSummary(FILE *out);

// Platform layer: read up to max bytes from the control input.
//   returns > 0   number of bytes read
//   returns 0     nothing available now (only when wait == 0)
//   returns < 0   end of input (or read error)
// wait != 0 blocks until data or end of input.
int DG_ControlRead(unsigned char *buf, int max, int wait);

extern int pov_hw_vissprites;       // high water mark (r_things.c)

#endif
