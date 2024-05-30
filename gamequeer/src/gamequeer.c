#include <stdint.h>

#include "HAL.h"
#include "gamequeer.h"

gq_header game;
gq_anim anim_current;
gq_anim_frame frame_current;
gq_stage stage_current;

uint8_t load_game() {
    // Load the game header
    if (!gq_memcpy_ram((uint8_t *) &game, GQ_PTR(GQ_PTR_NS_CART, 0), sizeof(gq_header))) {
        return 0;
    }

    // Load the starting stage
    if (!gq_memcpy_ram((uint8_t *) &stage_current, game.starting_stage, sizeof(gq_stage))) {
        return 0;
    }

    return 1;
}
