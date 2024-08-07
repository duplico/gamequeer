#include <stdio.h>

#include "HAL.h"
#include "gamequeer.h"
#include "gamequeer_bytecode.h"

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
            case GQ_OP_SETVAR:
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
                        snprintf(result_str, GQ_STR_SIZE, "%ld", (t_gq_int) cmd.arg2);
                    } else {
                        t_gq_int arg2_int = gq_load_int(cmd.arg2);
                        snprintf(result_str, GQ_STR_SIZE, "%ld", arg2_int);
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
                break;
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
            case GQ_OP_GOTOIFN:
                // If the condition is false, either because it's a literal false or the variable is 0,
                // jump to the specified address.
                if ((cmd.flags & GQ_OPF_LITERAL_ARG2 && !cmd.arg2) || !gq_load_int(cmd.arg2)) {
                    code_ptr = cmd.arg1;
                    // Skip the rest of this loop, as we've already loaded the next command.
                    continue;
                }
                break;
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
            case GQ_OP_STRCAT:
                // TODO: Break out into a function, maybe?
                gq_memcpy_to_ram((uint8_t *) arg1_str, cmd.arg1, GQ_STR_SIZE);
                gq_memcpy_to_ram((uint8_t *) arg2_str, cmd.arg2, GQ_STR_SIZE);
                snprintf(result_str, GQ_STR_SIZE, "%s%s", arg1_str, arg2_str);
                gq_memcpy_from_ram(cmd.arg1, (uint8_t *) result_str, GQ_STR_SIZE);
                break;
            default:
                gq_game_unload_flag = 1;
                break;
        }

        code_ptr += sizeof(gq_op);
    } while (cmd.opcode != GQ_OP_DONE);
}
