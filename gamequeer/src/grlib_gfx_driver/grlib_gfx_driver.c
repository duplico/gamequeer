#include <string.h>

#include "gamequeer.h"
#include "gfx.h"
#include "grlib.h"
#include "grlib_gfx.h"

uint8_t frame_buffer[OLED_HORIZONTAL_MAX][OLED_VERTICAL_MAX] = {
    0,
};

void gfx_driver_init(char *window_title) {
    gfx_open(OLED_HORIZONTAL_MAX + LEDS_W * 2, OLED_VERTICAL_MAX, window_title);
}

static void gfx_driver_pixelDraw(void *displayData, int16_t x, int16_t y, uint16_t value) {
    if (x < 0 || x >= OLED_HORIZONTAL_MAX || y < 0 || y >= OLED_VERTICAL_MAX) {
        return;
    }
    frame_buffer[x][y] = value ? 1 : 0;
}

/*
 * HAL_oled_fill_run() -- emulator implementation (see the doc comment on
 * its declaration in gamequeer.h for the full contract).
 *
 * frame_buffer here is uint8_t[x][y] (one byte per pixel), so unlike the
 * badge's packed 1bpp framebuffer (sh1107.c) there's no bit-packing to do
 * -- this is a plain per-column store loop. The bounds check mirrors
 * gfx_driver_pixelDraw()'s existing defensive check (rather than trusting
 * the caller's clip) since this is, like that function, a raw framebuffer
 * write with no further indirection between it and the display buffer.
 * Performance here is not the point (see issue #261 / docs/perf-
 * investigation.md's "Emulator measurability" note) -- pixel-identical
 * output vs. the old per-pixel path is.
 */
void HAL_oled_fill_run(int16_t x, int16_t y, uint16_t length, uint8_t value) {
    if (y < 0 || y >= OLED_VERTICAL_MAX || length == 0) {
        return;
    }
    if (x < 0) {
        // Defensive only -- oled.c's callers already clip x to
        // [clipRegion.xMin, clipRegion.xMax], both non-negative.
        if ((uint16_t) -x >= length) {
            return;
        }
        length = (uint16_t) (length + x);
        x      = 0;
    }
    if (x >= OLED_HORIZONTAL_MAX) {
        // Defensive only -- see above. Without this, the clamp below
        // (OLED_HORIZONTAL_MAX - x) would underflow when x is already
        // past the right edge, wrapping length to a huge uint16_t and
        // driving the fill loop far out of frame_buffer's bounds.
        return;
    }
    if (x + length > OLED_HORIZONTAL_MAX) {
        length = (uint16_t) (OLED_HORIZONTAL_MAX - x);
    }

    uint8_t pixel = value ? 1 : 0;
    for (uint16_t i = 0; i < length; i++) {
        frame_buffer[x + i][y] = pixel;
    }
}

static void gfx_driver_pixelDrawMultiple(
    void *displayData,
    int16_t x,
    int16_t y,
    int16_t x0, // offset
    int16_t count,
    int16_t bPP,
    const uint8_t *data,
    const uint32_t *palette) {
    // NB: Supports 1BPP only

    uint16_t image_data_byte;

    while (count > 0) {
        image_data_byte = *data++;
        for (; (x0 < 8 && count); x0++, count--) {
            volatile uint16_t val;
            val = (image_data_byte >> (8 - x0 - 1)) & 1;
            val = palette[val];
            gfx_driver_pixelDraw(displayData, x, y, val);
            x++;
        }
        x0 = 0;
    }
}

static void gfx_driver_lineDrawH(void *displayData, int16_t x1, int16_t x2, int16_t y, uint16_t value) {
    for (int16_t x = x1; x <= x2; x++) {
        gfx_driver_pixelDraw(displayData, x, y, value);
    }
}

static void gfx_driver_lineDrawV(void *displayData, int16_t x, int16_t y1, int16_t y2, uint16_t value) {
    for (int16_t y = y1; y <= y2; y++) {
        gfx_driver_pixelDraw(displayData, x, y, value);
    }
}

static void gfx_driver_rectFill(void *displayData, const Graphics_Rectangle *rect, uint16_t value) {
    for (int16_t y = rect->yMin; y <= rect->yMax; y++) {
        for (int16_t x = rect->xMin; x <= rect->xMax; x++) {
            gfx_driver_pixelDraw(displayData, x, y, value);
        }
    }
}

static uint32_t gfx_driver_colorTranslate(void *displayData, uint32_t value) {
    // Translate from a 24-bit RGB color to one accepted by the display.
    return (value ? 1 : 0);
}

static void gfx_driver_flush(void *displayData) {
    for (int16_t y = 0; y < OLED_VERTICAL_MAX; y++) {
        for (int16_t x = 0; x < OLED_HORIZONTAL_MAX; x++) {
            if (frame_buffer[x][y]) {
                gfx_color(255, 255, 255);
            } else {
                gfx_color(0, 0, 0);
            }
            gfx_point(x + LEDS_W, y);
        }
    }
    gfx_flush();
}

static void gfx_driver_clearDisplay(void *displayData, uint16_t value) {
    memset(frame_buffer, value ? 1 : 0, sizeof(frame_buffer));
}

const Graphics_Display g_gfx = {
    sizeof(Graphics_Display),     // size
    frame_buffer,                 // displayData - unneeded here
    OLED_HORIZONTAL_MAX,          // width
    OLED_VERTICAL_MAX,            // height
    gfx_driver_pixelDraw,         // callPixelDraw
    gfx_driver_pixelDrawMultiple, // callPixelDrawMultiple
    gfx_driver_lineDrawH,         // callLineDrawH
    gfx_driver_lineDrawV,         // callLineDrawV
    gfx_driver_rectFill,          // callRectFill
    gfx_driver_colorTranslate,    // callColorTranslate
    gfx_driver_flush,             // callFlush
    gfx_driver_clearDisplay       // callClearDisplay
};
