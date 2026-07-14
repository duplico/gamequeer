#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gamequeer.h"

#include "HAL.h"
#include "gfx.h"
#include "gq_perf.h"
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
 * The framebuffer is 127x127 pixels: OLED_HORIZONTAL_MAX = OLED_VERTICAL_MAX = 127.
 * The OLED_*_MAX constants are the width/height (exclusive upper bound on the
 * coordinate index); valid coordinates run 0..MAX-1, as enforced by the bounds
 * check in grlib_gfx_driver.c.
 * Golden fixture authors: the PGM header will read "P5\n127 127\n255\n".
 *
 * frame_buffer is indexed [x][y] with x=column, y=row.  PGM rows are written
 * left-to-right (increasing x), top-to-bottom (increasing y), which matches
 * the grlib convention used by gfx_driver_flush().
 */
extern uint8_t frame_buffer[OLED_HORIZONTAL_MAX][OLED_VERTICAL_MAX];

#ifdef GQ_HEADLESS
/* Instrumentation counter defined in gamequeer.c (draw_oled_stack() call
 * count), only compiled in headless builds -- see its declaration there
 * for why a pixel-level golden alone can't assert "N draws" vs "1 draw,
 * same pixels". */
extern uint32_t gq_draw_oled_stack_count;
#endif

/* Write the current draw_oled_stack() invocation count as a decimal integer
 * followed by a newline. Headless-build-only (see gq_draw_oled_stack_count
 * above); the caller is responsible for gating on GQ_HEADLESS. */
static int dump_draw_count(const char *path) {
#ifdef GQ_HEADLESS
    FILE *f = fopen(path, "wb");
    if (!f) {
        fprintf(stderr, "dump_draw_count: cannot open %s for writing\n", path);
        return 0;
    }
    fprintf(f, "%lu\n", (unsigned long) gq_draw_oled_stack_count);
    fclose(f);
    return 1;
#else
    (void) path;
    fprintf(stderr, "dump_draw_count: --draw-count-out requires a GQ_HEADLESS build\n");
    return 0;
#endif
}

#ifdef GQ_PERF_INSTRUMENT
/* Write the current gq_perf_stats contents as plain text: the struct header
 * (magic/version) followed by one line per section (count, accumulated
 * duration, min, max, and a derived average -- all in microseconds).
 * See include/gq_perf.h for the struct layout and section list.
 *
 * This whole function (and the --perf-dump flag that calls it, further
 * down) is compiled out entirely -- not just internally short-circuited --
 * in a non-instrumented build. Unlike dump_draw_count()'s
 * always-present-but-internally-gated pattern above, --perf-dump must not
 * add ANY bytes to a non-instrumented binary: this feature exists
 * specifically to validate the zero-cost claim for GQ_PERF_INSTRUMENT via a
 * byte-identical .map/binary comparison (see gq_perf.h), so even a
 * recognized-but-errors-out flag would break that proof. */
static int dump_perf_stats(const char *path) {
    FILE *f = fopen(path, "wb");
    if (!f) {
        fprintf(stderr, "dump_perf_stats: cannot open %s for writing\n", path);
        return 0;
    }
    fprintf(f, "magic=0x%08lx version=%u\n", (unsigned long) gq_perf_stats.magic, (unsigned) gq_perf_stats.version);
    for (int i = 0; i < GQ_PERF_SEC_COUNT; i++) {
        const gq_perf_section_t *s = &gq_perf_stats.sections[i];
        uint32_t avg_us            = s->count ? (s->total_us / s->count) : 0;
        fprintf(
            f,
            "%-24s count=%-8lu total_us=%-12lu min_us=%-8lu max_us=%-8lu avg_us=%-8lu\n",
            gq_perf_section_names[i],
            (unsigned long) s->count,
            (unsigned long) s->total_us,
            (unsigned long) s->min_us,
            (unsigned long) s->max_us,
            (unsigned long) avg_us);
    }
    fclose(f);
    return 1;
}
#endif /* GQ_PERF_INSTRUMENT */

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
     *   --ticks N            : run exactly N system_tick iterations then exit
     *   --dump PATH          : write the framebuffer as a binary PGM after the run
     *   --input FILE         : replay button events from a script (see HAL_input_load)
     *   --draw-count-out PATH: write the draw_oled_stack() invocation count
     *                          (decimal, headless builds only)
     *   --perf-dump PATH     : write gq_perf_stats as text (GQ_PERF_INSTRUMENT
     *                          builds only; see dump_perf_stats() above)
     * Defaults: unlimited ticks, no dump, no scripted input, no draw-count
     * output, no perf dump (same as before).
     */
    long ticks_limit           = -1; /* -1 = run forever */
    const char *dump           = NULL;
    const char *input          = NULL;
    const char *cart           = NULL;
    const char *draw_count_out = NULL;
#ifdef GQ_PERF_INSTRUMENT
    const char *perf_dump = NULL;
#endif

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
        if (strcmp(argv[i], "--ticks") == 0) {
            /* Only require that a next argument exists; don't reject values
             * that happen to start with '-' (e.g. a negative number), since
             * the strtol() check below already validates the value itself. */
            if (i + 1 >= argc) {
                fprintf(stderr, "main: --ticks requires a value\n");
                free(hal_argv);
                return 1;
            }
            char *endptr;
            ticks_limit = strtol(argv[++i], &endptr, 10);
            if (*endptr != '\0' || ticks_limit <= 0) {
                fprintf(stderr, "main: --ticks requires a positive integer, got '%s'\n", argv[i]);
                free(hal_argv);
                return 1;
            }
        } else if (strcmp(argv[i], "--dump") == 0) {
            /* Only require that a next argument exists; a path legitimately
             * starting with '-' should not be rejected. */
            if (i + 1 >= argc) {
                fprintf(stderr, "main: --dump requires a value\n");
                free(hal_argv);
                return 1;
            }
            dump = argv[++i];
        } else if (strcmp(argv[i], "--input") == 0) {
            /* Only require that a next argument exists; a path legitimately
             * starting with '-' should not be rejected. */
            if (i + 1 >= argc) {
                fprintf(stderr, "main: --input requires a value\n");
                free(hal_argv);
                return 1;
            }
            input = argv[++i];
        } else if (strcmp(argv[i], "--draw-count-out") == 0) {
            /* Only require that a next argument exists; a path legitimately
             * starting with '-' should not be rejected. */
            if (i + 1 >= argc) {
                fprintf(stderr, "main: --draw-count-out requires a value\n");
                free(hal_argv);
                return 1;
            }
            draw_count_out = argv[++i];
#ifdef GQ_PERF_INSTRUMENT
        } else if (strcmp(argv[i], "--perf-dump") == 0) {
            /* Only require that a next argument exists; a path legitimately
             * starting with '-' should not be rejected. */
            if (i + 1 >= argc) {
                fprintf(stderr, "main: --perf-dump requires a value\n");
                free(hal_argv);
                return 1;
            }
            perf_dump = argv[++i];
#endif /* GQ_PERF_INSTRUMENT */
        } else {
            if (cart == NULL) {
                cart = argv[i];
            }
            hal_argv[hal_argc++] = argv[i];
        }
    }
    hal_argv[hal_argc] = NULL;

    if (cart == NULL) {
        fprintf(stderr, "main: no cart path provided\n");
        free(hal_argv);
        return 1;
    }

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

    if (draw_count_out != NULL) {
        if (!dump_draw_count(draw_count_out)) {
            return 1;
        }
    }

#ifdef GQ_PERF_INSTRUMENT
    if (perf_dump != NULL) {
        if (!dump_perf_stats(perf_dump)) {
            return 1;
        }
    }
#endif /* GQ_PERF_INSTRUMENT */

    return 0;
}
