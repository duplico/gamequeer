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

t_gq_int *game_id     = (t_gq_int *) &gq_builtin_ints[GQI_GAME_ID * GQ_INT_SIZE];
t_gq_int *menu_active = (t_gq_int *) &gq_builtin_ints[GQI_MENU_ACTIVE * GQ_INT_SIZE];
t_gq_int *menu_value  = (t_gq_int *) &gq_builtin_ints[GQI_MENU_VALUE * GQ_INT_SIZE];
t_gq_int *game_color  = (t_gq_int *) &gq_builtin_ints[GQI_GAME_COLOR * GQ_INT_SIZE];
t_gq_int *anim0_x     = (t_gq_int *) &gq_builtin_ints[GQI_BGANIM_X * GQ_INT_SIZE];
t_gq_int *anim0_y     = (t_gq_int *) &gq_builtin_ints[GQI_BGANIM_Y * GQ_INT_SIZE];
t_gq_int *anim1_x     = (t_gq_int *) &gq_builtin_ints[GQI_FGANIM1_X * GQ_INT_SIZE];
t_gq_int *anim1_y     = (t_gq_int *) &gq_builtin_ints[GQI_FGANIM1_Y * GQ_INT_SIZE];
t_gq_int *anim2_x     = (t_gq_int *) &gq_builtin_ints[GQI_FGANIM2_X * GQ_INT_SIZE];
t_gq_int *anim2_y     = (t_gq_int *) &gq_builtin_ints[GQI_FGANIM2_Y * GQ_INT_SIZE];

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

gq_menu *menu_current;
char menu_current_prompt[GQ_STR_SIZE];
uint8_t menu_offset_y        = 0;
uint8_t menu_option_selected = 0;

uint8_t timer_active = 0;
t_gq_int timer_interval;
t_gq_int timer_counter;

const uint32_t palette_bw[] = {0x000000, 0xffffff};
const uint32_t palette_wb[] = {0xffffff, 0x000000};

void run_code(t_gq_pointer code_ptr);

void menu_load(t_gq_pointer menu_ptr, t_gq_pointer menu_prompt) {
    t_gq_int menu_option_count;
    t_gq_pointer menu_size;

    // Determine the size of the current menu based on its option count.
    gq_memcpy_to_ram((uint8_t *) &menu_option_count, menu_ptr, GQ_INT_SIZE);
    menu_size = GQ_INT_SIZE + menu_option_count * sizeof(gq_menu_option);

    // Load the menu into RAM.
    menu_current = (gq_menu *) malloc(menu_size);
    gq_memcpy_to_ram((uint8_t *) menu_current, menu_ptr, menu_size);

    // Load the menu prompt into RAM.
    if (menu_prompt) {
        gq_memcpy_to_ram((uint8_t *) menu_current_prompt, menu_prompt, GQ_STR_SIZE);
        menu_offset_y = 18; // TODO: constant or something
    } else {
        menu_current_prompt[0] = '\0';
        menu_offset_y          = 0;
    }

    // Initialize the menu options and activate it.
    menu_option_selected = 0;
    *menu_active         = 1;
}

void menu_close() {
    if (!*menu_active) {
        return;
    }

    *menu_active = 0;
    free(menu_current);
    GQ_EVENT_SET(GQ_EVENT_REFRESH);
}

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

    // Close the menu
    menu_close(); // Sets GQ_EVENT_REFRESH

    if (stage_current.menu_pointer) {
        // If this stage has a menu, load it.
        menu_load(stage_current.menu_pointer, stage_current.menu_prompt_pointer);
    }

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

    return 1;
}

uint8_t load_game() {
    // Load the game header
    if (!gq_memcpy_to_ram((uint8_t *) &game, GQ_PTR(GQ_PTR_NS_CART, 0), sizeof(gq_header))) {
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

    GQ_EVENT_SET(GQ_EVENT_REFRESH);

    return 1;
}

void draw_oled_stack() {
    gq_anim_frame frame_current;

    // First, start with a blank slate.
    Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
    Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);
    Graphics_clearDisplay(&g_sContext);

    // Then draw the animation stack.
    for (uint8_t i = 0; i < MAX_CONCURRENT_ANIMATIONS; i++) {
        if (!current_animations[i].in_use) {
            continue;
        }

        switch (i) { // TODO: Handle masks
            case 0:
                current_animations[i].x = *anim0_x;
                current_animations[i].y = *anim0_y;
                break;
            case 1:
            case 2:
                current_animations[i].x = *anim1_x;
                current_animations[i].y = *anim1_y;
                break;
            case 3:
            case 4:
                current_animations[i].x = *anim2_x;
                current_animations[i].y = *anim2_y;
                break;
        }

        // Load the current frame
        if (!gq_memcpy_to_ram(
                (uint8_t *) &frame_current,
                current_animations[i].anim.frame_pointer + current_animations[i].frame * sizeof(gq_anim_frame),
                sizeof(gq_anim_frame))) {
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
        if (!gq_memcpy_to_ram(frame_data, frame_current.data_pointer, frame_current.data_size)) {
            free(frame_data);
            return;
        }

        img.pPixel = frame_data;

        Graphics_drawImage(&g_sContext, &img, current_animations[i].x, current_animations[i].y);
        free(frame_data);
    }

    // Draw the labels
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

    // Then, draw the menu, if there is one.
    if (*menu_active) {
        Graphics_Rectangle menu_background = {0, 0, 128, menu_offset_y + menu_current->option_count * 10};
        Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
        Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);
        Graphics_fillRectangle(&g_sContext, &menu_background);
        Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
        Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);

        if (menu_current_prompt[0]) {
            Graphics_drawString(&g_sContext, menu_current_prompt, -1, 6, 3, 0);
        }

        for (uint8_t i = 0; i < menu_current->option_count; i++) {
            Graphics_drawString(&g_sContext, menu_current->options[i].label, -1, 15, menu_offset_y + i * 10, 0);
            if (i == menu_option_selected) {
                Graphics_drawString(&g_sContext, ">", -1, 6, menu_offset_y + i * 10, 0);
            }
        }
    }

    Graphics_flushBuffer(&g_sContext);
}

void system_tick() {
    // Should be called by the 100 Hz system tick

    // Handle the LEDs
    led_tick();

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

void run_arithmetic(gq_op *cmd) {
    t_gq_int arg1;
    t_gq_int arg2;
    t_gq_int result;

    if (cmd->opcode == GQ_OP_NOT || cmd->opcode == GQ_OP_NEG || cmd->opcode == GQ_OP_BWNOT) {
        // These operations only have arg2 as an operand; arg1 is the result.
        // No need to load anything to arg1 for a unary operation.
    } else {
        // All other operations have arg1 and arg2 as operands.
        gq_memcpy_to_ram((uint8_t *) &arg1, cmd->arg1, GQ_INT_SIZE);
    }
    if (!(cmd->flags & GQ_OPF_LITERAL_ARG2)) {
        gq_memcpy_to_ram((uint8_t *) &arg2, cmd->arg2, GQ_INT_SIZE);
    } else {
        arg2 = cmd->arg2;
    }

    switch (cmd->opcode) {
        case GQ_OP_ADDBY:
            result = arg1 + arg2;
            break;
        case GQ_OP_SUBBY:
            result = arg1 - arg2;
            break;
        case GQ_OP_MULBY:
            result = arg1 * arg2;
            break;
        case GQ_OP_DIVBY:
            result = arg1 / arg2;
            break;
        case GQ_OP_MODBY:
            result = arg1 % arg2;
            break;
        case GQ_OP_EQ:
            result = arg1 == arg2;
            break;
        case GQ_OP_NE:
            result = arg1 != arg2;
            break;
        case GQ_OP_GT:
            result = arg1 > arg2;
            break;
        case GQ_OP_LT:
            result = arg1 < arg2;
            break;
        case GQ_OP_GE:
            result = arg1 >= arg2;
            break;
        case GQ_OP_LE:
            result = arg1 <= arg2;
            break;
        case GQ_OP_AND:
            result = arg1 && arg2;
            break;
        case GQ_OP_OR:
            result = arg1 || arg2;
            break;
        case GQ_OP_NOT:
            result = !arg2;
            break;
        case GQ_OP_NEG:
            result = -arg2;
            break;
        case GQ_OP_BWNOT:
            result = ~arg2;
            break;
        case GQ_OP_BWAND:
            result = arg1 & arg2;
            break;
        case GQ_OP_BWOR:
            result = arg1 | arg2;
            break;
        case GQ_OP_BWXOR:
            result = arg1 ^ arg2;
            break;
        case GQ_OP_BWSHL:
            result = arg1 << arg2;
            break;
        case GQ_OP_BWSHR:
            result = arg1 >> arg2;
            break;
        case GQ_OP_QCGET:
            result = get_badge_bit(arg2);
            break;
        default:
            return;
    }

    gq_assign_int(cmd->arg1, result);
}

void run_code(t_gq_pointer code_ptr) {
    gq_op cmd;
    gq_op_code opcode;

    char result_str[GQ_STR_SIZE];
    char arg1_str[GQ_STR_SIZE];
    char arg2_str[GQ_STR_SIZE];

    if (GQ_PTR_ISNULL(code_ptr)) {
        return;
    }

    do {
        // TODO: bounds checking for the code_ptr
        gq_memcpy_to_ram((uint8_t *) &cmd, code_ptr, sizeof(gq_op));
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
            case GQ_OP_PLAY:
                // TODO: check if it's literal
                load_animation(cmd.arg2, cmd.arg1);
                break;
            case GQ_OP_CUE:
                led_play_cue(cmd.arg1, 0);
                break;
            case GQ_OP_SETVAR:
                if (cmd.flags & GQ_OPF_TYPE_INT && cmd.flags & GQ_OPF_TYPE_STR) {
                    // If both STR and INT flags are set, this is a cast from int to str.
                    // TODO: This command is one of the danger zones. We have no type
                    //  introspection available in the interpreter, so we have to rely on
                    //  the compiler having generated good code. If it turns out that arg1
                    //  is an int, then an overflow is possible, because this code treats it
                    //  as a string.
                    // On the other hand, the opposite isn't terribly concerning. If arg1
                    //  is a string and arg2 is an int, then we'll probably print some garbage,
                    //  but it won't hurt anything.
                    if (cmd.flags & GQ_OPF_LITERAL_ARG2) {
                        snprintf(result_str, GQ_STR_SIZE, "%d", cmd.arg2);
                    } else {
                        t_gq_int arg2_int = gq_load_int(cmd.arg2);
                        snprintf(result_str, GQ_STR_SIZE, "%d", arg2_int);
                    }
                    gq_memcpy_from_ram(cmd.arg1, (uint8_t *) result_str, GQ_STR_SIZE);
                } else if (cmd.flags & GQ_OPF_TYPE_INT) {
                    // If only the INT flag is set, this is an int to int assignment.
                    if (cmd.flags & GQ_OPF_LITERAL_ARG2) {
                        gq_assign_int(cmd.arg1, cmd.arg2);
                    } else {
                        gq_memcpy(cmd.arg1, cmd.arg2, GQ_INT_SIZE);
                    }
                } else if (cmd.flags & GQ_OPF_TYPE_STR) {
                    // If only the STR flag is set, this is a str to str assignment.
                    gq_memcpy(cmd.arg1, cmd.arg2, GQ_STR_SIZE);
                }
                break;
            case GQ_OP_GOTO:
                code_ptr = cmd.arg1;
                // Skip the rest of this loop, as we've already loaded the next command.
                continue;
            case GQ_OP_ADDBY:
            case GQ_OP_SUBBY:
            case GQ_OP_MULBY:
            case GQ_OP_DIVBY:
            case GQ_OP_MODBY:
            case GQ_OP_EQ:
            case GQ_OP_NE:
            case GQ_OP_GT:
            case GQ_OP_LT:
            case GQ_OP_GE:
            case GQ_OP_LE:
            case GQ_OP_AND:
            case GQ_OP_OR:
            case GQ_OP_NOT:
            case GQ_OP_NEG:
            case GQ_OP_BWAND:
            case GQ_OP_BWOR:
            case GQ_OP_BWXOR:
            case GQ_OP_BWNOT:
            case GQ_OP_BWSHL:
            case GQ_OP_BWSHR:
            case GQ_OP_QCGET:
                run_arithmetic(&cmd);
                break;
            case GQ_OP_GOTOIFN:
                // If the condition is false, either because it's a literal false or the variable is 0,
                // jump to the specified address.
                if ((cmd.flags & GQ_OPF_LITERAL_ARG2 && !cmd.arg2) || !gq_load_int(cmd.arg2)) {
                    code_ptr = cmd.arg1;
                    // Skip the rest of this loop, as we've already loaded the next command.
                    continue;
                }
                break;
            case GQ_OP_TIMER:
                if (cmd.flags & GQ_OPF_LITERAL_ARG2) {
                    timer_interval = cmd.arg2;
                } else {
                    timer_interval = gq_load_int(cmd.arg2);
                }

                if (timer_interval > 0) {
                    timer_active  = 1;
                    timer_counter = 0;
                } else {
                    timer_active = 0;
                }
                break;
            case GQ_OP_QCSET:
                if (cmd.flags & GQ_OPF_LITERAL_ARG2) {
                    set_badge_bit(cmd.arg2, 1);
                } else {
                    set_badge_bit(gq_load_int(cmd.arg2), 1);
                }
                break;
            case GQ_OP_QCCLR:
                if (cmd.flags & GQ_OPF_LITERAL_ARG2) {
                    set_badge_bit(cmd.arg2, 0);
                } else {
                    set_badge_bit(gq_load_int(cmd.arg2), 0);
                }
                break;
            case GQ_OP_STRCAT:
                // TODO: Break out into a function, maybe?
                gq_memcpy_to_ram((uint8_t *) arg1_str, cmd.arg1, GQ_STR_SIZE);
                gq_memcpy_to_ram((uint8_t *) arg2_str, cmd.arg2, GQ_STR_SIZE);
                snprintf(result_str, GQ_STR_SIZE, "%s%s", arg1_str, arg2_str);
                gq_memcpy_from_ram(cmd.arg1, (uint8_t *) result_str, GQ_STR_SIZE);
                break;
            default:
                break;
        }

        code_ptr += sizeof(gq_op);
    } while (cmd.opcode != GQ_OP_DONE);
}

void handle_events() {
    for (uint16_t event_type = 0x0000; event_type < GQ_EVENT_COUNT; event_type++) {
        if (GQ_EVENT_GET(event_type)) {
            GQ_EVENT_CLR(event_type);
            // If we're in a menu, hijack button events to navigate the menu.
            if (*menu_active) {
                switch (event_type) {
                    GQ_EVENT_SET(GQ_EVENT_REFRESH); // TODO: Only sometimes?
                    case GQ_EVENT_BUTTON_A:
                        // Select the current menu option
                        *menu_value = menu_current->options[menu_option_selected].value;
                        menu_close();
                        GQ_EVENT_SET(GQ_EVENT_MENU);
                        break;
                    case GQ_EVENT_BUTTON_B:
                        // Cancel the menu
                        menu_close();
                        break;
                    case GQ_EVENT_BUTTON_L:
                        // Move the selection up
                        if (menu_option_selected > 0) {
                            menu_option_selected--;
                            GQ_EVENT_SET(GQ_EVENT_REFRESH);
                        }
                        break;
                    case GQ_EVENT_BUTTON_R:
                        // Move the selection down
                        if (menu_option_selected < menu_current->option_count - 1) {
                            menu_option_selected++;
                            GQ_EVENT_SET(GQ_EVENT_REFRESH);
                        }
                        break;
                    default:
                        goto unblocked_events;
                        break;
                }
                continue;
            }

        unblocked_events:
            if (event_type == GQ_EVENT_REFRESH) {
                // Special event: refresh the OLED stack
                draw_oled_stack();
            } else if (!GQ_PTR_ISNULL(stage_current.event_commands[event_type])) {
                // Otherwise, look for an event command to run in the current stage.
                run_code(stage_current.event_commands[event_type]);
            }
        }
    }
}
