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

/*
 * Same redraw as HAL_update_leds(), except it must never block waiting on
 * driver hardware: on a target where the LED redraw path can be in flight
 * when this is called (e.g. a busy TLC5948A SPI transfer whose completion
 * interrupt is masked in the caller's context), an implementation may drop
 * this redraw instead of waiting. leds.c calls this instead of
 * HAL_update_leds() from led_tick() and the code paths reachable only
 * through it (led_anim_done()'s bg-restore and non-bg-cue-stop branches):
 * those are the sole call paths that run from the badge's RTC ISR, where a
 * blocking wait for an in-flight transfer could deadlock (the transfer's
 * own completion interrupt can't run until the RTC ISR returns). Every
 * other LED flush (led_stop() called directly, load_game()'s boot colors)
 * runs from ordinary main-loop context and keeps using HAL_update_leds().
 * On hosts with no such hazard (e.g. the emulator), this may simply be an
 * alias for HAL_update_leds().
 */
void HAL_update_leds_nonblocking();

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
