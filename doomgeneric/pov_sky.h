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

// Cloud clock in milliseconds: the base set by the `clouds` line plus the live drift.
void POV_SkySetCloudBase(double ms);
void POV_SkySetCloudLive(double ms);
// Whole picture points the clouds have moved at this picture width (the picture is redrawn only when this
// changes).
long POV_SkyDriftPoints(int view_w);

// Once per picture, before the planes (needs viewangle and the view size).
void POV_SkyBegin(void);
// One sky column: rows yl..yh of column x.
void POV_SkyColumn(int x, int yl, int yh);

#endif
