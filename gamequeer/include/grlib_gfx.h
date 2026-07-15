#ifndef GRLIB_GFX_H
#define GRLIB_GFX_H

#include <gfx.h>
#include <grlib.h>

/*
 * OLED_VERTICAL_MAX / OLED_HORIZONTAL_MAX -- the emulator's display
 * dimensions (height/width), used as an EXCLUSIVE bound: valid coordinates
 * run 0..MAX-1 (frame_buffer[][] is sized [HORIZONTAL_MAX][VERTICAL_MAX],
 * and every coordinate bounds check in grlib_gfx_driver.c is `>= MAX`;
 * main.c only iterates 0..MAX-1 over frame_buffer's dimensions when
 * writing out the PGM, so it has no separate bounds check of its own).
 * This is the emulator's counterpart to the badge's LCD_X_SIZE/LCD_Y_SIZE
 * (ccs_workspace/qc2024/sh1107.h), which are 128 and used exactly the same
 * way. Both values are also fed as `width`/`height` into a Graphics_Display
 * (g_gfx here, g_oled on the badge); Graphics_initContext() (context.c)
 * derives the INCLUSIVE clipRegion.xMax/yMax as `width/height - 1` from
 * that, once, centrally -- so this macro must stay a size, not a
 * pre-decremented max index, or the display gets clipped one pixel short
 * on each axis. Was incorrectly set to 127 (commit a77ea39, "Fix an off by
 * one error") -- see gamequeer#297: that shrank the emulator's rendered/
 * validated area to 127x127, one row/column short of the real 128x128
 * badge display, leaving the true edge (x=127, y=127) permanently
 * untested by the golden suite.
 */
#define OLED_VERTICAL_MAX   128
#define OLED_HORIZONTAL_MAX 128

#define LEDS_W 20
#define LEDS_H (OLED_VERTICAL_MAX / 5)

extern const Graphics_Display g_gfx;

void gfx_driver_init(char *window_title);

#endif
