#ifndef GAMEQUEER_H
#define GAMEQUEER_H

#include <grlib.h>
#include <stdint.h>

#define GQ_MAGIC_SIZE 4
#define GQ_MAGIC      "GQ01"
#define GQ_STR_SIZE   22
#define GQ_INT_SIZE   4

#define GQ_PTR_NS_MASK            0xFF000000
#define GQ_PTR_NS_NULL            0x00
#define GQ_PTR_NS_CART            0x01
#define GQ_PTR_NS_SAVE            0x02
#define GQ_PTR_NS_FRAM            0x03
#define GQ_PTR_NS_FBUF            0x04
#define GQ_PTR_NS_HEAP            0x05
#define GQ_PTR_BUILTIN_INT        0x80
#define GQ_PTR_BUILTIN_STR        0x81
#define GQ_PTR_BUILTIN_MENU_FLAGS 0x82

#define GQ_PTR_NS(POINTER)     ((POINTER & GQ_PTR_NS_MASK) >> 24)
#define GQ_PTR_ADDR(POINTER)   (POINTER & ~GQ_PTR_NS_MASK)
#define GQ_PTR(NS, ADDR)       ((NS << 24) | ADDR)
#define GQ_PTR_ISNULL(POINTER) (GQ_PTR_NS(POINTER) == GQ_PTR_NS_NULL)

#define GQ_SCREEN_W 128
#define GQ_SCREEN_H 128

#define CART_FLASH_SIZE_MBYTES 16
#define SAVE_FLASH_SIZE_MBYTES 16

#define MAX_CONCURRENT_ANIMATIONS 5
#define GQ_HEAP_SIZE              0x200

#define GQ_MENU_MAX_OPTIONS     6
#define GQ_MENU_FLAG_CHOICE     1
#define GQ_MENU_FLAG_TEXT_ENTRY 2

#define GQ_MENU_TEXT_MODE_CHAR 0
#define GQ_MENU_TEXT_MODE_POS  1

#define BADGES_ALLOWED 320

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

typedef uint32_t t_gq_pointer;
typedef int32_t t_gq_int;

typedef enum gq_menu_text_symbol_type {
    GQ_MENU_TEXT_SYMBOL_CAPS = 0x00,
    GQ_MENU_TEXT_SYMBOL_LOWER,
    GQ_MENU_TEXT_SYMBOL_NUM,
    GQ_MENU_TEXT_SYMBOL_SPECIAL,
    GQ_MENU_TEXT_SYMBOL_COUNT
} gq_menu_text_symbol_type;

typedef enum gq_game_color {
    GQ_COLOR_UNASSIGNED = 0x00,
    GQ_COLOR_BLACK,
    GQ_COLOR_WHITE,
    GQ_COLOR_RED,
    GQ_COLOR_ORANGE,
    GQ_COLOR_YELLOW,
    GQ_COLOR_GREEN,
    GQ_COLOR_BLUE,
    GQ_COLOR_PURPLE,
    GQ_COLOR_CYAN,
    GQ_COLOR_PINK,
    GQ_COLOR_BROWN,
    GQ_COLOR_GRAY,
    GQ_COLOR_LTGRAY,
    GQ_COLOR_COUNT
} gq_game_color;

typedef struct gq_header {
    uint8_t magic[GQ_MAGIC_SIZE]; // Magic number
    uint16_t id;                  // Numerical ID of the game
    char title[GQ_STR_SIZE];      // Game title, null-terminated
    uint16_t anim_count;          // Number of animations
    uint16_t stage_count;         // Number of stages
    t_gq_pointer starting_stage;  // Pointer to the starting stage
    t_gq_pointer startup_code;    // Pointer to the startup code.
    t_gq_pointer persistent_vars; // Pointer to the persistent variables
    uint8_t color;                // Color of the cartridge, as per gq_game_color - may be assigned at write-time.
    uint8_t flags;                // Reserved for future use
    uint16_t crc16;               // CRC16 checksum of the header
} __attribute__((packed)) gq_header;

typedef struct gq_anim {
    uint16_t id;                // Numerical ID of the animation (sequential, 0-based)
    uint16_t frame_count;       // Number of frames
    uint16_t ticks_per_frame;   // Number of 10ms system ticks each frame is shown for
    uint16_t flags;             // TBD
    uint8_t width;              // Width of the animation
    uint8_t height;             // Height of the animation
    t_gq_pointer frame_pointer; // Pointer to the first gq_anim_frame
} __attribute__((packed)) gq_anim;

typedef struct gq_anim_onscreen {
    uint16_t ticks;  // Number of ticks until the next frame
    uint16_t frame;  // Current frame
    uint16_t in_use; // Whether the animation is in use
    int16_t x;       // X position of the animation
    int16_t y;       // Y position of the animation
    gq_anim anim;    // Animation playing
} __attribute__((packed)) gq_anim_onscreen;

typedef struct gq_anim_frame {
    uint8_t bPP;               // Bits per pixel and compression flags
    t_gq_pointer data_pointer; // Pointer to the frame data
    uint32_t data_size;        // Size of the frame data
} __attribute__((packed)) gq_anim_frame;

typedef struct rgbcolor16_t {
    uint16_t r;
    uint16_t g;
    uint16_t b;
} __attribute__((packed)) rgbcolor16_t;

typedef struct rgbcolor8_t {
    uint8_t r;
    uint8_t g;
    uint8_t b;
} __attribute__((packed)) rgbcolor8_t;

// NOTE: This is specifically not packed, because it doesn't need to be
//       saved, so we'll just keep it in its native bit alignment.
typedef struct rgbdelta_t {
    int_fast32_t r;
    int_fast32_t g;
    int_fast32_t b;
} rgbdelta_t;

typedef struct gq_ledcue_frame_t {
    uint16_t duration; // Duration of the frame in ticks
    // Flags for the frame:
    uint8_t transition_smooth : 1; // Smoothly fade to the next frame
    rgbcolor8_t leds[5];
} __attribute__((packed)) gq_ledcue_frame_t;

typedef struct gq_ledcue_t {
    uint16_t frame_count; // Number of frames
    uint8_t loop  : 1;    // Whether the cue loops indefinitely
    uint8_t bgcue : 1;    // Whether the cue was invoked as a background cue
    t_gq_pointer frames;  // Pointer to the first frame
} __attribute__((packed)) gq_ledcue_t;

typedef enum gq_special_var_int {
    GQI_GAME_ID = 0x00,
    GQI_MENU_ACTIVE,
    GQI_MENU_VALUE,
    GQI_GAME_COLOR,
    GQI_BGANIM_X,
    GQI_BGANIM_Y,
    GQI_FGANIM1_X,
    GQI_FGANIM1_Y,
    GQI_FGMASK1_X,
    GQI_FGMASK1_Y,
    GQI_FGANIM2_X,
    GQI_FGANIM2_Y,
    GQI_FGMASK2_X,
    GQI_FGMASK2_Y,
    GQI_LABEL1_X,
    GQI_LABEL1_Y,
    GQI_LABEL2_X,
    GQI_LABEL2_Y,
    GQI_LABEL3_X,
    GQI_LABEL3_Y,
    GQI_LABEL4_X,
    GQI_LABEL4_Y,
    GQI_LABEL_FLAGS,
    GQI_PLAYER_ID,
    GQI_COUNT
} gq_special_var_int;

typedef enum gq_special_var_str {
    GQS_GAME_TITLE = 0x00,
    GQS_PLAYER_HANDLE,
    GQS_LABEL1,
    GQS_LABEL2,
    GQS_LABEL3,
    GQS_LABEL4,
    GQS_TEXTMENU_RESULT,
    GQS_COUNT
} gq_special_var_str;

typedef enum gq_event_type {
    GQ_EVENT_ENTER = 0x00,
    GQ_EVENT_BUTTON_A,
    GQ_EVENT_BUTTON_B,
    GQ_EVENT_BUTTON_L,
    GQ_EVENT_BUTTON_R,
    GQ_EVENT_BUTTON_CLICK,
    GQ_EVENT_BGDONE,
    GQ_EVENT_MENU,
    GQ_EVENT_TIMER,
    GQ_EVENT_FGDONE1,
    GQ_EVENT_FGDONE2,
    GQ_EVENT_REFRESH,
    GQ_EVENT_COUNT
} gq_event_type;

extern uint16_t s_gq_event;
#define GQ_EVENT_GET(event_type) ((0x0001 << event_type) & s_gq_event)
#define GQ_EVENT_SET(event_type) s_gq_event |= (0x0001 << event_type)
#define GQ_EVENT_CLR(event_type) s_gq_event &= ~(0x0001 << event_type)

typedef struct gq_event {
    t_gq_pointer commands_pointer; // Pointer to the commands
} __attribute__((packed)) gq_event;

typedef struct gq_stage {
    uint16_t id;                                 // Numerical ID of the stage (sequential, 0-based)
    t_gq_pointer anim_bg_pointer;                // Pointer to the background animation (NULL if none)
    t_gq_pointer cue_bg_pointer;                 // Pointer to the background lighting cue (NULL if none)
    t_gq_pointer menu_pointer;                   // Pointer to the menu definition for this stage
    t_gq_pointer prompt_pointer;                 // Pointer to the prompt for the menu
    t_gq_pointer event_commands[GQ_EVENT_COUNT]; // Event commands
} __attribute__((packed)) gq_stage;

typedef struct gq_menu_option {
    char label[GQ_STR_SIZE]; // Text of the menu option
    t_gq_int value;          // Value of the menu option
} __attribute__((packed)) gq_menu_option;

typedef struct gq_menu {
    t_gq_int option_count;    // Number of options in the menu
    gq_menu_option options[]; // options in the menu
} __attribute__((packed)) gq_menu;

extern Graphics_Context g_sContext;
extern uint8_t gq_heap[GQ_HEAP_SIZE];
extern rgbcolor16_t gq_leds[5];
extern gq_ledcue_t leds_cue;
extern uint8_t leds_animating;

extern uint8_t gq_builtin_ints[];
extern uint8_t gq_builtin_strs[];

extern uint8_t timer_active;
extern t_gq_int timer_interval;
extern t_gq_int timer_counter;

extern t_gq_int *menu_active;
extern char *menu_text_result;

void run_code(t_gq_pointer code_ptr);

void menu_close();

void draw_menu_choice();
void draw_menu_text();
uint8_t handle_event_menu_choice(uint16_t event_type);
uint8_t handle_event_menu_text(uint16_t event_type);
void menu_text_load(t_gq_pointer menu_prompt);
void menu_choice_load(t_gq_pointer menu_ptr, t_gq_pointer menu_prompt);

t_gq_int get_badge_word(t_gq_int badge_id);
void set_badge_bit(t_gq_int badge_id, t_gq_int value);
t_gq_int get_badge_bit(t_gq_int badge_id);

uint8_t load_game(uint8_t namespace);
uint8_t load_stage(t_gq_pointer stage_ptr);
uint8_t load_animation(uint8_t index, t_gq_pointer anim_ptr);
void system_tick();
void led_tick();
void led_play_cue(t_gq_pointer cue_ptr, uint8_t background);
void led_stop();
void handle_events();
void gq_draw_image(
    const Graphics_Context *context,
    t_gq_pointer image_bytes,
    int16_t bPP,
    int16_t width,
    int16_t height,
    t_gq_int x,
    t_gq_int y);

#endif
