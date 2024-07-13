#include <stdint.h>

#include "HAL.h"
#include "gamequeer.h"
#include "gamequeer_bytecode.h"
#include "grlib.h"
#include "stdlib.h"

gq_header game;
uint8_t bg_animating = 0;

gq_anim_onscreen current_animations[MAX_CONCURRENT_ANIMATIONS];

gq_stage stage_current;

uint32_t curr_frame;
uint8_t *frame_data;
uint8_t gq_heap[GQ_HEAP_SIZE]; // TODO: Consider dynamically allocating?

uint8_t menu_active            = 0;
uint8_t menu_option_selected   = 0;
t_gq_int GQ_BUILTIN_menu_value = 0;
// TODO: Add all the other built-ins

gq_menu *menu_current; // TODO: we need a cap on menu sizes.

// TODO: Move
const uint32_t palette_bw[] = {0x000000, 0xffffff};
const uint32_t palette_wb[] = {0xffffff, 0x000000};

// TODO: Move
void run_code(t_gq_pointer code_ptr);

void menu_load(t_gq_pointer menu_ptr, t_gq_pointer menu_prompt) {
    // TODO: assert !menu_active
    t_gq_int menu_option_count;
    t_gq_pointer menu_size;

    // Determine the size of the current menu based on its option count.
    gq_memcpy_ram((uint8_t *) &menu_option_count, menu_ptr, GQ_INT_SIZE);
    menu_size = GQ_INT_SIZE + menu_option_count * sizeof(gq_menu_option);

    // Load the menu into RAM.
    menu_current = (gq_menu *) malloc(menu_size);
    gq_memcpy_ram((uint8_t *) menu_current, menu_ptr, menu_size);

    // Initialize the menu options and activate it.
    menu_option_selected = 0;
    menu_active          = 1;

    // TODO: flag to the main loop indicating we need to redraw.
}

void menu_close() {
    // TODO: make sure we prevent stage changes while a menu is open,
    //       OR we close the menu on a stage change. Maybe both.

    if (!menu_active) {
        return;
    }

    menu_active = 0;
    free(menu_current);

    // TODO: flag to the main loop indicating we need to redraw.
}

/**
 * @brief Loads a new stage.
 *
 * @param stage_ptr
 * @return uint8_t
 */
uint8_t load_stage(t_gq_pointer stage_ptr) {
    // Load the stage header
    if (!gq_memcpy_ram((uint8_t *) &stage_current, stage_ptr, sizeof(gq_stage))) {
        return 0;
    }

    if (stage_current.anim_bg_pointer) {
        // If this stage has an animation, load it.
        if (!load_animation(0, stage_current.anim_bg_pointer)) {
            return 0;
        }
    } else {
        // TODO: Otherwise, clear the current animation
    }

    if (stage_current.cue_bg_pointer) {
        // If this stage has a background cue, play it.
        led_play_cue(stage_current.cue_bg_pointer, 1);
    } else if (leds_animating && leds_cue.bgcue) {
        // If we're currently playing a background cue, stop it.
        led_stop();
    }

    if (stage_current.menu_pointer) {
        // If this stage has a menu, load it.
        menu_load(stage_current.menu_pointer, 0);
    }

    // Set stage entry event flag
    GQ_EVENT_SET(GQ_EVENT_ENTER);

    return 1;
}

uint8_t load_game() {
    // Load the game header
    if (!gq_memcpy_ram((uint8_t *) &game, GQ_PTR(GQ_PTR_NS_CART, 0), sizeof(gq_header))) {
        return 0;
    }

    if (!load_stage(game.starting_stage)) {
        return 0;
    }

    // Run the initialization commands
    run_code(game.startup_code);

    for (uint8_t i = 0; i < 5; i++) {
        gq_leds[i].r = 0x1000;
        gq_leds[i].g = 0x2000;
        gq_leds[i].b = 0x0000;
    }
    HAL_update_leds();

    return 1;
}

uint8_t load_animation(uint8_t index, t_gq_pointer anim_ptr) {
    // TODO: Assert index < MAX_CONCURRENT_ANIMATIONS
    gq_anim_onscreen *anim = &current_animations[index];

    // Load the animation header
    if (!gq_memcpy_ram((uint8_t *) &anim->anim, anim_ptr, sizeof(gq_anim))) {
        anim->in_use = 0;
        return 0;
    }

    // Set up the parameters of the animation
    anim->x      = 0; // TODO: Set
    anim->y      = 0; // TODO: Set
    anim->in_use = 1;
    anim->frame  = 0;
    anim->ticks  = 0; // Set to 0 to draw the first frame immediately.

    return 1;
}

// TODO: rename this function because it draws the entire screen stack, not just the animations.
void draw_animations() {
    gq_anim_frame frame_current;

    // First, draw the animation stack
    for (uint8_t i = 0; i < MAX_CONCURRENT_ANIMATIONS; i++) {
        if (!current_animations[i].in_use) {
            continue;
        }

        // Load the current frame
        if (!gq_memcpy_ram(
                (uint8_t *) &frame_current,
                current_animations[i].anim.frame_pointer + current_animations[i].frame * sizeof(gq_anim_frame),
                sizeof(gq_anim_frame))) {
            // TODO: Handle errors
            continue;
        }

        // Draw the frame on the screen
        Graphics_Image img;
        img.bPP       = frame_current.bPP;
        img.xSize     = current_animations[i].anim.width;
        img.ySize     = current_animations[i].anim.height;
        img.numColors = 2;
        img.pPalette  = palette_bw;

        // Load the frame data
        frame_data = (uint8_t *) malloc(frame_current.data_size);
        if (!gq_memcpy_ram(frame_data, frame_current.data_pointer, frame_current.data_size)) {
            free(frame_data);
            return;
        }

        img.pPixel = frame_data;

        Graphics_drawImage(&g_sContext, &img, current_animations[i].x, current_animations[i].y);
        free(frame_data);
    }

    // Next, draw any labels
    // TODO: Implement

    // Then, draw the menu, if there is one.
    if (menu_active) {
        // TODO: make this look better.
        for (uint8_t i = 0; i < menu_current->option_count; i++) {
            Graphics_drawString(&g_sContext, menu_current->options[i].label, -1, 15, i * 10, 0);
            if (i == menu_option_selected) {
                Graphics_drawString(&g_sContext, ">", -1, 6, i * 10, 0);
            }
        }
    }
}

void anim_tick() {
    // Should be called by the 100 Hz system tick
    uint8_t need_to_redraw = 0;

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
            // TODO: Handle events for other animations
            current_animations[i].in_use = 0;
            if (i == 0) {
                // Background animation done, fire event.
                GQ_EVENT_SET(GQ_EVENT_BGDONE);
            }
        }
        need_to_redraw = 1;
    }

    if (need_to_redraw) {
        // TODO: Call this based on an event from the main loop, instead?
        draw_animations();
    }
}

void run_code(t_gq_pointer code_ptr) {
    gq_op cmd;
    gq_op_code opcode;
    if (GQ_PTR_ISNULL(code_ptr)) {
        return;
    }

    do {
        gq_memcpy_ram((uint8_t *) &cmd, code_ptr, sizeof(gq_op));
        opcode = (gq_op_code) cmd.opcode;

        switch (opcode) {
            case GQ_OP_DONE:
                break;
            case GQ_OP_NOP:
                break;
            case GQ_OP_GOSTAGE:
                load_stage(cmd.arg1);
                opcode = GQ_OP_DONE;
                break;
            case GQ_OP_PLAYBG:
                // TODO: bounds checking or whatever:
                load_animation(0, cmd.arg1);
                break;
            case GQ_OP_CUE:
                led_play_cue(cmd.arg1, 0);
                break;
            case GQ_OP_SETVAR:
                if (cmd.flags & GQ_OPF_TYPE_INT) {
                    gq_memcpy(cmd.arg1, cmd.arg2, GQ_INT_SIZE);
                } else if (cmd.flags & GQ_OPF_TYPE_STR) {
                    gq_memcpy(cmd.arg1, cmd.arg2, GQ_STR_SIZE);
                }
                break;
            case GQ_OP_GOTO:
                code_ptr = cmd.arg1;
                // Skip the rest of this loop, as we've already loaded the next command.
                continue;
            default:
                break;
        }

        code_ptr += sizeof(gq_op);
    } while (cmd.opcode != GQ_OP_DONE);
}

// TODO: Allow a mask?
void handle_events() {
    for (uint16_t event_type = 0x0000; event_type < GQ_EVENT_COUNT; event_type++) {
        if (GQ_EVENT_GET(event_type)) {
            GQ_EVENT_CLR(event_type);
            // If we're in a menu, hijack button events to navigate the menu.
            if (menu_active) {
                switch (event_type) {
                    case GQ_EVENT_BUTTON_A:
                        // Select the current menu option
                        // TODO: should this be a click instead?
                        GQ_BUILTIN_menu_value = menu_current->options[menu_option_selected].value;
                        menu_close();
                        break;
                    case GQ_EVENT_BUTTON_B:
                        // Cancel the menu
                        // TODO: does this have meaning?
                        menu_close();
                        break;
                    case GQ_EVENT_BUTTON_L:
                        // Move the selection up
                        if (menu_option_selected > 0) {
                            menu_option_selected--;
                        }
                        break;
                    case GQ_EVENT_BUTTON_R:
                        // Move the selection down
                        if (menu_option_selected < menu_current->option_count - 1) {
                            menu_option_selected++;
                        }
                        break;
                    default:
                        goto unblocked_events;
                        break;
                }
                continue;
            }

        unblocked_events:
            // Check whether this event type is used in the current stage.
            if (!GQ_PTR_ISNULL(stage_current.event_commands[event_type])) {
                run_code(stage_current.event_commands[event_type]);
            }
        }
    }
}
