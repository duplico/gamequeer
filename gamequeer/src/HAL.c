#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <unistd.h>

#include "gamequeer.h"
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
            return 0;
    }
}

uint8_t gq_memcpy(t_gq_pointer dest, t_gq_pointer src, uint32_t size) {
    for (t_gq_pointer i = 0; i < size; i++) {
        if (!write_byte(dest + i, read_byte(src + i))) {
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

void HAL_update_leds() {
    for (uint8_t i = 0; i < 5; i++) {
        gfx_color(gq_leds[i].r >> 8, gq_leds[i].g >> 8, gq_leds[i].b >> 8);
        gfx_fillrect(0, i * LEDS_H, LEDS_W, i * LEDS_H + LEDS_H);
        gfx_fillrect(
            LEDS_W + OLED_HORIZONTAL_MAX, i * LEDS_H, LEDS_W + OLED_HORIZONTAL_MAX + LEDS_W, i * LEDS_H + LEDS_H);
    }
    gfx_flush();
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

    if (file != stdin) {
        fclose(file);
    }
}

void HAL_event_poll() {
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
}
