#include <stdio.h>

#include "m_argv.h"

#include "doomgeneric.h"

pixel_t* DG_ScreenBuffer = NULL;
int DG_OutW = DOOMGENERIC_RESX;
int DG_OutH = DOOMGENERIC_RESY;

void M_FindResponseFile(void);
void D_DoomMain (void);


void doomgeneric_Create(int argc, char **argv)
{
	// save arguments
    myargc = argc;
    myargv = argv;

	M_FindResponseFile();

	DG_ScreenBuffer = malloc((size_t)DG_CAPACITY_X * DG_CAPACITY_Y * 4);

	DG_Init();

	D_DoomMain ();
}

