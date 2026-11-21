//
// Copyright(C) 1993-1996 Id Software, Inc.
// Copyright(C) 2005-2014 Simon Howard
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
// DESCRIPTION:
//	System specific interface stuff.
//


#ifndef __R_MAIN__
#define __R_MAIN__

#include <stdint.h>

#include "d_player.h"
#include "r_data.h"




//
// POV related.
//
extern fixed_t		viewcos;
extern fixed_t		viewsin;

extern int		viewwindowx;
extern int		viewwindowy;



extern int		centerx;
extern int		centery;

extern fixed_t		centerxfrac;
extern fixed_t		centeryfrac;
extern fixed_t		projection;

// cosmergon-pov (r_main.c, R_ExecuteSetViewSize): sky scale, the largest wall scale and the nearest
// distance of a thing, all following the picture size.
extern fixed_t		pov_sky_iscale;
extern fixed_t		pov_max_wall_scale;
extern fixed_t		pov_minz;

extern int		validcount;

extern int		linecount;
extern int		loopcount;


//
// Lighting LUT.
// Used for z-depth cuing per column/row,
//  and other lighting effects (sector ambient, flash).
//

// Lighting constants.
// Now why not 32 levels here?
#define LIGHTLEVELS	        16
#define LIGHTSEGSHIFT	         4

#define MAXLIGHTSCALE		48
#define LIGHTSCALESHIFT		12
// cosmergon-pov: 256 (was 128): a theme's haze goes beyond the 2048 units upstream's table ends at. The levels
// of the old entries are unchanged and the new ones equal the last old one (80 / (j + 1) is 0 from j = 80 on).
#define MAXLIGHTZ	       256
#define LIGHTZSHIFT		20

// cosmergon-pov: index into scalelight for a scale (pixels per unit, 16.16) given as `shift`
// (LIGHTSCALESHIFT or one less for sprites). The scale is first normalised to the reference width
// (320), so that a wall at a given distance gets the same light in a 1280 picture as in a 320 one.
// At 320 the factor is exactly 1: the result is upstream's `scale >> shift`.
extern int		viewwidth;		// r_draw.c

static inline int R_LightIndex(fixed_t scale, int shift)
{
    return (int)(((int64_t)scale * POV_REF_W / viewwidth) >> shift);
}

// cosmergon-pov: haze (lump POVFOG): beyond a distance the colormap row of a flat (pov_fog_j) or a wall
// (pov_fog_scale, the scale normalised as above) is one further. 0 = off, the upstream light.
extern int pov_fog_j;
extern int pov_fog_scale;

static inline int R_FogRow(fixed_t scale)
{
    return (pov_fog_scale && (int64_t)scale * POV_REF_W / viewwidth < pov_fog_scale) ? 256 : 0;
}

extern lighttable_t*	scalelight[LIGHTLEVELS][MAXLIGHTSCALE];
extern lighttable_t*	scalelightfixed[MAXLIGHTSCALE];
extern lighttable_t*	zlight[LIGHTLEVELS][MAXLIGHTZ];

extern int		extralight;
extern lighttable_t*	fixedcolormap;


// Number of diminishing brightness levels.
// There a 0-31, i.e. 32 LUT in the COLORMAP lump.
#define NUMCOLORMAPS		32


// Blocky/low detail mode.
//B remove this?
//  0 = high, 1 = low
extern	int		detailshift;	


//
// Function pointers to switch refresh/drawing functions.
// Used to select shadow mode etc.
//
extern void		(*colfunc) (void);
extern void		(*transcolfunc) (void);
extern void		(*basecolfunc) (void);
extern void		(*fuzzcolfunc) (void);
// No shadow effects on floors.
extern void		(*spanfunc) (void);


//
// Utility functions.
int
R_PointOnSide
( fixed_t	x,
  fixed_t	y,
  node_t*	node );

int
R_PointOnSegSide
( fixed_t	x,
  fixed_t	y,
  seg_t*	line );

angle_t
R_PointToAngle
( fixed_t	x,
  fixed_t	y );

angle_t
R_PointToAngle2
( fixed_t	x1,
  fixed_t	y1,
  fixed_t	x2,
  fixed_t	y2 );

fixed_t
R_PointToDist
( fixed_t	x,
  fixed_t	y );


fixed_t R_ScaleFromGlobalAngle (angle_t visangle);

subsector_t*
R_PointInSubsector
( fixed_t	x,
  fixed_t	y );

void
R_AddPointToBox
( int		x,
  int		y,
  fixed_t*	box );



//
// REFRESH - the actual rendering functions.
//

// Called by G_Drawer.
void R_RenderPlayerView (player_t *player);

// Called by startup code.
void R_Init (void);

// Called by M_Responder.
void R_SetViewSize (int blocks, int detail);

#endif
