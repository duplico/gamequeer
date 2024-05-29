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

#define GQ_PTR_NS(POINTER) ((POINTER & GQ_PTR_NS_MASK) >> 24)

typedef uint32_t t_gq_pointer;

typedef struct gq_header {
    uint8_t magic[GQ_MAGIC_SIZE]; // Magic number
    uint16_t id;                  // Numerical ID of the game
    char title[GQ_STR_SIZE];      // Game title, null-terminated
    uint16_t anim_count;          // Number of animations
    uint16_t stage_count;         // Number of stages
    t_gq_pointer starting_stage;  // Pointer to the starting stage
    uint16_t flags;               // TODO
    uint16_t crc16;               // CRC16 checksum of the header
} gq_header;

// TODO: Add variable table

typedef struct gq_anim {
    uint16_t id;                // Numerical ID of the animation (sequential, 0-based)
    uint16_t frame_count;       // Number of frames
    uint16_t frame_rate;        // TODO
    uint16_t flags;             // TODO
    uint8_t width;              // Width of the animation
    uint8_t height;             // Height of the animation
    t_gq_pointer frame_pointer; // Pointer to the first gq_anim_frame
} gq_anim;

typedef struct gq_anim_frame {
    uint8_t bPP;               // Bits per pixel and compression flags
    t_gq_pointer data_pointer; // Pointer to the frame data
    uint32_t data_size;        // Size of the frame data
} gq_anim_frame;

typedef struct gq_stage {
    uint16_t id;                      // Numerical ID of the stage (sequential, 0-based)
    t_gq_pointer anim_bg_pointer;     // Pointer to the background animation (NULL if none)
    t_gq_pointer menu_pointer;        // Pointer to the menu definition for this stage
    t_gq_pointer events_code_pointer; // Pointer to the events code
    uint32_t events_code_size;        // Size of the events code
} gq_stage;

#endif
