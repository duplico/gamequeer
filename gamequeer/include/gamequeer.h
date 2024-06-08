#ifndef GAMEQUEER_H
#define GAMEQUEER_H

#include <grlib.h>
#include <stdint.h>

#define GQ_MAGIC_SIZE 4
#define GQ_MAGIC      "GQ01"
#define GQ_STR_SIZE   22

#define GQ_PTR_NS_MASK 0xFF000000
#define GQ_PTR_NS_NULL 0x00
#define GQ_PTR_NS_CART 0x01
#define GQ_PTR_NS_SAVE 0x02
#define GQ_PTR_NS_FRAM 0x03
#define GQ_PTR_NS_FBUF 0x04
#define GQ_PTR_BUILTIN 0x80

#define GQ_PTR_NS(POINTER)     ((POINTER & GQ_PTR_NS_MASK) >> 24)
#define GQ_PTR(NS, ADDR)       ((NS << 24) | ADDR)
#define GQ_PTR_ISNULL(POINTER) (GQ_PTR_NS(POINTER) == GQ_PTR_NS_NULL)

#define GQ_SCREEN_W 128
#define GQ_SCREEN_H 128

#define CART_FLASH_SIZE_MBYTES 16
#define SAVE_FLASH_SIZE_MBYTES 16

typedef uint32_t t_gq_pointer;

// TODO: Is packing like this unsafe on ARM?
typedef struct gq_header {
    uint8_t magic[GQ_MAGIC_SIZE]; // Magic number
    uint16_t id;                  // Numerical ID of the game
    char title[GQ_STR_SIZE];      // Game title, null-terminated
    uint16_t anim_count;          // Number of animations
    uint16_t stage_count;         // Number of stages
    t_gq_pointer starting_stage;  // Pointer to the starting stage
    uint16_t flags;               // TODO
    uint16_t crc16;               // CRC16 checksum of the header
} __attribute__((packed)) gq_header;

// TODO: Add variable table

typedef struct gq_anim {
    uint16_t id;                // Numerical ID of the animation (sequential, 0-based)
    uint16_t frame_count;       // Number of frames
    uint16_t frame_rate;        // TODO
    uint16_t flags;             // TODO
    uint8_t width;              // Width of the animation
    uint8_t height;             // Height of the animation
    t_gq_pointer frame_pointer; // Pointer to the first gq_anim_frame
} __attribute__((packed)) gq_anim;

typedef struct gq_anim_frame {
    uint8_t bPP;               // Bits per pixel and compression flags
    t_gq_pointer data_pointer; // Pointer to the frame data
    uint32_t data_size;        // Size of the frame data
} __attribute__((packed)) gq_anim_frame;

typedef enum gq_event_type {
    GQ_EVENT_ENTER = 0x00,
    GQ_EVENT_BUTTON_A,
    GQ_EVENT_BUTTON_B,
    GQ_EVENT_BUTTON_L,
    GQ_EVENT_BUTTON_R,
    GQ_EVENT_BUTTON_CLICK,
    GQ_EVENT_BGDONE,
    GQ_EVENT_MENU,
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
    t_gq_pointer menu_pointer;                   // Pointer to the menu definition for this stage
    t_gq_pointer event_commands[GQ_EVENT_COUNT]; // Event commands
} __attribute__((packed)) gq_stage;

extern Graphics_Context g_sContext;
extern uint8_t bg_animating;

uint8_t load_game();
uint8_t load_stage(t_gq_pointer stage_ptr);
uint8_t load_animation(t_gq_pointer anim_ptr);
uint8_t load_frame(t_gq_pointer frame_ptr);
uint8_t next_frame();

uint16_t handle_events();
void show_curr_frame();

#endif
