"""Grammar accept/reject suite for gqc (gamequeer#331, epic gamequeer#329).

Every case here compiles a small .gq source through `compile_gq` (see
conftest.py) and asserts on the exit code, and for rejects, on a stderr
fragment. These are deliberately not golden/byte-comparison tests (that's
gamequeer#333) -- the goal is coverage of grammar edge cases that currently
have zero test coverage anywhere in the repo.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ANIM_GIF = REPO_ROOT / "examples" / "assets" / "animations" / "perf_mask_mask.gif"

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def game_with_stage(body: str, decls: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level declarations (e.g. a
    `volatile { ... }` block)."""
    return f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ {body} }} }}\n"


# --- badge_get operator forms -----------------------------------------------
# badge_get is documented in grammar.py as "a right-associative unary prefix
# operator, e.g. badge_get(x)". It's used both with and without parens, and
# combined with a following binary operator; but (like every other operator)
# it's only valid inside an expression -- it can't stand alone as a command.


def test_badge_get_call_form_accepts(compile_gq):
    source = game_with_stage("x = badge_get(5);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_badge_get_bare_operand_accepts(compile_gq):
    source = game_with_stage(
        "x = badge_get y;", "volatile { int x = 0; int y = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_badge_get_combined_with_binary_op_accepts(compile_gq):
    source = game_with_stage(
        "x = badge_get(y) + 1;", "volatile { int x = 0; int y = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_badge_get_standalone_statement_rejects(compile_gq):
    # `badge_get y;` with no assignment target is not a valid event
    # statement -- badge_get only appears inside an int_expression.
    source = game_with_stage(
        "badge_get y;", "volatile { int y = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "ParseSyntaxException" in stderr


# --- badge_count() (gamequeer#387) -------------------------------------------
# Unlike badge_get, badge_count() is a nullary *call* -- no bare-operand
# form, and its parens are mandatory (empty) rather than wrapping an
# argument.


def test_badge_count_call_accepts(compile_gq):
    source = game_with_stage("x = badge_count();", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_badge_count_combined_with_binary_op_accepts(compile_gq):
    source = game_with_stage("x = badge_count() + 1;", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_badge_count_in_if_condition_accepts(compile_gq):
    # The realistic threshold-unlock idiom from the gamequeer#387 issue.
    source = game_with_stage(
        "if (badge_count() >= 5) { badge_set 42; }", "volatile { int x = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_badge_count_with_argument_rejects(compile_gq):
    # badge_count() is nullary -- Keyword("badge_count") commits (via the
    # grammar's `-`) as soon as "badge_count" itself matches, so a spurious
    # argument fails with a clean, source-located ParseSyntaxException
    # rather than silently being ignored or falling through to some other
    # (wrong) grammar interpretation.
    source = game_with_stage("x = badge_count(5);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "ParseSyntaxException" in stderr


def test_badge_count_standalone_statement_rejects(compile_gq):
    # Like badge_get, badge_count() only appears inside an int_expression --
    # it's not a statement on its own.
    source = game_with_stage("badge_count();")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0


def test_badge_count_prefixed_identifier_in_expression_accepts(compile_gq):
    # "badge_count" is matched via Keyword(), so it doesn't swallow a
    # badge_count-*prefixed* identifier -- same reasoning as
    # test_badge_get_prefixed_identifier_in_expression_accepts above
    # (gamequeer#354).
    source = game_with_stage(
        "y = badge_counter + 1;",
        "volatile { int badge_counter = 0; int y = 0; }",
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_badge_count_bare_no_parens_rejects(compile_gq):
    # Unlike badge_get, badge_count has no bare-operand form -- the parens
    # (even though empty) are mandatory.
    source = game_with_stage("x = badge_count;", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0


# --- fw_version() (gamequeer#411) ---------------------------------------------
# Same nullary-call shape as badge_count() above: mandatory-but-empty parens,
# no bare-operand form. test_fw_version.py covers what it actually lowers to
# (the compiler-injected probe stage) and the GQI_FW_VERSION write-protection
# it relies on; this section is just accept/reject grammar coverage.


def test_fw_version_call_accepts(compile_gq):
    source = game_with_stage("x = fw_version();", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_fw_version_combined_with_binary_op_accepts(compile_gq):
    source = game_with_stage("x = fw_version() + 1;", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_fw_version_in_if_condition_accepts(compile_gq):
    source = game_with_stage(
        "if (fw_version() == 0) { badge_set 42; }", "volatile { int x = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_fw_version_with_argument_rejects(compile_gq):
    # fw_version() is nullary -- Keyword("fw_version") commits (via the
    # grammar's `-`) as soon as "fw_version" itself matches, so a spurious
    # argument fails with a clean, source-located ParseSyntaxException.
    source = game_with_stage("x = fw_version(5);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "ParseSyntaxException" in stderr


def test_fw_version_standalone_statement_rejects(compile_gq):
    source = game_with_stage("fw_version();")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0


def test_fw_version_prefixed_identifier_in_expression_accepts(compile_gq):
    # "fw_version" is matched via Keyword(), so it doesn't swallow a
    # fw_version-*prefixed* identifier -- same reasoning as
    # test_badge_count_prefixed_identifier_in_expression_accepts above
    # (gamequeer#354).
    source = game_with_stage(
        "y = fw_version_flag + 1;",
        "volatile { int fw_version_flag = 0; int y = 0; }",
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_fw_version_bare_no_parens_rejects(compile_gq):
    # Like badge_count, fw_version has no bare-operand form -- the parens
    # (even though empty) are mandatory.
    source = game_with_stage("x = fw_version;", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0


def test_fw_version_write_rejects(compile_gq):
    # GQI_FW_VERSION is read-only by cart convention (gamequeer#411): writing
    # an as-yet-undefined reserved int corrupts adjacent RAM on firmware that
    # predates it (gamequeer#410). See test_fw_version.py for more on this.
    source = game_with_stage("GQI_FW_VERSION = 5;")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "read-only" in stderr


# --- random()/min()/max()/clamp()/abs() (gamequeer#422) -----------------------
# Unlike badge_count()/fw_version() above, these all take one or more
# int_expression *arguments* -- closer in grammar shape to str()'s
# `str(<int_expression>)` cast (below) than to badge_count()'s empty parens.
# test_random.py/test_math_intrinsics.py cover what they actually lower to;
# test_constant_folding.py covers folding (min/max/clamp/abs fold when their
# arguments do; random() never does). This section is just accept/reject
# grammar coverage, including the same Keyword-not-bare-string/commits-on-
# match care badge_count/fw_version/str already established.


def test_random_call_accepts(compile_gq):
    source = game_with_stage("x = random(1, 10);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_random_combined_with_binary_op_accepts(compile_gq):
    source = game_with_stage("x = random(1, 10) + 1;", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_random_accepts_full_expression_arguments(compile_gq):
    # Unlike badge_count()/fw_version(), random()'s arguments are full
    # int_expressions, not bare operands -- e.g. "y + 1", not just "y".
    source = game_with_stage(
        "x = random(y + 1, z * 2);", "volatile { int x = 0; int y = 0; int z = 5; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_random_wrong_arity_too_few_rejects(compile_gq):
    # random() is binary -- Keyword("random") commits (via the grammar's
    # `-`) as soon as "random" itself matches, so a missing argument fails
    # with a clean, source-located ParseSyntaxException rather than
    # silently falling through to some other (wrong) interpretation.
    source = game_with_stage("x = random(1);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "ParseSyntaxException" in stderr


def test_random_wrong_arity_too_many_rejects(compile_gq):
    source = game_with_stage("x = random(1, 10, 100);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "ParseSyntaxException" in stderr


def test_random_bare_no_parens_rejects(compile_gq):
    source = game_with_stage("x = random;", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0


def test_random_prefixed_identifier_in_expression_accepts(compile_gq):
    # "random" is matched via Keyword(), so it doesn't swallow a
    # random-*prefixed* identifier -- same reasoning as
    # test_badge_count_prefixed_identifier_in_expression_accepts above
    # (gamequeer#354).
    source = game_with_stage(
        "y = random_seed + 1;",
        "volatile { int random_seed = 0; int y = 0; }",
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_min_call_accepts(compile_gq):
    source = game_with_stage("x = min(1, 2);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_min_wrong_arity_rejects(compile_gq):
    source = game_with_stage("x = min(1);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "ParseSyntaxException" in stderr


def test_min_prefixed_identifier_in_expression_accepts(compile_gq):
    source = game_with_stage(
        "y = minimum + 1;", "volatile { int minimum = 0; int y = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_max_call_accepts(compile_gq):
    source = game_with_stage("x = max(1, 2);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_max_wrong_arity_rejects(compile_gq):
    source = game_with_stage("x = max(1, 2, 3);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "ParseSyntaxException" in stderr


def test_max_prefixed_identifier_in_expression_accepts(compile_gq):
    source = game_with_stage(
        "y = maximum + 1;", "volatile { int maximum = 0; int y = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_clamp_call_accepts(compile_gq):
    source = game_with_stage("x = clamp(5, 0, 10);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_clamp_wrong_arity_too_few_rejects(compile_gq):
    source = game_with_stage("x = clamp(5, 0);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "ParseSyntaxException" in stderr


def test_clamp_wrong_arity_too_many_rejects(compile_gq):
    source = game_with_stage("x = clamp(5, 0, 10, 20);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "ParseSyntaxException" in stderr


def test_clamp_prefixed_identifier_in_expression_accepts(compile_gq):
    source = game_with_stage(
        "y = clamped + 1;", "volatile { int clamped = 0; int y = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_abs_call_accepts(compile_gq):
    source = game_with_stage("x = abs(-5);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_abs_wrong_arity_rejects(compile_gq):
    source = game_with_stage("x = abs(1, 2);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "ParseSyntaxException" in stderr


def test_abs_bare_no_parens_rejects(compile_gq):
    source = game_with_stage("x = abs;", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0


def test_abs_prefixed_identifier_in_expression_accepts(compile_gq):
    source = game_with_stage(
        "y = absolute + 1;", "volatile { int absolute = 0; int y = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


# --- str() cast: whole-RHS and inline (gamequeer#386) ------------------------


def test_str_cast_whole_rhs_accepts(compile_gq):
    source = game_with_stage(
        's := str(x);', "volatile { int x = 0; str s := \"\"; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_str_cast_inline_in_concat_chain_accepts(compile_gq):
    # gamequeer#386: str(x) is no longer restricted to the entire RHS of a
    # string assignment -- it can appear as one operand of a `+`
    # concatenation chain too.
    source = game_with_stage(
        's := str(x) + "b";', "volatile { int x = 0; str s := \"\"; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_str_cast_inline_at_head_of_chain_accepts(compile_gq):
    source = game_with_stage(
        's := str(x) + "b" + "c";', "volatile { int x = 0; str s := \"\"; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_str_cast_inline_multiple_in_one_chain_accepts(compile_gq):
    source = game_with_stage(
        's := str(x) + "-" + str(y);',
        "volatile { int x = 0; int y = 0; str s := \"\"; }",
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_str_cast_of_literal_expression_inline_accepts(compile_gq):
    # Interplay with gamequeer#385: the cast's argument doesn't need to be
    # a bare literal, just fold to one -- an arithmetic expression works
    # the same way it does for a whole-RHS str().
    source = game_with_stage(
        's := "n=" + str(2 + 3);', "volatile { str s := \"\"; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_str_cast_nested_str_of_str_rejects_cleanly(compile_gq):
    # str()'s argument is an int_expression; another str(...) isn't a valid
    # int_expression operand, so this is a plain grammar rejection, not a
    # crash.
    source = game_with_stage(
        's := str(str(x));', "volatile { int x = 0; str s := \"\"; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Traceback" not in stderr


def test_str_cast_of_string_literal_rejects_cleanly(compile_gq):
    # str()'s argument must be an int_expression -- a quoted string isn't
    # one.
    source = game_with_stage(
        's := str("5");', "volatile { str s := \"\"; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Traceback" not in stderr


def test_str_cast_as_standalone_statement_rejects_cleanly(compile_gq):
    # str(x) is only ever valid as an operand -- of `:=` (whole-RHS) or of
    # `+` (inline) -- never as a bare statement on its own.
    source = game_with_stage("str(x);", "volatile { int x = 0; }")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Traceback" not in stderr


# --- animation option forms --------------------------------------------------
# animation_options accepts a bare `;` (no options), a single inline option
# (which already ends in its own `;`), or a `{ ... }` block of options.


@pytest.mark.ffmpeg
@pytest.mark.parametrize(
    "option_clause",
    [";", "duration = 500;", "{ duration = 500; w = 64; }"],
    ids=["bare-semicolon", "single-inline", "braced-block"],
)
def test_animation_option_forms_accept(compile_gq, option_clause):
    source = game_with_stage(
        "badge_set 1;",
        f'animations {{ pmm <- "perf_mask_mask.gif" {option_clause} }}\n',
    )
    exit_code, stderr, _ = compile_gq(
        source, assets={"assets/animations/perf_mask_mask.gif": ANIM_GIF}
    )
    assert exit_code == 0, stderr


def test_animation_duplicate_option_rejects(compile_gq):
    # Not `ffmpeg`-marked: parse_animation_definition's duplicate-option
    # check runs in the loop that builds kwargs *before* it constructs
    # Animation(...), so this rejects before ffmpeg is ever invoked -- it
    # passes identically with or without a real ffmpeg on PATH.
    source = game_with_stage(
        "badge_set 1;",
        'animations { pmm <- "perf_mask_mask.gif" { duration = 500; duration = 600; } }\n',
    )
    exit_code, stderr, _ = compile_gq(
        source, assets={"assets/animations/perf_mask_mask.gif": ANIM_GIF}
    )
    assert exit_code != 0
    assert "Duplicate option duration for animation pmm" in stderr


# --- input events -------------------------------------------------------------


@pytest.mark.parametrize("button", ["A", "B", "<-", "->", "-"])
def test_input_event_button_accepts(compile_gq, button):
    source = f"{GAME_HEADER}stage start {{ event input({button}) badge_set 1; }}\n"
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_input_event_whitespace_around_parens_accepts(compile_gq):
    source = f"{GAME_HEADER}stage start {{ event input ( A ) badge_set 1; }}\n"
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_input_event_invalid_button_rejects(compile_gq):
    source = f"{GAME_HEADER}stage start {{ event input(C) badge_set 1; }}\n"
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "ParseSyntaxException" in stderr


def test_fgdone_invalid_slot_rejects(compile_gq):
    # Only fgdone(1) and fgdone(2) are valid -- there are two foreground
    # animation slots.
    source = f"{GAME_HEADER}stage start {{ event fgdone(3) badge_set 1; }}\n"
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Invalid fgdone number 3" in stderr


# --- game-block cardinality --------------------------------------------------
# game{} requires exactly one each of id, title, author, starting_stage, in
# any order (pyparsing's `&` "each" operator).


@pytest.mark.parametrize(
    "game_block,missing_key",
    [
        ('game { title := "T"; author := "A"; starting_stage = start; }', "id"),
        ('game { id = 1; author := "A"; starting_stage = start; }', "title"),
        ('game { id = 1; title := "T"; starting_stage = start; }', "author"),
        ('game { id = 1; title := "T"; author := "A"; }', "starting_stage"),
    ],
    ids=["missing-id", "missing-title", "missing-author", "missing-starting_stage"],
)
def test_game_block_missing_key_rejects(compile_gq, game_block, missing_key):
    source = f"{game_block}\nstage start {{ event enter {{ badge_set 1; }} }}\n"
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert missing_key in stderr


def test_game_block_duplicate_key_rejects(compile_gq):
    # Pins current behavior: pyparsing's "each" operator can't tell a
    # duplicate `id` from a missing everything-else, so the diagnostic
    # names the *other* three keys as "missing" rather than naming `id` as
    # duplicated. See gamequeer#331 investigation notes.
    source = (
        'game { id = 1; id = 2; title := "T"; author := "A"; starting_stage = start; }\n'
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Missing one or more required elements" in stderr


def test_game_block_shuffled_order_accepts(compile_gq):
    source = (
        'game { starting_stage = start; author := "A"; title := "T"; id = 1; }\n'
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


# --- negative literal vs. binary minus; left-associativity ------------------


def test_unspaced_minus_parses_as_binary_subtraction(compile_gq):
    # `10 -5` (no space before the 5) must still parse as `10 - 5`, not as
    # the two operands `10` and a negative literal `-5` with no operator
    # between them -- the latter would be a grammar-level parse error (two
    # adjacent operands with nothing joining them), not a silently wrong
    # value, so a correct fold to 5 is proof enough it parsed as intended.
    # Both operands are literals, so gamequeer#385 folds this to a single
    # literal 5 at parse time; before gamequeer#385 this asserted a SUBBY
    # op was present, but that alone never actually checked the computed
    # value was correct.
    source = game_with_stage("x = 10 -5;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "SUBBY" not in cmds
    setvar_lines = [line for line in cmds.splitlines() if "SETVAR" in line]
    assert len(setvar_lines) == 1
    assert "0x00000005" in setvar_lines[0]


def test_left_assoc_chain_evaluates_left_to_right(compile_gq):
    # Regression coverage for gamequeer#330/#341: `10 - 5 - 2` must compile
    # as (10 - 5) - 2 = 3, not 10 - (5 - 2) = 7. All three operands are
    # literals, so gamequeer#385 folds the whole expression to that single
    # literal 3 at parse time -- a naive right-to-left fold would wrongly
    # give 7, so this remains a real left-associativity regression guard,
    # just checking the folded *value* instead of the (now absent) SUBBY op
    # stream. See gamequeer#334's dedicated codegen suite
    # (test_codegen.py::test_left_assoc_subtraction_chain_mixed_with_
    # variable_folds_left) for this same left-fold order still pinned via a
    # non-foldable trailing operand.
    source = game_with_stage("x = 10 - 5 - 2;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "SUBBY" not in cmds
    setvar_lines = [line for line in cmds.splitlines() if "SETVAR" in line]
    assert len(setvar_lines) == 1
    assert "0x00000003" in setvar_lines[0]


# --- comments and empty event bodies ----------------------------------------


def test_comments_accept(compile_gq):
    source = (
        "// leading line comment\n"
        f"{GAME_HEADER}"
        "/* block comment */\n"
        "stage start {\n"
        "    // comment inside a stage\n"
        "    event enter {\n"
        "        badge_set 1; // trailing comment on a statement\n"
        "    }\n"
        "}\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_empty_event_body_accepts(compile_gq):
    source = f"{GAME_HEADER}stage start {{ event enter {{ }} }}\n"
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


# --- duplicate-name rejects ---------------------------------------------------


def test_duplicate_stage_name_rejects(compile_gq):
    source = (
        f"{GAME_HEADER}"
        "stage start { event enter { badge_set 1; } }\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Stage start already defined" in stderr


def test_duplicate_menu_name_rejects(compile_gq):
    source = (
        f"{GAME_HEADER}"
        'menus { m { 1: "a"; } m { 1: "b"; } }\n'
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Menu m already defined" in stderr


def test_duplicate_animation_name_rejects(compile_gq):
    source = (
        f"{GAME_HEADER}"
        'animations { circ <- "circle.bmp"; circ <- "circle.bmp"; }\n'
        "stage start { event enter { badge_set 1; } }\n"
    )
    circle_bmp = REPO_ROOT / "gqc" / "examples" / "skel" / "assets" / "animations" / "circle.bmp"
    exit_code, stderr, _ = compile_gq(
        source, assets={"assets/animations/circle.bmp": circle_bmp}
    )
    assert exit_code != 0
    assert "Animation circ already defined" in stderr


def test_duplicate_variable_name_across_sections_rejects(compile_gq):
    # A variable name reused across two *different* storage-class sections
    # takes the clean diagnostic path (Variable.__init__ raises ValueError,
    # caught and reported as a GqcParseError). Reusing a name *within the
    # same* volatile/persistent block takes the same clean path (fixed by
    # gamequeer#338); see test_diagnostics.py's
    # test_duplicate_variable_name_within_same_section_rejects_cleanly.
    source = (
        f"{GAME_HEADER}"
        "volatile { int x = 0; }\n"
        "persistent { int x = 1; }\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Duplicate definition of x" in stderr


def test_builtin_variable_redefinition_rejects(compile_gq):
    source = (
        f"{GAME_HEADER}"
        "volatile { int GQI_FGANIM1_X = 0; }\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Cannot redefine builtin variable GQI_FGANIM1_X" in stderr


def test_second_volatile_section_rejects(compile_gq):
    source = (
        f"{GAME_HEADER}"
        "volatile { int x = 0; }\n"
        "volatile { int y = 0; }\n"
        "stage start { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Storage class volatile already defined" in stderr


def test_menu_and_textmenu_conflict_rejects(compile_gq):
    source = (
        f"{GAME_HEADER}"
        'menus { m { 1: "a"; } }\n'
        "stage start { menu m; textmenu; event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Stage cannot have both a menu and text entry prompt" in stderr


# --- string and menu-option size limits --------------------------------------


def test_21_char_string_accepts(compile_gq):
    source = game_with_stage(
        "badge_set 1;", 'volatile { str s := "' + ("a" * 21) + '"; }'
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_22_char_string_rejects(compile_gq):
    source = game_with_stage(
        "badge_set 1;", 'volatile { str s := "' + ("a" * 22) + '"; }'
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "exceeds maximum of 21" in stderr


def test_6_option_menu_accepts(compile_gq):
    options = "".join(f'{i}: "opt{i}"; ' for i in range(6))
    source = (
        f"{GAME_HEADER}"
        f"menus {{ m {{ {options}}} }}\n"
        "stage start { menu m; event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_7_option_menu_rejects(compile_gq):
    options = "".join(f'{i}: "opt{i}"; ' for i in range(7))
    source = (
        f"{GAME_HEADER}"
        f"menus {{ m {{ {options}}} }}\n"
        "stage start { menu m; event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "too many options" in stderr


# --- keyword-prefixed identifiers (gamequeer#354) ----------------------------
# Several bare-string grammar literals (`pp.Suppress("str")`,
# `pp.Suppress("if")`, `pp.Suppress("else")`, and the `badge_get` unary
# operator, all matched via a plain `Literal` rather than a word-boundary-
# anchored `Keyword`) used to greedily consume a matching prefix of a longer
# identifier -- e.g. `str_scratch` lost its leading "str" to the `str(...)`
# cast literal. Because these all sit ahead of `-` (And, "no backtrack")
# operators, the mismatch after the truncated match surfaced as a hard
# ParseSyntaxException rather than falling through to try the identifier as
# a whole. `badge_get`/`else` are worse: since nothing *requires* the
# character after the literal to be non-identifier, a colliding identifier
# can still fully parse, just as the *wrong* tokens (see
# test_else_prefixed_identifier_accepts and
# test_badge_get_prefixed_identifier_in_expression_accepts below, which pin
# the corrupted-but-non-crashing failure mode against fresh regressions).


def test_str_prefixed_str_var_accepts(compile_gq):
    # The original gamequeer#354 report: a `str`-prefixed str variable name
    # used as the RHS operand of another string assignment used to trip the
    # `str(...)` cast literal.
    source = game_with_stage(
        's := str_scratch;',
        'volatile { str str_scratch := "x"; str s := ""; }',
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


@pytest.mark.parametrize(
    "prefix",
    ["int", "timer", "cue", "play", "loop"],
)
def test_int_keyword_prefixed_var_accepts(compile_gq, prefix):
    # Keyword-prefixed int variable names, both as an assignment target and
    # as an operand inside an int_expression.
    varname = f"{prefix}_v"
    source = game_with_stage(
        f"{varname} = {varname} + 1;",
        f"volatile {{ int {varname} = 0; }}",
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_badge_get_prefixed_identifier_in_expression_accepts(compile_gq):
    # `badge_get` is matched as one alternative of a bare-string oneOf(...)
    # inside int_expression's infixNotation; `badge_getter` used to lose its
    # leading `badge_get` to that operator, leaving a bogus `ter` operand.
    source = game_with_stage(
        "y = badge_getter + 1;",
        "volatile { int badge_getter = 0; int y = 0; }",
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_if_prefixed_identifier_as_assignment_target_accepts(compile_gq):
    # `ifconfig = 5;` used to lose its leading `if` to if_statement's
    # `Suppress("if")`, then hard-fail expecting `(`.
    source = game_with_stage(
        "ifconfig = 5;", "volatile { int ifconfig = 0; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_else_prefixed_identifier_accepts(compile_gq):
    # `elsewhere = 5;` immediately after a real if-block's true branch used
    # to have its leading `else` silently consumed by if_statement's
    # optional `Suppress("else")` (no word-boundary check), leaving `where =
    # 5;` to parse as its own (bogus) assignment -- a silent corruption
    # rather than a parse error. The if-condition here is a variable
    # comparison (not a bare literal) to route around an unrelated,
    # pre-existing CommandIf bug (see gamequeer#354's PR) that only
    # misfires for literal-only if-conditions.
    source = game_with_stage(
        "if (x == 1) { badge_set 1; } elsewhere = 5;",
        "volatile { int x = 0; int elsewhere = 0; }",
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_stage_prefixed_stage_name_accepts(compile_gq):
    source = (
        'game { id = 1; title := "T"; author := "A"; starting_stage = stage_one; }\n'
        "stage stage_one { event enter { gostage stage_two; } }\n"
        "stage stage_two { event enter { badge_set 1; } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


# --- real keywords still parse as keywords (not swallowed by the fix) -------


def test_str_cast_still_works_alongside_str_prefixed_var(compile_gq):
    source = game_with_stage(
        's := str(x);',
        "volatile { int x = 0; str s := \"\"; str str_scratch := \"y\"; }",
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_bare_timer_statement_still_works(compile_gq):
    source = game_with_stage("timer 5;")
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_if_else_statement_still_works(compile_gq):
    source = game_with_stage(
        "if (x == 1) { badge_set 1; } else { badge_clear 1; }",
        "volatile { int x = 0; }",
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr
