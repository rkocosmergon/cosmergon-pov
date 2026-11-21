// Modified for cosmergon-pov, November 2026, by RKO Consult UG (haftungsbeschraenkt);
// the changes are listed in COSMERGON.md and marked "cosmergon-pov" in the code.
#ifndef DOOM_GENERIC
#define DOOM_GENERIC

#include <stdlib.h>
#include <stdint.h>

#ifndef DOOMGENERIC_RESX
#define DOOMGENERIC_RESX 640
#endif  // DOOMGENERIC_RESX

#ifndef DOOMGENERIC_RESY
#define DOOMGENERIC_RESY 400
#endif  // DOOMGENERIC_RESY


#ifdef CMAP256

typedef uint8_t pixel_t;

#else  // CMAP256

typedef uint32_t pixel_t;

#endif  // CMAP256


extern pixel_t* DG_ScreenBuffer;
// cosmergon-pov: the picture in DG_ScreenBuffer is DG_OutW x DG_OutH, tightly packed; set by
// I_FinishUpdate before DG_DrawFrame (RESX x RESY without -pov-control). The buffer holds the
// largest picture (DG_CAPACITY_X x DG_CAPACITY_Y, which is POV_MAX_W x POV_MAX_H of i_video.h).
extern int DG_OutW;
extern int DG_OutH;
#ifdef POV_VIEW_ONLY
#define DG_CAPACITY_X 1280
#define DG_CAPACITY_Y 800
#else
#define DG_CAPACITY_X DOOMGENERIC_RESX
#define DG_CAPACITY_Y DOOMGENERIC_RESY
#endif

#ifdef __cplusplus
extern "C" {
#endif

void doomgeneric_Create(int argc, char **argv);
void doomgeneric_Tick();


//Implement below functions for your platform
void DG_Init();
void DG_DrawFrame();
void DG_SleepMs(uint32_t ms);
uint32_t DG_GetTicksMs();
int DG_GetKey(int* pressed, unsigned char* key);
void DG_SetWindowTitle(const char * title);

#ifdef __cplusplus
}
#endif

#endif //DOOM_GENERIC
