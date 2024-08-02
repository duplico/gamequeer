#include <stdint.h>

#include "HAL.h"
#include "gamequeer.h"
#include "grlib.h"

#include <gamequeer.h>

typedef struct gq_image_frame_on_screen {
    t_gq_pointer image_bytes;
    int16_t width;   // The width of the image
    int16_t height;  // The height of the image
    uint8_t x_start; // The x coordinate (within the image) of the first pixel to be drawn (0 unless clipping)
    uint8_t x_end;   // The x coordinate (within the image) of the last pixel to be drawn (width - 1 unless clipping)
    uint16_t x_bit_offset;   // The bit index (within its byte) that the current pixel is in
    uint16_t x_byte_offset;  // The byte index that the current pixel is in
    uint16_t x_pixel_offset; // x coordinate (within the image) of the current pixel
    uint8_t y_curr;          // The y coordinate (within the image) of the current row
    uint8_t y_end;       // The y coordinate (within the image) of the last row to be drawn (height - 1 unless clipping)
    uint8_t render_byte; // The raw image byte currently being read
    uint8_t pixel_value; // The value of the current pixel (used for RLE)
    uint8_t pixel_repeat; // How many repeats are left for the current pixel (used for RLE)
    uint8_t rle_type;     // The type of RLE encoding used (4 or 7) or 0 for uncompressed
} gq_image_frame_on_screen;

uint8_t gq_image_done(gq_image_frame_on_screen *frame) {
    return frame->y_curr >= frame->y_end;
}

uint8_t gq_image_get_pixel(gq_image_frame_on_screen *frame) {
    // NB: gate this function call on gq_image_done() to avoid undefined behavior
    // Also, you need to bootstrap it by calling a read_byte
    uint8_t need_to_read_byte = 0;

    // Get the current pixel.
    frame->pixel_value = (frame->render_byte >> (7 - frame->x_bit_offset)) & 0x01;

    // Next pixel.
    frame->x_pixel_offset++;
    frame->x_bit_offset++;

    // Check to see if we need to go to the next byte.
    if (frame->x_bit_offset == 8) {
        frame->x_byte_offset++;
        frame->x_bit_offset = 0;
        need_to_read_byte   = 1;
    }

    // Check to see if the next byte sends us to the next row.
    if (frame->x_pixel_offset > frame->x_end) {
        // We need to start a new row.
        frame->y_curr++;
        frame->x_pixel_offset = 0;
    }

    // If we need to read a new byte, do so.
    if (need_to_read_byte && !gq_image_done(frame)) {
        frame->render_byte = read_byte(frame->image_bytes + frame->x_byte_offset);
    }

    // Return the current pixel value.
    return frame->pixel_value;
}

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
    frame.rle_type            = bPP;
    frame.height              = height;
    frame.width               = width;
    frame.image_bytes         = image_bytes;

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
        frame.y_end = context->clipRegion.yMax - y + 1;
    } else {
        frame.y_end = height;
    }

    if (frame.rle_type == 1) {
        // Image is uncompressed; 1 bit per pixel.

        // First, check to see if the top of the image needs to be cut off (and we need to skip ahead)
        if (y < context->clipRegion.yMin) {
            // Determine the number of rows that lie above the clipping region.
            frame.y_curr = context->clipRegion.yMin - y;
        }

        // Draw this row of image pixels, starting at x_start and ending at x_end.
        // Draw the pixels.
        frame.x_pixel_offset = 0;
        frame.x_bit_offset   = 0;
        frame.x_byte_offset  = 0;
        frame.render_byte    = read_byte(frame.image_bytes + frame.x_byte_offset);

        while (!(gq_image_done(&frame))) {
            // Draw the pixel.
            int16_t draw_x     = x + frame.x_pixel_offset;
            int16_t draw_y     = y + frame.y_curr;
            uint8_t draw_pixel = gq_image_get_pixel(&frame);
            if (draw_x >= context->clipRegion.xMin && draw_x <= context->clipRegion.xMax &&
                draw_y >= context->clipRegion.yMin) {
                Graphics_drawPixelOnDisplay(context->display, draw_x, draw_y, palette[draw_pixel]);
            } else if (draw_x > context->clipRegion.yMax) {
                // We're done here.
                return;
            }
        }
    } else {
        // Image is compressed; RLE4 or RLE7
        frame.rle_type       = (frame.rle_type >> 4) & 0x0F;
        frame.x_pixel_offset = 0;
        frame.y_curr         = 0;

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
                    frame.y_curr++;

                    if (y + frame.y_curr > context->clipRegion.yMax) {
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

                if (y + frame.y_curr < context->clipRegion.yMin) {
                    frame.x_pixel_offset++;
                    continue;
                }

                if (y + frame.y_curr > context->clipRegion.yMax || frame.y_curr >= frame.y_end) {
                    // We're done here.
                    return;
                }

                // If we're here, then (x,y) is inside the clipping region.
                Graphics_drawPixelOnDisplay(
                    context->display, x + frame.x_pixel_offset, y + frame.y_curr, palette[frame.pixel_value]);
                frame.x_pixel_offset++;
            }
        } while (1);
    }
}
