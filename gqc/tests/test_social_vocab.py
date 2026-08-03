"""Social vocabulary suite for gqc (gamequeer#423, DEF CON sprint epic
gamequeer#419).

`cohort NAME = <lo>..<hi>;`, `have_met(id)`, `in_cohort(NAME, id)`,
`seen_self()`, and `count_seen()`/`count_seen(NAME)` are a first-class
desugaring over the *existing* badges-seen bitfield intrinsics
(`badge_get`/`badge_set`/`badge_count()`, gamequeer#387) -- FROZEN VM
CONTRACT, no new opcode, register, or on-cart struct. This mirrors
`test_badge_count.py`'s split: `test_grammar.py` covers accept/reject
grammar forms (including the reject-with-a-message cases: unknown cohort,
wrong arity); this module covers the actual op-stream shape each form
lowers to, plus the handful of cases specific to this feature
(`in_cohort()`'s constant folding, `count_seen(NAME)`'s `lo == 0`
optimization, `seen_self()`'s exact idiom shape).

Design notes for anyone extending this suite:
  - `have_met(id)` is implemented as a bare rename of `badge_get(id)` (see
    `IntExpression.get_result_symbol`'s `GqcHaveMetOperand` branch in
    `datamodel.py`), so its op-stream shape is asserted to be byte-for-byte
    identical to a hand-written `badge_get(id)`.
  - `count_seen()` (no argument) is literally the same `GqcBadgeCountOperand`
    marker `badge_count()` itself produces (see
    `parser.parse_count_seen_operand`), so its op-stream shape is asserted
    to be identical to `test_badge_count.py`'s own `badge_count()` shape
    pin.
  - `count_seen(NAME)` generalizes that loop with a compile-time `lo`
    offset (`IntExpression._emit_count_seen_range`); when `lo == 0` the
    offset-add is skipped, so its shape collapses to the exact same 9-op
    loop `badge_count()`/`count_seen()` use.
"""

from gqc import structs

from .opstream import one_event

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def game_with_stage(body: str, decls: str = "", cohorts: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level `cohort` declarations and
    a `volatile { ... }`-style decls block."""
    return f"{GAME_HEADER}{cohorts}\n{decls}\nstage start {{ event enter {{ {body} }} }}\n"


def _int_register_addrs() -> set:
    return {
        structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_HEAP, i * structs.GQ_INT_SIZE)
        for i in range(len(structs.GQ_REGISTERS_INT))
    }


# --- have_met(id): a bare rename of badge_get(id) ----------------------------


def test_have_met_op_stream_matches_badge_get(compile_gq):
    have_met_source = game_with_stage("x = have_met(y);", "volatile { int x = 0; int y = 0; }")
    badge_get_source = game_with_stage("x = badge_get(y);", "volatile { int x = 0; int y = 0; }")

    exit_code, stderr, out_dir = compile_gq(have_met_source, game_name="have_met")
    assert exit_code == 0, stderr
    have_met_ops = one_event((out_dir / "cmds.gqasm").read_text()).ops

    exit_code, stderr, out_dir = compile_gq(badge_get_source, game_name="badge_get")
    assert exit_code == 0, stderr
    badge_get_ops = one_event((out_dir / "cmds.gqasm").read_text()).ops

    assert [(op.name, op.flags, op.arg1, op.arg2) for op in have_met_ops] == [
        (op.name, op.flags, op.arg1, op.arg2) for op in badge_get_ops
    ]


def test_have_met_with_literal_argument_accepts(compile_gq):
    source = game_with_stage("x = have_met(42);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    qcget = next(op for op in ops if op.name == "QCGET")
    assert qcget.flags & structs.OpFlags.LITERAL_ARG2
    assert qcget.arg2 == 42


# --- in_cohort(NAME, id): range compare, folds when id is a literal ---------


def test_in_cohort_op_stream_shape(compile_gq):
    source = game_with_stage(
        "x = in_cohort(GUESTS, y);",
        cohorts="cohort GUESTS = 300..319;",
        decls="volatile { int x = 0; int y = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    # y is loaded into a register twice (once per side of the "&&" --
    # id_operand is referenced twice in the desugared range compare), then
    # GE/LE/AND, then the assignment's own final SETVAR.
    assert [op.name for op in ops] == [
        "SETVAR", "GE", "SETVAR", "LE", "AND", "SETVAR", "DONE",
    ]
    load_y_1, ge, load_y_2, le, op_and, final_setvar, _done = ops

    reg_addrs = _int_register_addrs()
    assert load_y_1.arg1 in reg_addrs and load_y_2.arg1 in reg_addrs
    assert load_y_1.arg1 != load_y_2.arg1  # distinct registers for each side

    assert ge.flags & structs.OpFlags.LITERAL_ARG2 and ge.arg2 == 300
    assert ge.arg1 == load_y_1.arg1
    assert le.flags & structs.OpFlags.LITERAL_ARG2 and le.arg2 == 319
    assert le.arg1 == load_y_2.arg1

    assert op_and.arg1 == ge.arg1
    assert op_and.arg2 == le.arg1

    assert not (final_setvar.flags & structs.OpFlags.LITERAL_ARG2)
    assert final_setvar.arg2 == op_and.arg1


def test_in_cohort_with_literal_id_folds_to_compile_time_constant(compile_gq):
    # id is a literal known to be inside the cohort's range -- the whole
    # in_cohort() call folds to the literal 1, exactly like any other
    # compile-time-constant expression (gamequeer#385) -- no GE/LE/AND ops
    # at all.
    source = game_with_stage(
        "x = in_cohort(GUESTS, 305);",
        cohorts="cohort GUESTS = 300..319;",
        decls="volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == ["SETVAR", "DONE"]
    setvar, _done = ops
    assert setvar.flags & structs.OpFlags.LITERAL_ARG2
    assert setvar.arg2 == 1


def test_in_cohort_with_literal_id_outside_range_folds_to_zero(compile_gq):
    source = game_with_stage(
        "x = in_cohort(GUESTS, 1);",
        cohorts="cohort GUESTS = 300..319;",
        decls="volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == ["SETVAR", "DONE"]
    setvar, _done = ops
    assert setvar.flags & structs.OpFlags.LITERAL_ARG2
    assert setvar.arg2 == 0


def test_in_cohort_combined_with_other_arithmetic_still_folds(compile_gq):
    # A literal-id in_cohort() nested inside a larger otherwise-foldable
    # expression folds all the way through, same as any other constant
    # subexpression (gamequeer#385).
    source = game_with_stage(
        "x = 1 + in_cohort(GUESTS, 305);",
        cohorts="cohort GUESTS = 300..319;",
        decls="volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == ["SETVAR", "DONE"]
    setvar, _done = ops
    assert setvar.flags & structs.OpFlags.LITERAL_ARG2
    assert setvar.arg2 == 2


def test_in_cohort_realistic_gate_idiom_compiles(compile_gq):
    # The realistic idiom from the gamequeer#423 issue: replaces a
    # hand-rolled "if (ID>=300 && ID<=319)" chain.
    source = game_with_stage(
        "if (in_cohort(GUESTS, GQI_PLAYER_ID)) { badge_set 63; }",
        cohorts="cohort GUESTS = 300..319;",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert "GE" in [op.name for op in ops]
    assert "LE" in [op.name for op in ops]
    assert "AND" in [op.name for op in ops]
    assert "QCSET" in [op.name for op in ops]


# --- seen_self(): the copy-pasted-verbatim idiom, desugared -----------------


def test_seen_self_op_stream_shape(compile_gq):
    source = game_with_stage("seen_self();")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    # if (badge_get(GQI_PLAYER_ID) == 0) { badge_set GQI_PLAYER_ID; }
    assert [op.name for op in ops] == ["QCGET", "EQ", "GOTOIFN", "QCSET", "DONE"]
    qcget, eq, gotoifn, qcset, _done = ops

    player_id_addr = structs.gq_ptr_apply_ns(structs.GQ_PTR_BUILTIN_INT, 0x00005C)
    assert not (qcget.flags & structs.OpFlags.LITERAL_ARG2)
    assert qcget.arg2 == player_id_addr

    assert eq.arg1 == qcget.arg1  # compares the badge_get() result register
    assert eq.flags & structs.OpFlags.LITERAL_ARG2 and eq.arg2 == 0

    assert not (gotoifn.flags & structs.OpFlags.LITERAL_ARG2)
    assert gotoifn.arg2 == eq.arg1  # tests the == result register
    assert gotoifn.arg1 == qcset.addr + structs.GQ_OP_SIZE  # skips past QCSET when false

    assert qcset.arg2 == player_id_addr


def test_seen_self_matches_hand_written_idiom(compile_gq):
    seen_self_source = game_with_stage("seen_self();")
    hand_written_source = game_with_stage(
        "if (badge_get(GQI_PLAYER_ID)==0) badge_set GQI_PLAYER_ID;"
    )

    exit_code, stderr, out_dir = compile_gq(seen_self_source, game_name="seen_self")
    assert exit_code == 0, stderr
    seen_self_ops = one_event((out_dir / "cmds.gqasm").read_text()).ops

    exit_code, stderr, out_dir = compile_gq(hand_written_source, game_name="hand_written")
    assert exit_code == 0, stderr
    hand_written_ops = one_event((out_dir / "cmds.gqasm").read_text()).ops

    assert [(op.name, op.flags, op.arg1, op.arg2) for op in seen_self_ops] == [
        (op.name, op.flags, op.arg1, op.arg2) for op in hand_written_ops
    ]


# --- count_seen(): identical to badge_count() --------------------------------


def test_count_seen_bare_op_stream_matches_badge_count(compile_gq):
    count_seen_source = game_with_stage("x = count_seen();", "volatile { int x = 0; }")
    badge_count_source = game_with_stage("x = badge_count();", "volatile { int x = 0; }")

    exit_code, stderr, out_dir = compile_gq(count_seen_source, game_name="count_seen")
    assert exit_code == 0, stderr
    count_seen_ops = one_event((out_dir / "cmds.gqasm").read_text()).ops

    exit_code, stderr, out_dir = compile_gq(badge_count_source, game_name="badge_count")
    assert exit_code == 0, stderr
    badge_count_ops = one_event((out_dir / "cmds.gqasm").read_text()).ops

    assert [(op.name, op.flags, op.arg1, op.arg2) for op in count_seen_ops] == [
        (op.name, op.flags, op.arg1, op.arg2) for op in badge_count_ops
    ]


# --- count_seen(NAME): a badge_count()-style loop bounded to [lo, hi] -------


def test_count_seen_range_op_stream_shape(compile_gq):
    source = game_with_stage(
        "x = count_seen(GUESTS);",
        cohorts="cohort GUESTS = 300..319;",
        decls="volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    # 2 init SETVARs (accumulator, counter), an 11-op bounded loop (GOTOIFN +
    # SUBBY + SETVAR-copy-idx + ADDBY-offset-by-lo + QCGET + ADDBY-accumulate
    # + GOTO-skip-false + break-GOTO + continue-GOTO), then the assignment's
    # own final SETVAR and the event's DONE.
    assert [op.name for op in ops] == [
        "SETVAR", "SETVAR",
        "GOTOIFN", "SUBBY", "SETVAR", "ADDBY", "QCGET", "ADDBY", "GOTO", "GOTO", "GOTO",
        "SETVAR", "DONE",
    ]
    (
        init_acc, init_idx,
        gotoifn, subby, copy_idx, addby_offset, qcget, addby_acc,
        goto_skip_false, goto_break, goto_continue,
        final_setvar, _done,
    ) = ops

    reg_addrs = _int_register_addrs()
    assert init_acc.arg1 in reg_addrs
    assert init_idx.arg1 in reg_addrs
    assert qcget.arg1 in reg_addrs
    assert len({init_acc.arg1, init_idx.arg1, qcget.arg1}) == 3  # only 3 registers, same as badge_count()

    assert init_acc.flags & structs.OpFlags.LITERAL_ARG2 and init_acc.arg2 == 0
    # hi - lo + 1 == 319 - 300 + 1 == 20 -- the cohort's own size, not
    # BADGES_ALLOWED.
    assert init_idx.flags & structs.OpFlags.LITERAL_ARG2 and init_idx.arg2 == 20

    assert not (gotoifn.flags & structs.OpFlags.LITERAL_ARG2)
    assert gotoifn.arg2 == init_idx.arg1

    assert subby.flags & structs.OpFlags.LITERAL_ARG2 and subby.arg2 == 1
    assert subby.arg1 == init_idx.arg1

    # bit_reg = idx_reg (copy), then bit_reg += lo -- the actual badge id.
    assert not (copy_idx.flags & structs.OpFlags.LITERAL_ARG2)
    assert copy_idx.arg2 == init_idx.arg1
    assert copy_idx.arg1 == qcget.arg1

    assert addby_offset.flags & structs.OpFlags.LITERAL_ARG2 and addby_offset.arg2 == 300
    assert addby_offset.arg1 == qcget.arg1

    # QCGET is self-referential (dst == src): badge_get(bit_reg) overwrites
    # bit_reg with the read result, safe because the VM reads src into a
    # local before writing dst (see gamequeer/src/bytecode.c).
    assert not (qcget.flags & structs.OpFlags.LITERAL_ARG2)
    assert qcget.arg1 == qcget.arg2

    assert addby_acc.arg1 == init_acc.arg1
    assert addby_acc.arg2 == qcget.arg1

    assert gotoifn.arg1 == goto_break.addr
    assert goto_skip_false.arg1 == goto_continue.addr
    assert goto_break.arg1 == goto_continue.addr + structs.GQ_OP_SIZE
    assert goto_continue.arg1 == gotoifn.addr

    assert not (final_setvar.flags & structs.OpFlags.LITERAL_ARG2)
    assert final_setvar.arg2 == init_acc.arg1


def test_count_seen_range_starting_at_zero_matches_badge_count_shape(compile_gq):
    # A cohort starting at badge id 0 skips the idx+lo offset computation
    # entirely (lo == 0 special-cased in IntExpression._emit_count_seen_range)
    # -- so its loop body collapses to the exact same shape badge_count()'s
    # own loop uses, just with a smaller BADGES_ALLOWED-replacement bound.
    source = game_with_stage(
        "x = count_seen(FOUNDERS);",
        cohorts="cohort FOUNDERS = 0..9;",
        decls="volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == [
        "SETVAR", "SETVAR",
        "GOTOIFN", "SUBBY", "QCGET", "ADDBY", "GOTO", "GOTO", "GOTO",
        "SETVAR", "DONE",
    ]
    init_acc, init_idx = ops[0], ops[1]
    assert init_idx.arg2 == 10  # hi - lo + 1 == 9 - 0 + 1


def test_count_seen_range_never_folds(compile_gq):
    # count_seen(NAME) reads live badge state, not a constant -- never
    # folds, even though lo/hi are themselves always compile-time constants
    # (same reasoning as badge_count(), gamequeer#387).
    source = game_with_stage(
        "x = count_seen(GUESTS) + 1;",
        cohorts="cohort GUESTS = 300..319;",
        decls="volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert "QCGET" in [op.name for op in ops]
