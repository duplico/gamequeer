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
"""

import pathlib

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
    source = game_with_stage("x = (1 + 2);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    addby_lines = [line for line in cmds.splitlines() if "ADDBY" in line]
    assert len(addby_lines) == 1
    assert "0x00000002" in addby_lines[0]


def test_fully_parenthesized_chain_compiles_with_correct_value(compile_gq):
    # The parenthesized RHS is itself a >3-token left-fold chain, so this
    # exercises both bugs at once: the fold first reduces "1+2+3+4" to a
    # single IntExpression, and then the outer bare-atom re-invocation used
    # to crash trying to len() that already-built IntExpression.
    source = game_with_stage("x = (1 + 2 + 3 + 4);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    addby_lines = [line for line in cmds.splitlines() if "ADDBY" in line]
    # Single accumulator register throughout -- same left-fold guarantee as
    # the unparenthesized chain (gamequeer#341).
    assert len(addby_lines) == 3
    assert "0x00000002" in addby_lines[0]
    assert "0x00000003" in addby_lines[1]
    assert "0x00000004" in addby_lines[2]
    dest_regs = {line.split()[3] for line in addby_lines}
    assert len(dest_regs) == 1


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


def test_nested_shift_or_chain_4_pairs_register_exhaustion_boundary(compile_gq):
    # Pin the current (post-fix) 4-register-exhaustion boundary: gqc has
    # exactly 4 int registers (GQ_REGISTERS_INT), and this shape's 4 nested
    # `(1<<a)|(1<<b)` groups each need a register alive concurrently with
    # its enclosing OR, exhausting the pool. This is a clean, documented
    # GqcParseError-style diagnostic, not a crash.
    source = game_with_stage(
        f"mask = {nested_shift_or_chain(4)};", "volatile { int mask = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert_no_traceback(stderr)
    assert "No free registers available" in stderr


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
    # result. Was already correct pre-#345-fix (the outer expression isn't a
    # bare parenthesized atom, so the buggy re-invocation path wasn't hit)
    # -- pinned here as a regression guard now that parse_int_expression's
    # atom-passthrough logic has changed.
    source = game_with_stage("x = 10 - (5 - (2 - 1));", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    lines = cmds.splitlines()
    subby_lines = [line for line in lines if "SUBBY" in line]
    setvar_lines = [line for line in lines if "SETVAR" in line]
    assert len(subby_lines) == 3
    # Innermost "2 - 1" is the only SUBBY against an immediate; the outer two
    # subtract a previously-computed register result (5 and 10 arrive as
    # SETVAR-loaded literals, then SUBBY operates register-to-register).
    assert "0x00000001" in subby_lines[0]  # 2 - 1
    assert any("0x00000002" in line for line in setvar_lines)  # literal 2
    assert any("0x00000005" in line for line in setvar_lines)  # literal 5
    assert any("0x0000000a" in line for line in setvar_lines)  # literal 10 (0x0a)


# --- flat chain stays single-register ---------------------------------------


def test_flat_6_term_chain_stays_single_register(compile_gq):
    source = game_with_stage("x = 1+2+3+4+5+6;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    addby_lines = [line for line in cmds.splitlines() if "ADDBY" in line]
    assert len(addby_lines) == 5
    dest_regs = {line.split()[3] for line in addby_lines}
    assert len(dest_regs) == 1
