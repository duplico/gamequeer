"""`badge_count()` intrinsic suite for gqc (gamequeer#387).

`badge_count()` is a nullary popcount over the 320-bit badges-seen bitfield
(`BADGES_ALLOWED` in `gqc/src/gqc/structs.py`, matching `BADGES_ALLOWED` in
the C VM's `gamequeer.h`). FROZEN VM CONTRACT: it lowers entirely to
*existing* bytecode -- a runtime `while (idx) { ... }` loop over the
existing `badge_get` opcode (`QCGET`), built from the same
`CommandLoop`/`CommandIf`/`CommandGoto`/`CommandArithmetic` machinery a
hand-written `.gq` `loop { }` statement already uses (see
`IntExpression._emit_badge_count`, `gqc/src/gqc/datamodel.py`) -- not an
unrolled `BADGES_ALLOWED`-times sequence and not a new opcode/register.

`test_grammar.py` covers accept/reject grammar forms;
`test_constant_folding.py` pins that `badge_count()` never folds. This
module covers the op-stream shape and the register-allocation/re-entrancy
behavior of embedding it inside a larger int expression -- including a real
gamequeer#387-shaped bug this feature's development uncovered and fixed:
gqc has a pre-existing "discard an already-built sub-expression and
re-derive it under the outer expression's own shared register pool"
mechanism (used for parenthesized sub-expressions, and for
`parser.parse_int_expression`'s same-precedence-chain left-fold), which was
harmless for every leaf/operator that existed before this feature (their
`resolve()` only ever depends on a `Variable`/`Stage` symbol-table lookup)
but broke for `badge_count()`, the first thing to put a
`CommandLoop`/break-or-continue-form `CommandGoto` inside int-expression
codegen (a discarded copy's `CommandGoto`s never get their real jump target
patched, and used to trip `linker.py`'s "is everything resolved?" sweep as
a false-positive FATAL error). See `commands.unregister_orphaned_commands`
for the fix. `test_badge_count_parenthesized_operand_compiles_once` and
`test_badge_count_leftmost_in_three_term_chain_compiles` below are direct
regression pins for that bug, not just feature coverage.
"""

from gqc import structs

from .opstream import one_event

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def game_with_stage(body: str, decls: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level declarations (e.g. a
    `volatile { ... }` block)."""
    return f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ {body} }} }}\n"


def assert_no_traceback(stderr: str):
    assert "Traceback" not in stderr, f"raw Python traceback leaked to stderr:\n{stderr}"


def _int_register_addrs() -> set:
    return {
        structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_HEAP, i * structs.GQ_INT_SIZE)
        for i in range(len(structs.GQ_REGISTERS_INT))
    }


# --- op-stream shape ----------------------------------------------------------


def test_badge_count_op_stream_shape(compile_gq):
    source = game_with_stage("x = badge_count();", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    # 2 init SETVARs (accumulator, counter), a 7-op `while (idx) { ... }`
    # loop (GOTOIFN + a 3-op true branch + GOTO-skip-false + break-GOTO +
    # the auto-appended continue-GOTO), then the assignment's own final
    # SETVAR copying the accumulator into x.
    assert [op.name for op in ops] == [
        "SETVAR", "SETVAR",
        "GOTOIFN", "SUBBY", "QCGET", "ADDBY", "GOTO", "GOTO", "GOTO",
        "SETVAR", "DONE",
    ]
    (
        init_acc, init_idx,
        gotoifn, subby, qcget, addby, goto_skip_false, goto_break, goto_continue,
        final_setvar, _done,
    ) = ops

    reg_addrs = _int_register_addrs()
    assert init_acc.arg1 in reg_addrs
    assert init_idx.arg1 in reg_addrs
    assert qcget.arg1 in reg_addrs
    assert len({init_acc.arg1, init_idx.arg1, qcget.arg1}) == 3  # 3 distinct registers

    assert init_acc.flags & structs.OpFlags.LITERAL_ARG2 and init_acc.arg2 == 0
    assert init_idx.flags & structs.OpFlags.LITERAL_ARG2 and init_idx.arg2 == structs.BADGES_ALLOWED

    # The loop condition is the raw counter register's own truthiness -- no
    # comparison opcode, which would need a 4th register just to hold the
    # comparison result without clobbering the counter itself (every
    # CommandArithmetic op, comparisons included, overwrites its own dst;
    # see IntExpression._emit_badge_count).
    assert not (gotoifn.flags & structs.OpFlags.LITERAL_ARG2)
    assert gotoifn.arg2 == init_idx.arg1

    assert subby.flags & structs.OpFlags.LITERAL_ARG2 and subby.arg2 == 1
    assert subby.arg1 == init_idx.arg1  # idx -= 1, in place

    assert not (qcget.flags & structs.OpFlags.LITERAL_ARG2)
    assert qcget.arg2 == init_idx.arg1  # badge_get(idx) -- a register index, not a literal one

    assert addby.arg1 == init_acc.arg1  # accumulates into the same register throughout
    assert addby.arg2 == qcget.arg1

    # GOTOIFN's false-branch target is the break-goto; the true branch's
    # own trailing GOTO skips past it to this iteration's end (the
    # continue-goto); break jumps past the *entire* loop (one GQ_OP_SIZE
    # past the continue-goto, gqc's actual loop-done address); continue
    # jumps back to the loop's own top (the GOTOIFN itself).
    assert gotoifn.arg1 == goto_break.addr
    assert goto_skip_false.arg1 == goto_continue.addr
    assert goto_break.arg1 == goto_continue.addr + structs.GQ_OP_SIZE
    assert goto_continue.arg1 == gotoifn.addr

    assert not (final_setvar.flags & structs.OpFlags.LITERAL_ARG2)
    assert final_setvar.arg2 == init_acc.arg1  # x = the accumulator register


def test_badge_count_bytecode_size_is_fixed_not_proportional_to_badges_allowed(compile_gq):
    # The whole point of the loop strategy over an unrolled one (see the
    # module docstring): badge_count()'s own bytecode is a small, *fixed*
    # 9 ops (90 bytes at GQ_OP_SIZE=10) regardless of BADGES_ALLOWED (320),
    # not ~2x BADGES_ALLOWED ops for an unrolled QCGET+ADDBY sequence.
    source = game_with_stage("x = badge_count();", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    # Everything except the assignment's own trailing SETVAR and the
    # event's final DONE belongs to badge_count() itself.
    badge_count_ops = ops[:-2]
    assert len(badge_count_ops) == 9
    assert len(badge_count_ops) < 2 * structs.BADGES_ALLOWED


# --- embedding inside a larger expression: register pressure and re-entrancy --


def test_badge_count_combined_with_binary_op_has_two_registers_free(compile_gq):
    source = game_with_stage("x = badge_count() + y;", "volatile { int x = 0; int y = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert sum(1 for op in ops if op.name == "QCGET") == 1


def test_badge_count_used_twice_in_one_expression_compiles(compile_gq):
    # Re-entrancy: two independent badge_count() evaluations in the same
    # expression, each with its own accumulator/counter/bit registers --
    # exactly fits gqc's 4-register int file (2 accumulators, this
    # expression's own peak of one call's 3 scratch registers while the
    # other's single surviving accumulator is still live).
    source = game_with_stage(
        "x = badge_count() + badge_count();", "volatile { int x = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert sum(1 for op in ops if op.name == "QCGET") == 2


def test_badge_count_long_left_associative_chain_compiles(compile_gq):
    # A left-associative chain of badge_count() calls never exceeds the
    # 4-register budget at any length: each call's own idx/bit scratch
    # registers free immediately after its loop is built, leaving only the
    # single running accumulator (1 register) live while the *next* call's
    # own 3 (accumulator/idx/bit) are allocated -- 1 + 3 = 4, regardless of
    # chain length. This also regression-pins the discard-and-rebuild fix
    # (see module docstring): a same-precedence chain longer than 3 tokens
    # routes every prefix through parser.parse_int_expression's left-fold,
    # which builds and discards an intermediate IntExpression for every
    # non-terminal prefix.
    source = game_with_stage(
        "x = badge_count() + badge_count() + badge_count() + badge_count();",
        "volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert sum(1 for op in ops if op.name == "QCGET") == 4


def test_badge_count_leftmost_in_three_term_chain_compiles(compile_gq):
    # Regression pin: badge_count() as the *left*most operand of a
    # same-precedence chain longer than 3 tokens -- this specific shape
    # used to crash with "FATAL: Unresolved symbols remain in command GOTO
    # 0x00000000" (the orphaned-discarded-copy bug; see module docstring)
    # before gamequeer#387's unregister_orphaned_commands fix.
    source = game_with_stage(
        "x = badge_count() + y + z;", "volatile { int x = 0; int y = 0; int z = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert sum(1 for op in ops if op.name == "QCGET") == 1


def test_badge_count_middle_of_three_term_chain_compiles(compile_gq):
    # Same regression as above, badge_count() in the *middle* position.
    source = game_with_stage(
        "x = y + badge_count() + z;", "volatile { int x = 0; int y = 0; int z = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert sum(1 for op in ops if op.name == "QCGET") == 1


def test_badge_count_parenthesized_operand_compiles_once(compile_gq):
    # Regression pin: explicit parenthesization forces gqc's grammar to
    # pre-build badge_count() as its own standalone IntExpression *before*
    # the outer "+" is even parsed (pyparsing's own recursive descent into
    # the parenthesized group) -- exactly the shape that used to trigger
    # the orphaned-discarded-copy bug (see module docstring). Also asserts
    # there's exactly one QCGET, not two -- i.e. the fix genuinely drops
    # the discarded copy rather than emitting it twice.
    source = game_with_stage("x = (badge_count()) + 1;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert sum(1 for op in ops if op.name == "QCGET") == 1


def test_badge_count_sibling_parenthesized_operands_compile(compile_gq):
    # Two independently-pre-built badge_count() sub-expressions combined
    # by an outer operator -- each one's own internal register allocation
    # started from an empty pool in isolation, so (before the fix) a naive
    # "reuse the discarded copy instead of rebuilding" approach would have
    # let the second one's internal temp-register reuse clobber the
    # first's still-unconsumed result (see
    # commands.unregister_orphaned_commands's docstring for why gqc
    # rebuilds under a shared pool instead of splicing).
    source = game_with_stage(
        "x = (badge_count()) + (badge_count());", "volatile { int x = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert sum(1 for op in ops if op.name == "QCGET") == 2


def test_badge_count_nested_pairs_exhausts_registers(compile_gq):
    # Two badge_count()-pair sub-expressions, each needing its own
    # transient 4-register peak while being (re)built under the *outer*
    # expression's shared pool, with the first pair's own accumulator
    # still live when the second pair starts -- 1 (first pair's surviving
    # accumulator) + up to 4 (second pair's own transient peak) exceeds
    # gqc's 4-register file. A clean diagnostic, not a crash or (worse) a
    # silent wrong answer -- same shape/precedent as
    # test_register_allocation_depth_5_exhausts_registers in
    # test_codegen.py.
    source = game_with_stage(
        "x = (badge_count() + badge_count()) + (badge_count() + badge_count());",
        "volatile { int x = 0; }",
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert_no_traceback(stderr)
    assert "No free registers available" in stderr


# --- realistic usage ----------------------------------------------------------


def test_badge_count_threshold_unlock_idiom_compiles(compile_gq):
    # The realistic idiom from the gamequeer#387 issue: gate content behind
    # a minimum number of distinct badges seen.
    source = game_with_stage(
        "if (badge_count() >= 5) { unlocked = 1; badge_set 63; }",
        "volatile { int unlocked = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert sum(1 for op in ops if op.name == "QCGET") == 1
    ge = next(op for op in ops if op.name == "GE")
    assert ge.flags & structs.OpFlags.LITERAL_ARG2
    assert ge.arg2 == 5
    assert "QCSET" in [op.name for op in ops]
