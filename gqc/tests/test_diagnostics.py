"""Diagnostics codification suite for gqc (gamequeer#337, epic gamequeer#329).

This is a *measurement baseline*, not a correctness suite: every case here
pins gqc's CURRENT exit code and stderr text for a category of compile-time
error, including a handful of cases where the current behavior is an
unhandled Python traceback rather than a clean diagnostic. Those are pinned
deliberately (and commented as such, with a cross-referenced issue) so that
fixing the underlying issue produces a visible, deliberate diff in this
suite instead of an invisible behavior change.

Scope notes:
  - test_grammar.py (gamequeer#331) already pins several reject diagnostics
    this issue's list also mentions: duplicate names (stage/menu/animation/
    variable), the game{} block's misleading duplicate-key message
    (gamequeer#142), and the string-length-at-declaration message. None of
    those are duplicated here.
  - gamequeer#335 (linker/cart-image suite) pins the *behavior* of the
    heap/persistent-size limits (i.e. that oversize carts are rejected).
    The two overflow cases here pin the exact *message text* instead; there
    is deliberately some light overlap in what gets exercised.
"""

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def game_with_stage(body: str, decls: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level declarations (e.g. a
    `volatile { ... }` block)."""
    return f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ {body} }} }}\n"


def assert_no_traceback(stderr: str):
    # Matches test_expressions.py's convention: check the broader "Traceback"
    # substring (not just the "(most recent call last):" header, which
    # varies with chained/grouped exceptions) and include stderr in the
    # assertion message so a failure is debuggable without rerunning.
    assert "Traceback" not in stderr, f"raw Python traceback leaked to stderr:\n{stderr}"


# --- undefined symbol references ---------------------------------------------
# `cue`, `gostage`, and `play` all reference another top-level definition by
# name, but they're resolved on three different schedules: `cue` is checked
# immediately at parse time (so it gets a real source location); `gostage`
# and `play` targets are only checked once at link time, once all commands'
# forward references have had a chance to resolve, so an unresolved one
# surfaces as a linker FATAL with no source location at all.


def test_undefined_cue_rejects_with_line_and_column(compile_gq):
    source = game_with_stage("cue nope;")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Error at line 3, column 28: Undefined cue nope" in stderr
    assert_no_traceback(stderr)


def test_undefined_gostage_target_rejects_as_linker_fatal_no_location(compile_gq):
    # Pins current behavior: unlike `cue` (checked at parse time, see above),
    # `gostage` targets are only checked at link time via the generic
    # unresolved-symbols sweep in linker.py's create_symbol_table, which has
    # no access to the original source location -- cross-ref gamequeer#232.
    source = game_with_stage("gostage nowhere;")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert (
        "FATAL: Unresolved symbols remain in command GOSTAGE 0: ['nowhere']"
        in stderr
    )
    assert_no_traceback(stderr)


def test_undefined_animation_in_play_rejects_as_linker_fatal_no_location(compile_gq):
    # Same link-time-only resolution path (and same gamequeer#232 cross-ref)
    # as gostage, above, just for CommandPlay instead of CommandGoStage.
    source = game_with_stage("play bganim nope;")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert (
        "FATAL: Unresolved symbols remain in command PLAYBG 0: ['nope']" in stderr
    )
    assert_no_traceback(stderr)


# --- undefined int identifier (gamequeer#428) --------------------------------
# `CommandWithIntExpressionArgument.resolve()` (gqc/src/gqc/commands.py) used
# to have no `else` branch for an int operand that names no known variable
# (or const/enum/builtin) at all: `self.arg2_name in Variable.var_table` being
# false just fell through without touching `unresolved_symbols` or `resolved`,
# so the command was reported resolved with `arg2` left at its zero-initialized
# default -- a typo'd or never-declared int identifier silently compiled to a
# literal 0 instead of failing to compile. Its string counterpart
# (CommandWithStrExpressionArgument.resolve(), just below) already had this
# `else` branch, so an undefined string identifier already hit the same
# link-time FATAL sweep as gostage/play above. The fix adds the missing
# branch so both types behave the same way.


def test_undefined_int_variable_rejects_instead_of_silently_reading_as_zero(
    compile_gq,
):
    source = game_with_stage("x = y;", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert (
        "FATAL: Unresolved symbols remain in command SETVAR: UNRESOLVED: ['y']"
        in stderr
    )
    assert_no_traceback(stderr)


def test_defined_int_variable_reference_still_accepts(compile_gq):
    # Sibling accept case for the reject test above: an int identifier that
    # *is* a known variable still resolves and compiles cleanly.
    source = game_with_stage(
        "x = y;", "volatile { int x = 0; int y = 5; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr
    assert_no_traceback(stderr)


# --- non-string menu/textmenu prompt -----------------------------------------
# Stage.resolve() raises a bare ValueError (not GqcParseError) if a bound
# prompt variable turns out not to be a string. Whether that ValueError is
# ever caught depends entirely on *when* it's raised relative to parsing:


def test_nonstring_prompt_defined_before_stage_rejects_cleanly(compile_gq):
    # The prompt variable is already in Variable.var_table by the time the
    # stage is parsed, so Stage.__init__'s own call to self.resolve() raises
    # the ValueError while still inside parse_stage_definition's try/except
    # ValueError -> GqcParseError, producing a normal clean diagnostic.
    source = (
        f"{GAME_HEADER}"
        "volatile { int p = 0; }\n"
        'menus { m { 1: "a"; } }\n'
        "stage start { menu m prompt p; event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Error at line 4, column 1: Prompt p is not a string" in stderr
    assert_no_traceback(stderr)


def test_nonstring_prompt_defined_after_stage_crashes_with_traceback(compile_gq):
    # Pins current *broken* behavior, cross-ref gamequeer#232: if the prompt
    # variable is instead declared *after* the stage that references it, the
    # stage doesn't yet have enough information to resolve at parse time, so
    # it's left unresolved and re-checked later from linker.py's
    # create_symbol_table (`for stage in Stage.stage_table.values(): if not
    # stage.resolve():`), which has no surrounding try/except at all. The
    # same ValueError that gets cleanly converted to a GqcParseError in the
    # "before" case instead propagates all the way out as an unhandled
    # Python traceback.
    source = (
        f"{GAME_HEADER}"
        'menus { m { 1: "a"; } }\n'
        "stage start { menu m prompt p; event enter { badge_set 1; } }\n"
        "volatile { int p = 0; }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Traceback (most recent call last):" in stderr
    assert "ValueError: Prompt p is not a string" in stderr
    assert "linker.py" in stderr and "stage.resolve()" in stderr


# --- str/int type-mismatch assignments ---------------------------------------
# Assigning a plain variable reference of the wrong type (as opposed to a
# literal, which the grammar routes through a different, type-specific path)
# is only caught once the destination command tries to resolve -- both
# directions produce a clean GqcParseError naming the *source* variable.


def test_string_assignment_of_int_variable_rejects(compile_gq):
    # `s := x;` where x is an int: `:=` accepts a bare identifier as a
    # string_operand regardless of the referenced variable's actual type,
    # so the type mismatch only surfaces when CommandSetStr resolves.
    source = game_with_stage(
        "s := x;", 'volatile { int x = 0; str s := ""; }'
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Error at line 3, column 28: Variable x is not a string" in stderr
    assert_no_traceback(stderr)


def test_int_assignment_of_str_variable_rejects(compile_gq):
    # `x = s;` where s is a str: the mirror-image case, via CommandSetInt.
    source = game_with_stage(
        "x = s;", 'volatile { int x = 0; str s := "hi"; }'
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Error at line 3, column 28: Variable s is not an int" in stderr
    assert_no_traceback(stderr)


# --- string-length violation: declaration vs. assignment (gamequeer#143) ----
# test_grammar.py's test_22_char_string_rejects already pins the
# declaration-time case ("str s := <22 chars>;"), where Variable.__init__'s
# length check names the *declared* variable. Assigning an overlong string
# literal to an already-declared variable inside an event body takes a
# different path -- Variable.get_str_literal interns the literal as its own
# auto-named persistent variable (`S<n>.strlit`) *before* the assignment
# command is ever built, so the same length check instead names that
# internal literal symbol, not the variable actually being assigned to.


def test_string_literal_length_violation_at_assignment_misnames_the_literal(compile_gq):
    source = game_with_stage(
        's := "' + ("a" * 22) + '";', 'volatile { str s := ""; }'
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert (
        "Error at line 3, column 34: String S0.strlit length 22 exceeds maximum of 21"
        in stderr
    )
    assert_no_traceback(stderr)


# --- Stage constructor validations (gamequeer#149) ---------------------------
# gamequeer#149's screenshot points at Stage.__init__'s `# TODO: Validate
# it's a valid event type` comment -- i.e. the constructor trusts its
# `events` argument's event_type values without checking them, which isn't
# reachable through normal grammar-driven parsing (the grammar itself
# restricts event_type tokens). The one validation in the same loop that
# *is* reachable through source text is the duplicate-event-type check,
# pinned below; it's not covered by test_grammar.py's duplicate-name family.


def test_duplicate_event_type_in_stage_rejects(compile_gq):
    source = (
        f"{GAME_HEADER}"
        "stage start { event enter { badge_set 1; } event enter { badge_set 2; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    # Note: EventType is an IntEnum, and its member prints as a bare integer
    # (0 == ENTER) in this f-string rather than its name.
    assert "Error at line 2, column 1: Event 0 already defined in stage start" in stderr
    assert_no_traceback(stderr)


# --- register exhaustion ------------------------------------------------------
# gamequeer#330/#341's left-fold codegen fix means a long *flat* chain of
# same-precedence operators (e.g. a 5-term `+` chain) no longer exhausts the
# 4-register int-expression pool (see gamequeer#342). A chain of nested
# unary operators still does: each level of unary nesting allocates a
# fresh register for its own result *before* recursing into its operand,
# and none of those intermediate registers are freed until the whole
# expression resolves -- so N nested unary ops need N simultaneously-live
# registers.


def test_register_exhaustion_via_nested_unary_negation_rejects(compile_gq):
    source = game_with_stage(
        "x = - - - - - a;", "volatile { int a = 1; int x = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Error at line 3, column 33: No free registers available" in stderr
    assert_no_traceback(stderr)


# --- heap/persistent size overflow (exit code 2) -----------------------------
# gamequeer#335 pins the *behavior* of these two hardware-derived size
# limits (that an oversize cart is rejected); these two cases pin the exact
# message text linker.py prints for each, which #335 doesn't assert on.


def test_volatile_heap_overflow_exits_2_with_message(compile_gq):
    # 200 extra volatile ints (800 bytes) plus the always-present register
    # variables (4 int + 4 str registers, 104 bytes) comfortably clears the
    # 512-byte heap limit.
    decls = "".join(f"int v{i} = 0; " for i in range(200))
    source = (
        f"{GAME_HEADER}"
        f"volatile {{ {decls}}}\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 2
    assert (
        "CRITICAL: Volatile variable table size exceeds maximum size of "
        "512 bytes; actual size is 904 bytes." in stderr
    )
    assert_no_traceback(stderr)


def test_persistent_section_overflow_exits_2_with_message(compile_gq):
    # 1100 extra persistent ints (4400 bytes) clears the 4 KB sector limit
    # even after accounting for the reserved per-badge persistent ints and
    # the CRC16 variable.
    decls = "".join(f"int v{i} = 0; " for i in range(1100))
    source = (
        f"{GAME_HEADER}"
        f"persistent {{ {decls}}}\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 2
    assert (
        "COMPILER ERROR: Persistent variable section exceeds 4 KB sector boundary."
        in stderr
    )
    assert (
        "This is a hardware limitation. Please reduce the use of persistent variables."
        in stderr
    )
    assert_no_traceback(stderr)


# --- same-section duplicate variable name (gamequeer#338) -------------------


def test_duplicate_variable_name_within_same_section_rejects_cleanly(
    compile_gq,
):
    # Flipped by gamequeer#338 (previously pinned the *broken* behavior:
    # reusing a variable name *within the same* volatile/persistent block
    # crashed with an unhandled AttributeError instead of a clean
    # GqcParseError). Both same-section definitions are constructed via
    # parse_variable_definition before either has a storageclass assigned
    # (that happens once for the whole block, afterwards, via
    # parse_variable_definition_storageclass), so
    # Variable.__init__'s duplicate-name check used to dereference
    # `.storageclass.startswith('builtin')` on a `None` storageclass.
    # Guarding that check now produces the same clean "Duplicate definition
    # of x" diagnostic as the cross-section case (see test_grammar.py's
    # test_duplicate_variable_name_across_sections_rejects).
    source = (
        f"{GAME_HEADER}"
        "volatile { int x = 0; int x = 1; }\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Duplicate definition of x" in stderr
    assert_no_traceback(stderr)


# --- duplicate storage-class section (gamequeer#338) -------------------------


def test_duplicate_storage_class_section_rejects_cleanly(compile_gq):
    # Exercises parse_variable_definition_storageclass's "already defined"
    # error path (a second `persistent { ... }` section reusing a storage
    # class already claimed by a real, non-init/non-register variable from
    # the first one). gamequeer#338 hardened this path's loop-variable
    # handling (it used to reference the `for` loop's variable directly,
    # which is only ever bound when the error condition is true today, but
    # was one refactor away from a NameError instead of this GqcParseError
    # if that stopped holding) -- this pins the fixed path's observable
    # behavior unchanged.
    source = (
        f"{GAME_HEADER}"
        "persistent { int a = 0; }\n"
        "persistent { int b = 1; }\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 1
    assert "Storage class persistent already defined by a" in stderr
    assert_no_traceback(stderr)
