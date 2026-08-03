"""`min()`/`max()`/`clamp()`/`abs()` intrinsic suite for gqc (gamequeer#422,
part of epic gamequeer#419).

All four desugar to *existing* compare/arithmetic ops -- no dedicated opcode
(FROZEN VM CONTRACT):

  - `min(a, b)`/`max(a, b)`: `result = a; if (<compare> b result) { result =
    b; }` (a `<`-compare for min, `>` for max) -- see
    `IntExpression._emit_minmax`, `gqc/src/gqc/datamodel.py`. `min`/`max`
    share this one lowering method (and, at the grammar layer, one
    `GqcMinMaxOperand` marker with a `want_max` flag -- see
    `parser.parse_min_operand`/`parse_max_operand`).
  - `clamp(x, lo, hi)`: `min(max(x, lo), hi)`, composed directly from two
    `_emit_minmax` calls (`IntExpression._emit_clamp`).
  - `abs(x)`: `result = x; if (result < 0) { result = -result; }`, via the
    `_emit_negate_if_negative` helper shared with `random()`'s own seed
    normalization (`IntExpression._emit_abs`).

`test_grammar.py` covers accept/reject grammar forms; `test_constant_folding.py`
covers folding (all four fold when their arguments do -- unlike `random()`,
which never folds). This module covers the op-stream shape.
"""

from gqc import structs

from .opstream import one_event

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def game_with_stage(body: str, decls: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level declarations (e.g. a
    `volatile { ... }` block)."""
    return f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ {body} }} }}\n"


# --- min()/max() ----------------------------------------------------------------


def test_min_op_stream_shape(compile_gq):
    source = game_with_stage(
        "x = min(a, b);", "volatile { int x = 0; int a = 3; int b = 7; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == [
        "SETVAR",  # result = a
        "SETVAR",  # cmp = b
        "LT",  # cmp = (cmp(b) < result(a))
        "GOTOIFN",
        "SETVAR",  # result = b (only if b < a)
        "SETVAR",  # x = result
        "DONE",
    ]


def test_max_op_stream_shape(compile_gq):
    source = game_with_stage(
        "x = max(a, b);", "volatile { int x = 0; int a = 3; int b = 7; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == [
        "SETVAR", "SETVAR", "GT", "GOTOIFN", "SETVAR", "SETVAR", "DONE",
    ]


def test_min_with_literal_first_argument_compiles(compile_gq):
    source = game_with_stage("x = min(1, y);", "volatile { int x = 0; int y = 5; }")
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


def test_min_with_full_expression_arguments_compiles(compile_gq):
    source = game_with_stage(
        "x = min(a + 1, b * 2);", "volatile { int x = 0; int a = 3; int b = 7; }"
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


def test_min_combined_with_binary_op_compiles(compile_gq):
    source = game_with_stage(
        "x = min(a, b) + 1;", "volatile { int x = 0; int a = 3; int b = 7; }"
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


def test_max_used_twice_in_one_expression_compiles(compile_gq):
    source = game_with_stage(
        "x = max(a, b) + max(a, b);", "volatile { int x = 0; int a = 3; int b = 7; }"
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


def test_min_in_if_condition_compiles(compile_gq):
    source = game_with_stage(
        "if (min(a, b) == 0) { badge_set 1; }",
        "volatile { int a = 3; int b = 7; }",
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


# --- clamp() ----------------------------------------------------------------


def test_clamp_op_stream_shape(compile_gq):
    source = game_with_stage(
        "x = clamp(a, lo, hi);",
        "volatile { int x = 0; int a = 3; int lo = 0; int hi = 10; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    # clamp(x, lo, hi) = min(max(x, lo), hi): a max()'s own 5 ops (result =
    # x; cmp = lo; cmp = cmp > result; if (cmp) result = lo), then a min()'s
    # own 5 ops against hi, then the assignment's SETVAR + DONE.
    assert [op.name for op in ops] == [
        "SETVAR", "SETVAR", "GT", "GOTOIFN", "SETVAR",  # max(x, lo)
        "SETVAR", "SETVAR", "LT", "GOTOIFN", "SETVAR",  # min(that, hi)
        "SETVAR",  # x = result
        "DONE",
    ]


def test_clamp_within_range_leaves_value_unchanged_registers(compile_gq):
    # Not a runtime-behavior test (gqc doesn't execute the game) -- just
    # confirms clamp() compiles for the realistic in-range case too, not
    # just boundary values.
    source = game_with_stage(
        "x = clamp(5, 0, 10);", "volatile { int x = 0; }"
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


def test_clamp_combined_with_binary_op_compiles(compile_gq):
    source = game_with_stage(
        "x = clamp(a, 0, 10) + 1;", "volatile { int x = 0; int a = 3; }"
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


# --- abs() --------------------------------------------------------------------


def test_abs_op_stream_shape(compile_gq):
    source = game_with_stage("x = abs(a);", "volatile { int x = 0; int a = -3; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    assert [op.name for op in ops] == [
        "SETVAR",  # result = a
        "SETVAR",  # cmp = result
        "LT",  # cmp = (cmp < 0)
        "GOTOIFN",
        "NEG",  # result = -result (only if result < 0)
        "SETVAR",  # x = result
        "DONE",
    ]


def test_abs_of_literal_negative_argument_compiles(compile_gq):
    source = game_with_stage("x = abs(-5);", "volatile { int x = 0; }")
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


def test_abs_combined_with_binary_op_compiles(compile_gq):
    source = game_with_stage(
        "x = abs(a) + 1;", "volatile { int x = 0; int a = -3; }"
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


def test_abs_of_full_expression_argument_compiles(compile_gq):
    source = game_with_stage(
        "x = abs(a - b);", "volatile { int x = 0; int a = 3; int b = 7; }"
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


def test_abs_used_twice_in_one_expression_compiles(compile_gq):
    source = game_with_stage(
        "x = abs(a) + abs(b);", "volatile { int x = 0; int a = -3; int b = 7; }"
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr
