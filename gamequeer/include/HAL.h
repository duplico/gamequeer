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

#endif
