"""Smoke test for the in-process test-support helper (tests/support.py).

Not exercised by anything else in this package yet -- the grammar suite in
test_grammar.py drives gqc as a subprocess instead (see conftest.py's
compile_gq) -- but this proves reset_compiler_state() actually does its job:
parsing the same minimal game twice in one process, with a reset in
between, must not trip any of gqc's duplicate-definition checks.
"""

import io

from gqc import linker, parser
from gqc.datamodel import Cohort, Constant, Enum

from .support import reset_compiler_state

MINIMAL_GAME = (
    'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'
    "stage start { event enter { badge_set 1; } }\n"
)

# const/enum/cohort (gamequeer#421/#423) all register into their own
# class-level tables (Constant.const_table, Enum.enum_table,
# Cohort.cohort_table) directly from a parse action -- see
# parser.parse_const_definition/parse_enum_definition/
# parse_cohort_definition -- so re-parsing this twice without a reset would
# trip Constant.define's/Enum.define's/Cohort.__init__'s own
# duplicate-definition ValueErrors, exactly like the pre-#421 registries
# below already do.
GAME_WITH_CONST_ENUM_COHORT = (
    'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'
    "const MAX_HP = 21;\n"
    "enum Difficulty { Easy, Medium, Hard }\n"
    "cohort GUESTS = 300..319;\n"
    "stage start { event enter { badge_set 1; } }\n"
)


def test_reset_compiler_state_allows_reparsing_in_process():
    for _ in range(2):
        reset_compiler_state()
        linker.create_reserved_variables()
        parser.parse(io.StringIO(MINIMAL_GAME))


def test_reset_compiler_state_clears_const_enum_cohort_tables():
    # gamequeer#427 review: reset_compiler_state() was missing
    # Constant.const_table/Enum.enum_table/Cohort.cohort_table, so a second
    # in-process parse of a game with any const/enum/cohort declaration
    # would raise a spurious "already defined" error even on a clean
    # source, purely from the *first* parse's leftover state.
    for _ in range(2):
        reset_compiler_state()
        linker.create_reserved_variables()
        parser.parse(io.StringIO(GAME_WITH_CONST_ENUM_COHORT))

        assert Constant.const_table["MAX_HP"] == 21
        assert Constant.const_table["Difficulty.Easy"] == 0
        assert Constant.const_table["Difficulty.Medium"] == 1
        assert Constant.const_table["Difficulty.Hard"] == 2
        assert Enum.enum_table["Difficulty"] == ["Easy", "Medium", "Hard"]
        assert Cohort.cohort_table["GUESTS"].lo == 300
        assert Cohort.cohort_table["GUESTS"].hi == 319
