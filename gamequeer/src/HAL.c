#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#include "gamequeer.h"
#include "gq_perf.h"
#include "grlib_gfx.h"

uint8_t flash_cart[CART_FLASH_SIZE_MBYTES * 1024 * 1024];
uint8_t flash_save[SAVE_FLASH_SIZE_MBYTES * 1024 * 1024];
uint8_t flash_fram[512];

uint8_t read_byte(t_gq_pointer ptr) {
    switch (GQ_PTR_NS(ptr)) {
        case GQ_PTR_NS_CART:
            return flash_cart[GQ_PTR_ADDR(ptr)];
        case GQ_PTR_NS_SAVE:
            return flash_save[GQ_PTR_ADDR(ptr)];
        case GQ_PTR_NS_FRAM:
            return flash_fram[GQ_PTR_ADDR(ptr)];
        case GQ_PTR_NS_FBUF:
            return 0;
        case GQ_PTR_NS_HEAP:
            return gq_heap[GQ_PTR_ADDR(ptr)];
        case GQ_PTR_BUILTIN_INT:
            return gq_builtin_ints[GQ_PTR_ADDR(ptr)];
        case GQ_PTR_BUILTIN_STR:
            return gq_builtin_strs[GQ_PTR_ADDR(ptr)];
        default:
            gq_game_unload_flag = 1;
            return 0;
    }
}

uint8_t write_byte(t_gq_pointer ptr, uint8_t value) {
    switch (GQ_PTR_NS(ptr)) {
        case GQ_PTR_NS_CART:
            flash_cart[GQ_PTR_ADDR(ptr)] = value;
            return 1;
        case GQ_PTR_NS_SAVE:
            flash_save[GQ_PTR_ADDR(ptr)] = value;
            return 1;
        case GQ_PTR_NS_FRAM:
            flash_fram[GQ_PTR_ADDR(ptr)] = value;
            return 1;
        case GQ_PTR_NS_FBUF:
            return 0;
        case GQ_PTR_NS_HEAP:
            gq_heap[GQ_PTR_ADDR(ptr)] = value;
            return 1;
        case GQ_PTR_BUILTIN_INT:
            gq_builtin_ints[GQ_PTR_ADDR(ptr)] = value;
            return 1;
        case GQ_PTR_BUILTIN_STR:
            gq_builtin_strs[GQ_PTR_ADDR(ptr)] = value;
            return 1;
        default:
            gq_game_unload_flag = 1;
            return 0;
    }
}

uint8_t gq_memcpy(t_gq_pointer dest, t_gq_pointer src, uint32_t size) {
    for (t_gq_pointer i = 0; i < size; i++) {
        if (!write_byte(dest + i, read_byte(src + i))) {
            gq_game_unload_flag = 1;
            return 0;
        }
    }
    return 1;
}

uint8_t gq_memcpy_to_ram(uint8_t *dest, t_gq_pointer src, uint32_t size) {
    for (t_gq_pointer i = 0; i < size; i++) {
        dest[i] = read_byte(src + i);
    }
    return 1;
}

uint8_t gq_memcpy_from_ram(t_gq_pointer dest, uint8_t *src, uint32_t size) {
    for (t_gq_pointer i = 0; i < size; i++) {
        if (!write_byte(dest + i, src[i])) {
            return 0;
        }
    }
    return 1;
}

uint8_t gq_assign_int(t_gq_pointer dest, t_gq_int value) {
    for (uint8_t i = 0; i < GQ_INT_SIZE; i++) {
        if (!write_byte(dest + i, (value >> (i * 8)) & 0xFF)) {
            return 0;
        }
    }
    return 1;
}

t_gq_int gq_load_int(t_gq_pointer src) {
    t_gq_int value = 0;
    for (uint8_t i = 0; i < GQ_INT_SIZE; i++) {
        value |= read_byte(src + i) << (i * 8);
    }
    return value;
}

// --dump-leds state (see HAL_leds_dump_open()/HAL_leds_dump_close() below).
// NULL whenever --dump-leds wasn't given, which both HAL_update_leds()
// (skip the CSV row) and HAL_sleep() (skip the tick-counter increment)
// check -- the common case pays only those two cheap branches.
static FILE *leds_dump_file = NULL;
// Count of HAL_sleep() calls so far, i.e. the number of system_tick()
// iterations completed *before* the current one (main()'s loop calls
// system_tick() then HAL_sleep() then increments its own ticks_done, once
// each per iteration -- see HAL_sleep() below for where this is
// incremented, only while a --dump-leds file is open). This is an
// iteration count, not a wall-clock time: it's equally meaningful in every
// build (HAL_sleep() is called exactly once per iteration whether or not
// GQ_HEADLESS is set), but only a headless build's iterations run back to
// back with no real-time pacing -- an interactive build's HAL_sleep() paces
// each iteration to ~10ms, so tick N there also corresponds to roughly
// N*10ms of wall-clock time, which a headless run's tick N does not.
// Caveat: because the counter only advances at end-of-iteration, tick 0
// labels both load_game()'s pre-loop boot-color row (see load_game() in
// gamequeer.c) *and* any redraw that happens to land during the first loop
// iteration itself -- currently unreachable (led_tick()'s subtick countdown
// needs 4 calls before its first redraw), but a fixture scripting an
// immediate foreground cue could someday produce two same-tick rows.
static uint32_t leds_dump_tick_count = 0;

void HAL_leds_dump_close() {
    if (leds_dump_file) {
        fclose(leds_dump_file);
        leds_dump_file = NULL;
    }
}

int HAL_leds_dump_open(const char *path) {
    // Defensive: main() only calls this once per process today, but close
    // out any previously-open dump file first (rather than leaking its FILE*)
    // and reset the tick counter, so a hypothetical future caller opening a
    // second dump gets its own 0-based `tick` column instead of continuing
    // the previous run's count.
    HAL_leds_dump_close();
    leds_dump_tick_count = 0;

    leds_dump_file = fopen(path, "wb");
    if (!leds_dump_file) {
        fprintf(stderr, "HAL_leds_dump_open: cannot open %s for writing\n", path);
        return 0;
    }
    fprintf(leds_dump_file, "tick,r0,g0,b0,r1,g1,b1,r2,g2,b2,r3,g3,b3,r4,g4,b4\n");
    return 1;
}

void HAL_update_leds() {
    for (uint8_t i = 0; i < 5; i++) {
        gfx_color(gq_leds[i].r >> 8, gq_leds[i].g >> 8, gq_leds[i].b >> 8);
        gfx_fillrect(0, i * LEDS_H, LEDS_W, i * LEDS_H + LEDS_H);
        gfx_fillrect(
            LEDS_W + OLED_HORIZONTAL_MAX, i * LEDS_H, LEDS_W + OLED_HORIZONTAL_MAX + LEDS_W, i * LEDS_H + LEDS_H);
    }
    gfx_flush();

    // One CSV row per actual redraw (this function is only ever called when
    // the LED subsystem has new output to show -- see leds.c's led_tick()
    // need_to_redraw gating and led_stop()), not per tick: rows are ~4 ticks
    // apart during a cue (LEDS_SUBTICKS' 25 Hz vs. the 100 Hz system tick),
    // and can be any distance apart otherwise. Columns are the 8-bit
    // authored color (gq_leds is the 16-bit expanded form used for
    // sub-tick fade interpolation; >> 8 recovers the meaningful high byte,
    // same as the gfx_color() call above).
    if (leds_dump_file) {
        fprintf(
            leds_dump_file,
            "%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u\n",
            (unsigned) leds_dump_tick_count,
            (unsigned) (gq_leds[0].r >> 8),
            (unsigned) (gq_leds[0].g >> 8),
            (unsigned) (gq_leds[0].b >> 8),
            (unsigned) (gq_leds[1].r >> 8),
            (unsigned) (gq_leds[1].g >> 8),
            (unsigned) (gq_leds[1].b >> 8),
            (unsigned) (gq_leds[2].r >> 8),
            (unsigned) (gq_leds[2].g >> 8),
            (unsigned) (gq_leds[2].b >> 8),
            (unsigned) (gq_leds[3].r >> 8),
            (unsigned) (gq_leds[3].g >> 8),
            (unsigned) (gq_leds[3].b >> 8),
            (unsigned) (gq_leds[4].r >> 8),
            (unsigned) (gq_leds[4].g >> 8),
            (unsigned) (gq_leds[4].b >> 8));
    }
}

void HAL_new_game() {
    // Nothing to do, on the emulator.
}

void HAL_init(int argc, char *argv[]) {
    gfx_driver_init("Gamequeer");
    Graphics_initContext(&g_sContext, &g_gfx);

    if (argc < 2) {
        fprintf(stderr, "Usage: %s <cart_image>\n", argv[0]);
        exit(1);
    }

    const char *filename = argv[1];
    FILE *file;
    if (strcmp(filename, "-") == 0) {
        file = stdin;
    } else {
        file = fopen(filename, "rb");
    }
    if (file == NULL) {
        fprintf(stderr, "Error opening file: %s\n", filename);
        exit(1);
    }
    size_t bytesRead = fread(flash_cart, sizeof(uint8_t), CART_FLASH_SIZE_MBYTES * 1024 * 1024, file);
    (void) bytesRead;

    if (file != stdin) {
        fclose(file);
    }
}

/* -------------------------------------------------------------------------
 * Scripted input for deterministic / headless runs
 * -------------------------------------------------------------------------
 * HAL_input_load() reads a text file of button-event names (one per line):
 *   A, B, L, R, CLICK
 * Events are injected by HAL_event_poll() one at a time (one event per poll
 * call) then exhausted.  Blank lines and unknown tokens are silently skipped.
 * This is minimal — enough to exercise button-driven game logic in tests.
 */

#define HAL_INPUT_MAX_EVENTS 256

static uint16_t hal_input_events[HAL_INPUT_MAX_EVENTS];
static int hal_input_count  = 0;
static int hal_input_cursor = 0;

void HAL_input_load(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "HAL_input_load: cannot open %s\n", path);
        exit(1);
    }

    char line[64];
    hal_input_count  = 0;
    hal_input_cursor = 0;

    while (fgets(line, sizeof(line), f) && hal_input_count < HAL_INPUT_MAX_EVENTS) {
        /* Strip trailing newline/whitespace */
        size_t len = strlen(line);
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r' || line[len - 1] == ' ')) {
            line[--len] = '\0';
        }

        uint16_t ev = 0;
        if (strcmp(line, "A") == 0) {
            ev = (uint16_t) (1u << GQ_EVENT_BUTTON_A);
        } else if (strcmp(line, "B") == 0) {
            ev = (uint16_t) (1u << GQ_EVENT_BUTTON_B);
        } else if (strcmp(line, "L") == 0) {
            ev = (uint16_t) (1u << GQ_EVENT_BUTTON_L);
        } else if (strcmp(line, "R") == 0) {
            ev = (uint16_t) (1u << GQ_EVENT_BUTTON_R);
        } else if (strcmp(line, "CLICK") == 0) {
            ev = (uint16_t) (1u << GQ_EVENT_BUTTON_CLICK);
        }

        if (ev != 0) {
            hal_input_events[hal_input_count++] = ev;
        }
    }
    fclose(f);
}

void HAL_event_poll() {
    /* If a scripted input sequence is loaded, drain it one event per poll. */
    if (hal_input_count > 0 && hal_input_cursor < hal_input_count) {
        s_gq_event |= hal_input_events[hal_input_cursor++];
        return;
    }

    /* Otherwise fall through to live X11 key polling (no-op in headless). */
    static char c;
    c = gfx_getKey(); // returns 0 if no key pressed, 1,2,3 for mouse buttons, or ascii code of keyboard character
    switch (c) {
        case 'a': // "left"
            GQ_EVENT_SET(GQ_EVENT_BUTTON_L);
            break;
        case 'd': // "right"
            GQ_EVENT_SET(GQ_EVENT_BUTTON_R);
            break;
        case 'l': // "a"
            GQ_EVENT_SET(GQ_EVENT_BUTTON_A);
            break;
        case 'k': // "b"
            GQ_EVENT_SET(GQ_EVENT_BUTTON_B);
            break;
        case 's': // "click"
            GQ_EVENT_SET(GQ_EVENT_BUTTON_CLICK);
            break;
    }
}

void HAL_sleep() {
    // Called exactly once per main()-loop iteration in every build
    // (headless or not), so this is the one place to count iterations for
    // --dump-leds's CSV `tick` column -- see leds_dump_tick_count above.
    // Placed before the #ifdef/return below so it's hit on every path.
    // Gated on leds_dump_file (like HAL_update_leds()'s row-write check) so
    // a run without --dump-leds pays no per-iteration cost for a counter
    // nothing reads.
    if (leds_dump_file) {
        leds_dump_tick_count++;
    }
#ifdef GQ_HEADLESS
    /* In headless mode, skip the 10ms timing loop entirely so that --ticks N
     * runs complete instantly without real-time delays. */
    return;
#else
    static uint8_t first_loop           = 1;
    static int32_t time_diff_us         = 0;
    static int32_t time_diff_us_catchup = 0;
    static struct timeval pre_event_loop, post_event_loop;

    // Although the actual badge/console uses an timer to use an interrupt-driven
    //  system tick, we'll simulate it here with a busy wait.
    //  Every time we exit this function, we'll record the "pre" event loop time,
    //  and every time we enter, we'll record a "post" event loop time.
    //  We'll use that to keep our time loop as close to 10ms as possible.

    // But if it's the first loop, just exit immediately.
    if (first_loop) {
        first_loop = 0;
        gettimeofday(&pre_event_loop, NULL);
        return;
    }
    gettimeofday(&post_event_loop, NULL);

    // The difference, in usecs, between the start of the last event loop and
    //  its end (measured based on when it entered and exited this function):
    time_diff_us = (post_event_loop.tv_sec - pre_event_loop.tv_sec) * 1000000 +
        (post_event_loop.tv_usec - pre_event_loop.tv_usec);

    if (time_diff_us < 10000) {
        // If the last event loop handler took less than 10ms, sleep for the difference
        uint32_t sleep_time = 10000 - time_diff_us;
        if (sleep_time > time_diff_us_catchup) {
            sleep_time -= time_diff_us_catchup;
            time_diff_us_catchup = 0;
        } else {
            time_diff_us_catchup -= sleep_time;
            sleep_time = 0;
        }
        usleep(sleep_time);
    } else {
        // Otherwise, don't sleep at all, but remember how much we were off by
        time_diff_us_catchup += time_diff_us - 10000;
    }

    // Now that we're done sleeping, it's time to enter a new event loop.
    //  Record the time that happened.
    gettimeofday(&pre_event_loop, NULL);
#endif /* GQ_HEADLESS */
}

#ifdef GQ_PERF_INSTRUMENT
/*
 * Emulator implementation of HAL_perf_now() -- see gq_perf.h for the full
 * timing-source design note, including what a firmware implementation must
 * provide (this is the emulator half only; the firmware side is a separate,
 * not-yet-done task in ccs_workspace/qc2024/).
 *
 * CLOCK_MONOTONIC is immune to wall-clock adjustments (NTP steps, etc.),
 * which matters for a duration measurement even though this build never
 * runs long enough in practice for that to bite. Scaled to whole
 * microseconds and truncated to uint32_t, matching gq_perf_time_t; this
 * wraps every ~71.6 minutes, which is fine per gq_perf.h's timer-width
 * note -- gq_perf_record()'s delta math only needs correctness across a
 * single measured interval, not across the whole process lifetime.
 */
gq_perf_time_t HAL_perf_now(void) {
    /* Cache the last successful reading. A bare 0 on clock_gettime() failure
     * is not actually benign here: gq_perf_record()'s delta math (see
     * gq_perf.h) is HAL_perf_now() - entry_time, so a lone 0 on either side
     * of an ENTER/EXIT pair underflows to a spurious ~UINT32_MAX-us duration
     * and poisons that section's max_us. Falling back to the last known-good
     * timestamp instead keeps a single (practically unreachable, but not
     * impossible) clock_gettime() failure from corrupting stats -- at worst
     * it slightly under/over-counts one interval, which is an accepted
     * limitation for a development/measurement-only build (see gq_perf.h). */
    static gq_perf_time_t last_good_us = 0;
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return last_good_us;
    }
    last_good_us = (gq_perf_time_t) ((uint64_t) ts.tv_sec * 1000000u + (uint64_t) ts.tv_nsec / 1000u);
    return last_good_us;
}
#endif /* GQ_PERF_INSTRUMENT */
