"""Named compile-time constants and enums suite for gqc (gamequeer#421, epic
gamequeer#419).

`const NAME = <int-expression>;` and `enum Name { A, B, C }` (referenced as
`Name.Member`) are pure parse-time sugar (`datamodel.Constant`/
`datamodel.Enum`): every reference is substituted with a literal
`GqcIntOperand` at the point it's parsed, reusing gamequeer#385's
`fold_constant_int_expression` for anything more than a bare literal RHS --
by the time codegen sees one, it's indistinguishable from a hand-written int
literal. This keeps the feature entirely inside gqc: no new opcode,
register, or on-cart format (FROZEN VM CONTRACT).

Scoping (the "keep it simple" decision the issue asks for), pinned here: a
single flat, file-global namespace, resolved eagerly in source order -- a
`const`/`enum` must be declared *before* its first use, like a `#define` in
a single-pass C preprocessor (see `datamodel.Constant`'s docstring for the
full reasoning). This is a deliberate, documented departure from ordinary
variable/stage/animation references, which *are* forward-reference-tolerant.
"""

import pytest

from gqc import structs

from .opstream import one_event

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def game_with_stage(body: str, decls: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level declarations (e.g. a
    `const`/`enum` block)."""
    return f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ {body} }} }}\n"


def assert_no_traceback(stderr: str):
    assert "Traceback" not in stderr, f"raw Python traceback leaked to stderr:\n{stderr}"


def _folded_setvar_value(cmds_text: str) -> int:
    """Assert `cmds_text`'s only real op is a single literal SETVAR (i.e.
    the whole expression folded to one constant) and return its value."""
    ops = one_event(cmds_text).ops
    assert [op.name for op in ops] == ["SETVAR", "DONE"]
    setvar, _done = ops
    assert setvar.flags & structs.OpFlags.LITERAL_ARG2
    return setvar.arg2


# --- const: declaration + use, folds to a literal ----------------------------


def test_const_bare_literal_accepts_and_folds(compile_gq):
    source = game_with_stage(
        "x = MAX_HP;", "const MAX_HP = 21;\nvolatile { int x = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert _folded_setvar_value(cmds) == 21


def test_const_expression_rhs_folds_at_declaration(compile_gq):
    # The const's own RHS is an int_expression, so it gets gamequeer#385's
    # folding for free -- "20 + 1" never appears as a runtime ADDBY anywhere,
    # not at the declaration and not at any of its uses.
    source = game_with_stage(
        "x = MAX_HP;", "const MAX_HP = 20 + 1;\nvolatile { int x = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "ADDBY" not in cmds
    assert _folded_setvar_value(cmds) == 21


def test_const_used_multiple_times_each_folds_independently(compile_gq):
    source = game_with_stage(
        "x = MAX_HP; y = MAX_HP + 1;",
        "const MAX_HP = 21;\nvolatile { int x = 0; int y = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    assert [op.name for op in ops] == ["SETVAR", "SETVAR", "DONE"]
    setvar_x, setvar_y, _done = ops
    assert setvar_x.flags & structs.OpFlags.LITERAL_ARG2
    assert setvar_x.arg2 == 21
    assert setvar_y.flags & structs.OpFlags.LITERAL_ARG2
    assert setvar_y.arg2 == 22


def test_const_referencing_an_earlier_const_folds(compile_gq):
    source = game_with_stage(
        "x = DOUBLE_MAX_HP;",
        "const MAX_HP = 21;\nconst DOUBLE_MAX_HP = MAX_HP * 2;\n"
        "volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "MULBY" not in cmds
    assert _folded_setvar_value(cmds) == 42


def test_const_usable_in_if_condition(compile_gq):
    source = game_with_stage(
        "if (x > MAX_HP) { badge_set 1; }",
        "const MAX_HP = 21;\nvolatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    gt = next(op for op in ops if op.name == "GT")
    assert gt.flags & structs.OpFlags.LITERAL_ARG2
    assert gt.arg2 == 21


def test_const_mixed_with_variable_folds_only_the_literal_side(compile_gq):
    # Same "literal subtree folds, variable side stays a real op" behavior
    # test_constant_folding.py already pins for bare literals -- a `const`
    # reference is just another literal by the time int_operand sees it.
    source = game_with_stage(
        "x = y + MAX_HP;", "const MAX_HP = 21;\nvolatile { int x = 0; int y = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    addby = next(op for op in ops if op.name == "ADDBY")
    assert addby.flags & structs.OpFlags.LITERAL_ARG2
    assert addby.arg2 == 21


# --- enum: declaration + Name.Member use, auto-numbered from 0 ---------------


def test_enum_members_auto_number_from_zero(compile_gq):
    source = game_with_stage(
        "x = Difficulty.Easy; y = Difficulty.Medium; z = Difficulty.Hard;",
        "enum Difficulty { Easy, Medium, Hard }\n"
        "volatile { int x = 0; int y = 0; int z = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    setvars = [op for op in ops if op.name == "SETVAR"]
    assert [op.arg2 for op in setvars] == [0, 1, 2]
    for op in setvars:
        assert op.flags & structs.OpFlags.LITERAL_ARG2


def test_enum_member_usable_in_expression_and_folds(compile_gq):
    source = game_with_stage(
        "x = Difficulty.Hard + 1;",
        "enum Difficulty { Easy, Medium, Hard }\nvolatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "ADDBY" not in cmds
    assert _folded_setvar_value(cmds) == 3


def test_enum_member_usable_in_if_condition(compile_gq):
    source = game_with_stage(
        "if (x > Difficulty.Easy) { badge_set 1; }",
        "enum Difficulty { Easy, Medium, Hard }\nvolatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    ops = one_event(cmds).ops
    gt = next(op for op in ops if op.name == "GT")
    assert gt.flags & structs.OpFlags.LITERAL_ARG2
    assert gt.arg2 == 0


def test_const_referencing_enum_member_folds_at_declaration(compile_gq):
    source = game_with_stage(
        "x = HARD_BONUS;",
        "enum Difficulty { Easy, Medium, Hard }\n"
        "const HARD_BONUS = Difficulty.Hard + 10;\n"
        "volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "ADDBY" not in cmds
    assert _folded_setvar_value(cmds) == 12


# --- "const"/"enum" keywords don't swallow a prefixed identifier ------------
# Matches the existing gamequeer#354 convention pinned for "str"/"badge_get"/
# "badge_count" -- both are matched via Keyword(), not a bare string.


def test_const_prefixed_identifier_accepts(compile_gq):
    source = game_with_stage(
        "constant_value = 5;", "volatile { int constant_value = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_enum_prefixed_identifier_accepts(compile_gq):
    source = game_with_stage(
        "enumerate_x = 5;", "volatile { int enumerate_x = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


# --- reject: duplicate definitions -------------------------------------------


def test_duplicate_const_rejects(compile_gq):
    source = (
        f"{GAME_HEADER}"
        "const A = 1;\n"
        "const A = 2;\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Duplicate definition of constant A" in stderr
    assert_no_traceback(stderr)


def test_duplicate_enum_name_rejects(compile_gq):
    source = (
        f"{GAME_HEADER}"
        "enum Difficulty { Easy, Hard }\n"
        "enum Difficulty { Trivial, Brutal }\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Duplicate definition of enum Difficulty" in stderr
    assert_no_traceback(stderr)


def test_duplicate_member_within_enum_rejects(compile_gq):
    source = (
        f"{GAME_HEADER}"
        "enum Difficulty { Easy, Easy, Hard }\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Duplicate member Easy in enum Difficulty" in stderr
    assert_no_traceback(stderr)


# --- reject: unknown enum / unknown member -----------------------------------


def test_unknown_enum_rejects(compile_gq):
    source = game_with_stage(
        "x = Bogus.Whatever;", "volatile { int x = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Unknown enum Bogus" in stderr
    assert_no_traceback(stderr)


def test_unknown_member_of_known_enum_rejects(compile_gq):
    source = game_with_stage(
        "x = Difficulty.Nightmare;",
        "enum Difficulty { Easy, Hard }\nvolatile { int x = 0; }",
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Unknown member Nightmare of enum Difficulty" in stderr
    assert_no_traceback(stderr)


# --- reject: out-of-range constant value -------------------------------------


def test_const_value_exceeding_int32_range_rejects(compile_gq):
    # A bare literal RHS is never routed through fold_constant_int_expression
    # (int_expression's own parse action short-circuits a lone GqcIntOperand
    # straight through -- see parser.parse_int_expression), so this needs
    # its own explicit range check in Constant.define; without it, an
    # over-range `const` would silently reach struct.pack and fail later
    # with an unrelated OverflowError instead of a clean diagnostic here.
    source = (
        f"{GAME_HEADER}"
        "const BIG = 99999999999;\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    # Split across two assertions (not one long substring): rich's console
    # wraps long error lines at the terminal width, which would otherwise
    # insert an unpredictable newline into a single "in stderr" check --
    # matches the splitting convention test_diagnostics.py's own
    # long-message cases already use.
    assert "Constant BIG value 99999999999 is out of range for a" in stderr
    assert "32-bit int (t_gq_int)" in stderr
    assert_no_traceback(stderr)


def test_const_value_at_int32_max_accepts(compile_gq):
    source = game_with_stage(
        "x = INT32_MAX;", "const INT32_MAX = 2147483647;\nvolatile { int x = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert _folded_setvar_value(cmds) == 2147483647


# --- reject: const initializer isn't a compile-time constant -----------------


def test_const_initialized_from_a_variable_rejects(compile_gq):
    # `const` has no runtime fallback -- unlike a `volatile`/`persistent`
    # variable initializer, its RHS must fold all the way to a literal at
    # declaration time. A reference to an actual runtime variable (or,
    # indistinguishably from gqc's point of view, a typo'd/undeclared name)
    # is rejected here rather than silently accepted as an unresolved
    # symbol.
    source = (
        f"{GAME_HEADER}"
        "volatile { int y = 5; }\n"
        "const A = y + 1;\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    # Split across two assertions for the same rich line-wrap reason as
    # test_const_value_exceeding_int32_range_rejects, above.
    assert "Constant A must be initialized with a compile-time" in stderr
    assert "constant integer expression" in stderr
    assert_no_traceback(stderr)


# --- scoping: declare-before-use (documented, deliberate limitation) --------


def test_const_referenced_before_its_declaration_does_not_error_at_parse_time(
    compile_gq,
):
    # Pins the documented declare-before-use scoping decision (see this
    # module's docstring and datamodel.Constant's): a `const` referenced
    # textually before its own declaration is not in Constant.const_table
    # yet, so parser.parse_int_operand's identifier branch falls through to
    # treating "LATER" as an ordinary (variable) reference instead, exactly
    # as it would for any other not-yet-defined name.
    #
    # That reference is then silently left at arg2 == 0 rather than
    # reported as an unresolved symbol -- a *separate*, pre-existing gap in
    # CommandWithIntExpressionArgument.resolve() (its int-operand branch is
    # missing the "else: unresolved_symbols.append(...)" its own
    # string-operand counterpart, CommandWithStrExpressionArgument.resolve,
    # already has), not something gamequeer#421 introduces or is
    # responsible for fixing. Pinned here (gqc exits 0) so that gap is
    # visible and cross-referenced rather than silently masked by this
    # feature's own tests.
    source = (
        f"{GAME_HEADER}"
        "volatile { int x = 0; }\n"
        "stage start { event enter { x = LATER; } }\n"
        "const LATER = 5;\n"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    setvar = one_event(cmds).ops[0]
    assert not (setvar.flags & structs.OpFlags.LITERAL_ARG2)
    assert setvar.arg2 == 0
