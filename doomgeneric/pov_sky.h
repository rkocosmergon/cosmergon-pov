// cosmergon-pov: the sky of a theme (COSMERGON.md, "The sky"). Drawn per point, not from a texture
// column: bands of elevation, stars, sun or moon, drifting clouds, and the colours of the time of day.
// Inert without the theme lumps POVSKY and POVCLD.

#ifndef POV_SKY_H
#define POV_SKY_H

// Looks for the lumps (after the theme is loaded). Returns 1 when the sky is ours.
int POV_SkyLoad(void);
int POV_SkyActive(void);

// `daytime`: minutes 0..1439, local time chosen by the sender. Default 720.
void POV_SkySetMinute(int minute);
int  POV_SkyMinute(void);
// The 256 colours (768 bytes) of a minute of the day, interpolated between the key palettes.
void POV_SkyPalette(int minute, unsigned char *out768);

// World time of the clouds in milliseconds: the base set by the `clouds` line plus the live clock.
void POV_SkySetCloudBase(double ms);
void POV_SkySetCloudLive(double ms);
// Where the field lies in the world: the grid position of its cube, the level of the field in the cube, the cube's
// dimension in cells (`world` line); the world coordinates of the window's cell 0, 0 (`origin` line).
void POV_SkySetWorld(int cx, int cy, int cz, int level, int dim);
void POV_SkySetOrigin(int ox, int oy);
// Neighbour cubes (`cube` / `nocube`), ids 0..63.
void POV_SkyCube(int id, int cx, int cy, int cz, int dim);
void POV_SkyNoCube(int id);
// True when a cloud has moved a whole point since the picture drawn last (live mode draws only then).
int POV_SkyDirty(void);

// Once per picture, before the planes (needs viewangle and the view size).
void POV_SkyBegin(void);
// One sky column: rows yl..yh of column x.
void POV_SkyColumn(int x, int yl, int yh);

#endif
