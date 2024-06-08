#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gamequeer.h"

#include "HAL.h"
#include "gfx.h"
#include "grlib.h"
#include "grlib_gfx.h"

Graphics_Context g_sContext;

uint16_t s_gq_event = 0;

void init() {
    Graphics_setForegroundColor(&g_sContext, ClrWhite);
    Graphics_setBackgroundColor(&g_sContext, ClrBlack);
    Graphics_setFont(&g_sContext, &g_sFontFixed6x8);
    Graphics_clearDisplay(&g_sContext);

    // TODO: load the local starting stage
}

// TODO: Implement RL7 graphics loading based on
// https://github.com/duplico/qc16_badge/blob/master/ccs_workspace/qbadge/ui/graphics.c#L23

int main(int argc, char *argv[]) {
    HAL_init(argc, argv);
    init();

    load_game();

    // TODO: Add the LEDs
    // TODO: Load the starting animation
    while (1) {
        // Perform the current animation step
        anim_tick();

        // TODO: Perform the current menu step

        // TODO: Perform the current lighting cue step

        // Perform polling for other event sources
        HAL_event_poll();

        handle_events();

        HAL_sleep();
    }
}
