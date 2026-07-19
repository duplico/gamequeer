"""Codegen/bytecode op-stream suite for gqc (gamequeer#334, epic
gamequeer#329).

Every case here compiles a small `.gq` source through `compile_gq` (see
conftest.py) and asserts on the actual emitted op stream -- decoded from
`cmds.gqasm` via `opstream.py` (built from the same `gqc.structs.GqOp`
values the real bytecode serializes, see that module's docstring) or, for
the one case not visible there, from the real `.gqgame` binary's `gq_stage`
struct.

This complements, and doesn't replace or duplicate, `test_expressions.py`
(gamequeer#345's nested-parenthesization/register-exhaustion regressions)
and `test_statements.py` (gamequeer#356's literal-if-condition fix) -- their
cases aren't repeated here. Every assertion below was checked against gqc's
actual compiled output during development; none are aspirational.
"""

import io
import pathlib

import pytest

from gqc import linker, parser, structs
from gqc.commands import CommandDone, CommandSetInt, CommandSetStr

from .opstream import decode_stage_event_table, one_event, parse_gqasm
from .support import reset_compiler_state

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CIRCLE_BMP = REPO_ROOT / "gqc" / "examples" / "skel" / "assets" / "animations" / "circle.bmp"
FLASH_CUE = REPO_ROOT / "examples" / "assets" / "lighting" / "flash.gqcue"

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'

FIRST_STAGE_ADDR = structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_CART, structs.GQ_HEADER_SIZE)
SECOND_STAGE_ADDR = FIRST_STAGE_ADDR + structs.GQ_STAGE_SIZE


def game_with_stage(body: str, decls: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level declarations (e.g. a
    `volatile { ... }` block)."""
    return f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ {body} }} }}\n"


def assert_no_traceback(stderr: str):
    assert "Traceback" not in stderr, f"raw Python traceback leaked to stderr:\n{stderr}"


def _int_register_addrs() -> set:
    """The on-cart (heap-namespaced) addresses of gqc's `GQ_REGISTERS_INT`
    -- `structs.GQ_REGISTERS_INT` itself is a list of register *names*, not
    addresses, so op-stream assertions that compare against an `arg1`/`arg2`
    address need this instead."""
    return {
        structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_HEAP, i * structs.GQ_INT_SIZE)
        for i in range(len(structs.GQ_REGISTERS_INT))
    }


# --- precedence and associativity -------------------------------------------


def test_precedence_multiply_before_add(compile_gq):
    # 2 + 3 * 4: both operands of both operators are literals, so
    # gamequeer#385's constant folding collapses the entire expression to a
    # single literal (14, respecting '*' binding tighter than '+' -- a
    # naive left-to-right fold would wrongly give (2+3)*4 = 20) instead of
    # emitting any MULBY/ADDBY at all. Before gamequeer#385, this compiled
    # to a 6-op SETVAR/MULBY/SETVAR/ADDBY/SETVAR/DONE sequence; see
    # test_precedence_multiply_before_add_mixed_with_variable below for that
    # shape's still-live register-based-precedence coverage.
    source = game_with_stage("x = 2 + 3 * 4;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == ["SETVAR", "DONE"]
    setvar_x, _done = ops
    assert setvar_x.flags & structs.OpFlags.LITERAL_ARG2
    assert setvar_x.arg2 == 14


def test_precedence_multiply_before_add_mixed_with_variable(compile_gq):
    # Same precedence shape as above, but with a non-literal left operand
    # (y) so the expression can't fold away entirely -- '*' still binds
    # tighter than '+', so the literal-only "3 * 4" subtree folds to a
    # single literal 12 first (MULBY never appears in the op stream), and
    # only the outer "y + 12" survives as a real runtime add.
    source = game_with_stage("x = y + 3 * 4;", "volatile { int x = 0; int y = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == ["SETVAR", "ADDBY", "SETVAR", "DONE"]

    setvar_y, addby, setvar_x, _done = ops
    assert not (setvar_y.flags & structs.OpFlags.LITERAL_ARG2)  # loads y
    assert addby.flags & structs.OpFlags.LITERAL_ARG2
    assert addby.arg2 == 12  # the folded "3 * 4"
    assert addby.arg1 == setvar_y.arg1  # accumulates into y's own register
    assert setvar_x.arg2 == addby.arg1


def test_left_assoc_subtraction_chain_folds_left(compile_gq):
    # "10 - 5 - 2" is entirely literal, so gamequeer#385 folds it to a
    # single literal 3 -- (10 - 5) - 2, not the wrong right-assoc
    # 10 - (5 - 2) = 7 a naive fold could produce. Before gamequeer#385,
    # this compiled to a 4-op SETVAR/SUBBY/SUBBY/SETVAR/DONE sequence; see
    # test_left_assoc_subtraction_chain_mixed_with_variable_folds_left below
    # for that shape's still-live left-associativity coverage.
    source = game_with_stage("x = 10 - 5 - 2;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == ["SETVAR", "DONE"]
    setvar_x, _done = ops
    assert setvar_x.flags & structs.OpFlags.LITERAL_ARG2
    assert setvar_x.arg2 == 3


def test_left_assoc_subtraction_chain_mixed_with_variable_folds_left(compile_gq):
    # "10 - 5 - y" left-folds as (10 - 5) - y: the leftmost literal-only
    # pair ("10 - 5") folds to a single literal 5 first, and only the
    # trailing "5 - y" survives as a real runtime subtraction -- not
    # 10 - (5 - y), which would need a second register.
    source = game_with_stage("x = 10 - 5 - y;", "volatile { int x = 0; int y = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == ["SETVAR", "SUBBY", "SETVAR", "DONE"]

    setvar5, subby_y, setvar_x, _done = ops
    assert setvar5.flags & structs.OpFlags.LITERAL_ARG2 and setvar5.arg2 == 5
    assert not (subby_y.flags & structs.OpFlags.LITERAL_ARG2)  # subtracts y itself
    assert subby_y.arg1 == setvar5.arg1  # single accumulator throughout
    assert setvar_x.arg2 == setvar5.arg1


# --- unary operators ---------------------------------------------------------


def test_unary_neg_and_badge_get_qcget(compile_gq):
    # badge_get is QCGET with a LITERAL_ARG2 flag mask id; NEG's operand is
    # whatever variable/register it negates, referenced directly (not
    # loaded into a second register first, since NEG only has one operand).
    source = game_with_stage(
        "y = badge_get 1; x = -y;", "volatile { int x = 0; int y = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    qcget = next(op for op in ops if op.name == "QCGET")
    neg = next(op for op in ops if op.name == "NEG")

    assert qcget.flags & structs.OpFlags.LITERAL_ARG2
    assert qcget.arg2 == 1

    assert not (neg.flags & structs.OpFlags.LITERAL_ARG2)
    # NEG's arg1 is the destination register; arg2 is y's own address, not
    # a register -- unary ops don't need to pre-load their sole operand.
    assert neg.arg2 not in _int_register_addrs() and neg.arg2 != 0


# --- register allocation ------------------------------------------------------


def _balanced_sum_tree(depth: int, leaf: str = "1") -> str:
    """A fully-balanced binary tree of `+` operations, `depth` levels deep
    (e.g. depth 2, leaf "1" -> "((1+1)+(1+1))"). With a non-foldable `leaf`
    (a variable reference), each level of nesting needs one more
    concurrently-live register than the last (the left subtree's result
    register stays allocated across the right subtree's own evaluation), so
    this is a clean way to dial up register pressure independently of
    gamequeer#345's nested shift/or chains (see test_expressions.py) -- gqc
    has exactly 4 int registers (GQ_REGISTERS_INT).

    `leaf` defaults to a literal for gamequeer#385's own fold-away
    demonstration (see test_register_allocation_depth_5_literal_tree_folds_
    away_entirely below): register-pressure tests that want this shape's
    *register* behavior, not its foldability, must pass a variable name
    instead (e.g. `leaf="v"`)."""
    if depth == 0:
        return leaf
    half = _balanced_sum_tree(depth - 1, leaf)
    return f"({half}+{half})"


def test_register_allocation_depth_4_balanced_tree_compiles(compile_gq):
    # A depth-4 balanced tree has 2**4 - 1 = 15 '+' nodes, and exactly fits
    # gqc's 4-register int file at its peak (see
    # test_register_allocation_depth_5_exhausts_registers for one level
    # deeper, which doesn't fit). Uses a variable leaf, not a literal one --
    # gamequeer#385 folds an all-literal version of this shape away
    # entirely (see test_register_allocation_depth_5_literal_tree_folds_
    # away_entirely), which would defeat the point of a register-pressure
    # test.
    source = game_with_stage(
        f"x = {_balanced_sum_tree(4, leaf='v')};", "volatile { int x = 0; int v = 1; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert sum(1 for op in ops if op.name == "ADDBY") == 15

    touched_addrs = {op.arg1 for op in ops if op.name in ("SETVAR", "ADDBY")}
    # All 4 registers get touched somewhere in the course of the tree (the
    # final SETVAR stores the result into `x` itself, not a register, so
    # this is a subset check rather than equality).
    assert _int_register_addrs() <= touched_addrs


def test_register_allocation_depth_5_exhausts_registers(compile_gq):
    # One level deeper needs a 5th concurrently-live register, which
    # gqc doesn't have -- a clean diagnostic, not a crash. Variable leaf,
    # same reasoning as test_register_allocation_depth_4_balanced_tree_
    # compiles above.
    source = game_with_stage(
        f"x = {_balanced_sum_tree(5, leaf='v')};", "volatile { int x = 0; int v = 1; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert_no_traceback(stderr)
    assert "No free registers available" in stderr


def test_register_allocation_depth_5_literal_tree_folds_away_entirely(compile_gq):
    # gamequeer#385's register-pressure win, demonstrated directly: the
    # exact depth-5 all-literal shape that used to exhaust gqc's 4-register
    # int file (see test_register_allocation_depth_5_exhausts_registers,
    # which pins that same shape's *variable*-leaf equivalent still doing
    # so) now folds to a single literal at parse time, with no registers,
    # no ADDBY, and no compile error at all. 2**5 == 32.
    source = game_with_stage(f"x = {_balanced_sum_tree(5)};", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == ["SETVAR", "DONE"]
    setvar_x, _done = ops
    assert setvar_x.flags & structs.OpFlags.LITERAL_ARG2
    assert setvar_x.arg2 == 32


# --- setvar-int control-flow (gamequeer#338) -----------------------------------


def test_parse_command_setvar_bare_int_returns_command_set_int():
    # Not driven through compile_gq: parse_int_operand's own parse action
    # (gqc/src/gqc/parser.py) wraps every bare int atom in a GqcIntOperand
    # before parse_command ever sees it, so a plain Python `int` `src` for a
    # non-str setvar is dead through the real grammar. Before gamequeer#338,
    # that branch wrapped such a bare int in a GqcIntOperand and then fell
    # off the end of parse_command with no return, silently dropping the
    # statement (returning None) instead of the CommandSetInt it built the
    # operand for. Call parse_command directly, bypassing the grammar, to
    # exercise the fixed control flow as if a future grammar change let a
    # bare int through.
    reset_compiler_state()
    linker.create_reserved_variables()
    try:
        cmd = parser.parse_command("", 0, [["setvar", "x", 5, "int"]])
        assert isinstance(cmd, CommandSetInt)
        assert cmd.dst_name == "x"
    finally:
        reset_compiler_state()


# --- statement lowering --------------------------------------------------------


def test_timer_literal_interval(compile_gq):
    source = game_with_stage("timer 100;")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    timer_op = next(
        op for op in one_event((out_dir / "cmds.gqasm").read_text()).ops if op.name == "TIMER"
    )
    assert timer_op.flags & structs.OpFlags.LITERAL_ARG2
    assert timer_op.arg2 == 100


def test_gostage_resolves_to_target_stage_address(compile_gq):
    # Two stages, each `gostage`-ing the other: the emitted GOSTAGE arg1
    # must be the *other* stage's own resolved address, not (e.g.) its
    # first event's address. Stages are addressed sequentially, right after
    # the fixed-size header, in declaration order (no animations here).
    #
    # Both events are of type ENTER, so a leading badge_set marker (1 vs. 2)
    # is used to tell the two EventBlocks apart -- rather than relying on
    # parse_gqasm() happening to return them in declaration order, which
    # isn't a documented guarantee.
    source = (
        'game { id = 1; title := "T"; author := "A"; starting_stage = first; }\n'
        "stage first { event enter { badge_set 1; gostage second; } }\n"
        "stage second { event enter { badge_set 2; gostage first; } }\n"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    blocks = parse_gqasm((out_dir / "cmds.gqasm").read_text())
    assert len(blocks) == 2
    first_block = next(b for b in blocks if b.ops[0].arg2 == 1)
    second_block = next(b for b in blocks if b.ops[0].arg2 == 2)
    first_gostage = next(op for op in first_block.ops if op.name == "GOSTAGE")
    second_gostage = next(op for op in second_block.ops if op.name == "GOSTAGE")

    # "first" is declared first, so it's laid out immediately after the
    # header; "second" immediately after that.
    assert first_gostage.arg1 == SECOND_STAGE_ADDR
    assert second_gostage.arg1 == FIRST_STAGE_ADDR


@pytest.mark.ffmpeg
def test_play_slot_arg_encoding(compile_gq):
    # bganim/fganim(n)/fgmask(n) all lower to PLAY with the same opcode;
    # only arg2 (the animation slot index) distinguishes them. See
    # parse_play in gqc/src/gqc/parser.py for the index arithmetic.
    source = game_with_stage(
        "play bganim circ; play fganim(1) circ; play fganim(2) circ; "
        "play fgmask(1) circ; play fgmask(2) circ;",
        'animations { circ <- "circle.bmp"; }',
    )
    exit_code, stderr, out_dir = compile_gq(
        source, assets={"assets/animations/circle.bmp": CIRCLE_BMP}
    )
    assert exit_code == 0, stderr

    ops = [op for op in one_event((out_dir / "cmds.gqasm").read_text()).ops if op.name == "PLAY"]
    assert [op.arg2 for op in ops] == [0, 1, 3, 2, 4]
    # All target the same (only) animation.
    assert len({op.arg1 for op in ops}) == 1


@pytest.mark.ffmpeg
def test_play_fganim_slot_3_rejected(compile_gq):
    # Only fganim(1)/fganim(2) (and fgmask(1)/fgmask(2)) are valid -- slot 3
    # is out of range for the 4 combined fganim/fgmask slots.
    source = game_with_stage(
        "play fganim(3) circ;", 'animations { circ <- "circle.bmp"; }'
    )
    exit_code, stderr, _ = compile_gq(
        source, assets={"assets/animations/circle.bmp": CIRCLE_BMP}
    )
    assert exit_code != 0
    assert_no_traceback(stderr)
    assert "out of bounds" in stderr


def test_cue_resolves_a_nonzero_address(compile_gq):
    source = game_with_stage("cue flash;", 'lightcues { flash <- "flash.gqcue"; }')
    exit_code, stderr, out_dir = compile_gq(
        source, assets={"assets/lighting/flash.gqcue": FLASH_CUE}
    )
    assert exit_code == 0, stderr

    cue_op = next(
        op for op in one_event((out_dir / "cmds.gqasm").read_text()).ops if op.name == "CUE"
    )
    assert cue_op.flags == 0
    assert cue_op.arg1 != 0


def test_badge_set_literal_is_a_single_qcset(compile_gq):
    source = game_with_stage("badge_set 5;")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == ["QCSET", "DONE"]
    assert ops[0].flags & structs.OpFlags.LITERAL_ARG2
    assert ops[0].arg2 == 5


def test_badge_set_expression_computes_then_qcsets(compile_gq):
    # A non-literal badge_set argument must be evaluated into a register
    # first (like any other int expression), and QCSET then references
    # that register -- not a literal.
    source = game_with_stage("badge_set x + 1;", "volatile { int x = 7; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == ["SETVAR", "ADDBY", "QCSET", "DONE"]
    setvar, addby, qcset, _done = ops
    assert not (qcset.flags & structs.OpFlags.LITERAL_ARG2)
    assert qcset.arg2 == addby.arg1 == setvar.arg1


# --- if/else and loop control flow --------------------------------------------


def test_if_else_gotoifn_and_goto_layout(compile_gq):
    source = game_with_stage(
        "if (x > 0) { x = 1; } else { x = 2; } x = 99;",
        "volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    names = [op.name for op in ops]
    assert names == [
        "SETVAR", "GT", "GOTOIFN", "SETVAR", "GOTO", "SETVAR", "SETVAR", "DONE",
    ]
    _setvar_x, _gt, gotoifn, true_setvar, true_goto, false_setvar, after_setvar, _done = ops

    # GOTOIFN jumps to the false branch's first instruction when the
    # condition is false.
    assert gotoifn.arg1 == false_setvar.addr
    # The true branch ends with a GOTO past the false branch, landing on the
    # first statement after the whole if/else.
    assert true_goto.arg1 == after_setvar.addr
    assert true_setvar.arg2 == 1 and false_setvar.arg2 == 2 and after_setvar.arg2 == 99


def test_break_and_continue_targets_in_nested_loop(compile_gq):
    # An inner infinite loop (just "continue;") nested inside an outer loop
    # that breaks out on a condition. Regression-pins:
    #  - break's GOTO targets the address right after the *outer* loop, not
    #    the inner one.
    #  - continue (explicit or the implicit trailing per-loop repeat GOTO
    #    every `loop { ... }` gets) targets its *own* loop's start address.
    #  - the inner loop's body is *only* an explicit `continue;`, so gqc
    #    doesn't also emit its own implicit repeat GOTO behind it --
    #    that would be a dead, identically-targeted duplicate
    #    (gamequeer#379).
    source = game_with_stage(
        "loop { if (x == 3) { break; } loop { continue; } x = x + 1; }",
        "volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    names = [op.name for op in ops]
    # SETVAR/EQ/GOTOIFN (if x==3), GOTO (break), GOTO (explicit continue --
    # this *is* the inner loop's only repeat GOTO), SETVAR/ADDBY/SETVAR
    # (x+=1), GOTO (outer loop's own implicit repeat), DONE.
    assert names == [
        "SETVAR", "EQ", "GOTOIFN", "GOTO",
        "GOTO",
        "SETVAR", "ADDBY", "SETVAR",
        "GOTO", "DONE",
    ]
    (
        _setvar_x, _eq, _gotoifn, break_goto,
        inner_continue_goto,
        _setvar, _addby, _setvar_store,
        outer_repeat_goto, done,
    ) = ops

    outer_loop_start = _setvar_x.addr
    inner_loop_start = inner_continue_goto.addr

    assert break_goto.arg1 == done.addr  # right after the *outer* loop
    assert inner_continue_goto.arg1 == inner_loop_start
    assert outer_repeat_goto.arg1 == outer_loop_start


def test_loop_ending_in_bare_continue_emits_single_goto(compile_gq):
    # gamequeer#379: `loop { continue; }` used to compile to two identical,
    # consecutive, self-targeting GOTOs -- the user's explicit `continue;`
    # plus gqc's own implicit trailing repeat GOTO (the second unreachable).
    # A loop body whose last top-level statement is already an unconditional
    # `continue;` should only ever emit that one GOTO.
    source = game_with_stage("loop { continue; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    names = [op.name for op in ops]
    assert names == ["GOTO", "DONE"]
    goto, _done = ops
    assert goto.arg1 == goto.addr  # self-targeting


def test_loop_ending_in_conditional_continue_still_gets_repeat_goto(compile_gq):
    # A `continue;` nested inside a trailing `if` is conditional -- it only
    # fires when the branch is taken -- so it must NOT suppress the loop's
    # own unconditional trailing repeat GOTO (that would drop the fallthrough
    # path back to the loop start entirely). This guards the dedup added for
    # gamequeer#379 against over-triggering.
    source = game_with_stage(
        "loop { if (x == 1) { continue; } x = x + 1; }",
        "volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    names = [op.name for op in ops]
    # SETVAR/EQ/GOTOIFN (if x==1), GOTO (the `continue;` inside the if),
    # SETVAR/ADDBY/SETVAR (x+=1), GOTO (loop's own implicit repeat), DONE.
    assert names == [
        "SETVAR", "EQ", "GOTOIFN", "GOTO",
        "SETVAR", "ADDBY", "SETVAR",
        "GOTO", "DONE",
    ]
    (
        setvar_x, _eq, _gotoifn, conditional_continue_goto,
        _setvar, _addby, _setvar_store,
        repeat_goto, _done,
    ) = ops

    loop_start = setvar_x.addr
    assert conditional_continue_goto.arg1 == loop_start
    assert repeat_goto.arg1 == loop_start
    # Two distinct GOTO ops, both targeting the loop start -- not
    # deduplicated, since only one of them is guaranteed to execute.
    assert conditional_continue_goto.addr != repeat_goto.addr


def test_outer_loop_ending_in_bare_continue_dedups_only_its_own_goto(compile_gq):
    # The gamequeer#379 dedup must key off each loop's *own* last top-level
    # statement, independently, at every nesting level: an outer loop ending
    # in a bare `continue;` drops its own duplicate repeat GOTO, and an inner
    # loop nested earlier in its body -- also ending in a bare `continue;` --
    # independently drops its own.
    source = game_with_stage("loop { loop { continue; } continue; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    names = [op.name for op in ops]
    # GOTO (inner loop's sole, explicit, self-targeting continue), GOTO
    # (outer's sole, explicit, self-targeting continue), DONE.
    assert names == ["GOTO", "GOTO", "DONE"]
    inner_continue_goto, outer_continue_goto, _done = ops

    outer_loop_start = inner_continue_goto.addr  # outer's first instruction
    inner_loop_start = inner_continue_goto.addr  # == outer's, inner is first

    assert inner_continue_goto.arg1 == inner_loop_start
    assert outer_continue_goto.arg1 == outer_loop_start
    assert inner_continue_goto.addr != outer_continue_goto.addr


def test_implicit_done_termination(compile_gq):
    # Every event's statement list gets an implicit trailing DONE appended
    # (see Event.__init__ in gqc/src/gqc/datamodel.py), regardless of what
    # the last user statement was.
    source = game_with_stage("badge_set 1;")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert ops[-1].name == "DONE"


# --- volatile initialization ---------------------------------------------------


def test_volatile_init_code_shape():
    # Not driven through compile_gq: the .init section (unlike .event)
    # isn't printed to cmds.gqasm at all (see create_symbol_table in
    # gqc/src/gqc/linker.py), so this inspects the actual Command objects
    # gqc's linker builds, via the in-process pattern from tests/support.py.
    reset_compiler_state()
    linker.create_reserved_variables()
    source = (
        f"{GAME_HEADER}"
        'volatile { int x = 7; str s := "hi"; }\n'
        "stage start { event enter { x = 1; } }\n"
    )
    parser.parse(io.StringIO(source))
    symbol_table = linker.create_symbol_table(table_dest=io.StringIO(), cmd_dest=io.StringIO())
    init_cmds = list(symbol_table[".init"].values())

    n_int_regs = len(structs.GQ_REGISTERS_INT)
    n_str_regs = len(structs.GQ_REGISTERS_STR)

    # Reserved int registers first, literal-initialized to 0:
    for cmd in init_cmds[:n_int_regs]:
        assert isinstance(cmd, CommandSetInt)
        assert cmd.dst_name in structs.GQ_REGISTERS_INT
        assert cmd.command_flags & structs.OpFlags.LITERAL_ARG2
        assert cmd.arg2 == 0

    # Then the reserved string registers, initialized from a paired
    # persistent `.init` copy (not a literal -- strings can't be).
    for cmd in init_cmds[n_int_regs : n_int_regs + n_str_regs]:
        assert isinstance(cmd, CommandSetStr)
        assert cmd.dst_name in structs.GQ_REGISTERS_STR
        assert not (cmd.command_flags & structs.OpFlags.LITERAL_ARG2)

    # Then the user's own declared volatile variables, in declaration order.
    x_init = init_cmds[n_int_regs + n_str_regs]
    s_init = init_cmds[n_int_regs + n_str_regs + 1]
    assert isinstance(x_init, CommandSetInt) and x_init.dst_name == "x"
    assert x_init.command_flags & structs.OpFlags.LITERAL_ARG2 and x_init.arg2 == 7
    assert isinstance(s_init, CommandSetStr) and s_init.dst_name == "s"

    # Terminated by an implicit DONE, same as event code.
    assert isinstance(init_cmds[-1], CommandDone)


# --- event table -----------------------------------------------------------


def test_event_table_pointers_enum_order_unused_slots_zero(compile_gq):
    source = (
        f"{GAME_HEADER}"
        "stage start {\n"
        "  event timer { badge_set 1; }\n"
        "  event enter { badge_set 2; }\n"
        "  event input(A) { badge_set 3; }\n"
        "}\n"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    cmds_text = (out_dir / "cmds.gqasm").read_text()
    blocks = {b.event_type: b for b in parse_gqasm(cmds_text)}
    assert set(blocks) == {"ENTER", "BUTTON_A", "TIMER"}

    gqgame_bytes = (out_dir / "game.gqgame").read_bytes()
    event_commands = decode_stage_event_table(gqgame_bytes, anim_count=0)
    assert len(event_commands) == len(structs.EventType)

    for event_type in structs.EventType:
        slot = event_commands[event_type.value]
        if event_type.name in blocks:
            assert slot == blocks[event_type.name].addr
        else:
            assert slot == 0
