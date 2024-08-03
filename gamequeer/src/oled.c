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
    uint16_t byte_index;     // The byte index that the current pixel is in
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

void gq_image_load_byte(gq_image_frame_on_screen *frame) {
    frame->render_byte = read_byte(frame->image_bytes + frame->byte_index);

    if (frame->rle_type == 4) {
        // RLE 4 bit encoding
        frame->pixel_repeat = (frame->render_byte >> 4) + 1;
        frame->pixel_value  = frame->render_byte & 0x0F;
    } else if (frame->rle_type == 7) {
        // RLE 7 bit encoding
        frame->pixel_repeat = (frame->render_byte >> 1) + 1;
        frame->pixel_value  = frame->render_byte & 0x01;
    } // TODO: Otherwise is an error.
}

uint8_t gq_image_get_pixel(gq_image_frame_on_screen *frame) {
    // NB: gate this function call on gq_image_done() to avoid undefined behavior
    // Also, you need to bootstrap it by calling a read_byte
    uint8_t need_to_read_byte = 0;

    // Get the current pixel.
    if (frame->rle_type == 1) {
        frame->pixel_value = (frame->render_byte >> (7 - frame->x_bit_offset)) & 0x01;
        frame->x_bit_offset++;
        if (frame->x_bit_offset == 8) {
            frame->byte_index++;
            frame->x_bit_offset = 0;
            need_to_read_byte   = 1;
        }
    } else {
        frame->pixel_repeat--;
        if (frame->pixel_repeat == 0) {
            need_to_read_byte = 1;
            frame->byte_index++;
        }
    }

    // Next pixel.
    frame->x_pixel_offset++;

    // Check to see if the next pixel sends us to the next row.
    if (frame->x_pixel_offset >= frame->width) {
        // We need to start a new row.
        frame->y_curr++;
        frame->x_pixel_offset = 0;
    }

    // If we need to read a new byte, do so.
    if (need_to_read_byte && !gq_image_done(frame)) {
        gq_image_load_byte(frame);
    }

    // Return the current pixel value.
    return frame->pixel_value;
}

void gq_load_image(
    t_gq_pointer image_bytes,
    int16_t bPP,
    int16_t width,
    int16_t height,
    t_gq_int x,
    t_gq_int y,
    gq_image_frame_on_screen *frame) {
    frame->height      = height;
    frame->width       = width;
    frame->image_bytes = image_bytes;
    frame->rle_type    = bPP;

    if (frame->rle_type != 1) {
        frame->rle_type = (frame->rle_type >> 4) & 0x0F;
    }

    // Set x_start
    if (x < g_sContext.clipRegion.xMin) {
        frame->x_start = g_sContext.clipRegion.xMin - x;
    } else {
        frame->x_start = 0;
    }

    // Set x_end
    if ((x + width - 1) > g_sContext.clipRegion.xMax) {
        frame->x_end = g_sContext.clipRegion.xMax - x;
    } else {
        frame->x_end = width - 1;
    }

    // Set y_end
    if ((y + height - 1) > g_sContext.clipRegion.yMax) {
        frame->y_end = g_sContext.clipRegion.yMax - y + 1;
    } else {
        frame->y_end = height;
    }

    gq_image_load_byte(frame);
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

    gq_load_image(image_bytes, bPP, width, height, x, y, &frame);

    while (!(gq_image_done(&frame))) {
        // Draw the pixel.
        int16_t draw_x     = x + frame.x_pixel_offset;
        int16_t draw_y     = y + frame.y_curr;
        uint8_t draw_pixel = gq_image_get_pixel(&frame);
        if (draw_x >= context->clipRegion.xMin && draw_x <= context->clipRegion.xMax &&
            draw_y >= context->clipRegion.yMin) {
            Graphics_drawPixelOnDisplay(context->display, draw_x, draw_y, palette[draw_pixel]);
        }
    }
}

void gq_draw_image_with_mask(
    const Graphics_Context *context,
    t_gq_pointer image_bytes,
    uint16_t image_bPP,
    t_gq_pointer mask_bytes,
    uint16_t mask_bPP,
    int16_t width,
    int16_t height,
    t_gq_int x,
    t_gq_int y) {
    // Structs for the image and mask.
    gq_image_frame_on_screen image_frame = {0};
    gq_image_frame_on_screen mask_frame  = {0};

    // TODO: Add real palette support
    const uint32_t palette[2] = {0, 1};

    gq_load_image(image_bytes, image_bPP, width, height, x, y, &image_frame);
    gq_load_image(mask_bytes, mask_bPP, width, height, x, y, &mask_frame);

    while (!gq_image_done(&image_frame) && !gq_image_done(&mask_frame)) {
        // Draw the pixel.
        int16_t draw_x = x + image_frame.x_pixel_offset;
        int16_t draw_y = y + image_frame.y_curr;

        uint8_t image_pixel = gq_image_get_pixel(&image_frame);
        uint8_t mask_pixel  = gq_image_get_pixel(&mask_frame);

        if (mask_pixel && draw_x >= context->clipRegion.xMin && draw_x <= context->clipRegion.xMax &&
            draw_y >= context->clipRegion.yMin) {
            Graphics_drawPixelOnDisplay(context->display, draw_x, draw_y, palette[image_pixel]);
        }
    }
}
