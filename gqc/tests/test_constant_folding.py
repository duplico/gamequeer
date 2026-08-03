"""Compile-time constant-folding suite for gqc (gamequeer#385, epic
gamequeer#329).

`fold_constant_int_expression` (`gqc/src/gqc/datamodel.py`) folds an int
expression whose operands are all literals into a single literal at compile
time -- pure sugar lowering to fewer of the *same* existing bytecode ops
(FROZEN VM CONTRACT: no new opcodes/registers/format changes). This suite
covers the feature directly; `test_codegen.py` and `test_expressions.py`
carry the baseline-emission flips this feature caused in their own
previously-existing cases (each flip is commented in place there).

Folding policy, pinned here:
  - every operator (arithmetic, comparison, logical, bitwise, shift, unary)
    folds when all its operands are literals and the result is
    representable;
  - a literal-only *subtree* folds even inside an otherwise non-foldable
    expression (mixed literal/variable case) -- adjacent-as-parsed only, no
    reassociation across a non-literal operand;
  - `/`/`%` match the VM's C truncation semantics exactly (round toward
    zero; remainder takes the dividend's sign) -- not Python's own `//`/`%`,
    which floor instead and disagree with C whenever operand signs differ;
  - a literal `/`/`%` divisor of 0 never folds (the VM leaves this
    unguarded at runtime -- see `bytecode.c`'s `run_arithmetic` -- so
    folding it would turn a runtime behavior into either a compile-time
    crash or a silently wrong constant);
  - `badge_get` never folds, regardless of its operand -- it reads live
    badge state, not a constant; `badge_count()` (gamequeer#387), which has
    no operand at all, never folds for the same reason;
  - a result that wouldn't fit `t_gq_int` (signed 32-bit) is left unfolded
    (gqc does not replicate the target compiler's signed-overflow
    behavior), as is a `<<`/`>>` shift amount outside `[0, 31]` or a `<<`
    of a negative left-hand value (both undefined behavior in C).
"""

import pytest

from gqc import structs

from .opstream import one_event, parse_gqasm

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def game_with_stage(body: str, decls: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level declarations (e.g. a
    `volatile { ... }` block)."""
    return f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ {body} }} }}\n"


def assert_no_traceback(stderr: str):
    assert "Traceback" not in stderr, f"raw Python traceback leaked to stderr:\n{stderr}"


def _folded_setvar_value(cmds_text: str) -> int:
    """Assert `cmds_text`'s only real op is a single literal SETVAR (i.e.
    the whole expression folded to one constant) and return its value.
    `opstream.Op.arg2` is `int(token, 16)` on gqasm's own `-0x...`/`0x...`
    text, which already round-trips a negative `t_gq_int` correctly (the
    sign is part of the token), so no extra reinterpretation is needed
    here."""
    ops = one_event(cmds_text).ops
    assert [op.name for op in ops] == ["SETVAR", "DONE"]
    setvar, _done = ops
    assert setvar.flags & structs.OpFlags.LITERAL_ARG2
    return setvar.arg2


# --- every operator folds to a single literal --------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("3 + 4", 7),
        ("3 - 4", -1),
        ("3 * 4", 12),
        ("7 / 2", 3),
        ("7 % 2", 1),
        ("7 == 7", 1),
        ("7 == 8", 0),
        ("7 != 8", 1),
        ("7 > 8", 0),
        ("8 > 7", 1),
        ("7 < 8", 1),
        ("7 >= 7", 1),
        ("7 <= 6", 0),
        ("5 && 1", 1),
        ("5 && 0", 0),
        ("0 || 0", 0),
        ("3 || 0", 1),
        ("5 & 3", 1),
        ("5 | 2", 7),
        ("5 ^ 1", 4),
        ("1 << 4", 16),
        ("256 >> 4", 16),
        ("!0", 1),
        ("!5", 0),
        ("-5", -5),
        ("~5", -6),
        ("-(-8)", 8),
    ],
)
def test_literal_only_expression_folds_to_single_literal(compile_gq, expr, expected):
    source = game_with_stage(f"x = {expr};", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert _folded_setvar_value(cmds) == expected


# --- mixed literal/variable: only the literal subtree folds -------------------


def test_mixed_expression_folds_only_the_literal_subtree(compile_gq):
    # "2 * 3" is a literal-only subtree nested inside an otherwise
    # non-foldable expression -- it folds to 6 (MULBY never appears), and
    # only the outer "y + 6" survives as a real runtime add.
    source = game_with_stage("x = y + 2 * 3;", "volatile { int x = 0; int y = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "MULBY" not in cmds
    ops = one_event(cmds).ops
    assert [op.name for op in ops] == ["SETVAR", "ADDBY", "SETVAR", "DONE"]
    _setvar_y, addby, _setvar_x, _done = ops
    assert addby.flags & structs.OpFlags.LITERAL_ARG2
    assert addby.arg2 == 6


def test_mixed_expression_does_not_reassociate_across_a_variable(compile_gq):
    # "1 + y + 1" must NOT fold the two literal 1s together across the
    # intervening variable -- folding only ever touches an *adjacent*
    # literal-only subtree as parsed, never reassociates across a
    # non-literal operand. Left-folds as (1 + y) + 1: the leading "1" alone
    # isn't a foldable pair (nothing to fold it with yet), so it loads into
    # a register and both ADDBY ops survive as real runtime adds.
    source = game_with_stage("x = 1 + y + 1;", "volatile { int x = 0; int y = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    addby_ops = [op for op in ops if op.name == "ADDBY"]
    assert len(addby_ops) == 2
    assert not (addby_ops[0].flags & structs.OpFlags.LITERAL_ARG2)  # += y
    assert addby_ops[1].flags & structs.OpFlags.LITERAL_ARG2  # += 1
    assert addby_ops[1].arg2 == 1


# --- negative-operand division/modulo match C truncation, not Python -------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("-7 / 2", -3),   # C truncates -3.5 toward zero; Python's // floors to -4
        ("-7 % 2", -1),   # remainder takes the dividend's sign in C
        ("7 / -2", -3),
        ("7 % -2", 1),
        ("-7 / -2", 3),
        ("-7 % -2", -1),
    ],
)
def test_negative_operand_division_matches_c_truncation(compile_gq, expr, expected):
    # `expected` values above are hand-computed against C's truncate-
    # toward-zero `/` and dividend-signed `%` (see run_arithmetic in
    # bytecode.c) -- deliberately *not* Python's own `//`/`%`, which floor
    # instead and disagree with C on every one of these cases (e.g.
    # Python's `-7 // 2` is -4, not C's -3).
    source = game_with_stage(f"x = {expr};", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert _folded_setvar_value(cmds) == expected


# --- division/modulo by a literal zero never folds --------------------------


def test_division_by_literal_zero_not_folded(compile_gq):
    source = game_with_stage("x = 5 / 0;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    divby = next(op for op in ops if op.name == "DIVBY")
    assert divby.flags & structs.OpFlags.LITERAL_ARG2
    assert divby.arg2 == 0


def test_modulo_by_literal_zero_not_folded(compile_gq):
    source = game_with_stage("x = 5 % 0;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    modby = next(op for op in ops if op.name == "MODBY")
    assert modby.flags & structs.OpFlags.LITERAL_ARG2
    assert modby.arg2 == 0


def test_division_by_a_folded_literal_zero_still_not_folded(compile_gq):
    # The divisor itself is a folded literal-only subtree ("0 * 9" -> 0),
    # not a bare "0" token -- still must not fold the division.
    source = game_with_stage("x = 5 / (0 * 9);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    divby = next(op for op in ops if op.name == "DIVBY")
    assert divby.flags & structs.OpFlags.LITERAL_ARG2
    assert divby.arg2 == 0


def test_int32_min_divided_by_negative_one_does_not_fold(compile_gq):
    # The classic C division-overflow gotcha: INT32_MIN / -1 == 2147483648,
    # which doesn't fit t_gq_int (the positive magnitude of INT32_MIN has no
    # positive int32 representation) -- must decline to fold even though
    # neither operand alone is a problem and the divisor isn't 0. The inner
    # "-2147483647 - 1" (INT32_MIN) still folds correctly on its own; only
    # the outer "/ -1" against it is left as a real DIVBY.
    source = game_with_stage(
        "x = (-2147483647 - 1) / -1;", "volatile { int x = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    setvar, divby, _setvar_x, _done = ops
    assert setvar.flags & structs.OpFlags.LITERAL_ARG2
    assert setvar.arg2 == -2147483648
    assert divby.flags & structs.OpFlags.LITERAL_ARG2
    assert divby.arg2 == -1


# --- int32 (t_gq_int) boundary: fold at the edge, decline past it -----------


def test_addition_folds_exactly_at_int32_max(compile_gq):
    # 2147483646 + 1 == 2147483647 (INT32_MAX) -- fits, folds.
    source = game_with_stage("x = 2147483646 + 1;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert _folded_setvar_value(cmds) == 2147483647


def test_addition_past_int32_max_does_not_fold(compile_gq):
    # 2147483647 + 1 would overflow t_gq_int -- gqc does not replicate the
    # target compiler's signed-overflow behavior, so this is left as a real
    # runtime ADDBY (whatever it does at runtime is unchanged by this
    # feature either way).
    source = game_with_stage("x = 2147483647 + 1;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    addby = next(op for op in ops if op.name == "ADDBY")
    assert addby.flags & structs.OpFlags.LITERAL_ARG2
    assert addby.arg2 == 1


def test_subtraction_folds_exactly_at_int32_min(compile_gq):
    # -2147483647 - 1 == -2147483648 (INT32_MIN) -- fits, folds.
    source = game_with_stage("x = -2147483647 - 1;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert _folded_setvar_value(cmds) == -2147483648


def test_bare_int32_min_literal_now_folds_cleanly(compile_gq):
    # Regression guard for gamequeer#395: on `default` (pre-dating this PR),
    # a bare "-2147483648" literal token independently crashes gqc at
    # compile time with a raw struct.error -- pyparsing's infix_notation
    # parses it as unary negation of the *positive* literal 2147483648
    # (itself out of t_gq_int range), and the old unary-NEG codegen embeds
    # that pre-negation operand directly without range-checking it. With
    # folding, the negation is computed in Python first and the
    # already-in-range result (-2147483648) is what gets embedded, so this
    # exact shape no longer reaches that path -- confirm it stays fixed.
    # (gamequeer#395 is still open: a bare literal that overflows even
    # *after* negation, e.g. "-2147483649", isn't helped by folding and
    # still hits the underlying bug -- out of scope here.)
    source = game_with_stage("x = -2147483648;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert _folded_setvar_value(cmds) == -2147483648


def test_negation_past_int32_min_does_not_fold(compile_gq):
    # -2147483647 - 1 - 1 would be -2147483649, past INT32_MIN -- declines
    # to fold (the inner "-2147483647 - 1" still folds to INT32_MIN on its
    # own; only the outer "- 1" against it is left as a real SUBBY).
    source = game_with_stage("x = (-2147483647 - 1) - 1;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    subby = next(op for op in ops if op.name == "SUBBY")
    assert subby.flags & structs.OpFlags.LITERAL_ARG2
    assert subby.arg2 == 1


# --- shift folding: valid range only, no negative-left UB -------------------


def test_shift_folds_within_valid_amount_range(compile_gq):
    source = game_with_stage("x = 1 << 30;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert _folded_setvar_value(cmds) == 1 << 30


def test_shift_amount_out_of_range_does_not_fold(compile_gq):
    # Matches the gamequeer#345 `1<<50` shapes in test_expressions.py: a
    # shift amount outside [0, 31] is undefined behavior in C, so gqc
    # declines to compute a specific answer for it at compile time.
    source = game_with_stage("x = 1 << 50;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    bwshl = next(op for op in ops if op.name == "BWSHL")
    assert bwshl.flags & structs.OpFlags.LITERAL_ARG2
    assert bwshl.arg2 == 50


def test_left_shift_of_negative_value_does_not_fold(compile_gq):
    # Left-shifting a negative value is undefined behavior in C -- even
    # though the shift amount itself (1) is in range, gqc declines to fold.
    source = game_with_stage("x = -1 << 1;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    bwshl = next(op for op in ops if op.name == "BWSHL")
    assert bwshl.flags & structs.OpFlags.LITERAL_ARG2
    assert bwshl.arg2 == 1


def test_right_shift_of_negative_value_folds_as_arithmetic_shift(compile_gq):
    # Right-shifting a negative value is implementation-defined (not UB) in
    # C, and every real-world compiler this project targets (including the
    # badge's TI cl430 build) implements it as an arithmetic (sign-
    # extending) shift, matching Python's own `>>` on a negative int -- so
    # this folds.
    source = game_with_stage("x = -8 >> 1;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert _folded_setvar_value(cmds) == -4


# --- badge_get never folds ---------------------------------------------------


def test_badge_get_never_folds_even_with_a_literal_operand(compile_gq):
    # badge_get reads live badge state, not a constant, regardless of
    # whether its own operand is a literal -- combined with a literal `+ 1`
    # here so a bug that treated QCGET as foldable would visibly collapse
    # the whole expression to a single SETVAR instead of a real ADDBY.
    source = game_with_stage("x = badge_get 1 + 1;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    assert any(op.name == "QCGET" for op in ops)
    addby = next(op for op in ops if op.name == "ADDBY")
    assert addby.flags & structs.OpFlags.LITERAL_ARG2
    assert addby.arg2 == 1


# --- badge_count() never folds (gamequeer#387) -------------------------------


def test_badge_count_never_folds(compile_gq):
    # badge_count() reads live badge state, not a constant, even though it
    # (unlike badge_get) has no operand at all to tempt a naive fold check
    # -- combined with a literal `+ 1` so a bug that treated it as foldable
    # would visibly collapse the whole expression to a single SETVAR
    # instead of a real loop + ADDBY.
    source = game_with_stage("x = badge_count() + 1;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    assert any(op.name == "QCGET" for op in ops)
    addby_ops = [op for op in ops if op.name == "ADDBY"]
    # One ADDBY inside the popcount loop (acc += bit) and one for the "+ 1"
    # itself, with the literal on the outer one.
    assert len(addby_ops) == 2
    addby_literal = next(op for op in addby_ops if op.flags & structs.OpFlags.LITERAL_ARG2)
    assert addby_literal.arg2 == 1


# --- fw_version() never folds (gamequeer#411) ---------------------------------


def test_fw_version_never_folds(compile_gq):
    # fw_version() is sugar for a reference to a hidden runtime-populated
    # variable (see linker.inject_fw_version_probe), not a literal -- so
    # "fw_version() + 1" must load it into a register and ADDBY the literal
    # 1, not collapse to a single literal SETVAR the way "1 + 1" would.
    source = game_with_stage("x = fw_version() + 1;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    # opstream.one_event's default ENTER lookup is ambiguous here: the
    # compiler-injected probe stage (linker.inject_fw_version_probe) has its
    # own ENTER event. The author's own `start` stage is always the first
    # ENTER block -- its Stage is registered before the probe stage's (see
    # inject_fw_version_probe's docstring).
    ops = next(b for b in parse_gqasm(cmds) if b.event_type == "ENTER").ops
    addby = next(op for op in ops if op.name == "ADDBY")
    assert addby.flags & structs.OpFlags.LITERAL_ARG2
    assert addby.arg2 == 1
    # The dst register was loaded from a variable (a SETVAR with a
    # non-literal source), not initialized with a literal -- i.e. gqc really
    # read fw_version()'s backing variable at runtime instead of folding it.
    load = next(op for op in ops if op.name == "SETVAR" and op.arg1 == addby.arg1)
    assert not (load.flags & structs.OpFlags.LITERAL_ARG2)


# --- random() never folds; min()/max()/clamp()/abs() do (gamequeer#422) -------


def test_random_never_folds(compile_gq):
    # random() reads (and mutates) live LCG state seeded from GQI_PLAYER_ID
    # and a per-call counter, not a constant -- combined with a literal
    # "+ 1" so a bug that treated it as foldable would visibly collapse the
    # whole expression to a single SETVAR instead of the real LCG arithmetic.
    source = game_with_stage("x = random(1, 10) + 1;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    addby_ops = [op for op in ops if op.name == "ADDBY"]
    # Several ADDBYs belong to random()'s own LCG arithmetic; exactly one
    # (the outermost) carries the literal "+ 1".
    literal_addbys = [op for op in addby_ops if op.flags & structs.OpFlags.LITERAL_ARG2 and op.arg2 == 1]
    assert len(literal_addbys) >= 1
    assert len(addby_ops) > 1


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("min(3, 7)", 3),
        ("min(7, 3)", 3),
        ("max(3, 7)", 7),
        ("max(7, 3)", 7),
        ("min(-3, 7)", -3),
        ("max(-3, -7)", -3),
        ("abs(5)", 5),
        ("abs(-5)", 5),
        ("abs(0)", 0),
        ("clamp(5, 0, 10)", 5),
        ("clamp(-5, 0, 10)", 0),
        ("clamp(15, 0, 10)", 10),
        ("clamp(5, 10, 0)", 0),  # lo > hi: min(max(5, 10), 0) = min(10, 0) = 0
    ],
)
def test_math_intrinsics_of_literal_arguments_fold(compile_gq, expr, expected):
    source = game_with_stage(f"x = {expr};", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert _folded_setvar_value(cmds) == expected


def test_min_never_folds_with_a_variable_argument(compile_gq):
    source = game_with_stage("x = min(y, 7) + 1;", "volatile { int x = 0; int y = 3; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert any(op.name in ("LT", "GT") for op in ops)
    addby_literal = next(op for op in ops if op.name == "ADDBY" and op.flags & structs.OpFlags.LITERAL_ARG2)
    assert addby_literal.arg2 == 1


def test_abs_never_folds_with_a_variable_argument(compile_gq):
    source = game_with_stage("x = abs(y) + 1;", "volatile { int x = 0; int y = -3; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert any(op.name == "NEG" for op in ops) or any(op.name == "LT" for op in ops)


def test_abs_of_int32_min_does_not_fold_overflow(compile_gq):
    # abs(INT32_MIN) is 2**31, one past T_GQ_INT_MAX -- not representable in
    # t_gq_int, so this must decline to fold (same overflow-declines-to-fold
    # policy as every other operator; see fold_constant_int_expression's
    # docstring) rather than silently emit a wrong/truncated constant.
    source = game_with_stage("x = abs(-2147483648);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] != ["SETVAR", "DONE"]
    assert any(op.name in ("NEG", "LT") for op in ops)
