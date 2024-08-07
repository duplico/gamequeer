#include <stdint.h>

#include "HAL.h"
#include "HAL_emulator.h"
#include "gamequeer.h"
#include "grlib.h"

#include <gamequeer.h>

#include "sh1107.h"

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
    uint8_t pixel_repeat;             // How many repeats are left for the current pixel (used for RLE)
    uint8_t rle_type;                 // The type of RLE encoding used (4 or 7) or 0 for uncompressed
    uint8_t *image_buffer;            // The buffer to store the image or its intermediate bytes in
    uint16_t bytes_remaining_to_load; // The number of bytes remaining to load from flash to the buffer
    int16_t frame_buffer_index;
    int16_t frame_buffer_page_index;
    uint16_t frame_buffer_bit;
} gq_image_frame_on_screen;

uint8_t image_buffer_main[IMAGE_BUFFER_SIZE];
uint8_t image_buffer_mask[IMAGE_BUFFER_SIZE];

uint8_t gq_image_done(gq_image_frame_on_screen *frame) {
    return frame->y_curr >= frame->y_end;
}

void gq_image_load_buffer(gq_image_frame_on_screen *frame) {
    // Load the image buffer with the next chunk of image data.
    uint32_t bytes_to_load = frame->bytes_remaining_to_load;
    if (bytes_to_load > IMAGE_BUFFER_SIZE) {
        bytes_to_load = IMAGE_BUFFER_SIZE;
    }

    gq_memcpy_to_ram(frame->image_buffer, frame->image_bytes, bytes_to_load);
    frame->bytes_remaining_to_load -= bytes_to_load;
    frame->image_bytes += bytes_to_load;
}

void gq_image_load_byte(gq_image_frame_on_screen *frame) {
    // Load the next byte from the image buffer.
    //  If the buffer is empty, load the next chunk of image data.
    if (frame->byte_index % IMAGE_BUFFER_SIZE == 0) {
        gq_image_load_buffer(frame);
        frame->byte_index = 0;
    }

    frame->render_byte = frame->image_buffer[frame->byte_index];

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

    // This also moves us to the next column in our page, if the pixel would actually get drawn.
    if (frame->x_pixel_offset >= frame->x_start) {
        frame->frame_buffer_index++;
    }

    // Next pixel.
    frame->x_pixel_offset++;

    // Check to see if the next pixel sends us to the next row.
    if (frame->x_pixel_offset >= frame->width) {
        // We need to start a new row.
        frame->y_curr++;
        frame->x_pixel_offset = 0;

        if (frame->x_pixel_offset >= frame->x_start) {
            if (frame->frame_buffer_bit == 0x01) {
                // If we're on the last row of the current page,
                // Go to the top row of the next page
                frame->frame_buffer_bit = 0x80;
                frame->frame_buffer_page_index += 128;
            } else {
                frame->frame_buffer_bit >>= 1;
            }
            // Regardless, we go to the first column of our page.
            frame->frame_buffer_index = frame->frame_buffer_page_index;
        }

        // Wrap back to the initial page.
        frame->frame_buffer_index = frame->frame_buffer_page_index;
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
    uint32_t frame_data_size,
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

    // Set the starting page of the frame buffer
    frame->frame_buffer_page_index = (y/8) * 128;
    // TODO: needed?:
//    if (y <= 0) {
//        frame->frame_buffer_page_index = 0;
//    } else {
//        frame->frame_buffer_page_index = (y/8) * 128;
//    }

    // Set x_start
    if (x < g_sContext.clipRegion.xMin) {
        frame->x_start = g_sContext.clipRegion.xMin - x;
    } else {
        frame->x_start = 0;
        // And align it to the proper column for the x coordinate.
        frame->frame_buffer_page_index += x;
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

    // Set the current byte of the frame buffer to the first byte of the current page
    frame->frame_buffer_index = frame->frame_buffer_page_index;
    // Set the starting row of the frame buffer page
    frame->frame_buffer_bit = 0x80 >> (y % 8);

    frame->bytes_remaining_to_load = frame_data_size;
    gq_image_load_byte(frame);
}

#define GRAM_BUFFER(page, column) frame_buffer[(page * LCD_X_SIZE) + column]
void gq_draw_image(
    const Graphics_Context *context,
    t_gq_pointer image_bytes,
    int16_t bPP,
    int16_t width,
    int16_t height,
    uint32_t img_frame_data_size,
    t_gq_int x,
    t_gq_int y) {
    // TODO: Add palette support.

    gq_image_frame_on_screen frame = {
        0,
    };
    frame.image_buffer = image_buffer_main;

    const uint32_t palette[2] = {0, 1};

    gq_load_image(image_bytes, bPP, width, height, img_frame_data_size, x, y, &frame);

    while (!(gq_image_done(&frame))) {
        // Draw the pixel.
        int16_t draw_x     = x + frame.x_pixel_offset;
        int16_t draw_y     = y + frame.y_curr;
        uint8_t draw_pixel = gq_image_get_pixel(&frame);

        if (draw_x >= context->clipRegion.xMin && draw_x <= context->clipRegion.xMax &&
            draw_y >= context->clipRegion.yMin) {
            // write pixel
            if (draw_pixel) { // && !(GRAM_BUFFER(lY/8, lX) & val)) {
                frame_buffer[frame.frame_buffer_index]  |= frame.frame_buffer_bit;
            } else {
                frame_buffer[frame.frame_buffer_index] &= ~frame.frame_buffer_bit;
            }
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
    uint32_t img_frame_data_size,
    uint32_t mask_frame_data_size,
    t_gq_int x,
    t_gq_int y) {

    gq_draw_image(context, image_bytes, image_bPP, width, height, img_frame_data_size, x, y);
//    // Structs for the image and mask.
//    gq_image_frame_on_screen image_frame = {0};
//    gq_image_frame_on_screen mask_frame  = {0};
//
//    image_frame.image_buffer = image_buffer_main;
//    mask_frame.image_buffer  = image_buffer_mask;
//
//    // TODO: Add real palette support
//    const uint32_t palette[2] = {0, 1};
//
//    gq_load_image(image_bytes, image_bPP, width, height, img_frame_data_size, x, y, &image_frame);
//    gq_load_image(mask_bytes, mask_bPP, width, height, mask_frame_data_size, x, y, &mask_frame);
//
//    while (!gq_image_done(&image_frame) && !gq_image_done(&mask_frame)) {
//        // Draw the pixel.
//        int16_t draw_x = x + image_frame.x_pixel_offset;
//        int16_t draw_y = y + image_frame.y_curr;
//
//        uint8_t image_pixel = gq_image_get_pixel(&image_frame);
//        uint8_t mask_pixel  = gq_image_get_pixel(&mask_frame);
//
//        if (mask_pixel && draw_x >= context->clipRegion.xMin && draw_x <= context->clipRegion.xMax &&
//            draw_y >= context->clipRegion.yMin) {
//            Graphics_drawPixelOnDisplay(context->display, draw_x, draw_y, palette[image_pixel]);
//        }
//    }
}
