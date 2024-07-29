#ifndef GRLIB_GFX_H
#define GRLIB_GFX_H

#include <gfx.h>
#include <grlib.h>

#define OLED_VERTICAL_MAX   127
#define OLED_HORIZONTAL_MAX 127

#define LEDS_W 20
#define LEDS_H (OLED_VERTICAL_MAX / 5)

extern const Graphics_Display g_gfx;

void gfx_driver_init(char *window_title);

#endif
