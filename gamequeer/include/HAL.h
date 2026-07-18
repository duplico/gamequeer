#ifndef _HAL_H
#define _HAL_H

#include "gamequeer.h"
#include <stdint.h>

uint8_t read_byte(t_gq_pointer ptr);
uint8_t write_byte(t_gq_pointer ptr, uint8_t value);

uint8_t gq_memcpy(t_gq_pointer dest, t_gq_pointer src, uint32_t size);
uint8_t gq_memcpy_to_ram(uint8_t *dest, t_gq_pointer src, uint32_t size);
uint8_t gq_memcpy_from_ram(t_gq_pointer dest, uint8_t *src, uint32_t size);
uint8_t gq_assign_int(t_gq_pointer dest, t_gq_int value);
t_gq_int gq_load_int(t_gq_pointer src);

void HAL_init(int argc, char *argv[]);

void HAL_update_leds();

void HAL_event_poll();
void HAL_sleep();
t_gq_int HAL_get_player_id();
void HAL_new_game();

/*
 * Load a button-event script for deterministic (headless) runs.
 * Each line of the file is one event name: A, B, L, R, CLICK.
 * Events are injected in order, one per HAL_event_poll() call.
 * Called by main() only when --input is given.
 */
void HAL_input_load(const char *path);

/*
 * Open a CSV file that will receive one row per HAL_update_leds() call (i.e.
 * every actual LED redraw) for the rest of the run -- see HAL_update_leds()
 * in HAL.c for the row format. Called by main() only when --dump-leds is
 * given, before the tick loop starts. Returns 1 on success, 0 if the file
 * couldn't be opened (main() should treat that as fatal, like the other
 * --dump*-family flags).
 */
int HAL_leds_dump_open(const char *path);

/*
 * Close and flush the CSV file opened by HAL_leds_dump_open(), if any.
 * Called by main() once after the tick loop ends.
 */
void HAL_leds_dump_close();

#endif
