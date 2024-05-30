import struct
from collections import namedtuple

# NB: These definitions must be kept strictly in sync with the corresponding
#     structs defined in ../../../gamequeer/include/gamequeer.h

GQ_STR_SIZE = 22
GQ_POINTER_SIZE = 4
T_GQ_POINTER_FORMAT = 'I'

GQ_PTR_NS_MASK = 0xFF000000
GQ_PTR_NS_NULL = 0x00
GQ_PTR_NS_CART = 0x01
GQ_PTR_NS_SAVE = 0x02
GQ_PTR_NS_FRAM = 0x03
GQ_PTR_NS_FBUF = 0x04
GQ_PTR_BUILTIN = 0x80

GQ_MAGIC_SIZE = 4
GQ_MAGIC = b'GQ01'

def gq_ptr_apply_ns(ns, ptr):
    return (ns << 24) | (ptr & 0x00FFFFFF)

def gq_ptr_get_ns(ptr):
    return (ptr & GQ_PTR_NS_MASK) >> 24

def gq_ptr_get_addr(ptr):
    return ptr & 0x00FFFFFF

# typedef struct gq_header {
#     uint8_t magic[GQ_MAGIC_SIZE]; // Magic number
#     uint16_t id;                  // Numerical ID of the game
#     char title[GQ_STR_SIZE];      // Game title, null-terminated
#     uint16_t anim_count;          // Number of animations
#     uint16_t stage_count;         // Number of stages
#     t_gq_pointer starting_stage;  // Pointer to the starting stage
#     uint16_t flags;               // TODO
#     uint16_t crc16;               // CRC16 checksum of the header
# } gq_header;
GqHeader = namedtuple('GqHeader', 'magic id title anim_count stage_count starting_stage_ptr flags crc16')
GQ_HEADER_FORMAT = f'<{GQ_MAGIC_SIZE}sH{GQ_STR_SIZE}sHH{T_GQ_POINTER_FORMAT}HH'
GQ_HEADER_SIZE = struct.calcsize(GQ_HEADER_FORMAT)

# typedef struct gq_anim {
#     uint16_t id;                // Numerical ID of the animation (sequential, 0-based)
#     uint16_t frame_count;       // Number of frames
#     uint16_t frame_rate;        // TODO
#     uint16_t flags;             // TODO
#     uint8_t width;              // Width of the animation
#     uint8_t height;             // Height of the animation
#     t_gq_pointer frame_pointer; // Pointer to the first gq_anim_frame
# } gq_anim;
GqAnim = namedtuple('GqAnim', 'id frame_count frame_rate flags width height frame_pointer')
GQ_ANIM_FORMAT = f'<HHHHBB{T_GQ_POINTER_FORMAT}'
GQ_ANIM_SIZE = struct.calcsize(GQ_ANIM_FORMAT)

# typedef struct gq_anim_frame {
#     uint8_t bPP;               // Bits per pixel and compression flags
#     t_gq_pointer data_pointer; // Pointer to the frame data
#     uint32_t data_size;        // Size of the frame data
# } gq_anim_frame;
GqAnimFrame = namedtuple('GqAnimFrame', 'bPP data_pointer data_size')
GQ_ANIM_FRAME_FORMAT = f'<B{T_GQ_POINTER_FORMAT}I'
GQ_ANIM_FRAME_SIZE = struct.calcsize(GQ_ANIM_FRAME_FORMAT)

# typedef struct gq_stage {
#     uint16_t id;                      // Numerical ID of the stage (sequential, 0-based)
#     t_gq_pointer anim_bg_pointer;     // Pointer to the background animation (NULL if none)
#     t_gq_pointer menu_pointer;        // Pointer to the menu definition for this stage
#     t_gq_pointer events_code_pointer; // Pointer to the events code
#     uint32_t events_code_size;        // Size of the events code
# } gq_stage;
GqStage = namedtuple('GqStage', 'id anim_bg_pointer menu_pointer events_code_pointer events_code_size')
GQ_STAGE_FORMAT = f'<H{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}I'
GQ_STAGE_SIZE = struct.calcsize(GQ_STAGE_FORMAT)
