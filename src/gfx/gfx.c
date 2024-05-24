/*
 * Original A simple graphics library for CSE 20211 by Douglas Thain
 * For original and documentation, see: https://www3.nd.edu/~dthain/courses/cse20211/fall2013/gfx/
 *
 * Updated 04/28/2021 - auth. Scott graham
 *       - fixed gfx_fillRect so it does not matter what order the corners are in
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
 * Updated 01/30/2022 - auth. Scott Graham, dsu.edu, added gfx_xsize(), gfx_ysize() to retrive window size in case it
 * changed
 */

#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "gfx.h"

/*
gfx_open creates several X11 objects, and stores them in globals
for use by the other functions in the library.
*/

static Display *gfx_display = 0;
static Window gfx_window;
static GC gfx_gc;
static Colormap gfx_colormap;
static int gfx_fast_color_mode = 0;

/* These values are saved by gfx_wait then retrieved later by gfx_xpos and gfx_ypos. */

static int saved_xpos = 0;
static int saved_ypos = 0;
// static int keyState[256] = { 0 };

/* Open a new graphics window. */

void gfx_open(int width, int height, const char *title) {
    gfx_display = XOpenDisplay(0);
    if (!gfx_display) {
        fprintf(stderr, "gfx_open: unable to open the graphics window.\n");
        exit(1);
    }

    Visual *visual = DefaultVisual(gfx_display, 0);
    if (visual && visual->class == TrueColor) {
        gfx_fast_color_mode = 1;
    } else {
        gfx_fast_color_mode = 0;
    }

    int blackColor = BlackPixel(gfx_display, DefaultScreen(gfx_display));
    int whiteColor = WhitePixel(gfx_display, DefaultScreen(gfx_display));

    gfx_window = XCreateSimpleWindow(
        gfx_display, DefaultRootWindow(gfx_display), 0, 0, width, height, 0, blackColor, blackColor);

    XSetWindowAttributes attr;
    attr.backing_store = Always;

    XChangeWindowAttributes(gfx_display, gfx_window, CWBackingStore, &attr);

    XStoreName(gfx_display, gfx_window, title);

    XSelectInput(gfx_display, gfx_window, StructureNotifyMask | KeyPressMask | ButtonPressMask);

    XMapWindow(gfx_display, gfx_window);

    gfx_gc = XCreateGC(gfx_display, gfx_window, 0, 0);

    gfx_colormap = DefaultColormap(gfx_display, 0);

    XSetForeground(gfx_display, gfx_gc, whiteColor);

    // Wait for the MapNotify event

    for (;;) {
        XEvent e;
        XNextEvent(gfx_display, &e);
        if (e.type == MapNotify)
            break;
    }
}
/* new functions to obtain graphic window dimensions */
int gfx_width() {
    XWindowAttributes window_attributes_return;
    XGetWindowAttributes(gfx_display, gfx_window, &window_attributes_return);
    return window_attributes_return.width;
}
int gfx_height() {
    XWindowAttributes window_attributes_return;
    XGetWindowAttributes(gfx_display, gfx_window, &window_attributes_return);
    return window_attributes_return.height;
}

/* Draw a single point at (x,y) */

void gfx_point(int x, int y) {
    XDrawPoint(gfx_display, gfx_window, gfx_gc, x, y);
}

/* Draw a line from (x1,y1) to (x2,y2) */

void gfx_line(int x1, int y1, int x2, int y2) {
    XDrawLine(gfx_display, gfx_window, gfx_gc, x1, y1, x2, y2);
}

void gfx_fillrect(int x1, int y1, int x2, int y2) {
    int topLeftX = (x1 < x2) ? x1 : x2;
    int topLeftY = (y1 < y2) ? y1 : y2;
    int width    = x2 - x1;
    width        = (width >= 0) ? width : -width;
    int height   = y2 - y1;
    height       = (height >= 0) ? height : -height;

    XFillRectangle(gfx_display, gfx_window, gfx_gc, topLeftX, topLeftY, width, height);
}

/* Change the current drawing color. */

void gfx_color(int r, int g, int b) {
    XColor color;

    if (gfx_fast_color_mode) {
        /* If this is a truecolor display, we can just pick the color directly. */
        color.pixel = ((b & 0xff) | ((g & 0xff) << 8) | ((r & 0xff) << 16));
    } else {
        /* Otherwise, we have to allocate it from the colormap of the display. */
        color.pixel = 0;
        color.red   = r << 8;
        color.green = g << 8;
        color.blue  = b << 8;
        XAllocColor(gfx_display, gfx_colormap, &color);
    }

    XSetForeground(gfx_display, gfx_gc, color.pixel);
}

/* Clear the graphics window to the background color. */

void gfx_clear() {
    XClearWindow(gfx_display, gfx_window);
}

/* Change the current background color. */

void gfx_clear_color(int r, int g, int b) {
    XColor color;
    color.pixel = 0;
    color.red   = r << 8;
    color.green = g << 8;
    color.blue  = b << 8;
    XAllocColor(gfx_display, gfx_colormap, &color);

    XSetWindowAttributes attr;
    attr.background_pixel = color.pixel;
    XChangeWindowAttributes(gfx_display, gfx_window, CWBackPixel, &attr);
}

/* Check whether an event is waiting in queue */

int gfx_event_waiting() {
    XEvent event;

    gfx_flush();

    while (XCheckMaskEvent(gfx_display, -1, &event)) {
        if (event.type == KeyPress) {
            XPutBackEvent(gfx_display, &event);
            return 1;
        } else if (event.type == ButtonPress) {
            XPutBackEvent(gfx_display, &event);
            return 1;
        }
    }
    return 0;
}

/* Wait for the user to press a key or mouse button. */

char gfx_wait() {
    XEvent event;

    gfx_flush();

    while (1) {
        XNextEvent(gfx_display, &event);

        if (event.type == KeyPress) {
            saved_xpos = event.xkey.x;
            saved_ypos = event.xkey.y;
            return XLookupKeysym(&event.xkey, 0);
        } else if (event.type == ButtonPress) {
            saved_xpos = event.xkey.x;
            saved_ypos = event.xkey.y;
            return event.xbutton.button;
        }
    }
}

/* Flush all previous output to the window. */
void gfx_flush() {
    XFlush(gfx_display);
}

/********************************
Code below added in Version gfx2
*********************************/

// get the X coordinate of the mouse at time of last button press our mouse click
// specifically gets the position after the last use of gfx_getkey() or gfx_wait()
// that actually returned a key press
int gfx_xClick() {
    return saved_xpos;
}
// get the Y coordinate of the mouse at time of last button press our mouse click
int gfx_yClick() {
    return saved_ypos;
}
// get the X coordinate of the mouse right now
int gfx_xNow() {
    Window tmp_returnWindow;
    int root_x, root_y, win_x, win_y, mask_return, result;
    result = XQueryPointer(
        gfx_display, gfx_window, &tmp_returnWindow, &tmp_returnWindow, &root_x, &root_y, &win_x, &win_y, &mask_return);
    return win_x;
}
// get the Y coordinate of the mouse right now
int gfx_yNow() {
    Window tmp_returnWindow;
    int root_x, root_y, win_x, win_y, mask_return, result;
    result = XQueryPointer(
        gfx_display, gfx_window, &tmp_returnWindow, &tmp_returnWindow, &root_x, &root_y, &win_x, &win_y, &mask_return);
    return win_y;
}

/************************************
Code above added in version gfx2
*************************************/

/*********************************
Code below added in Version gfx3
**********************************/

// gets a key that was pressed, but does not wait, if no key pressed
// returns 1,2,3 for L,M,R mouse buttons, or ' ' thru '~' for keyboard keys -- distinguishes shifted
char gfx_getKey() {
    if (gfx_event_waiting()) {
        char key = gfx_wait();
        while (gfx_event_waiting()) {
            gfx_wait();
        } // flush out any repeat-keys
        return key;
    }
}
/*
// routine to query the state of a key... (buttons too??) -- untested code, so commented for later revision
//  from here:
https://www.unknowncheats.me/forum/c-and-c-/183880-linux-detecting-key-held-simulating-getasynckeystate.html
// also look here:  https://tronche.com/gui/x/xlib/events/keyboard-pointer/keyboard-pointer.html  (mouse buttons?)
bool GetKeyState(KeySym keySym)
{
    if(g_pDisplay == NULL)
    {
        return false;
    }

    char szKey[32];
    int iKeyCodeToFind = XKeysymToKeycode(g_pDisplay, keySym);

    XQueryKeymap(g_pDisplay, szKey);

    return szKey[iKeyCodeToFind / 8] & (1 << (iKeyCodeToFind % 8));
}


// return true or false if a key is being held down
int gfx_KeyHeldDown(char key) {
    return ( (1<=key&&key<=3) || (' '<=key&&key<='~') ) ? keyStates[key] : 0 ;
}
*/
/*********************************
Code above added in Version gfx3
**********************************/
