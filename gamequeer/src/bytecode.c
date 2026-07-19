#include <stddef.h>
#include <string.h>

#include "HAL.h"
#include "gamequeer.h"
#include "gamequeer_bytecode.h"

// Zero-fills buf[from..buf_size), so that bytes beyond the NUL terminator
// don't carry stale stack contents when the whole buf_size-byte buffer is
// later copied out into VM memory (e.g. via gq_memcpy_from_ram).
static void gq_str_zero_pad(char *buf, size_t buf_size, size_t from) {
    while (from < buf_size) {
        buf[from++] = '\0';
    }
}

// Converts a signed 32-bit integer (`t_gq_int`) to a NUL-terminated decimal
// string, writing at most buf_size - 1 characters plus the terminator. This
// matches the truncation semantics of `snprintf` given a format specifier
// correctly widened for a 32-bit int (e.g. `%d`) -- not `%ld`, which this
// replaces and which is itself a varargs width mismatch for `int32_t` on
// LP64 hosts. Avoids pulling in TI's _printfi/div64u for the badge link.
static void gq_itoa(t_gq_int value, char *buf, size_t buf_size) {
    char digits[10]; // Max digits in a 32-bit magnitude (2147483648) is 10.
    size_t ndigits = 0;
    uint32_t uval;
    uint8_t negative = value < 0;
    size_t pos       = 0;

    if (buf_size == 0) {
        return;
    }

    if (negative) {
        // Negate via unsigned arithmetic to avoid signed overflow on INT32_MIN,
        // whose magnitude doesn't fit in a positive t_gq_int.
        uval = (uint32_t) (-(value + 1)) + 1u;
    } else {
        uval = (uint32_t) value;
    }

    if (uval == 0) {
        digits[ndigits++] = '0';
    } else {
        while (uval > 0) {
            digits[ndigits++] = (char) ('0' + (uval % 10));
            uval /= 10;
        }
    }

    if (negative && pos < buf_size - 1) {
        buf[pos++] = '-';
    }

    while (ndigits > 0 && pos < buf_size - 1) {
        buf[pos++] = digits[--ndigits];
    }

    buf[pos] = '\0';
    gq_str_zero_pad(buf, buf_size, pos + 1);
}

// Appends up to src_size bytes of the NUL-terminated string src onto dst,
// starting at *dst_pos, without writing past dst_size - 1 bytes of dst
// (leaving room for the terminator) or reading past src_size bytes of src.
// *dst_pos is updated to the new write position; the caller is responsible
// for NUL-terminating dst at *dst_pos once all fragments are appended.
static void gq_str_append_bounded(char *dst, size_t dst_size, size_t *dst_pos, const char *src, size_t src_size) {
    size_t i = 0;

    if (dst_size == 0) {
        return;
    }

    while (i < src_size && src[i] != '\0' && *dst_pos < dst_size - 1) {
        dst[*dst_pos] = src[i];
        (*dst_pos)++;
        i++;
    }
}

void run_arithmetic(gq_op *cmd) {
    t_gq_int arg1;
    t_gq_int arg2;
    t_gq_int result;

    if (cmd->opcode == GQ_OP_NOT || cmd->opcode == GQ_OP_NEG || cmd->opcode == GQ_OP_BWNOT) {
        // These operations only have arg2 as an operand; arg1 is the result.
        // No need to load anything to arg1 for a unary operation.
    } else {
        // All other operations have arg1 and arg2 as operands.
        gq_memcpy_to_ram((uint8_t *) &arg1, cmd->arg1, GQ_INT_SIZE);
    }
    if (!(cmd->flags & GQ_OPF_LITERAL_ARG2)) {
        gq_memcpy_to_ram((uint8_t *) &arg2, cmd->arg2, GQ_INT_SIZE);
    } else {
        arg2 = cmd->arg2;
    }

    switch (cmd->opcode) {
        case GQ_OP_ADDBY:
            result = arg1 + arg2;
            break;
        case GQ_OP_SUBBY:
            result = arg1 - arg2;
            break;
        case GQ_OP_MULBY:
            result = arg1 * arg2;
            break;
        case GQ_OP_DIVBY:
            result = arg1 / arg2;
            break;
        case GQ_OP_MODBY:
            result = arg1 % arg2;
            break;
        case GQ_OP_EQ:
            result = arg1 == arg2;
            break;
        case GQ_OP_NE:
            result = arg1 != arg2;
            break;
        case GQ_OP_GT:
            result = arg1 > arg2;
            break;
        case GQ_OP_LT:
            result = arg1 < arg2;
            break;
        case GQ_OP_GE:
            result = arg1 >= arg2;
            break;
        case GQ_OP_LE:
            result = arg1 <= arg2;
            break;
        case GQ_OP_AND:
            result = arg1 && arg2;
            break;
        case GQ_OP_OR:
            result = arg1 || arg2;
            break;
        case GQ_OP_NOT:
            result = !arg2;
            break;
        case GQ_OP_NEG:
            result = -arg2;
            break;
        case GQ_OP_BWNOT:
            result = ~arg2;
            break;
        case GQ_OP_BWAND:
            result = arg1 & arg2;
            break;
        case GQ_OP_BWOR:
            result = arg1 | arg2;
            break;
        case GQ_OP_BWXOR:
            result = arg1 ^ arg2;
            break;
        case GQ_OP_BWSHL:
            result = arg1 << arg2;
            break;
        case GQ_OP_BWSHR:
            result = arg1 >> arg2;
            break;
        case GQ_OP_QCGET:
            result = get_badge_bit(arg2);
            break;
        default:
            return;
    }

    gq_assign_int(cmd->arg1, result);
}

void run_code(t_gq_pointer code_ptr) {
    gq_op cmd;
    gq_op_code opcode;

    char result_str[GQ_STR_SIZE];
    char arg1_str[GQ_STR_SIZE];
    char arg2_str[GQ_STR_SIZE];

    if (GQ_PTR_ISNULL(code_ptr)) {
        return;
    }

    do {
        if (gq_game_unload_flag) {
            return;
        }
        // TODO: bounds checking for the code_ptr
        gq_memcpy_to_ram((uint8_t *) &cmd, code_ptr, sizeof(gq_op));
        opcode = (gq_op_code) cmd.opcode;

        switch (opcode) {
            case GQ_OP_DONE:
                break;
            case GQ_OP_NOP:
                break;
            case GQ_OP_GOSTAGE:
                load_stage(cmd.arg1);
                opcode = GQ_OP_DONE;
                break;
            case GQ_OP_PLAY:
                // TODO: check if it's literal
                load_animation(cmd.arg2, cmd.arg1);
                break;
            case GQ_OP_CUE:
                led_play_cue(cmd.arg1, 0);
                break;
            case GQ_OP_SETVAR: {
                // If this write targets one of the on-screen ("visual") builtin
                // variables (animation/label position, label text, label
                // flags), snapshot its current value first so we can tell,
                // after the write, whether anything actually changed. A
                // SETVAR that re-writes the same value it already held (e.g.
                // a timer handler that unconditionally re-sets a label every
                // tick) shouldn't force a full clear+render+flush -- see
                // gamequeer#265.
                uint8_t visual_write = (cmd.arg1 >= GQ_PTR(GQ_PTR_BUILTIN_INT, GQI_BGANIM_X * GQ_INT_SIZE) &&
                                        cmd.arg1 <= GQ_PTR(GQ_PTR_BUILTIN_INT, GQI_LABEL_FLAGS * GQ_INT_SIZE)) ||
                    (cmd.arg1 >= GQ_PTR(GQ_PTR_BUILTIN_STR, GQS_LABEL1 * GQ_STR_SIZE) &&
                     cmd.arg1 <= GQ_PTR(GQ_PTR_BUILTIN_STR, GQS_LABEL4 * GQ_STR_SIZE));
                // A str-typed write (including the int->str cast, which also
                // sets GQ_OPF_TYPE_STR) is GQ_STR_SIZE wide; a plain int
                // write is GQ_INT_SIZE wide. GQ_STR_SIZE is the larger of
                // the two, so it's big enough to hold either snapshot.
                size_t write_size = (cmd.flags & GQ_OPF_TYPE_STR) ? GQ_STR_SIZE : GQ_INT_SIZE;
                uint8_t old_value[GQ_STR_SIZE];
                if (visual_write) {
                    gq_memcpy_to_ram(old_value, cmd.arg1, write_size);
                }

                if (cmd.flags & GQ_OPF_TYPE_INT && cmd.flags & GQ_OPF_TYPE_STR) {
                    // If both STR and INT flags are set, this is a cast from int to str.
                    // TODO: This command is one of the danger zones. We have no type
                    //  introspection available in the interpreter, so we have to rely on
                    //  the compiler having generated good code. If it turns out that arg1
                    //  is an int, then an overflow is possible, because this code treats it
                    //  as a string.
                    // On the other hand, the opposite isn't terribly concerning. If arg1
                    //  is a string and arg2 is an int, then we'll probably print some garbage,
                    //  but it won't hurt anything.
                    if (cmd.flags & GQ_OPF_LITERAL_ARG2) {
                        gq_itoa((t_gq_int) cmd.arg2, result_str, GQ_STR_SIZE);
                    } else {
                        t_gq_int arg2_int = gq_load_int(cmd.arg2);
                        gq_itoa(arg2_int, result_str, GQ_STR_SIZE);
                    }
                    gq_memcpy_from_ram(cmd.arg1, (uint8_t *) result_str, GQ_STR_SIZE);
                } else if (cmd.flags & GQ_OPF_TYPE_INT) {
                    // If only the INT flag is set, this is an int to int assignment.
                    if (cmd.flags & GQ_OPF_LITERAL_ARG2) {
                        gq_assign_int(cmd.arg1, cmd.arg2);
                    } else {
                        gq_memcpy(cmd.arg1, cmd.arg2, GQ_INT_SIZE);
                    }
                } else if (cmd.flags & GQ_OPF_TYPE_STR) {
                    // If only the STR flag is set, this is a str to str assignment.
                    gq_memcpy(cmd.arg1, cmd.arg2, GQ_STR_SIZE);
                }
                // If we just wrote to a visual variable, and the value actually
                // changed, generate a screen refresh event. (If it's not a
                // visual variable, or the value is unchanged, no redraw is
                // needed.)
                if (visual_write) {
                    uint8_t new_value[GQ_STR_SIZE];
                    gq_memcpy_to_ram(new_value, cmd.arg1, write_size);
                    if (memcmp(old_value, new_value, write_size) != 0) {
                        GQ_EVENT_SET(GQ_EVENT_REFRESH);
                    }
                }

                break;
            }
            case GQ_OP_GOTO:
                code_ptr = cmd.arg1;
                // Skip the rest of this loop, as we've already loaded the next command.
                continue;
            case GQ_OP_ADDBY:
            case GQ_OP_SUBBY:
            case GQ_OP_MULBY:
            case GQ_OP_DIVBY:
            case GQ_OP_MODBY:
            case GQ_OP_EQ:
            case GQ_OP_NE:
            case GQ_OP_GT:
            case GQ_OP_LT:
            case GQ_OP_GE:
            case GQ_OP_LE:
            case GQ_OP_AND:
            case GQ_OP_OR:
            case GQ_OP_NOT:
            case GQ_OP_NEG:
            case GQ_OP_BWAND:
            case GQ_OP_BWOR:
            case GQ_OP_BWXOR:
            case GQ_OP_BWNOT:
            case GQ_OP_BWSHL:
            case GQ_OP_BWSHR:
            case GQ_OP_QCGET:
                run_arithmetic(&cmd);
                break;
            case GQ_OP_GOTOIFN: {
                // A literal arg2 *is* the condition value; a non-literal arg2 is
                // a variable address whose int value is the condition. Only the
                // latter goes through gq_load_int() -- treating a literal
                // condition's value as a memory address instead reads whatever
                // garbage happens to live there.
                t_gq_int cond;
                if (cmd.flags & GQ_OPF_LITERAL_ARG2) {
                    cond = cmd.arg2;
                } else {
                    cond = gq_load_int(cmd.arg2);
                }
                if (!cond) {
                    code_ptr = cmd.arg1;
                    // Skip the rest of this loop, as we've already loaded the next command.
                    continue;
                }
                break;
            }
            case GQ_OP_TIMER:
                if (cmd.flags & GQ_OPF_LITERAL_ARG2) {
                    timer_interval = cmd.arg2;
                } else {
                    timer_interval = gq_load_int(cmd.arg2);
                }

                if (timer_interval > 0) {
                    timer_active  = 1;
                    timer_counter = 0;
                } else {
                    timer_active = 0;
                }
                break;
            case GQ_OP_QCSET:
                if (cmd.flags & GQ_OPF_LITERAL_ARG2) {
                    set_badge_bit(cmd.arg2, 1);
                } else {
                    set_badge_bit(gq_load_int(cmd.arg2), 1);
                }
                break;
            case GQ_OP_QCCLR:
                if (cmd.flags & GQ_OPF_LITERAL_ARG2) {
                    set_badge_bit(cmd.arg2, 0);
                } else {
                    set_badge_bit(gq_load_int(cmd.arg2), 0);
                }
                break;
            case GQ_OP_STRCAT: {
                // TODO: Break out into a function, maybe?
                size_t result_len = 0;
                gq_memcpy_to_ram((uint8_t *) arg1_str, cmd.arg1, GQ_STR_SIZE);
                gq_memcpy_to_ram((uint8_t *) arg2_str, cmd.arg2, GQ_STR_SIZE);
                gq_str_append_bounded(result_str, GQ_STR_SIZE, &result_len, arg1_str, GQ_STR_SIZE);
                gq_str_append_bounded(result_str, GQ_STR_SIZE, &result_len, arg2_str, GQ_STR_SIZE);
                result_str[result_len] = '\0';
                gq_str_zero_pad(result_str, GQ_STR_SIZE, result_len + 1);
                gq_memcpy_from_ram(cmd.arg1, (uint8_t *) result_str, GQ_STR_SIZE);
                break;
            }
            default:
                gq_game_unload_flag = 1;
                break;
        }

        code_ptr += sizeof(gq_op);
    } while (cmd.opcode != GQ_OP_DONE);
}
