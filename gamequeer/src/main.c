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
}

/*
 * Write frame_buffer[OLED_HORIZONTAL_MAX][OLED_VERTICAL_MAX] as a binary PGM
 * (P5).  Each entry is 0 or 1; we map 0->0 and 1->255.
 *
 * The framebuffer is 127x127 pixels: OLED_HORIZONTAL_MAX = OLED_VERTICAL_MAX = 127
 * (not 128x128 — the OLED_*_MAX constants are the maximum coordinate index, which
 * is also the pixel count since grlib uses 0-based indexing up to and including MAX).
 * Golden fixture authors: the PGM header will read "P5\n127 127\n255\n".
 *
 * frame_buffer is indexed [x][y] with x=column, y=row.  PGM rows are written
 * left-to-right (increasing x), top-to-bottom (increasing y), which matches
 * the grlib convention used by gfx_driver_flush().
 */
extern uint8_t frame_buffer[OLED_HORIZONTAL_MAX][OLED_VERTICAL_MAX];

static int dump_framebuffer(const char *path) {
    FILE *f = fopen(path, "wb");
    if (!f) {
        fprintf(stderr, "dump_framebuffer: cannot open %s for writing\n", path);
        return 0;
    }

    /* PGM P5 header */
    fprintf(f, "P5\n%d %d\n255\n", OLED_HORIZONTAL_MAX, OLED_VERTICAL_MAX);

    uint8_t row[OLED_HORIZONTAL_MAX];
    for (int y = 0; y < OLED_VERTICAL_MAX; y++) {
        for (int x = 0; x < OLED_HORIZONTAL_MAX; x++) {
            row[x] = frame_buffer[x][y] ? 255 : 0;
        }
        if (fwrite(row, 1, OLED_HORIZONTAL_MAX, f) != (size_t) OLED_HORIZONTAL_MAX) {
            fprintf(stderr, "dump_framebuffer: write error\n");
            fclose(f);
            return 0;
        }
    }
    fclose(f);
    return 1;
}

int main(int argc, char *argv[]) {
    /* Deterministic-run parameters.
     *   --ticks N   : run exactly N system_tick iterations then exit
     *   --dump PATH : write the framebuffer as a binary PGM after the run
     *   --input FILE: replay button events from a script (see HAL_input_load)
     * Defaults: unlimited ticks, no dump, no scripted input (same as before).
     */
    long ticks_limit  = -1; /* -1 = run forever */
    const char *dump  = NULL;
    const char *input = NULL;
    const char *cart  = NULL;

    /* Build a filtered argv for HAL_init that strips our new flags so it
     * still sees the cart path at argv[1]. */
    char **hal_argv = (char **) malloc((size_t) (argc + 1) * sizeof(char *));
    if (!hal_argv) {
        fprintf(stderr, "main: out of memory\n");
        return 1;
    }
    int hal_argc         = 0;
    hal_argv[hal_argc++] = argv[0];

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--ticks") == 0 && i + 1 < argc) {
            char *endptr;
            ticks_limit = strtol(argv[++i], &endptr, 10);
            if (*endptr != '\0' || ticks_limit <= 0) {
                fprintf(stderr, "main: --ticks requires a positive integer, got '%s'\n", argv[i]);
                free(hal_argv);
                return 1;
            }
        } else if (strcmp(argv[i], "--dump") == 0 && i + 1 < argc) {
            dump = argv[++i];
        } else if (strcmp(argv[i], "--input") == 0 && i + 1 < argc) {
            input = argv[++i];
        } else {
            if (cart == NULL) {
                cart = argv[i];
            }
            hal_argv[hal_argc++] = argv[i];
        }
    }
    hal_argv[hal_argc] = NULL;

    HAL_init(hal_argc, hal_argv);
    free(hal_argv);

    if (input != NULL) {
        HAL_input_load(input);
    }

    init();

    load_game(GQ_PTR_NS_CART);

    long ticks_done = 0;
    while (ticks_limit < 0 || ticks_done < ticks_limit) {
        // Perform the current animation step
        system_tick();

        // Perform polling for other event sources
        HAL_event_poll();

        handle_events();

        HAL_sleep();
        ticks_done++;
    }

    if (dump != NULL) {
        if (!dump_framebuffer(dump)) {
            return 1;
        }
    }

    return 0;
}
