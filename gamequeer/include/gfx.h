/*
 * Original A simple graphics library for CSE 20211 by Douglas Thain
 * For original and documentation, see: https://www3.nd.edu/~dthain/courses/cse20211/fall2013/gfx/
 *
 * Updated 09/23,2020 - auth. Scott Graham, dsu.edu
 *       - added function: gfx_getKey()
 *             Get a single character input (keypress) without waiting, returns 0 if no key was pressed.
 *       - added functions: gfx_point() and gfx_fillrect()
 *             Nice to be able to just plot a point.
 *             Filling rectangles fast with underlying X11 lib is also nice.
 * Updated 11/29/2018 - auth. Scott Graham, dsu.edu
 *       - added functions: gfx_xNow(), gfx_yNow(), gfx_xClick(), gfx_yClick()
 *             Get the current mouse x,y coordinates, or at time of last button press/click.
 *
 * Updated 11/07/2012 - auth. Scott Graham, dsu.edu, Now much faster changing colors.
 * Updated 09/23/2011 - auth. Scott Graham, dsu.edu, Fixes a bug that could result in jerky animation.
 */

#ifndef GFX_H
#define GFX_H

/* Open a new graphics window. */
void gfx_open(int width, int height, const char *title);

/* Draw a point at (x,y) */
void gfx_point(int x, int y);

/* Draw a line from (x1,y1) to (x2,y2) */
void gfx_line(int x1, int y1, int x2, int y2);
void gfx_fillrect(int x1, int y1, int x2, int y2);
/* Change the current drawing color. */
void gfx_color(int red, int green, int blue);

/* Clear the graphics window to the background color. */
void gfx_clear();

/* Change the current background color. */
void gfx_clear_color(int red, int green, int blue);

/* Wait for the user to press a key or mouse button. */
char gfx_wait();

/* Return the X and Y dimensions of the window. */
int gfx_height();
int gfx_width();

/* Check to see if an event is waiting. */
int gfx_event_waiting();

/* Flush all previous output to the window. */
void gfx_flush();

/*--------------------------------*/
/* Added in gfx2 */

/* Return the X and Y coordinates of the last event. */
int gfx_xClick();
int gfx_yClick();
/* return mouse position */
int gfx_xNow();
int gfx_yNow();

/*---------------------------------*/
/* Added in gfx3 */

// get key without waiting if nothing has been pressed
char gfx_getKey();

#endif
