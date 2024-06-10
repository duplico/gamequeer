#include "gfx.h"
#include "grlib.h"

#define OLED_VERTICAL_MAX   128
#define OLED_HORIZONTAL_MAX 128

#define LEDS_W 20
#define LEDS_H (OLED_VERTICAL_MAX / 5)

void gfx_driver_init(char *window_title) {
    gfx_open(OLED_HORIZONTAL_MAX + LEDS_W * 2, OLED_VERTICAL_MAX, window_title);
}

static void gfx_driver_pixelDraw(void *displayData, int16_t x, int16_t y, uint16_t value) {
    if (value)
        gfx_color(255, 255, 255);
    else
        gfx_color(0, 0, 0);

    gfx_point(x + LEDS_W, y);
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
    if (value) {
        gfx_color(255, 255, 255);
    } else {
        gfx_color(0, 0, 0);
    }

    gfx_line(x1, y, x2, y);
}

static void gfx_driver_lineDrawV(void *displayData, int16_t x, int16_t y1, int16_t y2, uint16_t value) {
    if (value) {
        gfx_color(255, 255, 255);
    } else {
        gfx_color(0, 0, 0);
    }

    gfx_line(x, y1, x, y2);
}

static void gfx_driver_rectFill(void *displayData, const Graphics_Rectangle *rect, uint16_t value) {
    if (value) {
        gfx_color(255, 255, 255);
    } else {
        gfx_color(0, 0, 0);
    }

    gfx_fillrect(rect->sXMin, rect->sYMin, rect->sXMax, rect->sYMax);
}

static uint32_t gfx_driver_colorTranslate(void *displayData, uint32_t value) {
    // Translate from a 24-bit RGB color to one accepted by the display.
    return (value ? 1 : 0);
}

static void gfx_driver_flush(void *displayData) {
    gfx_flush();
}

static void gfx_driver_clearDisplay(void *displayData, uint16_t value) {
    uint8_t color_val = value ? 0xFF : 0x00;
    gfx_clear_color(color_val, color_val, color_val);
}

const Graphics_Display g_gfx = {
    sizeof(Graphics_Display),     // size
    0x00,                         // displayData - unneeded here
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
