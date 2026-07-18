"""Smoke test for the in-process test-support helper (tests/support.py).

Not exercised by anything else in this package yet -- the grammar suite in
test_grammar.py drives gqc as a subprocess instead (see conftest.py's
compile_gq) -- but this proves reset_compiler_state() actually does its job:
parsing the same minimal game twice in one process, with a reset in
between, must not trip any of gqc's duplicate-definition checks.
"""

import io

from gqc import linker, parser

from .support import reset_compiler_state

MINIMAL_GAME = (
    'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'
    "stage start { event enter { badge_set 1; } }\n"
)


def test_reset_compiler_state_allows_reparsing_in_process():
    for _ in range(2):
        reset_compiler_state()
        linker.create_reserved_variables()
        parser.parse(io.StringIO(MINIMAL_GAME))
