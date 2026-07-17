#include <stdint.h>

#include "HAL.h"
#include "HAL_emulator.h"
#include "gamequeer.h"
#include "gq_perf.h"
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
static uint8_t gq_image_peek_run(gq_image_frame_on_screen *frame, uint16_t *out_avail) {
    // NB: only call this function while !gq_image_done(frame) -- calling it
    // once the frame is done is undefined behavior (see the while
    // (!gq_image_done(...)) loops in gq_draw_image() and
    // gq_draw_image_with_mask() below). Also, you need to bootstrap it by
    // calling gq_image_load_byte() (done by gq_load_image()).
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

static void gq_image_advance_run(gq_image_frame_on_screen *frame, uint16_t count) {
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

/*
 * gq_image_advance_byte() -- fast-path advance for the byte-aligned
 * uncompressed fast paths in gq_draw_image() / gq_draw_image_with_mask()
 * below: consumes exactly 8 pixels (one full decoded source byte) in one
 * call, equivalent to calling gq_image_advance_run(frame, 1) eight times
 * in a row for an rle_type == 1 frame that starts byte-aligned
 * (frame->x_bit_offset == 0 on entry, which every caller's fast-path guard
 * already ensures). Skips the per-pixel x_bit_offset increment/compare
 * loop that eight individual gq_image_advance_run() calls would otherwise
 * pay, while updating decode state identically (byte/row-boundary
 * prefetch happens at the same point in the stream either way).
 */
static void gq_image_advance_byte(gq_image_frame_on_screen *frame) {
    frame->byte_index++;
    frame->x_pixel_offset = (uint16_t) (frame->x_pixel_offset + 8);

    if (frame->x_pixel_offset >= (uint16_t) frame->width) {
        frame->y_curr++;
        frame->x_pixel_offset = 0;
    }

    // A full source byte was just consumed -- always load the next one
    // (mirrors gq_image_advance_run()'s need_to_read_byte == 1 case for
    // rle_type == 1, which is unconditional there too).
    if (!gq_image_done(frame)) {
        gq_image_load_byte(frame);
    }
}

/*
 * gq_image_advance_row() -- row-level advance for the row-level
 * uncompressed fast paths in both gq_draw_image() (issue #308, finishing
 * what #303's row blit started) and gq_draw_image_with_mask() (issue #311,
 * applying the same pattern to each of the image/mask streams
 * independently): produces exactly the frame state that calling
 * gq_image_advance_byte() `nbytes` times in a row would produce, in one
 * bookkeeping update instead of a per-byte loop.
 *
 * Only valid under the same preconditions as the row fast path's own guard:
 * frame->x_bit_offset == 0 and frame->x_pixel_offset == 0 on entry,
 * frame->rle_type == 1, `nbytes` == frame->width / 8 (i.e. the call covers
 * one *entire* row), and the row's bytes don't straddle an image_buffer
 * reload boundary (frame->byte_index + nbytes <= IMAGE_BUFFER_SIZE, checked
 * by the caller). Given those, only the very LAST of the nbytes individual
 * gq_image_advance_byte() calls can ever (a) push x_pixel_offset to width
 * (every earlier call adds 8 short of that, since nbytes * 8 == width) or
 * (b) push byte_index to a multiple of IMAGE_BUFFER_SIZE and trigger
 * gq_image_load_buffer() (every earlier call's byte_index is strictly
 * between the row's starting byte_index and that boundary, per the
 * caller's guard) -- so row-end and any chunk reload happen at exactly the
 * same point in the stream as the per-byte loop, just computed directly
 * instead of discovered one byte at a time. The intermediate calls' only
 * other effect -- re-reading (and discarding) frame->render_byte from
 * image_buffer -- is unobservable here, since nothing reads render_byte
 * until the next decode step after this row finishes, so those calls are
 * skipped entirely.
 *
 * gq_draw_image_with_mask()'s image_frame and mask_frame each have their
 * own dedicated image_buffer (image_buffer_main / image_buffer_mask
 * respectively -- see their declarations below), so calling this once per
 * frame (image, then mask, or either order) is safe: a reload triggered
 * for one frame can never overwrite the other frame's buffer, only its
 * own. The only ordering rule that matters is the general one every row
 * fast path already follows -- read a frame's row bytes out of its buffer
 * before calling gq_image_advance_row() on THAT SAME frame, since that
 * call may reload that frame's buffer in place.
 */
static void gq_image_advance_row(gq_image_frame_on_screen *frame, uint16_t nbytes) {
    frame->byte_index     = (uint16_t) (frame->byte_index + nbytes);
    frame->x_pixel_offset = 0;
    frame->y_curr++;

    // Same as gq_image_advance_byte()'s final iteration: load the next
    // source byte (possibly triggering a chunk reload) unless the frame is
    // now fully drawn.
    if (!gq_image_done(frame)) {
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

    // Row-level uncompressed fast path (issue #303) invariant gate (issue
    // #312): rle_type, width, x, and context are all fixed for the whole
    // call (gq_load_image() sets frame.rle_type once and nothing below ever
    // changes it or frame.width; x/context are plain parameters), so every
    // term that doesn't depend on the current row is evaluated once here
    // instead of on every iteration of the loop below. The frame.width > 0
    // check matters even though gqc can't emit a zero-width image today:
    // without it, width == 0 satisfies width % 8 == 0 trivially and nbytes
    // would be 0 -- HAL_oled_blit_row() itself is documented to require
    // nbytes >= 1, and this is the only caller, so the guard belongs here.
    uint8_t row_fastpath_x_ok = frame.rle_type == 1 && frame.width > 0 && ((uint16_t) frame.width % 8) == 0 &&
        x >= context->clipRegion.xMin && (x + frame.width - 1) <= context->clipRegion.xMax;
    uint16_t row_fastpath_nbytes = (uint16_t) (frame.width / 8);

    while (!(gq_image_done(&frame))) {
        // Decode the next run (same procedure regardless of clipping --
        // see gq_image_peek_run()'s doc comment: the RLE stream must be
        // walked in order, so a clipped row/column still costs a decode,
        // just not a framebuffer write).
        int16_t draw_x = x + frame.x_pixel_offset;
        int16_t draw_y = y + frame.y_curr;

        // Row-level uncompressed fast path (issue #303): at the very start
        // of an uncompressed image row (x_bit_offset == 0, x_pixel_offset
        // == 0), if the invariant part above held and the row's y coordinate
        // lies within the clip region, forward the whole row in one
        // HAL_oled_blit_row() call instead of nbytes individual
        // HAL_oled_blit_byte() calls (the fast path just below this one),
        // and decode-advance the whole row in one gq_image_advance_row()
        // call (issue #308) instead of nbytes individual
        // gq_image_advance_byte() calls. Falls through to that byte-level
        // fast path (and ultimately the generic per-run path) for any row
        // that doesn't qualify -- narrower images, a row straddling the
        // clip region's left/right edge, or (defensively) a row whose bytes
        // straddle an image_buffer reload boundary. x_bit_offset/
        // x_pixel_offset are structurally always 0 here whenever this path
        // was also taken for the previous row (gq_image_advance_row() resets
        // x_pixel_offset and never touches x_bit_offset), but are still
        // checked explicitly rather than relied on, so the gate stays
        // self-contained if a future change to the fallback paths below ever
        // lets them drift.
        if (row_fastpath_x_ok && frame.x_bit_offset == 0 && frame.x_pixel_offset == 0 &&
            draw_y >= context->clipRegion.yMin && draw_y <= context->clipRegion.yMax) {
            uint16_t nbytes    = row_fastpath_nbytes;
            uint16_t row_index = frame.byte_index;

            // Buffer-straddle guard: HAL_oled_blit_row() needs the whole
            // row's source bytes to already be resident in image_buffer as
            // one contiguous span. IMAGE_BUFFER_SIZE is a multiple of every
            // row size the badge's cart images actually use (e.g. 1024 / 16
            // bytes for a full 128px row), so this should never trip in
            // practice -- checked rather than assumed, per this fast
            // path's guard comment above.
            if ((uint32_t) row_index + nbytes <= IMAGE_BUFFER_SIZE) {
                // Read the row's bytes out of image_buffer (via the HAL
                // call) BEFORE decode-advancing: gq_image_advance_row()
                // below may trigger gq_image_load_buffer(), which
                // overwrites image_buffer in place with the next cart
                // chunk -- so the source bytes must be consumed first.
                GQ_PERF_ENTER_RUNS(DRAW_WRITE);
                HAL_oled_blit_row(draw_x, draw_y, &frame.image_buffer[row_index], nbytes);
                GQ_PERF_EXIT_RUNS(DRAW_WRITE);

                GQ_PERF_ENTER_RUNS(DRAW_DECODE);
                gq_image_advance_row(&frame, nbytes);
                GQ_PERF_EXIT_RUNS(DRAW_DECODE);
                continue;
            }
        }

        // Byte-aligned uncompressed fast path (row-major framebuffer,
        // duplico/qc2024#45 Stage 1 / duplico/gamequeer#295): an
        // uncompressed source byte that is (a) currently byte-aligned in
        // the decode stream, (b) entirely within the current image row,
        // and (c) entirely within the clip region can be forwarded
        // straight from the decoded cart byte to the framebuffer in one
        // call, skipping the generic one-pixel-at-a-time peek/advance/
        // write path below entirely -- see HAL_oled_blit_byte()'s doc
        // comment (gamequeer.h) for why this is only a real win once the
        // destination framebuffer is row-major. Falls through to the
        // general per-run path for RLE content and any row/clip edge that
        // doesn't satisfy all three conditions.
        if (frame.rle_type == 1 && frame.x_bit_offset == 0 &&
            (uint16_t) (frame.x_pixel_offset + 8) <= (uint16_t) frame.width && draw_y >= context->clipRegion.yMin &&
            draw_y <= context->clipRegion.yMax && draw_x >= context->clipRegion.xMin &&
            (draw_x + 7) <= context->clipRegion.xMax) {
            GQ_PERF_ENTER_RUNS(DRAW_DECODE);
            uint8_t src_byte = frame.render_byte;
            gq_image_advance_byte(&frame);
            GQ_PERF_EXIT_RUNS(DRAW_DECODE);

            GQ_PERF_ENTER_RUNS(DRAW_WRITE);
            HAL_oled_blit_byte(draw_x, draw_y, src_byte, 8);
            GQ_PERF_EXIT_RUNS(DRAW_WRITE);
            continue;
        }

        uint16_t run_avail;
        GQ_PERF_ENTER_RUNS(DRAW_DECODE);
        uint8_t draw_pixel = gq_image_peek_run(&frame, &run_avail);
        gq_image_advance_run(&frame, run_avail);
        GQ_PERF_EXIT_RUNS(DRAW_DECODE);

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
            GQ_PERF_ENTER_RUNS(DRAW_WRITE);
            HAL_oled_fill_run(seg_x0, draw_y, (uint16_t) seg_len, (uint8_t) palette[draw_pixel]);
            GQ_PERF_EXIT_RUNS(DRAW_WRITE);
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

    // Row-level masked uncompressed fast path (issue #311) invariant gate
    // (issue #312, extending gq_draw_image()'s matching hoist to the masked
    // path): image_frame.rle_type/mask_frame.rle_type, width, x, and context
    // are all fixed for the whole call (gq_load_image() sets each frame's
    // rle_type once and nothing below ever changes it or width; x/context
    // are plain parameters), so every term that doesn't depend on the
    // current row is evaluated once here instead of on every iteration of
    // the loop below.
    uint8_t row_fastpath_x_ok = image_frame.rle_type == 1 && mask_frame.rle_type == 1 && width > 0 &&
        ((uint16_t) width % 8) == 0 && x >= context->clipRegion.xMin && (x + width - 1) <= context->clipRegion.xMax;
    uint16_t row_fastpath_nbytes = (uint16_t) (width / 8);

    while (!gq_image_done(&image_frame) && !gq_image_done(&mask_frame)) {
        int16_t draw_x = x + image_frame.x_pixel_offset;
        int16_t draw_y = y + image_frame.y_curr;

        // Row-level masked uncompressed fast path (issue #311, applying
        // gq_draw_image()'s row blit (#303) and row-level decode advance
        // (#308) to the masked path): at the very start of an image row
        // (x_pixel_offset == 0, checked independently per stream --
        // image_frame.x_pixel_offset == mask_frame.x_pixel_offset always
        // holds here in practice, same invariant the byte-aligned masked
        // fast path below relies on, but this gate checks both explicitly
        // rather than leaning on that invariant, so the precondition stays
        // self-contained even if a future change to either stream's
        // advance logic ever let them drift), if the invariant part above
        // held for both streams (x_bit_offset == 0, checked independently
        // per stream -- the image and mask are independently RLE/byte-
        // position-tracked even though they share width/height) and the
        // row's y coordinate lies within the clip region, forward the
        // whole row's image+mask bytes in one HAL_oled_blit_row_masked()
        // call instead of nbytes individual HAL_oled_blit_byte_masked()
        // calls, and decode-advance BOTH streams a whole row at a time via
        // gq_image_advance_row() (issue #308) instead of nbytes individual
        // gq_image_advance_byte() calls each. image_frame and mask_frame
        // each own a separate image_buffer (image_buffer_main /
        // image_buffer_mask), so a reload triggered by advancing one
        // stream can never clobber the other stream's buffer -- see
        // gq_image_advance_row()'s doc comment above. Both streams' row
        // bytes are read out of their buffers (via the HAL call) BEFORE
        // either gq_image_advance_row() call, since each frame's own
        // advance may reload that SAME frame's buffer in place. Falls
        // through to the byte-aligned fast path just below (and
        // ultimately the generic per-run merge loop) for any row that
        // doesn't qualify -- narrower images, RLE content on either
        // stream, a row straddling the clip region's edge, or
        // (defensively) either stream's row bytes straddling ITS OWN
        // image_buffer reload boundary.
        if (row_fastpath_x_ok && image_frame.x_bit_offset == 0 && mask_frame.x_bit_offset == 0 &&
            image_frame.x_pixel_offset == 0 && mask_frame.x_pixel_offset == 0 && draw_y >= context->clipRegion.yMin &&
            draw_y <= context->clipRegion.yMax) {
            uint16_t nbytes          = row_fastpath_nbytes;
            uint16_t image_row_index = image_frame.byte_index;
            uint16_t mask_row_index  = mask_frame.byte_index;

            // Buffer-straddle guard, checked independently per stream --
            // see gq_draw_image()'s matching comment. image_buffer_main
            // and image_buffer_mask are each IMAGE_BUFFER_SIZE bytes, but
            // the image and mask streams reload on independent schedules
            // (their own bytes_remaining_to_load / chunk cadence), so
            // either one -- not necessarily both -- could in principle be
            // mid-chunk at a row boundary.
            if ((uint32_t) image_row_index + nbytes <= IMAGE_BUFFER_SIZE &&
                (uint32_t) mask_row_index + nbytes <= IMAGE_BUFFER_SIZE) {
                GQ_PERF_ENTER_RUNS(DRAW_WRITE);
                HAL_oled_blit_row_masked(
                    draw_x,
                    draw_y,
                    &image_frame.image_buffer[image_row_index],
                    &mask_frame.image_buffer[mask_row_index],
                    nbytes);
                GQ_PERF_EXIT_RUNS(DRAW_WRITE);

                GQ_PERF_ENTER_RUNS(DRAW_DECODE);
                gq_image_advance_row(&image_frame, nbytes);
                gq_image_advance_row(&mask_frame, nbytes);
                GQ_PERF_EXIT_RUNS(DRAW_DECODE);
                continue;
            }
        }

        // Byte-aligned masked fast path (row-major framebuffer,
        // duplico/qc2024#45 Stage 1 / duplico/gamequeer#295): when BOTH
        // the image and mask streams are (a) uncompressed, (b) currently
        // byte-aligned in their own decode stream, and the shared position
        // is (c) entirely within the current image row and (d) entirely
        // within the clip region, one decoded image byte and one decoded
        // mask byte can be composited and written in a single byte-
        // parallel masked blit -- see HAL_oled_blit_byte_masked()'s doc
        // comment (gamequeer.h). image_frame.x_pixel_offset and
        // mask_frame.x_pixel_offset are always equal here (both frames
        // share `width` and are always advanced together, by run or by
        // byte, so they can only ever drift apart in x_bit_offset/rle
        // state, which this condition checks independently for each
        // stream). Falls through to the generic per-run merge loop below
        // for RLE content on either stream, any decode misalignment
        // between the two streams, or any row/clip edge that doesn't
        // satisfy all four conditions -- correctness for those cases is
        // unchanged (the merge loop below, using HAL_oled_fill_run(),
        // already gets whole-byte-fast RLE runs for free from that
        // primitive's own row-major implementation).
        if (image_frame.rle_type == 1 && mask_frame.rle_type == 1 && image_frame.x_bit_offset == 0 &&
            mask_frame.x_bit_offset == 0 && (uint16_t) (image_frame.x_pixel_offset + 8) <= (uint16_t) width &&
            draw_y >= context->clipRegion.yMin && draw_y <= context->clipRegion.yMax &&
            draw_x >= context->clipRegion.xMin && (draw_x + 7) <= context->clipRegion.xMax) {
            GQ_PERF_ENTER_RUNS(DRAW_DECODE);
            uint8_t src_byte  = image_frame.render_byte;
            uint8_t mask_byte = mask_frame.render_byte;
            gq_image_advance_byte(&image_frame);
            gq_image_advance_byte(&mask_frame);
            GQ_PERF_EXIT_RUNS(DRAW_DECODE);

            GQ_PERF_ENTER_RUNS(DRAW_WRITE);
            HAL_oled_blit_byte_masked(draw_x, draw_y, src_byte, mask_byte, 8);
            GQ_PERF_EXIT_RUNS(DRAW_WRITE);
            continue;
        }

        // Peek both streams' available run lengths at the current position
        // without committing either one -- the image and mask are
        // independently RLE-encoded, so one may offer a longer run than
        // the other even though both share the same width/height (enforced
        // by draw_animation_stack()'s caller-side dimension check). The
        // batch we can safely commit is bounded by whichever stream's run
        // (or row) ends first; within that shared run, both the image
        // value and the mask value are constant.
        uint16_t image_avail, mask_avail;
        GQ_PERF_ENTER_RUNS(DRAW_DECODE);
        uint8_t image_pixel = gq_image_peek_run(&image_frame, &image_avail);
        uint8_t mask_pixel  = gq_image_peek_run(&mask_frame, &mask_avail);
        uint16_t run_avail  = image_avail < mask_avail ? image_avail : mask_avail;

        gq_image_advance_run(&image_frame, run_avail);
        gq_image_advance_run(&mask_frame, run_avail);
        GQ_PERF_EXIT_RUNS(DRAW_DECODE);

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
            GQ_PERF_ENTER_RUNS(DRAW_WRITE);
            HAL_oled_fill_run(seg_x0, draw_y, (uint16_t) seg_len, (uint8_t) palette[image_pixel]);
            GQ_PERF_EXIT_RUNS(DRAW_WRITE);
        }
    }
}
