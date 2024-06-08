#ifndef GAMEQUEER_BYTECODE_H
#define GAMEQUEER_BYTECODE_H

#include <gamequeer.h>
#include <stdint.h>

typedef enum gq_op_flags {
    GQ_OPF_NONE = 0
} gq_opcode_flags;

typedef enum gq_op_code {
    GQ_OP_NOP     = 0x00,
    GQ_OP_DONE    = 0x01,
    GQ_OP_GOSTAGE = 0x02,
    GQ_OP_PLAYBG  = 0x03,
    GQ_OP_CUE     = 0x04, // TODO: Not implemented yet in gqc
    GQ_OP_COUNT
} gq_op_code;

// TODO: Technically we need to handle Endian-ness when deserializing
// though, most of our target platforms are little endian anyway, so
// maybe not critical

typedef struct gq_op {
    uint8_t opcode;    // Opcode
    uint8_t flags;     // Flags
    t_gq_pointer arg1; // Argument 1
    t_gq_pointer arg2; // Argument 2
} __attribute__((packed)) gq_op;

#endif
