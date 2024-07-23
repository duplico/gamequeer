#ifndef GAMEQUEER_BYTECODE_H
#define GAMEQUEER_BYTECODE_H

#include <gamequeer.h>
#include <stdint.h>

typedef enum gq_op_flags {
    GQ_OPF_NONE         = 0,
    GQ_OPF_TYPE_INT     = 1,
    GQ_OPF_TYPE_STR     = 2,
    GQ_OPF_LITERAL_ARG1 = 4,
    GQ_OPF_LITERAL_ARG2 = 8,
} gq_opcode_flags;

typedef enum gq_op_code {
    GQ_OP_NOP     = 0x00,
    GQ_OP_DONE    = 0x01,
    GQ_OP_GOSTAGE = 0x02,
    GQ_OP_PLAY    = 0x03,
    GQ_OP_CUE     = 0x04,
    GQ_OP_SETVAR  = 0x05,
    GQ_OP_GOTO    = 0x06,
    GQ_OP_ADDBY   = 0x07,
    GQ_OP_SUBBY   = 0x08,
    GQ_OP_MULBY   = 0x09,
    GQ_OP_DIVBY   = 0x0A,
    GQ_OP_MODBY   = 0x0B,
    GQ_OP_EQ      = 0x0C,
    GQ_OP_NE      = 0x0D,
    GQ_OP_GT      = 0x0E,
    GQ_OP_LT      = 0x0F,
    GQ_OP_GE      = 0x10,
    GQ_OP_LE      = 0x11,
    GQ_OP_AND     = 0x12,
    GQ_OP_OR      = 0x13,
    GQ_OP_NOT     = 0x14,
    GQ_OP_NEG     = 0x15,
    GQ_OP_GOTOIFN = 0x16,
    GQ_OP_TIMER   = 0x17,
    GQ_OP_BWAND   = 0x18,
    GQ_OP_BWOR    = 0x19,
    GQ_OP_BWXOR   = 0x1A,
    GQ_OP_BWNOT   = 0x1B,
    GQ_OP_BWSHL   = 0x1C,
    GQ_OP_BWSHR   = 0x1D,
    GQ_OP_COUNT
} gq_op_code;

typedef struct gq_op {
    uint8_t opcode;    // Opcode
    uint8_t flags;     // Flags
    t_gq_pointer arg1; // Argument 1
    t_gq_pointer arg2; // Argument 2
} __attribute__((packed)) gq_op;

#endif
