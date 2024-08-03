import sys
import math
import struct
from collections import namedtuple
from enum import IntEnum

# NB: These definitions must be kept strictly in sync with the corresponding
#     structs defined in ../../../gamequeer/include/gamequeer.h

BADGES_ALLOWED = 320

GQ_STR_SIZE = 22
GQ_POINTER_SIZE = 4
T_GQ_POINTER_FORMAT = 'I'

GQ_MENU_MAX_OPTIONS = 6

GQ_PTR_NS_MASK = 0xFF000000
GQ_PTR_NS_NULL = 0x00
GQ_PTR_NS_CART = 0x01
GQ_PTR_NS_SAVE = 0x02
GQ_PTR_NS_FRAM = 0x03
GQ_PTR_NS_FBUF = 0x04
GQ_PTR_NS_HEAP = 0x05
GQ_PTR_BUILTIN_INT = 0x80
GQ_PTR_BUILTIN_STR = 0x81
GQ_PTR_BUILTIN_MENU_FLAGS = 0x82

GQ_MAGIC_SIZE = 4
GQ_MAGIC = b'GQ01'

namespace_overflow_warned = False
addr_wrong_namespace_warned = False

GQ_CRC_SEED = 0x9F2A

def crc16_update(crc : int, buf : bytes) -> int:
    for b in buf:
        crc = (0xFF & (crc >> 8)) | ((crc & 0xFF) << 8)
        crc ^= b
        crc ^= (crc & 0xFF) >> 4
        crc ^= 0xFFFF & ((crc << 8) << 4)
        crc ^= ((crc & 0xff) << 4) << 1
    return crc

def crc16_buf(sbuf : bytes) -> int:
    crc = GQ_CRC_SEED
    return crc16_update(crc, sbuf)

def gq_ptr_apply_ns(ns, ptr):
    if ns < 0 or ns > 0xFF:
        raise ValueError(f'Invalid namespace {ns}')
        
    global namespace_overflow_warned
    if ptr & GQ_PTR_NS_MASK and not namespace_overflow_warned:
        print(f"WARNING: Attempting to set namespace on pointer {ptr:x} with namespace already set.")
        print(f"         This can also occur in the case of a namespace overflow. It's likely that")
        print(f"         this code section has exceeded the allowable size.")
        print(f"         Additional warnings of this type will be suppressed.")
        namespace_overflow_warned = True

    return (ns << 24) | (ptr & 0x00FFFFFF)

def gq_ptr_get_ns(ptr):
    return (ptr & GQ_PTR_NS_MASK) >> 24

def gq_ptr_get_addr(ptr, expected_namespace=None):
    global addr_wrong_namespace_warned
    if expected_namespace is not None and gq_ptr_get_ns(ptr) != expected_namespace and not addr_wrong_namespace_warned:
        print(f'INTERNAL COMPILER WARNING: Expected namespace {expected_namespace}, got {gq_ptr_get_ns(ptr)}', file=sys.stderr)
        print(f'                           Additional warnings of this type will be suppressed.', file=sys.stderr)
        addr_wrong_namespace_warned = True

    return ptr & 0x00FFFFFF

T_GQ_INT_FORMAT = 'i'
GQ_INT_FORMAT = f'<{T_GQ_INT_FORMAT}'
GQ_INT_SIZE = struct.calcsize(GQ_INT_FORMAT)

# typedef struct gq_header {
#     uint8_t magic[GQ_MAGIC_SIZE]; // Magic number
#     uint16_t id;                  // Numerical ID of the game
#     char title[GQ_STR_SIZE];      // Game title, null-terminated
#     uint16_t anim_count;          // Number of animations
#     uint16_t stage_count;         // Number of stages
#     t_gq_pointer starting_stage;  // Pointer to the starting stage
#     t_gq_pointer startup_code;    // Pointer to the startup code.
#     t_gq_pointer persistent_vars; // Pointer to the persistent variables
#     t_gq_pointer persistent_crc16; // Pointer to the persistent variable section's CRC16
#     uint8_t color;                // Color of the game cartridge
#     uint8_t flags;                // TBD
#     uint16_t crc16;               // CRC16 checksum of the header
# } gq_header;
GqHeader = namedtuple('GqHeader', 'magic id title anim_count stage_count starting_stage_ptr startup_code_ptr persistent_var_ptr persistent_crc16_ptr color flags crc16')
GQ_HEADER_FORMAT = f'<{GQ_MAGIC_SIZE}sH{GQ_STR_SIZE}sHH{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}BBH'
GQ_HEADER_SIZE = struct.calcsize(GQ_HEADER_FORMAT)

# typedef struct gq_anim {
#     uint16_t id;                // Numerical ID of the animation (sequential, 0-based)
#     uint16_t frame_count;       // Number of frames
#     uint16_t ticks_per_frame;   // Ticks per frame
#     uint16_t flags;             // TBD
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
GQ_LEDCUE_FRAME_FORMAT = f'<HB{"BBB" * 5}'
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
    TIMER = 0x08
    FGDONE1 = 0x09
    FGDONE2 = 0x0A
    REFRESH = 0x0B

class OpCode(IntEnum):
    LOOP_NOP = 0x00
    DONE = 0x01
    GOSTAGE = 0x02
    PLAY = 0x03
    CUE = 0x04
    SETVAR = 0x05
    GOTO = 0x06
    ADDBY = 0x07
    SUBBY = 0x08
    MULBY = 0x09
    DIVBY = 0x0A
    MODBY = 0x0B
    EQ = 0x0C
    NE = 0x0D
    GT = 0x0E
    LT = 0x0F
    GE = 0x10
    LE = 0x11
    AND = 0x12
    OR = 0x13
    NOT = 0x14
    NEG = 0x15
    GOTOIFN = 0x16
    TIMER = 0x17
    BWAND = 0x18
    BWOR = 0x19
    BWXOR = 0x1A
    BWNOT = 0x1B
    BWSHL = 0x1C
    BWSHR = 0x1D
    QCGET = 0x1E
    QCSET = 0x1F
    QCCLR = 0x20
    STRCAT = 0x21

class OpFlags(IntEnum):
    NONE = 0x00
    TYPE_INT = 0x01
    TYPE_STR = 0x02
    LITERAL_ARG1 = 0x04
    LITERAL_ARG2 = 0x08

# Bytecode format:
# typedef struct gq_op {
#     uint8_t opcode;    // Opcode
#     uint8_t flags;     // Flags
#     t_gq_pointer arg1; // Argument 1
#     t_gq_pointer arg2; // Argument 2
# } __attribute__((packed)) gq_op;

GqOp = namedtuple('GqOp', 'opcode flags arg1 arg2')
GQ_OP_FORMAT = f'<BB{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}'
GQ_OP_FORMAT_LITERAL_ARGS = f'<BB{T_GQ_INT_FORMAT}{T_GQ_INT_FORMAT}'
GQ_OP_FORMAT_LITERAL_ARG1 = f'<BB{T_GQ_INT_FORMAT}{T_GQ_POINTER_FORMAT}'
GQ_OP_FORMAT_LITERAL_ARG2 = f'<BB{T_GQ_POINTER_FORMAT}{T_GQ_INT_FORMAT}'
GQ_OP_SIZE = struct.calcsize(GQ_OP_FORMAT)
assert struct.calcsize(GQ_OP_FORMAT_LITERAL_ARG1) == GQ_OP_SIZE and struct.calcsize(GQ_OP_FORMAT_LITERAL_ARG2) == GQ_OP_SIZE and struct.calcsize(GQ_OP_FORMAT_LITERAL_ARGS) == GQ_OP_SIZE

# typedef struct gq_stage {
#     uint16_t id;                                 // Numerical ID of the stage (sequential, 0-based)
#     t_gq_pointer anim_bg_pointer;                // Pointer to the background animation (NULL if none)
#     t_gq_pointer cue_bg_pointer;                 // Pointer to the background lighting cue (NULL if none)
#     t_gq_pointer menu_pointer;                   // Pointer to the menu definition for this stage
#     t_gq_pointer prompt_pointer;            // Pointer to the prompt for the menu
#     t_gq_pointer event_commands[GQ_EVENT_COUNT]; // Event commands
# } __attribute__((packed)) gq_stage;
GqStage = namedtuple('GqStage', 'id anim_bg_pointer cue_bg_pointer menu_pointer prompt_pointer event_commands')
GQ_STAGE_FORMAT = f'<H{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}{T_GQ_POINTER_FORMAT}{len(EventType)}{T_GQ_POINTER_FORMAT}'
GQ_STAGE_SIZE = struct.calcsize(GQ_STAGE_FORMAT)

GqReservedVariable = namedtuple('GqReservedVariable', 'name type description addr')

GQ_RESERVED_INTS = [
    GqReservedVariable('GQI_GAME_ID', 'int', 'ID of the game', 0x000000),
    GqReservedVariable('GQI_MENU_ACTIVE', 'int', 'Menu active', 0x000004),
    GqReservedVariable('GQI_MENU_VALUE', 'int', 'Menu selection', 0x000008),
    GqReservedVariable('GQI_GAME_COLOR', 'int', 'Color of the game cartridge', 0x00000C),
    GqReservedVariable('GQI_BGANIM_X', 'int', 'Background animation X', 0x000010),
    GqReservedVariable('GQI_BGANIM_Y', 'int', 'Background animation Y', 0x000014),
    GqReservedVariable('GQI_FGANIM1_X', 'int', 'Foreground animation 0 X', 0x000018),
    GqReservedVariable('GQI_FGANIM1_Y', 'int', 'Foreground animation 0 Y', 0x00001C),
    GqReservedVariable('GQI_FGMASK1_X', 'int', 'Foreground mask 0 X', 0x000020),
    GqReservedVariable('GQI_FGMASK1_Y', 'int', 'Foreground mask 0 Y', 0x000024),
    GqReservedVariable('GQI_FGANIM2_X', 'int', 'Foreground animation 1 X', 0x000028),
    GqReservedVariable('GQI_FGANIM2_Y', 'int', 'Foreground animation 1 Y', 0x00002c),
    GqReservedVariable('GQI_FGMASK2_X', 'int', 'Foreground mask 1 X', 0x000030),
    GqReservedVariable('GQI_FGMASK2_Y', 'int', 'Foreground mask 1 Y', 0x000034),
    GqReservedVariable('GQI_LABEL1_X', 'int', 'Label 1 X', 0x000038),
    GqReservedVariable('GQI_LABEL1_Y', 'int', 'Label 1 Y', 0x00003C),
    GqReservedVariable('GQI_LABEL2_X', 'int', 'Label 2 X', 0x000040),
    GqReservedVariable('GQI_LABEL2_Y', 'int', 'Label 2 Y', 0x000044),
    GqReservedVariable('GQI_LABEL3_X', 'int', 'Label 3 X', 0x000048),
    GqReservedVariable('GQI_LABEL3_Y', 'int', 'Label 3 Y', 0x00004C),
    GqReservedVariable('GQI_LABEL4_X', 'int', 'Label 4 X', 0x000050),
    GqReservedVariable('GQI_LABEL4_Y', 'int', 'Label 4 Y', 0x000054),
    GqReservedVariable('GQI_LABEL_FLAGS', 'int', 'Label flags', 0x000058),
    GqReservedVariable('GQI_PLAYER_ID', 'int', 'Player ID', 0x00005C),
]

GQ_RESERVED_STRS = [
    GqReservedVariable('GQS_GAME_NAME', 'str', 'Name of the game', 0x000000),
    GqReservedVariable('GQS_PLAYER_HANDLE', 'str', 'Player handle', GQ_STR_SIZE),
    GqReservedVariable('GQS_LABEL1', 'str', 'Label 1', 2 * GQ_STR_SIZE),
    GqReservedVariable('GQS_LABEL2', 'str', 'Label 2', 3 * GQ_STR_SIZE),
    GqReservedVariable('GQS_LABEL3', 'str', 'Label 3', 4 * GQ_STR_SIZE),
    GqReservedVariable('GQS_LABEL4', 'str', 'Label 4', 5 * GQ_STR_SIZE),
    GqReservedVariable('GQS_TEXTMENU_RESULT', 'str', 'Text menu result', 6 * GQ_STR_SIZE),
]

GQ_RESERVED_PERSISTENT = []

for i in range(math.ceil(BADGES_ALLOWED / (8 * GQ_INT_SIZE))):
    GQ_RESERVED_PERSISTENT.append(GqReservedVariable(f'GQ_PERSISTENT_BADGES_{i}.builtin', 'int', 0, 0x000000 + 8 * i * GQ_INT_SIZE))

GQ_REGISTERS_INT = [
    'GQ_RI0.reg', 'GQ_RI1.reg',
]

GQ_REGISTERS_STR = [
    'GQ_RS0.reg', 'GQ_RS1.reg',
]
