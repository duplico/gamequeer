#include <stdint.h>
#include <string.h>

#include "HAL.h"
#include "gamequeer.h"

rgbcolor16_t gq_leds[5] = {
    0,
};

#define LEDS_SUBTICKS 4

uint8_t leds_animating = 0;
gq_ledcue_frame_t leds_cue_frame_curr;
rgbcolor16_t leds_cue_color_curr[5];
rgbcolor16_t leds_cue_color_next[5];
gq_ledcue_t leds_cue;
uint16_t leds_cue_frame_index         = 0;
uint16_t leds_cue_frame_ticks_elapsed = 0;

gq_ledcue_t leds_cue_bg;
uint8_t leds_cue_bg_saved                = 0;
uint16_t leds_cue_bg_frame_index         = 0;
uint16_t leds_cue_bg_frame_ticks_elapsed = 0;

void led_setup_frame();

void led_stop() {
    // Stop the animation flag.
    leds_animating = 0;
    // Unsave any background cue.
    leds_cue_bg_saved = 1;

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

    // Load the current frame into leds_cue_frame_curr:
    gq_memcpy_ram(
        (uint8_t *) &leds_cue_frame_curr,
        leds_cue.frames + leds_cue_frame_index * sizeof(gq_ledcue_frame_t),
        sizeof(gq_ledcue_frame_t));

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
        gq_memcpy_ram(
            (uint8_t *) &leds_cue_frame_next,
            leds_cue.frames + ((leds_cue_frame_index + 1) % leds_cue.frame_count) * sizeof(gq_ledcue_frame_t),
            sizeof(gq_ledcue_frame_t));
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
    gq_memcpy_ram((uint8_t *) &leds_cue, cue_ptr, sizeof(gq_ledcue_t));
    leds_animating       = 1;
    leds_cue_frame_index = 0;

    // If this is a background cue, we set it to loop.
    if (background) {
        leds_cue.bgcue = 1;
        leds_cue.loop  = 1;
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

                // Either way, we need to display the destination color of the current transition.
                for (uint8_t i = 0; i < 5; i++) {
                    gq_leds[i] = leds_cue_color_next[i];
                }
                need_to_redraw = 1;
            }
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
                // If the frame is not done and is a smooth transition, interpolate the colors.
                for (uint8_t i = 0; i < 5; i++) {
                    // Interpolate the colors.
                    gq_leds[i].r = leds_cue_color_curr[i].r +
                        ((leds_cue_color_next[i].r - leds_cue_color_curr[i].r) * leds_cue_frame_ticks_elapsed /
                         leds_cue_frame_curr.duration);
                    gq_leds[i].g = leds_cue_color_curr[i].g +
                        ((leds_cue_color_next[i].g - leds_cue_color_curr[i].g) * leds_cue_frame_ticks_elapsed /
                         leds_cue_frame_curr.duration);
                    gq_leds[i].b = leds_cue_color_curr[i].b +
                        ((leds_cue_color_next[i].b - leds_cue_color_curr[i].b) * leds_cue_frame_ticks_elapsed /
                         leds_cue_frame_curr.duration);
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
