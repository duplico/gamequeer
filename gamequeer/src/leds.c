#include <stdint.h>
#include <string.h>

#include "HAL.h"
#include "gamequeer.h"

rgbcolor16_t gq_leds[5] = {
    0,
};

#define LEDS_SUBTICKS 4

// Number of fractional bits used to represent the per-tick interpolation
// deltas computed in led_setup_frame() and consumed in led_tick(). This
// lets led_tick() replace a 32-bit divide (done every smooth-cue subtick,
// in RTC ISR context) with a precomputed reciprocal and a multiply+shift.
//
// 17 bits of fraction keeps the worst-case accumulated rounding error
// below 1 LSB of the 16-bit LED output even at the maximum possible
// gq_ledcue_frame_t.duration (0xFFFF ticks, i.e. up to 65534 smooth-cue
// evaluations of a single frame): error <= duration / 2^LED_DELTA_FRAC_BITS
// < 1. See leds.c unit-test sweep for empirical validation.
#define LED_DELTA_FRAC_BITS 17

uint8_t leds_animating = 0;
gq_ledcue_frame_t leds_cue_fg_frames[GQ_CUE_MAX_FRAMES];
gq_ledcue_frame_t leds_cue_bg_frames[GQ_CUE_MAX_FRAMES];
gq_ledcue_frame_t leds_cue_frame_curr;
rgbcolor16_t leds_cue_color_curr[5];
rgbcolor16_t leds_cue_color_next[5];
// Precomputed per-tick interpolation deltas for the current frame's smooth
// transition, in LED_DELTA_FRAC_BITS fixed point. Computed once per frame in
// led_setup_frame(); consumed (add-and-shift only, no divide) every smooth-cue
// subtick in led_tick(). rgbdelta_t is deliberately not persisted anywhere
// (not part of the on-cart cue format), so it costs RAM only, not FRAM/flash.
rgbdelta_t leds_cue_color_delta[5];
gq_ledcue_t leds_cue;
uint16_t leds_cue_frame_index         = 0;
uint16_t leds_cue_frame_ticks_elapsed = 0;

gq_ledcue_t leds_cue_bg;
uint8_t leds_cue_bg_saved                = 0;
uint16_t leds_cue_bg_frame_index         = 0;
uint16_t leds_cue_bg_frame_ticks_elapsed = 0;

void led_setup_frame();

// Precompute the fixed-point per-tick interpolation delta for one channel of
// one LED, given the signed distance to travel (diff = next - curr) and the
// frame duration (in ticks) over which to travel it.
//
// This is the one 32-bit divide per channel that used to happen every smooth
// subtick in led_tick() (in RTC ISR context); it now happens once per frame,
// in led_setup_frame(), instead.
//
// duration == 0 is guarded against (returns 0): the cooker always emits
// durations that are multiples of LEDS_SUBTICKS (see gqc's cues.py), so a
// legitimately-compiled cart never produces duration == 0 for a frame with a
// following frame, but nothing on this side of the cart format enforces that,
// so we guard here rather than trust it.
//
// The intermediate product is computed in 64-bit arithmetic (diff and
// duration are both well within 32 bits, but diff << LED_DELTA_FRAC_BITS is
// not) and the final fixed-point delta is saturated to fit in the 32-bit
// rgbdelta_t field. Saturation only matters for pathologically small
// durations (< ~5 ticks), which led_tick() never actually walks (the "frame
// done" transition fires before any interpolation step is taken for such
// short frames), so it exists purely to keep this function free of signed
// overflow (UB) rather than to affect anything visible.
static int32_t led_calc_delta(int32_t diff, uint16_t duration) {
    if (duration == 0) {
        return 0;
    }

    int64_t scaled = (int64_t) diff << LED_DELTA_FRAC_BITS;
    int64_t delta  = scaled / (int32_t) duration;

    if (delta > INT32_MAX) {
        delta = INT32_MAX;
    } else if (delta < INT32_MIN) {
        delta = INT32_MIN;
    }

    return (int32_t) delta;
}

void led_stop() {
    // Stop the animation flag.
    leds_animating = 0;
    // Unsave any background cue.
    leds_cue_bg_saved = 0;

    // Clear the current LED colors.
    for (uint8_t i = 0; i < 5; i++) {
        gq_leds[i] = (rgbcolor16_t) {.r = 0, .g = 0, .b = 0};
    }

    // Flush the LEDs.
    HAL_update_leds();
}

void led_anim_done() {
    // If we just completed a non-background cue, and we have a background cue saved, restore it.
    if (leds_cue_bg_saved && !leds_cue.bgcue) {
        leds_cue                     = leds_cue_bg;
        leds_cue_frame_index         = leds_cue_bg_frame_index;
        leds_cue_frame_ticks_elapsed = leds_cue_bg_frame_ticks_elapsed;
        leds_cue_bg_saved            = 0;
        led_setup_frame();
    } else {
        // Otherwise, just stop the animation.
        led_stop();
    }
}

void led_setup_frame() {
    // If we're not currently animating, there's nothing to do.
    if (!leds_animating) {
        return;
    }

    if (leds_cue.bgcue) {
        // If this is a background cue, load the frame from the bgcue buffer.
        leds_cue_frame_curr = leds_cue_bg_frames[leds_cue_frame_index];
    } else {
        // If this is a foreground cue, load the frame from the fgcue buffer.
        leds_cue_frame_curr = leds_cue_fg_frames[leds_cue_frame_index];
    }

    // And then add it to the left-shifted 16-bit version:
    for (uint8_t i = 0; i < 5; i++) {
        leds_cue_color_curr[i].r = leds_cue_frame_curr.leds[i].r << 8;
        leds_cue_color_curr[i].g = leds_cue_frame_curr.leds[i].g << 8;
        leds_cue_color_curr[i].b = leds_cue_frame_curr.leds[i].b << 8;
    }

    // Load the next frame, if there is one, and put its colors into leds_cue_color_next.
    // Note that we don't store the entire frame, just the colors. We don't need the metadata.
    if (leds_cue_frame_index + 1 < leds_cue.frame_count || leds_cue.loop) {
        // We can load the next frame sequentially if the current frame isn't the last frame;
        // otherwise, we need to go back to the start if we're looping.
        gq_ledcue_frame_t leds_cue_frame_next;
        if (leds_cue.bgcue) {
            leds_cue_frame_next = leds_cue_bg_frames[(leds_cue_frame_index + 1) % leds_cue.frame_count];
        } else {
            leds_cue_frame_next = leds_cue_fg_frames[(leds_cue_frame_index + 1) % leds_cue.frame_count];
        }
        for (uint8_t i = 0; i < 5; i++) {
            leds_cue_color_next[i].r = leds_cue_frame_next.leds[i].r << 8;
            leds_cue_color_next[i].g = leds_cue_frame_next.leds[i].g << 8;
            leds_cue_color_next[i].b = leds_cue_frame_next.leds[i].b << 8;
        }
    } else {
        // If there is no next frame, then load a dummy all-black frame.
        for (uint8_t i = 0; i < 5; i++) {
            leds_cue_color_next[i] = (rgbcolor16_t) {.r = 0, .g = 0, .b = 0};
        }
    }

    // Set up the frame transition deltas: one 32-bit divide per channel here,
    // instead of one per channel on every smooth-cue subtick in led_tick().
    for (uint8_t i = 0; i < 5; i++) {
        leds_cue_color_delta[i].r = led_calc_delta(
            (int32_t) leds_cue_color_next[i].r - leds_cue_color_curr[i].r, leds_cue_frame_curr.duration);
        leds_cue_color_delta[i].g = led_calc_delta(
            (int32_t) leds_cue_color_next[i].g - leds_cue_color_curr[i].g, leds_cue_frame_curr.duration);
        leds_cue_color_delta[i].b = led_calc_delta(
            (int32_t) leds_cue_color_next[i].b - leds_cue_color_curr[i].b, leds_cue_frame_curr.duration);
    }

    leds_cue_frame_ticks_elapsed = 0;
}

void led_play_cue(t_gq_pointer cue_ptr, uint8_t background) {
    if (leds_animating && !background && leds_cue.bgcue) {
        // If we're currently playing a background cue, save it for later before interrupting it.
        leds_cue_bg                     = leds_cue;
        leds_cue_bg_saved               = 1;
        leds_cue_bg_frame_index         = leds_cue_frame_index;
        leds_cue_bg_frame_ticks_elapsed = leds_cue_frame_ticks_elapsed;
    }

    // Load the new cue into RAM.
    gq_memcpy_to_ram((uint8_t *) &leds_cue, cue_ptr, sizeof(gq_ledcue_t));
    leds_animating       = 1;
    leds_cue_frame_index = 0;

    if (leds_cue.frame_count > GQ_CUE_MAX_FRAMES) {
        // If the cue has too many frames, truncate it.
        leds_cue.frame_count = GQ_CUE_MAX_FRAMES;
    }

    // If this is a background cue, we set it to loop.
    if (background) {
        leds_cue.bgcue = 1;
        leds_cue.loop  = 1;

        // Load the frames into RAM.
        gq_memcpy_to_ram(
            (uint8_t *) leds_cue_bg_frames, leds_cue.frames, leds_cue.frame_count * sizeof(gq_ledcue_frame_t));
    } else {
        // Load the frames into RAM.
        gq_memcpy_to_ram(
            (uint8_t *) leds_cue_fg_frames, leds_cue.frames, leds_cue.frame_count * sizeof(gq_ledcue_frame_t));
    }
    led_setup_frame();
}

void led_tick() {
    uint8_t need_to_redraw = 0;
    static uint8_t subtick = LEDS_SUBTICKS - 1;

    // We'll run our LED animations at 25 Hz instead of the full system tick rate of 100 Hz.
    if (subtick) {
        subtick--;
        return;
    }
    subtick = LEDS_SUBTICKS - 1;

    if (leds_animating) {
        // If the current frame is done, move to the next frame.
        if (leds_cue_frame_ticks_elapsed >= leds_cue_frame_curr.duration) {
            // Current frame is done. Next frame!
            leds_cue_frame_index++;
            if (leds_cue_frame_index >= leds_cue.frame_count) {
                // If we're at the end of the cue, loop back to the start or stop.
                if (leds_cue.loop) {
                    leds_cue_frame_index = 0;
                } else {
                    led_anim_done();
                }
            }

            // Either way, we need to display the destination color of the current transition.
            for (uint8_t i = 0; i < 5; i++) {
                gq_leds[i] = leds_cue_color_next[i];
            }
            need_to_redraw = 1;
            led_setup_frame(); // leds_cue_frame_ticks_elapsed is reset inside the function.
        } else {
            // The current frame is _not_ done, so we need to display the current colors.
            if (leds_cue_frame_ticks_elapsed == 0) {
                // If this is the first tick of the frame, set the colors to the current frame's colors.
                for (uint8_t i = 0; i < 5; i++) {
                    gq_leds[i].r = leds_cue_color_curr[i].r;
                    gq_leds[i].g = leds_cue_color_curr[i].g;
                    gq_leds[i].b = leds_cue_color_curr[i].b;
                }
                need_to_redraw = 1;
            } else if (leds_cue_frame_curr.transition_smooth) {
                // If the frame is not done and is a smooth transition, interpolate the colors
                // using the per-tick deltas precomputed in led_setup_frame(). No divide here:
                // just a 64-bit intermediate multiply (hardware-assisted via MPY32) and a
                // constant shift, instead of a 32-bit software divide per channel per subtick.
                for (uint8_t i = 0; i < 5; i++) {
                    gq_leds[i].r = leds_cue_color_curr[i].r +
                        (int32_t) (((int64_t) leds_cue_color_delta[i].r * leds_cue_frame_ticks_elapsed) >>
                                   LED_DELTA_FRAC_BITS);
                    gq_leds[i].g = leds_cue_color_curr[i].g +
                        (int32_t) (((int64_t) leds_cue_color_delta[i].g * leds_cue_frame_ticks_elapsed) >>
                                   LED_DELTA_FRAC_BITS);
                    gq_leds[i].b = leds_cue_color_curr[i].b +
                        (int32_t) (((int64_t) leds_cue_color_delta[i].b * leds_cue_frame_ticks_elapsed) >>
                                   LED_DELTA_FRAC_BITS);
                }

                need_to_redraw = 1;
            } else {
                // If the frame is not done and is not a smooth transition, do nothing, as we're
                // already displaying the current frame's colors.

                // No need to redraw.
            }
            leds_cue_frame_ticks_elapsed += 4;
        }
    }

    if (need_to_redraw) {
        HAL_update_leds();
    }
}
