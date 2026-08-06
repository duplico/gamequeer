"""Nested parenthesized int-expression regression suite (gamequeer#345, epic
gamequeer#329). To be absorbed into gamequeer#334's dedicated codegen test
suite when that lands.

Before this fix, `parse_int_expression`'s left-fold (added by gamequeer#341,
`gqc/src/gqc/parser.py`) only handled a flat token list. pyparsing's
`infix_notation` re-invokes the *same* parse action once more on the bare
atom whenever an entire (sub)expression collapses to a single already-built
`IntExpression` -- which happens for any fully-parenthesized expression, not
just deeply "nested" ones (`x = (1 + 2);` reproduced the crash on its own).
That second invocation handed `parse_int_expression` an `IntExpression`
instance directly (instead of a flat token list), and `if len(toks) > 3`
raised `TypeError: object of type 'IntExpression' has no len()`.

Separately, pyparsing's packrat recursive descent hits Python's own
recursion limit on sufficiently deep nesting (5+ levels for the shapes
below), raising a bare `RecursionError` before codegen is ever reached --
unrelated to the fold logic, so it's handled as its own clean diagnostic in
`parser.parse()` rather than "fixed" by restructuring the grammar.

Per gamequeer#331/#341 precedent, correctness is asserted cheaply from the
emitted `cmds.gqasm` listing rather than a full bytecode/VM run. The exact
nested-shift shapes from gamequeer#345's repro (which use `1<<50`, a
shift-by-a-not-representable-amount on the VM's 32-bit `t_gq_int`) are only
asserted to compile without crashing -- not to evaluate to a specific value,
since that value is platform/compiler-dependent (UB in C) and not something
gqc's compiler is responsible for. Correct-value assertions instead use
plain, portable arithmetic on the same "fully-parenthesized" shape that
actually triggers the bug. The nested-shift shapes were additionally
verified end to end against the headless emulator during development (see
the gamequeer#345 PR description) with a pass/fail gate cart (correct
result -> one lightcue, wrong result -> another) at nesting depths 1-3,
including a negative control confirming the gate discriminates correctly.

gamequeer#385 added compile-time constant folding for int expressions whose
operands are all literals. Several cases below are entirely literal (that
was the easiest way to pin gamequeer#345's parenthesization/associativity
fixes independently of variable resolution), so they now fold away to a
single literal rather than emitting real ADDBY/SUBBY ops -- their
assertions were updated (not just re-pinned) to check the *folded value* is
still correct, per gamequeer#385's own stated policy of deliberately
flipping baselines that a literal-only expression used to reach. Where a
case's original intent was to pin *codegen shape* (single-accumulator
register reuse, left-associativity) rather than a specific literal value,
a `_mixed_with_variable` sibling using a non-foldable operand preserves
that coverage instead.
"""

import pytest

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def game_with_stage(body: str, decls: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level declarations (e.g. a
    `volatile { ... }` block)."""
    return f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ {body} }} }}\n"


def assert_no_traceback(stderr: str):
    assert "Traceback" not in stderr, f"raw Python traceback leaked to stderr:\n{stderr}"


# --- the minimal previously-crashing shape: any fully-parenthesized RHS -----
# Nesting isn't actually required to hit the bug -- a single pair of parens
# around the *entire* right-hand side already reproduces it, because
# infix_notation re-invokes parse_int_expression on the bare, already-built
# IntExpression atom.


def test_fully_parenthesized_pair_compiles_with_correct_value(compile_gq):
    # Entirely literal -- gamequeer#385 folds this to a single literal 3 at
    # parse time, so no ADDBY (or any register) is emitted at all. Before
    # gamequeer#385, this was one ADDBY against immediate 2.
    source = game_with_stage("x = (1 + 2);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "ADDBY" not in cmds
    setvar_lines = [line for line in cmds.splitlines() if "SETVAR" in line]
    assert len(setvar_lines) == 1
    assert "0x00000003" in setvar_lines[0]


def test_fully_parenthesized_chain_compiles_with_correct_value(compile_gq):
    # The parenthesized RHS is itself a >3-token left-fold chain (exercising
    # gamequeer#345's fix, which built an IntExpression for it before the
    # outer bare-atom re-invocation saw it), but it's also entirely literal,
    # so gamequeer#385 folds the whole thing to a single literal 10 instead
    # of the 3-ADDBY single-accumulator sequence this used to emit.
    source = game_with_stage("x = (1 + 2 + 3 + 4);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "ADDBY" not in cmds
    setvar_lines = [line for line in cmds.splitlines() if "SETVAR" in line]
    assert len(setvar_lines) == 1
    assert "0x0000000a" in setvar_lines[0]  # 10


def test_fully_parenthesized_chain_mixed_with_variable_stays_single_register(compile_gq):
    # Same >3-token left-fold chain and parenthesization as above, but with
    # a trailing variable so it can't fold away entirely: "1+2+3+y" left-
    # folds as ((1+2)+3)+y. The purely-literal leading pair "1+2" folds to a
    # single literal 3 first, then "3+3" (still literal) folds to 6, and
    # only the final "+y" survives as a real accumulator add -- preserving
    # the single-accumulator-register guarantee gamequeer#341/#345 pinned
    # for the fully-literal version of this shape before gamequeer#385.
    source = game_with_stage(
        "x = (1 + 2 + 3 + y);", "volatile { int x = 0; int y = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    lines = cmds.splitlines()
    addby_lines = [line for line in lines if "ADDBY" in line]
    setvar_lines = [line for line in lines if "SETVAR" in line]
    assert len(addby_lines) == 1
    # The folded "1+2+3" (6) is loaded as ADDBY's accumulator operand, not
    # ADDBY's own arg2 -- ADDBY itself adds y's (non-literal) address.
    assert any("0x00000006" in line for line in setvar_lines)
    # Column layout is "Address Command Op Flags arg1 arg2" -- arg1 (index
    # 4) is the destination register; confirm ADDBY accumulates into the
    # same register the folded literal 6 was loaded into.
    dest_reg = addby_lines[0].split()[4]
    assert any(
        "0x00000006" in line and line.split()[4] == dest_reg for line in setvar_lines
    )


# --- exact gamequeer#345 repro shapes: nested (1<<a | 1<<b) | (...) chains --
# These use the issue's own `1<<50` sentinel, so only exit code / absence of
# a raw traceback is asserted -- not a specific numeric result (see module
# docstring).


def nested_shift_or_chain(pair_count: int) -> str:
    """Build the gamequeer#345 repro shape: `pair_count` nested
    `((1<<a)|(1<<b)) | (...)` groups, terminating in a bare `1<<50`. Matches
    the issue's own depth-2/4/5 examples verbatim at pair_count=2/4/5."""
    expr = "1<<50"
    for i in reversed(range(pair_count)):
        expr = f"(((1<<{2 * i})|(1<<{2 * i + 1})) | {expr})"
    return expr


@pytest.mark.parametrize("pair_count", [2, 3])
def test_nested_shift_or_chain_previously_typeerror_now_compiles(compile_gq, pair_count):
    source = game_with_stage(
        f"mask = {nested_shift_or_chain(pair_count)};", "volatile { int mask = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)


def test_nested_shift_or_chain_4_pairs_no_longer_exhausts_registers(compile_gq):
    # Before gamequeer#385, this shape's 4 nested `(1<<a)|(1<<b)` groups
    # each needed a register alive concurrently with its enclosing OR,
    # exhausting gqc's 4-register int file (GQ_REGISTERS_INT) -- a clean,
    # documented GqcParseError-style diagnostic, not a crash.
    #
    # gamequeer#385's constant folding changes this: each `(1<<a)|(1<<b)`
    # pair here has both `a` and `b` in [0, 31] (valid shift amounts), so
    # every pair folds to a single literal at parse time -- and because
    # IntExpression.get_result_symbol resolves a node's *right* operand
    # before deciding whether its (literal) *left* operand needs a
    # register, a folded literal's register load is deferred until after
    # the whole right-hand recursion (down to the one real, unfoldable
    # `1<<50` at the base) has already run and freed its own temporaries.
    # Concurrent register pressure no longer grows with nesting depth, so
    # this pair count -- and, empirically, every pair count reachable
    # before pyparsing's own parse-depth limit kicks in at 5 (see
    # test_nested_shift_or_chain_5_pairs_previously_recursionerror_now_
    # clean) -- compiles cleanly instead. General 4-register-exhaustion
    # coverage that isn't foldable away lives in test_codegen.py's
    # `_balanced_sum_tree(depth, leaf="v")` tests instead.
    source = game_with_stage(
        f"mask = {nested_shift_or_chain(4)};", "volatile { int mask = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)


def test_nested_shift_or_chain_5_pairs_previously_recursionerror_now_clean(compile_gq):
    # One level deeper than the register-exhaustion boundary: pyparsing's
    # packrat recursive descent exceeds Python's own recursion limit before
    # codegen is ever reached. Pin the clean one-line diagnostic instead of
    # a raw RecursionError traceback.
    source = game_with_stage(
        f"mask = {nested_shift_or_chain(5)};", "volatile { int mask = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert_no_traceback(stderr)
    assert "too deep" in stderr


# --- #341 review case: nested non-associative subtraction -------------------


def test_nested_subtraction_evaluates_nonassociatively(compile_gq):
    # 10 - (5 - (2 - 1)) = 10 - (5 - 1) = 10 - 4 = 6, not the flat left-fold
    # result -- and, being entirely literal, gamequeer#385 folds the whole
    # thing to that single literal 6 at parse time, with no SUBBY at all.
    # Before gamequeer#385, this was 3 SUBBY ops; see
    # test_nested_subtraction_evaluates_nonassociatively_mixed_with_variable
    # below for that shape's still-live non-associativity coverage.
    source = game_with_stage("x = 10 - (5 - (2 - 1));", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "SUBBY" not in cmds
    setvar_lines = [line for line in cmds.splitlines() if "SETVAR" in line]
    assert len(setvar_lines) == 1
    assert "0x00000006" in setvar_lines[0]


def test_nested_subtraction_evaluates_nonassociatively_mixed_with_variable(compile_gq):
    # Same nesting as above, but the innermost operand is a variable so the
    # expression can't fold away entirely: 10 - (5 - (2 - y)), evaluated
    # from the inside out via register reuse (not the flat left-fold
    # 10 - (5 - 2) - y would give). Each level's literal (2, 5, then 10)
    # arrives via its own SETVAR, and SUBBY operates register-to-register
    # at each step -- pinning the same non-associative codegen shape the
    # original all-literal test covered before gamequeer#385.
    source = game_with_stage(
        "x = 10 - (5 - (2 - y));", "volatile { int x = 0; int y = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    lines = cmds.splitlines()
    subby_lines = [line for line in lines if "SUBBY" in line]
    setvar_lines = [line for line in lines if "SETVAR" in line]
    assert len(subby_lines) == 3
    # Column layout is "Address Command Op Flags arg1 arg2" -- Flags (index
    # 3) carries LITERAL_ARG2 (0x08) only when arg2 is an embedded literal.
    # Innermost "2 - y" subtracts y's own (non-literal) address, unlike the
    # outer two, which subtract a previously-computed register result (5
    # and 10 arrive as SETVAR-loaded literals first).
    assert subby_lines[0].split()[3] == "0x00"
    assert any("0x00000002" in line for line in setvar_lines)  # literal 2
    assert any("0x00000005" in line for line in setvar_lines)  # literal 5
    assert any("0x0000000a" in line for line in setvar_lines)  # literal 10 (0x0a)


# --- flat chain stays single-register ---------------------------------------


def test_flat_6_term_chain_stays_single_register(compile_gq):
    # Entirely literal -- gamequeer#385 folds this to a single literal 21
    # (0x15) at parse time, with no ADDBY at all. Before gamequeer#385, this
    # was 5 ADDBY ops against a single accumulator register; see
    # test_flat_6_term_chain_mixed_with_variable_stays_single_register below
    # for that shape's still-live single-register coverage.
    source = game_with_stage("x = 1+2+3+4+5+6;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "ADDBY" not in cmds
    setvar_lines = [line for line in cmds.splitlines() if "SETVAR" in line]
    assert len(setvar_lines) == 1
    assert "0x00000015" in setvar_lines[0]  # 21


def test_flat_6_term_chain_mixed_with_variable_stays_single_register(compile_gq):
    # Same 6-term left-fold chain, but with a trailing variable so it can't
    # fold away entirely: "1+2+3+4+5+y" left-folds its purely-literal
    # leading run ("1+2+3+4+5") to a single literal 15 (0x0f) first, and
    # only the final "+y" survives as a real accumulator add against a
    # single register.
    source = game_with_stage(
        "x = 1+2+3+4+5+y;", "volatile { int x = 0; int y = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    lines = cmds.splitlines()
    addby_lines = [line for line in lines if "ADDBY" in line]
    setvar_lines = [line for line in lines if "SETVAR" in line]
    assert len(addby_lines) == 1
    assert any("0x0000000f" in line for line in setvar_lines)


# --- gamequeer#453: same-precedence chain nested inside a differently- ------
# --- precedenced parent via parens -------------------------------------------
#
# A bare/outermost "(a + b + c)" -- the RHS of "x = (a + b + c);", or any
# fully-parenthesized subexpression at the *top* of an assignment/condition
# -- is handed to parser.parse_int_expression directly, whose own >3-token
# branch left-folds it before it's ever built into an IntExpression (see the
# "flat chain" and "fully parenthesized" sections above). But a
# same-precedence chain of 3+ terms nested *inside* a differently-
# precedenced parent, e.g. the "748 + b + c" in "roll = a % (748 + b + c);"
# (gamequeer#453, blocking the BLOOPER cart, gq-games#49, whose generator
# emits exactly this shape), never reaches parse_int_expression as its own
# invocation: pyparsing's infix_notation matches a parenthesized sub-group
# via its own internal Forward, which doesn't run int_expression's parse
# action on that sub-group's content. It arrives at
# IntExpression.get_result_symbol (datamodel.py) as a single flat >3-token
# list instead of already being reduced to nested
# [operand, operator, operand] triples, and before this fix that branch
# unconditionally raised `ValueError: Invalid subexpression length N: should
# be [operand, operator, operand] or [operator operand]`.
#
# Per gamequeer#331/#341/#345 precedent (see this module's docstring),
# correctness is asserted cheaply from the emitted `cmds.gqasm` listing --
# a fully-literal nested chain folds (gamequeer#385) to a single SETVAR
# literal whose value directly pins left-to-right evaluation order, and a
# mixed literal/variable chain pins the real ADDBY/SUBBY op count and
# register-reuse shape the same way the flat-chain and outermost-
# parenthesized-chain tests above do. The exact issue repro shape (a nested
# `+` chain, non-associative-agnostic) and the BLOOPER end-to-end integration
# check are additionally verified against the headless emulator -- see
# gamequeer/tests/golden/nested_precedence_group.gq, whose second stage
# nests a `-` chain (order-*sensitive*) inside a `*` parent specifically to
# discriminate a wrong (right-)fold direction from a crash.


def test_nested_group_inside_binary_op_parent_previously_raised_now_compiles(compile_gq):
    # The issue's own minimal repro shape, verbatim: a 3-term same-
    # precedence `+` chain nested inside a `%` parent via parens. All
    # variables (not literals), so this exercises the real
    # IntExpression.get_result_symbol left-fold codegen path, not just
    # parser.py/fold_constant_int_expression's side of the fix.
    source = game_with_stage(
        "roll = a % (748 + b + c);",
        "volatile { int a = 0; int b = 0; int c = 0; int roll = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "MODBY" in cmds
    assert "ADDBY" in cmds


def test_nested_group_as_left_operand_previously_raised_now_compiles(compile_gq):
    # Same nested chain, but as the parent operator's *left* operand instead
    # of its right -- "(a + b + c) % d", the mirror image of the issue's own
    # "a % (748 + b + c)" repro.
    source = game_with_stage(
        "roll = (a + b + c) % d;",
        "volatile { int a = 0; int b = 0; int c = 0; int d = 0; int roll = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "MODBY" in cmds
    assert "ADDBY" in cmds


def test_nested_group_both_operands_previously_raised_now_compiles(compile_gq):
    # Both operands of the parent operator are their own nested 3+-term
    # chains: "(a + b + c) % (d + e + f)".
    source = game_with_stage(
        "roll = (a + b + c) % (d + e + f);",
        "volatile { int a = 0; int b = 0; int c = 0; int d = 0; int e = 0; int f = 0; int roll = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "MODBY" in cmds
    assert cmds.count("ADDBY") >= 2


def test_nested_group_5_term_chain_previously_raised_now_compiles(compile_gq):
    # One level deeper than the issue's own 3-term repro: a 5-term nested
    # chain ("1 + b + c + d + e"), all variables past the leading literal so
    # it can't fold away and has to recurse through
    # IntExpression.get_result_symbol's left-fold more than once.
    source = game_with_stage(
        "roll = a % (1 + b + c + d + e);",
        "volatile { int a = 0; int b = 0; int c = 0; int d = 0; int e = 0; int roll = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "MODBY" in cmds
    assert cmds.count("ADDBY") == 4


def test_nested_group_doubly_nested_previously_raised_now_compiles(compile_gq):
    # Two levels of nesting: the previously-crashing shape itself
    # ("a % (b + c + d)") as one operand of a further-outer `+`.
    source = game_with_stage(
        "roll = (a % (b + c + d)) + e;",
        "volatile { int a = 0; int b = 0; int c = 0; int d = 0; int e = 0; int roll = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "MODBY" in cmds
    assert "ADDBY" in cmds


def test_nested_group_fully_literal_evaluates_left_to_right_subtraction(compile_gq):
    # gamequeer#385 folding: entirely literal, so this must fold all the way
    # to a single literal SETVAR -- and the *value* pins left-to-right
    # evaluation ((100-5)-9=86), not right-to-left (100-(5-9)=104), the
    # fold-direction check a purely-associative `+` chain can't provide (see
    # test_nested_shift_or_chain_* above for why `+`/`|` chains alone were
    # never sufficient to pin fold direction).
    source = game_with_stage("x = 1 * (100 - 5 - 9);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "SUBBY" not in cmds
    assert "MULBY" not in cmds
    setvar_lines = [line for line in cmds.splitlines() if "SETVAR" in line]
    assert len(setvar_lines) == 1
    assert "0x00000056" in setvar_lines[0]  # 86


def test_nested_group_fully_literal_evaluates_left_to_right_division(compile_gq):
    # Same fold-direction pin as above, but with `/`, whose C-truncating
    # semantics make left- vs right-fold diverge even more sharply:
    # (100/10)/3 == 3 (truncating), while 100/(10/3) == 100/3 == 33.
    source = game_with_stage("x = 1 + (100 / 10 / 3);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "DIVBY" not in cmds
    assert "ADDBY" not in cmds
    setvar_lines = [line for line in cmds.splitlines() if "SETVAR" in line]
    assert len(setvar_lines) == 1
    assert "0x00000004" in setvar_lines[0]  # 1 + (100/10/3) = 1 + 3 = 4


def test_nested_group_mixed_with_variable_stays_left_associative(compile_gq):
    # Same nested "100 - 5 - y" shape as
    # test_nested_subtraction_evaluates_nonassociatively_mixed_with_variable
    # above, but nested inside a differently-precedenced `*` parent (the
    # gamequeer#453 shape) instead of being the bare/outermost RHS. The
    # purely-literal leading pair "100 - 5" folds to a single literal 95
    # first (gamequeer#385), and only the final "- y" survives as a real
    # SUBBY against that folded literal -- pinning the same single-SUBBY,
    # left-associative codegen shape the outermost version already pins,
    # now for the nested case gamequeer#453 fixes.
    source = game_with_stage(
        "x = 1 * (100 - 5 - y);", "volatile { int x = 0; int y = 0; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    lines = cmds.splitlines()
    subby_lines = [line for line in lines if "SUBBY" in line]
    setvar_lines = [line for line in lines if "SETVAR" in line]
    assert len(subby_lines) == 1
    assert any("0x0000005f" in line for line in setvar_lines)  # literal 95 (0x5f)
