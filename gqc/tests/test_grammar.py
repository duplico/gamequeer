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


# --- str() cast: whole-RHS only ---------------------------------------------


def test_str_cast_whole_rhs_accepts(compile_gq):
    source = game_with_stage(
        's := str(x);', "volatile { int x = 0; str s := \"\"; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_str_cast_partial_rhs_rejects(compile_gq):
    # str(x) is only valid as the entire RHS of a string assignment, not as
    # one operand of a `+` concatenation expression.
    source = game_with_stage(
        's := str(x) + "b";', "volatile { int x = 0; str s := \"\"; }"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Expected ';'" in stderr


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


@pytest.mark.ffmpeg
def test_animation_duplicate_option_rejects(compile_gq):
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
    # between them.
    source = game_with_stage("x = 10 -5;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    assert "SUBBY" in cmds


def test_left_assoc_chain_evaluates_left_to_right(compile_gq):
    # Regression coverage for gamequeer#330/#341: `10 - 5 - 2` must compile
    # as (10 - 5) - 2 = 3, not 10 - (5 - 2) = 7. Asserted cheaply from the
    # emitted gqasm listing (two SUBBY ops against immediates 5 then 2, in
    # that order) rather than a full bytecode/VM run -- see gamequeer#334
    # for the dedicated codegen suite.
    source = game_with_stage("x = 10 - 5 - 2;", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr
    cmds = (out_dir / "cmds.gqasm").read_text()
    subby_lines = [line for line in cmds.splitlines() if "SUBBY" in line]
    assert len(subby_lines) == 2
    assert "0x00000005" in subby_lines[0]
    assert "0x00000002" in subby_lines[1]


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
    # caught and reported as a GqcParseError). Note: reusing a name *within
    # the same* volatile/persistent block currently crashes with an
    # unhandled AttributeError instead -- both definitions are constructed
    # before either has a storageclass assigned, so the duplicate-name
    # check's `.storageclass.startswith(...)` hits None. Not covered here;
    # flagged for gamequeer#338 (latent traps).
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
