/*
 * Headless (no-op) stub for the gfx display backend.
 *
 * When GQ_HEADLESS is defined, this file replaces gfx.c so the emulator
 * builds and runs without a DISPLAY.  The grlib→frame_buffer render path
 * (grlib_gfx_driver.c) is fully intact; only the X11 sink is stubbed out.
 *
 * All gfx_* functions that normally touch the X11 window become no-ops.
 * gfx_getKey() always returns 0 (no key), which lets HAL_event_poll() work
 * without modification in headless mode.
 */

#include "gfx.h"

void gfx_open(int width, int height, const char *title) {
    (void) width;
    (void) height;
    (void) title;
}

int gfx_width(void) {
    return 0;
}

int gfx_height(void) {
    return 0;
}

void gfx_point(int x, int y) {
    (void) x;
    (void) y;
}

void gfx_line(int x1, int y1, int x2, int y2) {
    (void) x1;
    (void) y1;
    (void) x2;
    (void) y2;
}

void gfx_fillrect(int x1, int y1, int x2, int y2) {
    (void) x1;
    (void) y1;
    (void) x2;
    (void) y2;
}

void gfx_color(int r, int g, int b) {
    (void) r;
    (void) g;
    (void) b;
}

void gfx_clear(void) {
}

void gfx_clear_color(int r, int g, int b) {
    (void) r;
    (void) g;
    (void) b;
}

int gfx_event_waiting(void) {
    return 0;
}

char gfx_wait(void) {
    return 0;
}

void gfx_flush(void) {
}

int gfx_xClick(void) {
    return 0;
}

int gfx_yClick(void) {
    return 0;
}

int gfx_xNow(void) {
    return 0;
}

int gfx_yNow(void) {
    return 0;
}

char gfx_getKey(void) {
    return 0;
}
