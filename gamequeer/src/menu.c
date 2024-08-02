#include <stdint.h>
#include <string.h>

#include "HAL.h"
#include "gamequeer.h"

// Positioning configuration
#define MENU_HINT_BAR_Y 95
#define MENU_HINT_A_X   116
#define MENU_HINT_A_Y   116
#define MENU_HINT_R     9

#define MENU_HINT_B_X (116 - MENU_HINT_R - 16)
#define MENU_HINT_B_Y MENU_HINT_A_Y

#define MENU_HINT_DDIAL_X      17
#define MENU_HINT_DDIAL_Y      MENU_HINT_A_X
#define MENU_HINT_DDIAL_R      11
#define MENU_HINT_DDIAL_ICON_R 5

#define MENU_HINT_CLICK_X  (MENU_HINT_DDIAL_X + MENU_HINT_DDIAL_R + MENU_HINT_DDIAL_ICON_R * 3)
#define MENU_HINT_CLICK_Y  MENU_HINT_DDIAL_Y
#define MENU_HINT_CLICK_RI 3

#define CURSOR_BOX_TOP               (textentry_ypos - 2)
#define CURSOR_BOX_LEFT              (textentry_curser_left)
#define CURSOR_BOX_BOTTOM            (textentry_ypos + 8 + 2)
#define CURSOR_BOX_RIGHT             (textentry_curser_left + 6)
#define CURSOR_BOX_LINE_ARROW_WIDTH  3
#define CURSOR_BOX_LINE_ARROW_HEIGHT 4
#define CURSOR_BOX_HLINE_LENGTH      6
#define CURSOR_BOX_VLINE_TOP         (CURSOR_BOX_TOP - 10)
#define CURSOR_BOX_VLINE_BOTTOM      (CURSOR_BOX_BOTTOM + 10)
#define CURSOR_BOX_VLINE_LEFT        (textentry_curser_left + 3)
#define CURSOR_BOX_HLINE_LEFT        (CURSOR_BOX_VLINE_LEFT - CURSOR_BOX_HLINE_LENGTH)
#define CURSOR_BOX_HLINE_RIGHT       (CURSOR_BOX_VLINE_LEFT + CURSOR_BOX_HLINE_LENGTH)

char *menu_text_result = (char *) &gq_builtin_strs[GQS_TEXTMENU_RESULT * GQ_STR_SIZE];
uint8_t menu_text_symbol_type;
uint8_t menu_current_buffer[GQ_INT_SIZE + GQ_MENU_MAX_OPTIONS * sizeof(gq_menu_option)];
gq_menu *menu_current = (gq_menu *) menu_current_buffer;

t_gq_int *menu_active = (t_gq_int *) &gq_builtin_ints[GQI_MENU_ACTIVE * GQ_INT_SIZE];
t_gq_int *menu_value  = (t_gq_int *) &gq_builtin_ints[GQI_MENU_VALUE * GQ_INT_SIZE];

char menu_current_prompt[GQ_STR_SIZE];
uint8_t menu_offset_y        = 0;
uint8_t menu_option_selected = 0;
uint8_t menu_text_mode       = 0;

void menu_text_select_last_in_class() {
    if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_CAPS) {
        menu_text_result[menu_option_selected] = 'Z';
    } else if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_LOWER) {
        menu_text_result[menu_option_selected] = 'z';
    } else if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_NUM) {
        menu_text_result[menu_option_selected] = '9';
    } else {
        menu_text_result[menu_option_selected] = '@';
    }
}

void menu_text_select_first_in_class() {
    if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_CAPS) {
        menu_text_result[menu_option_selected] = 'A';
    } else if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_LOWER) {
        menu_text_result[menu_option_selected] = 'a';
    } else if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_NUM) {
        menu_text_result[menu_option_selected] = '0';
    } else {
        menu_text_result[menu_option_selected] = ' ';
    }
}

void trim_menu_text_result() {
    // Clear any contents after the null terminator.
    uint8_t i                         = 0;
    uint8_t null_term_index           = GQ_STR_SIZE - 1;
    menu_text_result[GQ_STR_SIZE - 1] = '\0'; // Guarantee null termination
    while (menu_text_result[i] && i < GQ_STR_SIZE) {
        i++;
    }
    null_term_index = i;

    for (; i < GQ_STR_SIZE; i++) {
        menu_text_result[i] = '\0';
    }

    if (!null_term_index) {
        return;
    }

    // Trim any trailing spaces.
    for (i = null_term_index - 1; i > 0 && menu_text_result[i - 1] == ' '; i--) {
        menu_text_result[i - 1] = '\0';
    }
}

void menu_select_symbol_type_from_index() {
    if (menu_text_result[0] >= 'a' && menu_text_result[0] <= 'z') {
        menu_text_symbol_type = GQ_MENU_TEXT_SYMBOL_LOWER;
    } else if (menu_text_result[0] >= 'A' && menu_text_result[0] <= 'Z') {
        menu_text_symbol_type = GQ_MENU_TEXT_SYMBOL_CAPS;
    } else if (menu_text_result[0] >= '0' && menu_text_result[0] <= '9') {
        menu_text_symbol_type = GQ_MENU_TEXT_SYMBOL_NUM;
    } else {
        menu_text_symbol_type = GQ_MENU_TEXT_SYMBOL_SPECIAL;
    }
}

void menu_text_load(t_gq_pointer menu_prompt) {
    // Load the menu prompt into RAM.
    if (menu_prompt) {
        gq_memcpy_to_ram((uint8_t *) menu_current_prompt, menu_prompt, GQ_STR_SIZE);
        menu_offset_y = 18; // TODO: constant or something
    } else {
        menu_current_prompt[0] = '\0';
        menu_offset_y          = 0;
    }

    // Clear out any text after the null terminator, and trim any trailing spaces.
    trim_menu_text_result();

    if (menu_text_result[0]) {
        // If there's already text in the buffer, it's because the enter event set it.
        // We need to honor it.

        // Set the character entry type accordingly.
        menu_select_symbol_type_from_index();

    } else {
        menu_text_symbol_type = GQ_MENU_TEXT_SYMBOL_CAPS;
        menu_text_result[0]   = 'A';
    }

    // Initialize the menu options and activate it.
    menu_option_selected = 0;
    menu_text_mode       = GQ_MENU_TEXT_MODE_CHAR;
    *menu_active         = GQ_MENU_FLAG_TEXT_ENTRY;
    GQ_EVENT_SET(GQ_EVENT_REFRESH);
}

void menu_choice_load(t_gq_pointer menu_ptr, t_gq_pointer menu_prompt) {
    t_gq_int menu_option_count;
    t_gq_pointer menu_size;

    // Determine the size of the current menu based on its option count.
    gq_memcpy_to_ram((uint8_t *) &menu_option_count, menu_ptr, GQ_INT_SIZE);
    menu_size = GQ_INT_SIZE + menu_option_count * sizeof(gq_menu_option);

    // Load the menu into RAM.
    gq_memcpy_to_ram((uint8_t *) menu_current, menu_ptr, menu_size);

    // Load the menu prompt into RAM.
    if (menu_prompt) {
        gq_memcpy_to_ram((uint8_t *) menu_current_prompt, menu_prompt, GQ_STR_SIZE);
        menu_offset_y = 18; // TODO: constant or something
    } else {
        menu_current_prompt[0] = '\0';
        menu_offset_y          = 0;
    }

    // Initialize the menu options and activate it.
    menu_option_selected = 0;
    *menu_active         = GQ_MENU_FLAG_CHOICE;
    GQ_EVENT_SET(GQ_EVENT_REFRESH);
}

void menu_close() {
    *menu_active = 0;

    if (*menu_active) {
        GQ_EVENT_SET(GQ_EVENT_REFRESH);
    }
}

void draw_frame_bar(uint8_t y) {
    Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
    Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);
    Graphics_drawLineH(&g_sContext, 0, 127, y);
    Graphics_drawLineH(&g_sContext, 0, 127, y + 3);

    for (uint8_t i = 0; i < 128; i += 2) {
        Graphics_drawPixel(&g_sContext, i, y + 1);
        Graphics_drawPixel(&g_sContext, i + 1, y + 2);
    }
}

void draw_hint_bar() {
    Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
    Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);
    Graphics_Rectangle hint_bar = {0, MENU_HINT_BAR_Y, 127, 127};
    Graphics_fillRectangle(&g_sContext, &hint_bar);
    Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
    Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);
    draw_frame_bar(MENU_HINT_BAR_Y);
}

void draw_hint_a() {
    Graphics_drawCircle(&g_sContext, MENU_HINT_A_X, MENU_HINT_A_Y, MENU_HINT_R);
    Graphics_drawString(&g_sContext, "A", -1, MENU_HINT_A_X - MENU_HINT_R - 4, MENU_HINT_A_Y - MENU_HINT_R - 5, 0);
}

void draw_hint_ok() {
    // Draw a hint in the far bottom right of the screen showing that the A button is
    //  used to confirm a selection.
    draw_hint_a();
    Graphics_drawStringCentered(&g_sContext, "OK", -1, MENU_HINT_A_X + 1, MENU_HINT_A_Y, 0);
}

void draw_hint_b() {
    Graphics_drawCircle(&g_sContext, MENU_HINT_B_X, MENU_HINT_B_Y, MENU_HINT_R);
    Graphics_drawString(&g_sContext, "B", -1, MENU_HINT_B_X - MENU_HINT_R - 4, MENU_HINT_B_Y - MENU_HINT_R - 5, 0);
}

void draw_hint_b_text(char *text) {
    draw_hint_b();
    Graphics_drawStringCentered(&g_sContext, text, -1, MENU_HINT_B_X + 1, MENU_HINT_B_Y, 0);
}

void draw_hint_dial() {
    Graphics_drawCircle(&g_sContext, MENU_HINT_DDIAL_X, MENU_HINT_DDIAL_Y, MENU_HINT_R);

    // For the dial hint draw a circle with a plus in the middle
    Graphics_drawCircle(
        &g_sContext,
        MENU_HINT_DDIAL_X - MENU_HINT_DDIAL_R,
        MENU_HINT_DDIAL_Y - MENU_HINT_DDIAL_R,
        MENU_HINT_DDIAL_ICON_R);
    Graphics_drawLine(
        &g_sContext,
        MENU_HINT_DDIAL_X - MENU_HINT_DDIAL_R - MENU_HINT_DDIAL_ICON_R,
        MENU_HINT_DDIAL_Y - MENU_HINT_DDIAL_R,
        MENU_HINT_DDIAL_X - MENU_HINT_DDIAL_R + MENU_HINT_DDIAL_ICON_R,
        MENU_HINT_DDIAL_Y - MENU_HINT_DDIAL_R);
    Graphics_drawLine(
        &g_sContext,
        MENU_HINT_DDIAL_X - MENU_HINT_DDIAL_R,
        MENU_HINT_DDIAL_Y - MENU_HINT_DDIAL_R - MENU_HINT_DDIAL_ICON_R,
        MENU_HINT_DDIAL_X - MENU_HINT_DDIAL_R,
        MENU_HINT_DDIAL_Y - MENU_HINT_DDIAL_R + MENU_HINT_DDIAL_ICON_R);
}

void draw_updown(uint8_t x, uint8_t y) {
    // Draw an up arrow
    Graphics_drawLine(&g_sContext, x - 3, y - 3, x, y - 6);
    Graphics_drawLine(&g_sContext, x, y - 6, x + 3, y - 3);

    // And a down arrow below
    Graphics_drawLine(&g_sContext, x - 3, y + 3, x, y + 6);
    Graphics_drawLine(&g_sContext, x, y + 6, x + 3, y + 3);
}

void draw_leftright(uint8_t x, uint8_t y) {
    // Draw a left arrow
    Graphics_drawLine(&g_sContext, x - 3, y - 3, x - 6, y);
    Graphics_drawLine(&g_sContext, x - 6, y, x - 3, y + 3);

    // And a right arrow to the right
    Graphics_drawLine(&g_sContext, x + 3, y - 3, x + 6, y);
    Graphics_drawLine(&g_sContext, x + 6, y, x + 3, y + 3);
}

void draw_hint_dial_updown() {
    draw_hint_dial();
    draw_updown(MENU_HINT_DDIAL_X, MENU_HINT_DDIAL_Y);
}

void draw_hint_dial_leftright() {
    draw_hint_dial();
    draw_leftright(MENU_HINT_DDIAL_X, MENU_HINT_DDIAL_Y);
}

void draw_hint_click() {
    // Draw a hint in the next slot in the bottom of the screen, showing that the D-dial click
    //  is used for something.

    Graphics_drawCircle(&g_sContext, MENU_HINT_CLICK_X, MENU_HINT_CLICK_Y, MENU_HINT_R);
    Graphics_drawCircle(
        &g_sContext,
        MENU_HINT_CLICK_X - MENU_HINT_DDIAL_R,
        MENU_HINT_CLICK_Y - MENU_HINT_DDIAL_R,
        MENU_HINT_DDIAL_ICON_R);
    Graphics_fillCircle(
        &g_sContext, MENU_HINT_CLICK_X - MENU_HINT_DDIAL_R, MENU_HINT_CLICK_Y - MENU_HINT_DDIAL_R, MENU_HINT_CLICK_RI);
}

void draw_hint_click_updown() {
    draw_hint_click();
    draw_updown(MENU_HINT_CLICK_X, MENU_HINT_CLICK_Y);
}

void draw_hint_click_leftright() {
    draw_hint_click();
    draw_leftright(MENU_HINT_CLICK_X, MENU_HINT_CLICK_Y);
}

void draw_menu_choice() {
    if (*menu_active != GQ_MENU_FLAG_CHOICE)
        return;

    Graphics_Rectangle menu_background = {0, 0, 128, menu_offset_y + menu_current->option_count * 10};
    Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
    Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);
    Graphics_fillRectangle(&g_sContext, &menu_background);
    Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
    Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);

    if (menu_current_prompt[0]) {
        Graphics_drawString(&g_sContext, menu_current_prompt, -1, 6, 3, 0);
    }

    for (uint8_t i = 0; i < menu_current->option_count; i++) {
        Graphics_drawString(&g_sContext, menu_current->options[i].label, -1, 15, menu_offset_y + i * 10, 0);
        if (i == menu_option_selected) {
            Graphics_drawString(&g_sContext, ">", -1, 6, menu_offset_y + i * 10, 0);
        }
    }

    draw_frame_bar(menu_offset_y + menu_current->option_count * 10);

    draw_hint_bar();
    draw_hint_ok();
    draw_hint_dial_updown();
}

void draw_menu_text() {
    uint8_t textentry_ypos        = menu_offset_y + 8;
    uint8_t textentry_curser_left = 6 * menu_option_selected;

    if (*menu_active != GQ_MENU_FLAG_TEXT_ENTRY)
        return;

    Graphics_Rectangle menu_background = {0, 0, 128, CURSOR_BOX_VLINE_BOTTOM + 5};
    Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
    Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);
    Graphics_fillRectangle(&g_sContext, &menu_background);
    Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
    Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);

    draw_frame_bar(CURSOR_BOX_VLINE_BOTTOM + 2);

    if (menu_current_prompt[0]) {
        Graphics_drawString(&g_sContext, menu_current_prompt, -1, 6, 3, 0);
    }

    // First draw the entire string with a black background and white foreground
    Graphics_drawString(&g_sContext, menu_text_result, -1, 0, textentry_ypos, 1);

    // Now, draw the cursor box:
    Graphics_drawLineH(&g_sContext, CURSOR_BOX_LEFT, CURSOR_BOX_RIGHT, CURSOR_BOX_TOP);
    Graphics_drawLineH(&g_sContext, CURSOR_BOX_LEFT, CURSOR_BOX_RIGHT, CURSOR_BOX_BOTTOM);

    // Draw vertical bars above and below the cursor box
    Graphics_drawLine(&g_sContext, CURSOR_BOX_VLINE_LEFT, CURSOR_BOX_VLINE_TOP, CURSOR_BOX_VLINE_LEFT, CURSOR_BOX_TOP);
    Graphics_drawLine(
        &g_sContext, CURSOR_BOX_VLINE_LEFT, CURSOR_BOX_VLINE_BOTTOM, CURSOR_BOX_VLINE_LEFT, CURSOR_BOX_BOTTOM);

    // Draw a hint about what the d-dial will do, based on our text selection mode.
    if (menu_text_mode == GQ_MENU_TEXT_MODE_CHAR) {
        // Draw an arrow up and an arrow down at the ends of the vertical bars.
        // Up
        Graphics_drawLine(
            &g_sContext,
            CURSOR_BOX_VLINE_LEFT,
            CURSOR_BOX_VLINE_TOP,
            CURSOR_BOX_VLINE_LEFT - CURSOR_BOX_LINE_ARROW_WIDTH,
            CURSOR_BOX_VLINE_TOP + CURSOR_BOX_LINE_ARROW_HEIGHT);
        Graphics_drawLine(
            &g_sContext,
            CURSOR_BOX_VLINE_LEFT,
            CURSOR_BOX_VLINE_TOP,
            CURSOR_BOX_VLINE_LEFT + CURSOR_BOX_LINE_ARROW_WIDTH,
            CURSOR_BOX_VLINE_TOP + CURSOR_BOX_LINE_ARROW_HEIGHT);

        // Down
        Graphics_drawLine(
            &g_sContext,
            CURSOR_BOX_VLINE_LEFT,
            CURSOR_BOX_VLINE_BOTTOM,
            CURSOR_BOX_VLINE_LEFT - CURSOR_BOX_LINE_ARROW_WIDTH,
            CURSOR_BOX_VLINE_BOTTOM - CURSOR_BOX_LINE_ARROW_HEIGHT);
        Graphics_drawLine(
            &g_sContext,
            CURSOR_BOX_VLINE_LEFT,
            CURSOR_BOX_VLINE_BOTTOM,
            CURSOR_BOX_VLINE_LEFT + CURSOR_BOX_LINE_ARROW_WIDTH,
            CURSOR_BOX_VLINE_BOTTOM - CURSOR_BOX_LINE_ARROW_HEIGHT);
    } else {
        // TODO: Do we need left/right indicators?
    }

    // Now draw the hints.
    draw_hint_bar();
    draw_hint_ok();
    // TODO:
    // hint for the B button

    draw_hint_click();

    if (menu_text_mode == GQ_MENU_TEXT_MODE_CHAR) {
        draw_hint_dial_updown();
        draw_hint_click_leftright();
    } else {
        draw_hint_dial_leftright();
        draw_hint_click_updown();
    }

    if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_CAPS) {
        draw_hint_b_text("az");
    } else if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_LOWER) {
        draw_hint_b_text("09");
    } else if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_NUM) {
        draw_hint_b_text("$!");
    } else {
        draw_hint_b_text("AZ");
    }
}

uint8_t handle_event_menu_choice(uint16_t event_type) {
    switch (event_type) {
        case GQ_EVENT_BUTTON_A:
            // Select the current menu option
            *menu_value = menu_current->options[menu_option_selected].value;
            menu_close();
            GQ_EVENT_SET(GQ_EVENT_MENU);
            break;
        case GQ_EVENT_BUTTON_L:
            // Move the selection up
            if (menu_option_selected > 0) {
                menu_option_selected--;
                GQ_EVENT_SET(GQ_EVENT_REFRESH);
            }
            break;
        case GQ_EVENT_BUTTON_R:
            // Move the selection down
            if (menu_option_selected < menu_current->option_count - 1) {
                menu_option_selected++;
                GQ_EVENT_SET(GQ_EVENT_REFRESH);
            }
            break;
        default:
            return 0;
            break;
    }
    return 1;
}

uint8_t handle_event_menu_text(uint16_t event_type) {
    // NB: Text order is A-Z, a-z, 0-9, space, special characters ('!'--)
    switch (event_type) {
        case GQ_EVENT_BUTTON_A:
            // Confirm
            menu_close(); // Sets the refresh event
            GQ_EVENT_SET(GQ_EVENT_MENU);
            break;
        case GQ_EVENT_BUTTON_B:
            // Change the symbol type
            if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_CAPS) {
                menu_text_symbol_type = GQ_MENU_TEXT_SYMBOL_LOWER;
            } else if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_LOWER) {
                menu_text_symbol_type = GQ_MENU_TEXT_SYMBOL_NUM;
            } else if (menu_text_symbol_type == GQ_MENU_TEXT_SYMBOL_NUM) {
                menu_text_symbol_type = GQ_MENU_TEXT_SYMBOL_SPECIAL;
            } else {
                menu_text_symbol_type = GQ_MENU_TEXT_SYMBOL_CAPS;
            }
            menu_text_select_first_in_class();
            GQ_EVENT_SET(GQ_EVENT_REFRESH);
            break;
        case GQ_EVENT_BUTTON_L:
            if (menu_text_mode == GQ_MENU_TEXT_MODE_CHAR) {
                // Change the character at the current position to the previous one alphabetically
                if (menu_text_result[menu_option_selected] == 'A' || menu_text_result[menu_option_selected] == 'a' ||
                    menu_text_result[menu_option_selected] == '0' || menu_text_result[menu_option_selected] == '@') {
                    // time to wrap
                    menu_text_select_last_in_class();
                } else if (menu_text_result[menu_option_selected] == ':') {
                    // special case for the special characters that are divided by numerals in ASCII
                    menu_text_result[menu_option_selected] = '/';
                } else if (!menu_text_result[menu_option_selected]) {
                    menu_text_select_first_in_class();
                } else {
                    menu_text_result[menu_option_selected]--;
                }
            } else {
                trim_menu_text_result();
                // Move the selection left
                if (menu_option_selected > 0) {
                    menu_option_selected--;
                    menu_select_symbol_type_from_index();
                }
            }
            GQ_EVENT_SET(GQ_EVENT_REFRESH);
            break;
        case GQ_EVENT_BUTTON_R:
            if (menu_text_mode == GQ_MENU_TEXT_MODE_CHAR) {
                // Change the character at the current position to the next one alphabetically
                if (menu_text_result[menu_option_selected] == 'Z') {
                    menu_text_result[menu_option_selected] = 'A';
                } else if (menu_text_result[menu_option_selected] == 'z') {
                    menu_text_result[menu_option_selected] = 'a';
                } else if (menu_text_result[menu_option_selected] == '9') {
                    menu_text_result[menu_option_selected] = '0';
                } else if (menu_text_result[menu_option_selected] == '@') {
                    menu_text_result[menu_option_selected] = ' ';
                } else if (menu_text_result[menu_option_selected] == '/') {
                    menu_text_result[menu_option_selected] = ':';
                } else if (!menu_text_result[menu_option_selected]) {
                    menu_text_select_first_in_class();
                } else {
                    menu_text_result[menu_option_selected]++;
                }
                GQ_EVENT_SET(GQ_EVENT_REFRESH);
            } else {
                // Move the selection right

                // But, not past the null terminator.
                if (menu_text_result[menu_option_selected] == '\0') {
                    break;
                }

                if (menu_option_selected < GQ_STR_SIZE - 2) { // preserve null term
                    menu_option_selected++;
                    if (!menu_text_result[menu_option_selected] == '\0') {
                        menu_select_symbol_type_from_index();
                    }
                }
            }
            GQ_EVENT_SET(GQ_EVENT_REFRESH);
            break;
        case GQ_EVENT_BUTTON_CLICK:
            // Toggle the selection mode
            if (menu_text_mode == GQ_MENU_TEXT_MODE_CHAR) {
                menu_text_mode = GQ_MENU_TEXT_MODE_POS;
            } else {
                menu_text_mode = GQ_MENU_TEXT_MODE_CHAR;
            }
            GQ_EVENT_SET(GQ_EVENT_REFRESH);
            break;
        default:
            return 0;
    }
    return 1;
}
