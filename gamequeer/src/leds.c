#include <stdint.h>

#include "HAL.h"
#include "gamequeer.h"

rgbcolor16_t gq_leds[5] = {
    0,
};
rgbdelta_t leds_delta[5];

gq_ledcue_frame_t leds_curr;
gq_ledcue_frame_t leds_next;

void led_tick() {
    // TODO: Do stuff
    uint8_t need_to_redraw = 0;

    if (need_to_redraw) {
        HAL_update_leds();
    }
}
