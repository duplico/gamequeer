#include <stdint.h>

#include "HAL.h"
#include "gamequeer.h"
#include "grlib.h"

#include <gamequeer.h>

void gq_draw_image(
    const Graphics_Context *context,
    t_gq_pointer image_bytes,
    int16_t bPP,
    int16_t width,
    int16_t height,
    t_gq_int x,
    t_gq_int y) {
    // TODO: Add palette support.

    uint8_t render_byte;
    const uint32_t palette[2] = {0, 1};
    int16_t x0, x1, x2;
    uint16_t x_bit_offset, x_byte_offset, x_pixel_offset;
    uint8_t y_offset = 0;

    uint8_t pixel_value;
    uint8_t pixel_repeat;
    uint8_t rle_type;

    // Return without doing anything if the entire image lies outside the
    // current clipping region.
    if ((x > context->clipRegion.xMax) || ((x + width - 1) < context->clipRegion.xMin) ||
        (y > context->clipRegion.yMax) || ((y + height - 1) < context->clipRegion.yMin)) {
        return;
    }

    // Get the starting X offset within the image based on the current clipping region.
    if (x < context->clipRegion.xMin) {
        x0 = context->clipRegion.xMin - x;
    } else {
        x0 = 0;
    }

    // Get the ending X offset within the image based on the current clipping region.
    if ((x + width - 1) > context->clipRegion.xMax) {
        x2 = context->clipRegion.xMax - x;
    } else {
        x2 = width - 1;
    }

    // Reduce the height of the image, if required, based on the current clipping region.
    if ((y + height - 1) > context->clipRegion.yMax) {
        height = context->clipRegion.yMax - y + 1;
    }

    if (bPP == 1) {
        // Image is uncompressed; 1 bit per pixel.

        // First, check to see if the top of the image needs to be cut off (and we need to skip ahead)
        if (y < context->clipRegion.yMin) {
            // Determine the number of rows that lie above the clipping region.
            y_offset = context->clipRegion.yMin - y;

            // Skip past the data for the rows that lie above the clipping region.
            // image_bytes += (((width * bPP) + 7) / 8) * y_offset;
        }

        while (y_offset < height) {
            // Draw this row of image pixels, starting at x0 and ending at x2.
            // Draw the pixels.
            x_pixel_offset = x0;
            x_bit_offset   = x0 % 8;
            x_byte_offset  = y_offset * (width / 8) + (x0 / 8);

            while (x_pixel_offset <= x2) {
                // Read the byte from the image data.
                render_byte = read_byte(image_bytes + x_byte_offset);

                // Draw the current byte's worth of pixels (up to 8):
                while (x_bit_offset < 8 && x_pixel_offset <= x2) {
                    // Draw the pixel.
                    Graphics_drawPixelOnDisplay(
                        context->display,
                        x + x_pixel_offset,
                        y + y_offset,
                        palette[(render_byte >> (7 - x_bit_offset)) & 0x01]);

                    // Increment the pixel offset.
                    x_pixel_offset++;
                    x_bit_offset++;
                }

                x_bit_offset = 0;
                x_byte_offset++;
            }

            y_offset++;
        }
    } else {
        // Image is compressed; RLE4 or RLE7
        rle_type       = (bPP >> 4) & 0x0F;
        x_pixel_offset = 0;
        y_offset       = 0;

        do {
            render_byte = read_byte(image_bytes);
            image_bytes++;

            if (rle_type == 7) {
                // RLE 7 bit encoding
                pixel_repeat = (render_byte >> 1) + 1;
                pixel_value  = render_byte & 0x01;
            } else if (rle_type == 4) {
                // TODO: We probably won't ever need this.
                // RLE 4 bit encoding
                pixel_repeat = (render_byte >> 4) + 1;
                pixel_value  = render_byte & 0x0F;
            } else {
                // Invalid RLE type.
                return;
            }

            while (pixel_repeat--) {
                if (x_pixel_offset == width) {
                    x_pixel_offset = 0;
                    y_offset++;

                    if (y + y_offset > context->clipRegion.yMax) {
                        return;
                    }
                }

                if (x < x0) {
                    x_pixel_offset++;
                    continue;
                }

                if (x > x2) {
                    x_pixel_offset++;
                    continue;
                }

                if (y + y_offset < context->clipRegion.yMin) {
                    x_pixel_offset++;
                    continue;
                }

                if (y + y_offset > context->clipRegion.yMax || y_offset >= height) {
                    // We're done here.
                    return;
                }

                // If we're here, then (x,y) is inside the clipping region.
                Graphics_drawPixelOnDisplay(context->display, x + x_pixel_offset, y + y_offset, palette[pixel_value]);
                x_pixel_offset++;
            }
        } while (1);
    }
}
