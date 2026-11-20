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
//	Rendering of moving objects, sprites.
//


#ifndef __R_THINGS__
#define __R_THINGS__



// cosmergon-pov: one vissprite per thing in view; the control channel has at most 256 things
// (ids 0..255), the player is never linked into a sector. Overflow is an error (r_things.c).
#ifdef POV_UPSTREAM_LIMITS
#define MAXVISSPRITES  	128
#else
#define MAXVISSPRITES  	256
#endif

extern vissprite_t	vissprites[MAXVISSPRITES];
extern vissprite_t*	vissprite_p;
extern vissprite_t	vsprsortedhead;

// Constant arrays used for psprite clipping
//  and initializing clipping.
extern short		negonearray[SCREENWIDTH];
extern short		screenheightarray[SCREENWIDTH];

// vars for R_DrawMaskedColumn
extern short*		mfloorclip;
extern short*		mceilingclip;
extern fixed_t		spryscale;
extern fixed_t		sprtopscreen;

extern fixed_t		pspritescale;
extern fixed_t		pspriteiscale;


void R_DrawMaskedColumn (column_t* column);


void R_SortVisSprites (void);

void R_AddSprites (sector_t* sec);
void R_AddPSprites (void);
void R_DrawSprites (void);
void R_InitSprites (char** namelist);
void R_ClearSprites (void);
void R_DrawMasked (void);

void
R_ClipVisSprite
( vissprite_t*		vis,
  int			xl,
  int			xh );


#endif
