#include <stdint.h>

#include "HAL.h"
#include "gamequeer.h"
#include "grlib.h"

#include <gamequeer.h>

typedef struct gq_image_frame_on_screen {
    t_gq_pointer image_bytes;
    uint8_t x_start;
    uint8_t x_end;
    uint16_t x_bit_offset;
    uint16_t x_byte_offset;
    uint16_t x_pixel_offset;
    uint8_t y_offset;
    uint8_t render_byte;
    uint8_t pixel_value;
    uint8_t pixel_repeat;
    uint8_t rle_type;
} gq_image_frame_on_screen;

void gq_draw_image(
    const Graphics_Context *context,
    t_gq_pointer image_bytes,
    int16_t bPP,
    int16_t width,
    int16_t height,
    t_gq_int x,
    t_gq_int y) {
    // TODO: Add palette support.

    gq_image_frame_on_screen frame = {
        0,
    };

    const uint32_t palette[2] = {0, 1};

    // Return without doing anything if the entire image lies outside the
    // current clipping region.
    if ((x > context->clipRegion.xMax) || ((x + width - 1) < context->clipRegion.xMin) ||
        (y > context->clipRegion.yMax) || ((y + height - 1) < context->clipRegion.yMin)) {
        return;
    }

    // Get the starting X offset within the image based on the current clipping region.
    if (x < context->clipRegion.xMin) {
        frame.x_start = context->clipRegion.xMin - x;
    } else {
        frame.x_start = 0;
    }

    // Get the ending X offset within the image based on the current clipping region.
    if ((x + width - 1) > context->clipRegion.xMax) {
        frame.x_end = context->clipRegion.xMax - x;
    } else {
        frame.x_end = width - 1;
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
            frame.y_offset = context->clipRegion.yMin - y;

            // Skip past the data for the rows that lie above the clipping region.
            // image_bytes += (((width * bPP) + 7) / 8) * y_offset;
        }

        while (frame.y_offset < height) {
            // Draw this row of image pixels, starting at x_start and ending at x_end.
            // Draw the pixels.
            frame.x_pixel_offset = frame.x_start;
            frame.x_bit_offset   = frame.x_start % 8;
            frame.x_byte_offset  = frame.y_offset * (width / 8) + (frame.x_start / 8);

            while (frame.x_pixel_offset <= frame.x_end) {
                // Read the byte from the image data.
                frame.render_byte = read_byte(image_bytes + frame.x_byte_offset);

                // Draw the current byte's worth of pixels (up to 8):
                while (frame.x_bit_offset < 8 && frame.x_pixel_offset <= frame.x_end) {
                    // Draw the pixel.
                    Graphics_drawPixelOnDisplay(
                        context->display,
                        x + frame.x_pixel_offset,
                        y + frame.y_offset,
                        palette[(frame.render_byte >> (7 - frame.x_bit_offset)) & 0x01]);

                    // Increment the pixel offset.
                    frame.x_pixel_offset++;
                    frame.x_bit_offset++;
                }

                frame.x_bit_offset = 0;
                frame.x_byte_offset++;
            }

            frame.y_offset++;
        }
    } else {
        // Image is compressed; RLE4 or RLE7
        frame.rle_type       = (bPP >> 4) & 0x0F;
        frame.x_pixel_offset = 0;
        frame.y_offset       = 0;

        do {
            frame.render_byte = read_byte(image_bytes);
            image_bytes++;

            if (frame.rle_type == 7) {
                // RLE 7 bit encoding
                frame.pixel_repeat = (frame.render_byte >> 1) + 1;
                frame.pixel_value  = frame.render_byte & 0x01;
            } else if (frame.rle_type == 4) {
                // TODO: We probably won't ever need this.
                // RLE 4 bit encoding
                frame.pixel_repeat = (frame.render_byte >> 4) + 1;
                frame.pixel_value  = frame.render_byte & 0x0F;
            } else {
                // Invalid RLE type.
                return;
            }

            while (frame.pixel_repeat--) {
                if (frame.x_pixel_offset == width) {
                    frame.x_pixel_offset = 0;
                    frame.y_offset++;

                    if (y + frame.y_offset > context->clipRegion.yMax) {
                        return;
                    }
                }

                if (x < frame.x_start) {
                    frame.x_pixel_offset++;
                    continue;
                }

                if (x > frame.x_end) {
                    frame.x_pixel_offset++;
                    continue;
                }

                if (y + frame.y_offset < context->clipRegion.yMin) {
                    frame.x_pixel_offset++;
                    continue;
                }

                if (y + frame.y_offset > context->clipRegion.yMax || frame.y_offset >= height) {
                    // We're done here.
                    return;
                }

                // If we're here, then (x,y) is inside the clipping region.
                Graphics_drawPixelOnDisplay(
                    context->display, x + frame.x_pixel_offset, y + frame.y_offset, palette[frame.pixel_value]);
                frame.x_pixel_offset++;
            }
        } while (1);
    }
}
