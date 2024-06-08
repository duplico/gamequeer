#include <stdint.h>

#include "HAL.h"
#include "gamequeer.h"
#include "gamequeer_bytecode.h"
#include "grlib.h"
#include "stdlib.h"

gq_header game;
uint8_t bg_animating = 0;
gq_anim anim_current;
gq_anim_frame frame_current;
gq_stage stage_current;

uint32_t curr_frame;
uint8_t *frame_data;

// TODO: Move
const uint32_t palette_bw[] = {0x000000, 0xffffff};
const uint32_t palette_wb[] = {0xffffff, 0x000000};

/**
 * @brief Loads a frame description (but not the data buffer).
 *
 * @param frame_ptr A pointer to the frame to be loaded.
 * @return The status of the frame loading operation (0 for success, non-zero for failure).
 */
uint8_t load_frame(t_gq_pointer frame_ptr) {
    // Load the current frame
    if (!gq_memcpy_ram((uint8_t *) &frame_current, frame_ptr, sizeof(gq_anim_frame))) {
        return 0;
    }

    return 1;
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
        if (!load_animation(stage_current.anim_bg_pointer)) {
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

uint8_t load_animation(t_gq_pointer anim_ptr) {
    // Load the animation header
    if (!gq_memcpy_ram((uint8_t *) &anim_current, anim_ptr, sizeof(gq_anim))) {
        return 0;
    }

    // Set the current frame to the first frame
    if (!gq_memcpy_ram((uint8_t *) &frame_current, anim_current.frame_pointer, sizeof(gq_anim_frame))) {
        return 0;
    }

    curr_frame   = 0;
    bg_animating = 1;

    return 1;
}

void show_curr_frame() {
    // Load the frame data
    frame_data = (uint8_t *) malloc(frame_current.data_size);
    if (!gq_memcpy_ram(frame_data, frame_current.data_pointer, frame_current.data_size)) {
        free(frame_data);
        return;
    }

    Graphics_Image img;
    img.bPP       = frame_current.bPP;
    img.xSize     = anim_current.width;
    img.ySize     = anim_current.height;
    img.numColors = 2;
    img.pPalette  = palette_bw;
    img.pPixel    = frame_data;

    Graphics_drawImage(&g_sContext, &img, 0, 0);
    free(frame_data);
}

uint8_t next_frame() {
    // TODO: Assert bg_animating.
    curr_frame++;
    if (curr_frame >= anim_current.frame_count) {
        curr_frame   = 0;
        bg_animating = 0;
        GQ_EVENT_SET(GQ_EVENT_BGDONE);
        return 0; // Done
    }

    t_gq_pointer next_frame_ptr = anim_current.frame_pointer + curr_frame * sizeof(gq_anim_frame);
    load_frame(next_frame_ptr);
    return curr_frame;
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
                load_animation(cmd.arg1);
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