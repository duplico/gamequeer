#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "gamequeer.h"
#include "grlib_gfx.h"

uint8_t flash_cart[CART_FLASH_SIZE_MBYTES * 1024 * 1024];
uint8_t flash_save[SAVE_FLASH_SIZE_MBYTES * 1024 * 1024];
uint8_t flash_fram[512];

uint8_t read_byte(t_gq_pointer ptr) {
    switch (GQ_PTR_NS(ptr)) {
        case GQ_PTR_NS_CART:
            return flash_cart[ptr & ~GQ_PTR_NS_MASK];
        case GQ_PTR_NS_SAVE:
            return flash_save[ptr & ~GQ_PTR_NS_MASK];
        case GQ_PTR_NS_FRAM:
            return flash_fram[ptr & ~GQ_PTR_NS_MASK];
        case GQ_PTR_NS_FBUF:
            return 0; // TODO: Implement framebuffer
        default:
            return 0;
    }
}

uint8_t write_byte(t_gq_pointer ptr, uint8_t value) {
    switch (GQ_PTR_NS(ptr)) {
        case GQ_PTR_NS_CART:
            flash_cart[ptr & ~GQ_PTR_NS_MASK] = value;
            return 1;
        case GQ_PTR_NS_SAVE:
            flash_save[ptr & ~GQ_PTR_NS_MASK] = value;
            return 1;
        case GQ_PTR_NS_FRAM:
            flash_fram[ptr & ~GQ_PTR_NS_MASK] = value;
            return 1;
        case GQ_PTR_NS_FBUF:
            return 0; // TODO: Implement framebuffer
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

uint8_t gq_memcpy_ram(uint8_t *dest, t_gq_pointer src, uint32_t size) {
    for (t_gq_pointer i = 0; i < size; i++) {
        dest[i] = read_byte(src + i);
    }
    return 1;
}

void HAL_init(int argc, char *argv[]) {
    gfx_driver_init("Gamequeer");
    Graphics_initContext(&g_sContext, &g_gfx);

    // TODO: Load the binary file cart image from the command line
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
    // TODO: Validate the length in some other way:
    // if (bytesRead != CART_FLASH_SIZE_MBYTES * 1024 * 1024) {
    //     fprintf(stderr, "Error reading file: %s\n", filename);
    //     exit(1);
    // }
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
        case 'k': // "a"
            GQ_EVENT_SET(GQ_EVENT_BUTTON_A);
            break;
        case 'l': // "b"
            GQ_EVENT_SET(GQ_EVENT_BUTTON_B);
            break;
        case ' ': // "click"
            GQ_EVENT_SET(GQ_EVENT_BUTTON_CLICK);
            break;
    }
}

void HAL_sleep() {
    // TODO: Figure out how to emulate the badge sleep behavior
    usleep(30000);
}
