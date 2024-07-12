import struct
from collections import namedtuple
from enum import IntEnum

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
GQ_PTR_NS_HEAP = 0x05
GQ_PTR_BUILTIN = 0x80

GQ_MAGIC_SIZE = 4
GQ_MAGIC = b'GQ01'

def gq_ptr_apply_ns(ns, ptr):
    return (ns << 24) | (ptr & 0x00FFFFFF)

def gq_ptr_get_ns(ptr):
    return (ptr & GQ_PTR_NS_MASK) >> 24

def gq_ptr_get_addr(ptr):
    return ptr & 0x00FFFFFF

GQ_INT_FORMAT = '<i'
GQ_INT_SIZE = struct.calcsize(GQ_INT_FORMAT)

# typedef struct gq_header {
#     uint8_t magic[GQ_MAGIC_SIZE]; // Magic number
#     uint16_t id;                  // Numerical ID of the game
#     char title[GQ_STR_SIZE];      // Game title, null-terminated
#     uint16_t anim_count;          // Number of animations
#     uint16_t stage_count;         // Number of stages
#     t_gq_pointer starting_stage;  // Pointer to the starting stage
#     t_gq_pointer startup_code;    // Pointer to the startup code.
#     uint16_t flags;               // TODO
#     uint16_t crc16;               // CRC16 checksum of the header
# } gq_header;
GqHeader = namedtuple('GqHeader', 'magic id title anim_count stage_count starting_stage_ptr startup_code_ptr flags crc16')
GQ_HEADER_FORMAT = f'<{GQ_MAGIC_SIZE}sH{GQ_STR_SIZE}sHH{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}HH'
GQ_HEADER_SIZE = struct.calcsize(GQ_HEADER_FORMAT)

# typedef struct gq_anim {
#     uint16_t id;                // Numerical ID of the animation (sequential, 0-based)
#     uint16_t frame_count;       // Number of frames
#     uint16_t ticks_per_frame;   // TODO
#     uint16_t flags;             // TODO
#     uint8_t width;              // Width of the animation
#     uint8_t height;             // Height of the animation
#     t_gq_pointer frame_pointer; // Pointer to the first gq_anim_frame
# } gq_anim;
GqAnim = namedtuple('GqAnim', 'id frame_count ticks_per_frame flags width height frame_pointer')
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

# typedef struct rgbcolor16_t {
#     uint16_t r;
#     uint16_t g;
#     uint16_t b;
# } __attribute__((packed)) rgbcolor16_t;
RgbColor16 = namedtuple('RgbColor16', 'r g b')
RGB_COLOR16_FORMAT = '<HHH'
RGB_COLOR16_SIZE = struct.calcsize(RGB_COLOR16_FORMAT)

# typedef struct gq_ledcue_frame_t {
#     uint16_t duration; // Duration of the frame in ticks
#     uint8_t flags;    // Flags for the frame
#     rgbcolor8_t leds[5];
# } __attribute__((packed)) gq_ledcue_frame_t;
GqLedCueFrame = namedtuple('GqLedCueFrame', 'duration flags r0 g0 b0 r1 g1 b1 r2 g2 b2 r3 g3 b3 r4 g4 b4')
GQ_LEDCUE_FRAME_FORMAT = f'<HB{"BBB" * 5}' # TODO: pack these elsewhere
GQ_LEDCUE_FRAME_SIZE = struct.calcsize(GQ_LEDCUE_FRAME_FORMAT)

# typedef struct gq_ledcue_t {
#     uint16_t frame_count; // Number of frames
#     uint8_t flags;       // Flags for the cue
#     t_gq_pointer frames;  // Pointer to the first frame
# } __attribute__((packed)) gq_ledcue_t;
GqLedCue = namedtuple('GqLedCue', 'frame_count flags frames')
GQ_LEDCUE_FORMAT = f'<HB{T_GQ_POINTER_FORMAT}'
GQ_LEDCUE_SIZE = struct.calcsize(GQ_LEDCUE_FORMAT)

class LedCueFlags(IntEnum):
    NONE = 0x00
    LOOP = 0x01
    BGCUE = 0x02

class LedCueFrameFlags(IntEnum):
    NONE = 0x00
    TRANSITION_SMOOTH = 0x01

# typedef enum gq_event_type {
#     GQ_EVENT_ENTER = 0x00,
#     GQ_EVENT_BUTTON_A,
#     GQ_EVENT_BUTTON_B,
#     GQ_EVENT_BUTTON_L,
#     GQ_EVENT_BUTTON_R,
#     GQ_EVENT_BUTTON_CLICK,
#     GQ_EVENT_BGDONE,
#     GQ_EVENT_MENU,
#     GQ_EVENT_COUNT
# } gq_event_type;

class EventType(IntEnum):
    ENTER = 0x00
    BUTTON_A = 0x01
    BUTTON_B = 0x02
    BUTTON_L = 0x03
    BUTTON_R = 0x04
    BUTTON_CLICK = 0x05
    BGDONE = 0x06
    MENU = 0x07

# TODO: read this from the C header instead
class OpCode(IntEnum):
    NOP = 0x00
    DONE = 0x01
    GOSTAGE = 0x02
    PLAYBG = 0x03
    CUE = 0x04
    SETVAR = 0x05

class OpFlags(IntEnum):
    NONE = 0x00
    TYPE_INT = 0x01
    TYPE_STR = 0x02

# Bytecode format:
# typedef struct gq_op {
#     uint8_t opcode;    // Opcode
#     uint8_t flags;     // Flags
#     t_gq_pointer arg1; // Argument 1
#     t_gq_pointer arg2; // Argument 2
# } __attribute__((packed)) gq_op;

GqOp = namedtuple('GqOp', 'opcode flags arg1 arg2')
GQ_OP_FORMAT = f'<BB{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}'
GQ_OP_SIZE = struct.calcsize(GQ_OP_FORMAT)

# typedef struct gq_stage {
#     uint16_t id;                                 // Numerical ID of the stage (sequential, 0-based)
#     t_gq_pointer anim_bg_pointer;                // Pointer to the background animation (NULL if none)
#     t_gq_pointer cue_bg_pointer;                 // Pointer to the background lighting cue (NULL if none)
#     t_gq_pointer menu_pointer;                   // Pointer to the menu definition for this stage
#     t_gq_pointer event_commands[GQ_EVENT_COUNT]; // Event commands
# } __attribute__((packed)) gq_stage;
GqStage = namedtuple('GqStage', 'id anim_bg_pointer cue_bg_pointer menu_pointer event_commands')
GQ_STAGE_FORMAT = f'<H{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}{len(EventType)}{T_GQ_POINTER_FORMAT}'
GQ_STAGE_SIZE = struct.calcsize(GQ_STAGE_FORMAT)

GqReservedVariable = namedtuple('GqReservedVariable', 'name type description addr')

GQ_RESERVED_VARIABLES = [
    GqReservedVariable('GQ_game_name', 'str', 'Name of the game', 0x000000),
    GqReservedVariable('GQ_game_id', 'int', 'ID of the game', 0x000004),
    # TODO: Space available here
    GqReservedVariable('GQ_player_handle', 'str', 'Player handle', 0x00000C),
    GqReservedVariable('GQ_player_id', 'int', 'Player ID', 0x000010),
    GqReservedVariable('GQ_player_seen', 'int', 'Player seen', 0x000014),
    GqReservedVariable('GQ_menu_value', 'int', 'Menu selection', 0x000018),
    GqReservedVariable('GQ_menu_label', 'str', 'Menu label', 0x00001C),
    GqReservedVariable('GQ_text_input', 'str', 'Text input', 0x000020),
]
