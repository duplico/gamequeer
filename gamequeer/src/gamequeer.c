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

// TODO: Move
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

void draw_animations() {
    gq_anim_frame frame_current;

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
        }

        code_ptr += sizeof(gq_op);
    } while (cmd.opcode != GQ_OP_DONE);
}

// TODO: Allow a mask?
uint16_t handle_events() {
    for (uint16_t event_type = 0x0000; event_type < GQ_EVENT_COUNT; event_type++) {
        if (GQ_EVENT_GET(event_type)) {
            // Check whether this event type is used in the current stage.
            if (!GQ_PTR_ISNULL(stage_current.event_commands[event_type])) {
                run_code(stage_current.event_commands[event_type]);
            }

            GQ_EVENT_CLR(event_type);
        }
    }
}
