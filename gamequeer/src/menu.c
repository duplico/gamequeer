#include <stdint.h>
#include <string.h>

#include "gamequeer.h"

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
}

void draw_menu_text() {
    if (*menu_active != GQ_MENU_FLAG_TEXT_ENTRY)
        return;

    Graphics_Rectangle menu_background = {0, 0, 128, menu_offset_y + 20};
    Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
    Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);
    Graphics_fillRectangle(&g_sContext, &menu_background);
    Graphics_setForegroundColor(&g_sContext, GRAPHICS_COLOR_WHITE);
    Graphics_setBackgroundColor(&g_sContext, GRAPHICS_COLOR_BLACK);

    if (menu_current_prompt[0]) {
        Graphics_drawString(&g_sContext, menu_current_prompt, -1, 6, 3, 0);
    }

    // TODO: move:
    uint8_t textentry_ypos        = 48;
    uint8_t textentry_xpos        = 0;
    uint8_t textentry_curser_left = textentry_xpos + 6 * menu_option_selected;

    // First draw the entire string with a black background and white foreground
    Graphics_drawString(&g_sContext, menu_text_result, -1, textentry_xpos, textentry_ypos, 1);

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
        // Draw an arrow left and an arrow right at the ends of the vertical bars.
        // Left (at the top)
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
