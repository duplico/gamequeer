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

const uint32_t palette_bw[] = {0x000000, 0xffffff};
const uint32_t palette_wb[] = {0xffffff, 0x000000};

uint8_t s_clicked   = 0;
uint8_t s_anim_done = 0;

void init() {
    Graphics_setForegroundColor(&g_sContext, ClrWhite);
    Graphics_setBackgroundColor(&g_sContext, ClrBlack);
    Graphics_setFont(&g_sContext, &g_sFontFixed6x8);
    Graphics_clearDisplay(&g_sContext);

    // TODO: load the local starting stage
}

int main(int argc, char *argv[]) {
    HAL_init(argc, argv);
    init();

    load_game();

    // TODO: Add the LEDs
    // TODO: Load the starting animation
    while (1) {
        // Perform the current animation step
        // TODO
        // Graphics_drawImage(&g_sContext, &fingerprint_1BPP_UNCOMP, 0, 0);
        Graphics_drawString(&g_sContext, "Hello, world!", -1, 0, 96, false);

        // Perform polling for other event sources
        HAL_event_poll();

        ////////// Handle events //////////
        // Animation done
        if (s_anim_done) {
            // Handle the animation done event.
            // TODO: implement
            s_anim_done = 0;
        }
        // Button pressed (A, B, left, right, click)
        if (s_clicked) {
            // Handle the click; quit the game.
            exit(0);
            s_clicked = 0;
        }

        HAL_sleep();
    }
}
