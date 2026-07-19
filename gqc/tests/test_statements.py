"""`if`-statement regression suite for gamequeer#356.

`CommandIf.__init__` (`gqc/src/gqc/commands.py`) used to call
`super().__init__()` (`CommandWithIntExpressionArgument.__init__`) *before*
setting `self.true_cmds`/`self.false_cmds`. That parent `__init__`
unconditionally calls `self.resolve()` at its end, which -- because `self`
is a `CommandIf` -- dispatches to the overridden `CommandIf.resolve()`, not
the parent's own. That override iterates `self.true_cmds`, which didn't
exist yet.

This only actually crashed when the if-condition was a **bare integer
literal** (e.g. `if (1) { ... }`): a literal condition resolves
synchronously to `True` inside that first `resolve()` call, reaching the
`self.true_cmds` loop. Any condition referencing a variable (`if (x == 1)`)
instead returns `False` from that same first `resolve()` call (the
variable isn't linked yet), short-circuiting `CommandIf.resolve()`'s own
`if not super().resolve(): return False` guard *before* reaching the
`true_cmds` loop -- sidestepping the bug entirely, which is why no
pre-existing `.gq` example ever hit it.

The fix moves the `true_cmds`/`false_cmds`/section-size/`goto_cmd` setup
above the `super().__init__()` call, so that eager first `resolve()` call
has what it needs regardless of whether it's reached.

Per gamequeer#331/#341 precedent, correctness is asserted from the emitted
`cmds.gqasm` listing (GOTOIFN's flags/arg2 encode the literal condition;
the branch bodies and any `else`-arm `GOTO` are laid out as expected)
rather than a full bytecode/VM run. The behavior was additionally verified
end to end against the headless emulator during development: a pass/fail
gate cart (`cue lime` vs `cue red` chosen by an `if (1)`/`if (0)` literal
condition, observed via `--dump-leds`) discriminated correctly in both
polarities, which also caught and confirmed the fix for a second,
previously-unreachable bug this one exposed -- see the module-level note
below.
"""

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def game_with_stage(body: str, decls: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level declarations (e.g. a
    `volatile { ... }` block)."""
    return f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ {body} }} }}\n"


def assert_no_traceback(stderr: str):
    assert "Traceback" not in stderr, f"raw Python traceback leaked to stderr:\n{stderr}"


def gotoifn_line(cmds: str) -> str:
    lines = [line for line in cmds.splitlines() if "GOTOIFN" in line]
    assert len(lines) == 1, f"expected exactly one GOTOIFN line, got: {lines}"
    return lines[0]


# --- bare literal conditions (the exact gamequeer#356 repro shape) ---------


def test_literal_true_condition_compiles_clean(compile_gq):
    source = game_with_stage("if (1) { badge_set 1; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    fields = gotoifn_line(cmds).split()
    # Flags (index 3) carries LITERAL_ARG2 (0x08) only; arg2 (index 5) is
    # the literal condition value itself (1 == true).
    assert fields[3] == "0x08"
    assert fields[5] == "0x00000001"
    assert "QCSET" in cmds  # badge_set 1 -- the true branch survived.


def test_literal_false_condition_compiles_clean(compile_gq):
    source = game_with_stage("if (0) { badge_set 1; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    fields = gotoifn_line(cmds).split()
    assert fields[3] == "0x08"
    assert fields[5] == "0x00000000"
    assert "QCSET" in cmds  # still emitted -- the branch always compiles.


def test_literal_true_condition_with_else_compiles_clean(compile_gq):
    source = game_with_stage(
        "if (1) { badge_set 1; } else { badge_clear 1; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    fields = gotoifn_line(cmds).split()
    assert fields[3] == "0x08"
    assert fields[5] == "0x00000001"
    # Both arms compile, joined by the true-arm's GOTO past the false arm.
    assert "QCSET" in cmds
    assert "QCCLR" in cmds
    assert "GOTO " in cmds or "\nGOTO" in cmds


def test_literal_false_condition_with_else_compiles_clean(compile_gq):
    source = game_with_stage(
        "if (0) { badge_set 1; } else { badge_clear 1; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    fields = gotoifn_line(cmds).split()
    assert fields[3] == "0x08"
    assert fields[5] == "0x00000000"
    assert "QCSET" in cmds
    assert "QCCLR" in cmds


# --- parenthesized literal, e.g. `if ((1))` --------------------------------
# gamequeer#345/#358 added an atom-passthrough for a fully-parenthesized
# int_expression that collapses back to a bare literal operand; confirm
# that shape reaches CommandIf the same way a bare literal does, rather
# than being wrapped as an IntExpression.


def test_parenthesized_literal_true_condition_compiles_clean(compile_gq):
    source = game_with_stage("if ((1)) { badge_set 1; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    fields = gotoifn_line(cmds).split()
    assert fields[3] == "0x08"
    assert fields[5] == "0x00000001"


def test_parenthesized_literal_false_condition_compiles_clean(compile_gq):
    source = game_with_stage("if ((0)) { badge_set 1; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    fields = gotoifn_line(cmds).split()
    assert fields[3] == "0x08"
    assert fields[5] == "0x00000000"


# --- literal condition inside a loop's if ----------------------------------
# Distinct code path from a top-level stage-event if: the true branch here
# includes a `break`, whose own resolve() depends on the loop's exit
# address -- exercising CommandIf's eager true_cmds resolution against
# another Command subtype's resolve().


def test_literal_condition_inside_loop_compiles_clean(compile_gq):
    source = game_with_stage("loop { if (1) { badge_set 1; break; } }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    fields = gotoifn_line(cmds).split()
    assert fields[3] == "0x08"
    assert fields[5] == "0x00000001"


# --- nested if-in-if, both literal ------------------------------------------


def test_nested_literal_conditions_compile_clean(compile_gq):
    source = game_with_stage(
        "if (1) { if (0) { badge_set 1; } else { badge_set 2; } } else { badge_set 3; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    gotoifn_lines = [line for line in cmds.splitlines() if "GOTOIFN" in line]
    assert len(gotoifn_lines) == 2


# --- still-working variable-condition case (regression guard) --------------
# The pre-fix bug never reached this shape (see module docstring), but pin
# it anyway so a future change to CommandIf's resolve() ordering can't break
# it silently.


def test_variable_condition_still_works(compile_gq):
    source = game_with_stage(
        "if (x == 1) { badge_set 1; } else { badge_clear 1; }",
        "volatile { int x = 0; }",
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)
    cmds = (out_dir / "cmds.gqasm").read_text()
    fields = gotoifn_line(cmds).split()
    # Not a literal condition -- no LITERAL_ARG2 flag; arg2 is a variable address.
    assert fields[3] == "0x00"
