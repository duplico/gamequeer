#include <stdint.h>

#include "HAL.h"
#include "HAL_emulator.h"
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
    uint8_t pixel_repeat;             // How many repeats are left for the current pixel (used for RLE)
    uint8_t rle_type;                 // The type of RLE encoding used (4 or 7) or 0 for uncompressed
    uint8_t *image_buffer;            // The buffer to store the image or its intermediate bytes in
    uint16_t bytes_remaining_to_load; // The number of bytes remaining to load from flash to the buffer
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

    if (gq_game_unload_flag) {
        return;
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

/*
 * gq_image_peek_run() / gq_image_advance_run() -- run-aware decode (issue
 * #261), replacing the old one-pixel-at-a-time gq_image_get_pixel().
 *
 * These two are split (rather than one combined "get next N pixels" call)
 * so that gq_draw_image_with_mask() can peek both the image and mask
 * streams' available run lengths *before* deciding how far to advance
 * either one -- the image and mask are independently RLE-encoded, so their
 * run boundaries don't generally line up even though their dimensions
 * match. See gq_draw_image_with_mask() for that combine loop.
 *
 * gq_image_peek_run() does NOT mutate frame state (other than the implicit
 * read of the already-decoded frame->pixel_value / frame->pixel_repeat /
 * frame->render_byte -- it consumes nothing new from the image stream).
 * It reports the value of the pixel at the current position, and how many
 * consecutive pixels starting there (including the current one) are
 * guaranteed to share that value *and* stay within the current image row
 * (a run is never split across rows by this call -- gq_draw_image() and
 * gq_draw_image_with_mask() only ever need same-row spans, since a single
 * HAL_oled_fill_run() call only fills one display row).
 *
 * gq_image_advance_run() commits `count` pixels (1 <= count <=
 * the avail value returned by the immediately preceding
 * gq_image_peek_run() call on the same frame) and updates decode state
 * exactly as if gq_image_get_pixel() (the old per-pixel function) had been
 * called `count` times in a row -- byte/run-boundary prefetch and row-wrap
 * happen at the same point in the stream either way, so output is
 * pixel-identical to the old code for any valid `count`.
 */
uint8_t gq_image_peek_run(gq_image_frame_on_screen *frame, uint16_t *out_avail) {
    // NB: gate this function call on gq_image_done() to avoid undefined behavior.
    // Also, you need to bootstrap it by calling gq_image_load_byte() (done by
    // gq_load_image()).
    uint16_t row_remaining = (uint16_t) frame->width - frame->x_pixel_offset;

    if (frame->rle_type == 1) {
        // Uncompressed images carry no run-length information -- expose
        // one pixel at a time, same as the old per-pixel path.
        *out_avail = 1;
        return (frame->render_byte >> (7 - frame->x_bit_offset)) & 0x01;
    }

    uint16_t avail = frame->pixel_repeat;
    if (avail > row_remaining) {
        avail = row_remaining;
    }
    *out_avail = avail;
    return frame->pixel_value;
}

void gq_image_advance_run(gq_image_frame_on_screen *frame, uint16_t count) {
    uint8_t need_to_read_byte = 0;

    if (frame->rle_type == 1) {
        // count is always 1 here (see gq_image_peek_run() above).
        frame->x_bit_offset++;
        if (frame->x_bit_offset == 8) {
            frame->byte_index++;
            frame->x_bit_offset = 0;
            need_to_read_byte   = 1;
        }
    } else {
        frame->pixel_repeat -= count;
        if (frame->pixel_repeat == 0) {
            need_to_read_byte = 1;
            frame->byte_index++;
        }
    }

    // Advance to the pixel(s) after this run segment.
    frame->x_pixel_offset += count;

    // Check to see if we've reached the end of the row.
    if (frame->x_pixel_offset >= frame->width) {
        // We need to start a new row.
        frame->y_curr++;
        frame->x_pixel_offset = 0;
    }

    // If we need to read a new byte, do so.
    if (need_to_read_byte && !gq_image_done(frame)) {
        gq_image_load_byte(frame);
    }
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

    frame->bytes_remaining_to_load = frame_data_size;
    gq_image_load_byte(frame);
}

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
        // Decode the next run (same procedure regardless of clipping --
        // see gq_image_peek_run()'s doc comment: the RLE stream must be
        // walked in order, so a clipped row/column still costs a decode,
        // just not a framebuffer write).
        int16_t draw_x = x + frame.x_pixel_offset;
        int16_t draw_y = y + frame.y_curr;

        uint16_t run_avail;
        uint8_t draw_pixel = gq_image_peek_run(&frame, &run_avail);
        gq_image_advance_run(&frame, run_avail);

        // Vertical clip: matches the original per-pixel check, which only
        // ever tested draw_y >= yMin -- the upper bound is already enforced
        // structurally by frame.y_end (see gq_load_image()).
        if (draw_y < context->clipRegion.yMin) {
            continue;
        }

        // Horizontal clip: intersect the run [draw_x, draw_x + run_avail)
        // with [xMin, xMax]. Equivalent to clipping each pixel of the run
        // individually (the original behavior) because both the run and
        // the clip bound are contiguous intervals.
        int16_t seg_x0  = draw_x;
        int16_t seg_len = (int16_t) run_avail;
        if (seg_x0 < context->clipRegion.xMin) {
            int16_t trim = context->clipRegion.xMin - seg_x0;
            seg_x0 += trim;
            seg_len -= trim;
        }
        if (seg_x0 + seg_len - 1 > context->clipRegion.xMax) {
            seg_len = context->clipRegion.xMax - seg_x0 + 1;
        }
        if (seg_len > 0) {
            HAL_oled_fill_run(seg_x0, draw_y, (uint16_t) seg_len, (uint8_t) palette[draw_pixel]);
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
    // Structs for the image and mask.
    gq_image_frame_on_screen image_frame = {0};
    gq_image_frame_on_screen mask_frame  = {0};

    image_frame.image_buffer = image_buffer_main;
    mask_frame.image_buffer  = image_buffer_mask;

    // TODO: Add real palette support
    const uint32_t palette[2] = {0, 1};

    gq_load_image(image_bytes, image_bPP, width, height, img_frame_data_size, x, y, &image_frame);
    gq_load_image(mask_bytes, mask_bPP, width, height, mask_frame_data_size, x, y, &mask_frame);

    while (!gq_image_done(&image_frame) && !gq_image_done(&mask_frame)) {
        int16_t draw_x = x + image_frame.x_pixel_offset;
        int16_t draw_y = y + image_frame.y_curr;

        // Peek both streams' available run lengths at the current position
        // without committing either one -- the image and mask are
        // independently RLE-encoded, so one may offer a longer run than
        // the other even though both share the same width/height (enforced
        // by draw_animation_stack()'s caller-side dimension check). The
        // batch we can safely commit is bounded by whichever stream's run
        // (or row) ends first; within that shared run, both the image
        // value and the mask value are constant.
        uint16_t image_avail, mask_avail;
        uint8_t image_pixel = gq_image_peek_run(&image_frame, &image_avail);
        uint8_t mask_pixel  = gq_image_peek_run(&mask_frame, &mask_avail);
        uint16_t run_avail  = image_avail < mask_avail ? image_avail : mask_avail;

        gq_image_advance_run(&image_frame, run_avail);
        gq_image_advance_run(&mask_frame, run_avail);

        // Transparent (mask=0) run: nothing to draw, same as the original
        // per-pixel path which never called Graphics_drawPixelOnDisplay()
        // for mask_pixel == 0.
        if (!mask_pixel) {
            continue;
        }

        // Vertical clip -- see gq_draw_image()'s matching comment.
        if (draw_y < context->clipRegion.yMin) {
            continue;
        }

        // Horizontal clip -- see gq_draw_image()'s matching comment.
        int16_t seg_x0  = draw_x;
        int16_t seg_len = (int16_t) run_avail;
        if (seg_x0 < context->clipRegion.xMin) {
            int16_t trim = context->clipRegion.xMin - seg_x0;
            seg_x0 += trim;
            seg_len -= trim;
        }
        if (seg_x0 + seg_len - 1 > context->clipRegion.xMax) {
            seg_len = context->clipRegion.xMax - seg_x0 + 1;
        }
        if (seg_len > 0) {
            HAL_oled_fill_run(seg_x0, draw_y, (uint16_t) seg_len, (uint8_t) palette[image_pixel]);
        }
    }
}
