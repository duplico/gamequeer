#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "HAL.h"
#include "gamequeer.h"
#include "gamequeer_bytecode.h"
#include "grlib.h"

gq_header game;

gq_anim_onscreen current_animations[MAX_CONCURRENT_ANIMATIONS];

gq_stage stage_current;

uint32_t curr_frame;
uint8_t *frame_data;
uint8_t gq_heap[GQ_HEAP_SIZE];

uint8_t gq_builtin_ints[GQI_COUNT * GQ_INT_SIZE] = {
    0,
};

uint8_t gq_builtin_strs[GQS_COUNT * GQ_STR_SIZE] = {
    0,
};

t_gq_int *game_id    = (t_gq_int *) &gq_builtin_ints[GQI_GAME_ID * GQ_INT_SIZE];
t_gq_int *game_color = (t_gq_int *) &gq_builtin_ints[GQI_GAME_COLOR * GQ_INT_SIZE];
t_gq_int *anim0_x    = (t_gq_int *) &gq_builtin_ints[GQI_BGANIM_X * GQ_INT_SIZE];
t_gq_int *anim0_y    = (t_gq_int *) &gq_builtin_ints[GQI_BGANIM_Y * GQ_INT_SIZE];
t_gq_int *anim1_x    = (t_gq_int *) &gq_builtin_ints[GQI_FGANIM1_X * GQ_INT_SIZE];
t_gq_int *anim1_y    = (t_gq_int *) &gq_builtin_ints[GQI_FGANIM1_Y * GQ_INT_SIZE];
t_gq_int *anim2_x    = (t_gq_int *) &gq_builtin_ints[GQI_FGANIM2_X * GQ_INT_SIZE];
t_gq_int *anim2_y    = (t_gq_int *) &gq_builtin_ints[GQI_FGANIM2_Y * GQ_INT_SIZE];

t_gq_int *label_x[4] = {
    (t_gq_int *) &gq_builtin_ints[GQI_LABEL1_X * GQ_INT_SIZE],
    (t_gq_int *) &gq_builtin_ints[GQI_LABEL2_X * GQ_INT_SIZE],
    (t_gq_int *) &gq_builtin_ints[GQI_LABEL3_X * GQ_INT_SIZE],
    (t_gq_int *) &gq_builtin_ints[GQI_LABEL4_X * GQ_INT_SIZE],
};

t_gq_int *label_y[4] = {
    (t_gq_int *) &gq_builtin_ints[GQI_LABEL1_Y * GQ_INT_SIZE],
    (t_gq_int *) &gq_builtin_ints[GQI_LABEL2_Y * GQ_INT_SIZE],
    (t_gq_int *) &gq_builtin_ints[GQI_LABEL3_Y * GQ_INT_SIZE],
    (t_gq_int *) &gq_builtin_ints[GQI_LABEL4_Y * GQ_INT_SIZE],
};

t_gq_int *label_flags = (t_gq_int *) &gq_builtin_ints[GQI_LABEL_FLAGS * GQ_INT_SIZE];

t_gq_int *player_id = (t_gq_int *) &gq_builtin_ints[GQI_PLAYER_ID * GQ_INT_SIZE];

char *game_title = (char *) &gq_builtin_strs[GQS_GAME_TITLE * GQ_STR_SIZE];

char *labels[4] = {
    (char *) &gq_builtin_strs[GQS_LABEL1 * GQ_STR_SIZE],
    (char *) &gq_builtin_strs[GQS_LABEL2 * GQ_STR_SIZE],
    (char *) &gq_builtin_strs[GQS_LABEL3 * GQ_STR_SIZE],
    (char *) &gq_builtin_strs[GQS_LABEL4 * GQ_STR_SIZE],
};

uint8_t timer_active = 0;
t_gq_int timer_interval;
t_gq_int timer_counter;

const uint32_t palette_bw[] = {0x000000, 0xffffff};
const uint32_t palette_wb[] = {0xffffff, 0x000000};

/**
 * @brief Loads a new stage.
 *
 * @param stage_ptr
 * @return uint8_t
 */
uint8_t load_stage(t_gq_pointer stage_ptr) {
    // Load the stage header
    if (!gq_memcpy_to_ram((uint8_t *) &stage_current, stage_ptr, sizeof(gq_stage))) {
        return 0;
    }

    // Stop all animations and reset their positions to (0, 0)
    for (uint8_t i = 0; i < MAX_CONCURRENT_ANIMATIONS; i++) {
        current_animations[i].in_use = 0;
    }

    *anim0_x = 0;
    *anim0_y = 0;
    *anim1_x = 0;
    *anim1_y = 0;
    *anim2_x = 0;
    *anim2_y = 0;

    if (stage_current.anim_bg_pointer) {
        // If this stage has an animation, load it.
        if (!load_animation(0, stage_current.anim_bg_pointer)) {
            return 0;
        }
    }

    if (stage_current.cue_bg_pointer) {
        // If this stage has a background cue, play it.
        led_play_cue(stage_current.cue_bg_pointer, 1);
    } else if (leds_animating) {
        // If we're currently playing a cue, stop it.
        led_stop();
    }

    // Clear all unhandled events
    for (uint16_t event_type = 0x0000; event_type < GQ_EVENT_COUNT; event_type++) {
        GQ_EVENT_CLR(event_type);
    }

    // Close any menu (text or choice)
    menu_close();

    // Clear the menu text (can be changed in the enter event)
    menu_text_result[0] = '\0';

    // Stage loading will happen at the end of GQ_EVENT_ENTER.

    // Clean up labels.
    for (uint8_t i = 0; i < 4; i++) {
        labels[i][0] = '\0';

        *label_x[i] = 0;
        *label_y[i] = 0;
    }
    *label_flags = 0;

    // If a timer is active, stop it.
    timer_active = 0;

    // Set stage entry event flag
    GQ_EVENT_SET(GQ_EVENT_ENTER);

    // Request a re-draw
    GQ_EVENT_SET(GQ_EVENT_REFRESH);

    return 1;
}

uint8_t load_game(uint8_t namespace) {
    // Load the game header
    if (!gq_memcpy_to_ram((uint8_t *) &game, GQ_PTR((uint32_t) namespace, 0), sizeof(gq_header))) {
        return 0;
    }

    *player_id = 0; // TODO: Move

    *game_id    = game.id;
    *game_color = game.color;
    memcpy(game_title, game.title, GQ_STR_SIZE);

    // Run the initialization commands
    run_code(game.startup_code);

    for (uint8_t i = 0; i < 5; i++) {
        gq_leds[i].r = 0x1000;
        gq_leds[i].g = 0x2000;
        gq_leds[i].b = 0x0000;
    }
    HAL_update_leds();

    if (!load_stage(game.starting_stage)) {
        return 0;
    }

    return 1;
}

uint8_t load_animation(uint8_t index, t_gq_pointer anim_ptr) {
    if (index >= MAX_CONCURRENT_ANIMATIONS) {
        return 0;
    }

    gq_anim_onscreen *anim = &current_animations[index];

    // Load the animation header
    if (!gq_memcpy_to_ram((uint8_t *) &anim->anim, anim_ptr, sizeof(gq_anim))) {
        anim->in_use = 0;
        return 0;
    }

    anim->in_use = 1;
    anim->frame  = 0;
    anim->ticks  = anim->anim.ticks_per_frame;
#ifdef GQ_MIN_FRAME_DURATION
    if (anim->ticks < GQ_MIN_FRAME_DURATION) {
        anim->ticks = GQ_MIN_FRAME_DURATION;
    }
#endif

    GQ_EVENT_SET(GQ_EVENT_REFRESH);

    return 1;
}

void draw_animation_stack() {
    gq_anim_frame frame_current;
    gq_anim_frame frame_current_mask;
    uint8_t anim_index = 0;
    do {
        if (current_animations[anim_index].in_use) {
            switch (anim_index) { // TODO: Handle masks
                case 0:
                    current_animations[anim_index].x = *anim0_x;
                    current_animations[anim_index].y = *anim0_y;
                    break;
                case 1:
                    current_animations[anim_index].x = *anim1_x;
                    current_animations[anim_index].y = *anim1_y;
                    break;
                case 3:
                    current_animations[anim_index].x = *anim2_x;
                    current_animations[anim_index].y = *anim2_y;
                    break;
            }

            // Load the current frame metadata
            if (!gq_memcpy_to_ram(
                    (uint8_t *) &frame_current,
                    current_animations[anim_index].anim.frame_pointer +
                        current_animations[anim_index].frame * sizeof(gq_anim_frame),
                    sizeof(gq_anim_frame))) {
                continue; // TODO: not this
            }

            // Check whether this animation has a mask
            if (anim_index != 0 && current_animations[anim_index + 1].in_use &&
                current_animations[anim_index + 1].anim.width == current_animations[anim_index].anim.width &&
                current_animations[anim_index + 1].anim.height == current_animations[anim_index].anim.height) {
                // The animation has a mask. Note that we enforce that the mask has the same dimensions as the frame.
                if (!gq_memcpy_to_ram(
                        (uint8_t *) &frame_current_mask,
                        current_animations[anim_index + 1].anim.frame_pointer +
                            current_animations[anim_index + 1].frame * sizeof(gq_anim_frame),
                        sizeof(gq_anim_frame))) {
                    continue; // TODO: not this
                }

                gq_draw_image_with_mask(
                    &g_sContext,
                    frame_current.data_pointer,
                    frame_current.bPP,
                    frame_current_mask.data_pointer,
                    frame_current_mask.bPP,
                    current_animations[anim_index].anim.width,
                    current_animations[anim_index].anim.height,
                    frame_current.data_size,
                    frame_current_mask.data_size,
                    current_animations[anim_index].x,
                    current_animations[anim_index].y);

            } else {
                // No mask.
                // Draw the frame on the screen
                gq_draw_image(
                    &g_sContext,
                    frame_current.data_pointer,
                    frame_current.bPP,
                    current_animations[anim_index].anim.width,
                    current_animations[anim_index].anim.height,
                    frame_current.data_size,
                    current_animations[anim_index].x,
                    current_animations[anim_index].y);
            }
        }
        // Go to the next index.
        if (anim_index == 0) {
            anim_index = 1;
        } else if (anim_index == 1) {
            anim_index = 3;
        } else {
            break;
        }
    } while (1);
}

void draw_label_stack() {
    for (uint8_t i = 0; i < 4; i++) {
        if (labels[i][0]) {
            // Check the color flag (least significant bit)
            if (*label_flags & 0b0001 << i * 8) {
                Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
                Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);
            } else {
                Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);
                Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
            }

            Graphics_drawString(
                &g_sContext, labels[i], -1, *label_x[i], *label_y[i], (*label_flags & (0b0010 << i * 8)) ? 1 : 0);
        }
    }
}

void draw_oled_stack() {
    // First, start with a blank slate.
    Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
    Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);
    Graphics_clearDisplay(&g_sContext);

    // Draw the animations
    draw_animation_stack();

    // Draw the labels
    draw_label_stack();

    // Then, draw the menu, if there is one.
    if (*menu_active == 1) {
        draw_menu_choice();
    } else if (*menu_active == GQ_MENU_FLAG_TEXT_ENTRY) {
        draw_menu_text();
    }

    Graphics_flushBuffer(&g_sContext);
}

void system_tick() {
    // Should be called by the 100 Hz system tick

    // Handle the LEDs
#ifndef GQ_SUPPRESS_LED_TICK
    led_tick();
#endif

    // Handle timers
    if (timer_active) {
        timer_counter++;
        if (timer_counter >= timer_interval) {
            timer_active = 0;
            GQ_EVENT_SET(GQ_EVENT_TIMER);
        }
    }

    // Tick any active animations
    for (uint8_t i = 0; i < MAX_CONCURRENT_ANIMATIONS; i++) {
        if (!current_animations[i].in_use) {
            continue;
        }

        if (current_animations[i].ticks > 0) {
            current_animations[i].ticks--;
            continue;
        }

        // If we're here, it's time for this animation to go to the next frame.
        current_animations[i].frame++;
        current_animations[i].ticks = current_animations[i].anim.ticks_per_frame;
        if (current_animations[i].frame >= current_animations[i].anim.frame_count) {
            // Animation is complete
            current_animations[i].in_use = 0;
            if (i == 0) {
                // Background animation done, fire event.
                GQ_EVENT_SET(GQ_EVENT_BGDONE);
            } else if (i == 1) {
                // Foreground animation 1 done, fire event.
                GQ_EVENT_SET(GQ_EVENT_FGDONE1);
            } else if (i == 3) {
                // Foreground animation 2 done, fire event.
                GQ_EVENT_SET(GQ_EVENT_FGDONE2);
            }
        }
        GQ_EVENT_SET(GQ_EVENT_REFRESH);
    }
}

t_gq_int get_badge_word(t_gq_int badge_id) {
    if (badge_id < 0 || badge_id >= BADGES_ALLOWED) {
        return 0;
        // TODO: Error flag?
    }

    t_gq_pointer badge_word_offset = badge_id / (GQ_INT_SIZE * 8);
    return gq_load_int(game.persistent_vars + GQP_OFFSET_BADGES + badge_word_offset);
}

void set_badge_bit(t_gq_int badge_id, t_gq_int value) {
    if (badge_id < 0 || badge_id >= BADGES_ALLOWED) {
        return;
    }

    t_gq_pointer badge_word_offset = badge_id / (GQ_INT_SIZE * 8);
    t_gq_pointer badge_word_ptr    = game.persistent_vars + GQP_OFFSET_BADGES + badge_word_offset;
    t_gq_int badge_word            = gq_load_int(badge_word_ptr);

    t_gq_int bit_offset = badge_id % (GQ_INT_SIZE * 8);
    t_gq_int bit_mask   = 1 << bit_offset;

    if (badge_word & bit_mask) {
        // Bit is already set
        if (value) {
            return;
        }
    } else {
        // Bit is already clear
        if (!value) {
            return;
        }
    }

    if (value) {
        badge_word |= bit_mask;
    } else {
        badge_word &= ~bit_mask;
    }

    gq_assign_int(badge_word_ptr, badge_word);
}

t_gq_int get_badge_bit(t_gq_int badge_id) {
    if (badge_id < 0 || badge_id >= BADGES_ALLOWED) {
        return 0;
    }

    t_gq_int badge_word = get_badge_word(badge_id);
    t_gq_int bit_offset = badge_id % (GQ_INT_SIZE * 8);
    t_gq_int bit_mask   = 1 << bit_offset;

    return (badge_word & bit_mask) != 0;
}

void handle_events() {
    for (uint16_t event_type = 0x0000; event_type < GQ_EVENT_COUNT; event_type++) {
        if (GQ_EVENT_GET(event_type)) {
            GQ_EVENT_CLR(event_type);
            // If we're in a menu, hijack button events to navigate the menu.
            if (*menu_active == GQ_MENU_FLAG_CHOICE) {
                if (!handle_event_menu_choice(event_type))
                    goto unblocked_events;
                continue;
            } else if (*menu_active == GQ_MENU_FLAG_TEXT_ENTRY) {
                if (!handle_event_menu_text(event_type))
                    goto unblocked_events;
                continue;
            }

            // Or else, if we're in a TEXT menu, do the same:

        unblocked_events:
            if (event_type == GQ_EVENT_REFRESH) {
                // Special event: refresh the OLED stack
                draw_oled_stack();
            } else if (!GQ_PTR_ISNULL(stage_current.event_commands[event_type])) {
                // Otherwise, look for an event command to run in the current stage.
                run_code(stage_current.event_commands[event_type]);
            }

            if (event_type == GQ_EVENT_ENTER) {
                if (GQ_PTR_NS(stage_current.menu_pointer) == GQ_PTR_BUILTIN_MENU_FLAGS) {
                    // This special pointer type is used to indicate the menu is for textentry.
                    menu_text_load(stage_current.prompt_pointer);
                } else if (stage_current.menu_pointer) {
                    // If this stage has a menu, load it.
                    menu_choice_load(stage_current.menu_pointer, stage_current.prompt_pointer);
                }
            }
        }
    }
}
