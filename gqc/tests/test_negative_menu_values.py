"""Regression coverage for gamequeer#362: a negative menu option value used
to crash `gqc compile` with an `OverflowError`, the `Menu.to_bytes()`
sibling of the `Variable.to_bytes()` bug fixed for gamequeer#359 (PR #361).

The end-to-end (CLI) case below uses the `compile_gq` fixture from
conftest.py, matching the accept/reject style of test_grammar.py. The
byte-level cases drive gqc in-process (see tests/support.py) so they can
inspect the actual on-cart encoding of each menu option's value instead of
just the exit code, without needing to reverse-engineer file offsets out of
the compiled `.gqgame` binary.
"""

import io
import struct

import pytest

from gqc import linker, parser, structs
from gqc.datamodel import Menu

from .support import reset_compiler_state

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def _compile_in_process(decls: str):
    """Compile a minimal game with the given top-level `decls` (e.g. a
    `menus { ... }` block) in-process, and return the resulting symbol
    table for inspection."""
    reset_compiler_state()
    linker.create_reserved_variables()
    source = f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ }} }}\n"
    parser.parse(io.StringIO(source))
    return linker.create_symbol_table(table_dest=io.StringIO(), cmd_dest=io.StringIO())


# --- CLI (black-box) cases --------------------------------------------------


def test_negative_menu_value_compiles(compile_gq):
    source = (
        f"{GAME_HEADER}"
        'menus { m1 { -1 : "neg"; 2 : "pos"; } }\n'
        "stage start { event enter { } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


# --- in-process (white-box) cases -------------------------------------------


def test_menu_negative_value_encodes_twos_complement():
    _compile_in_process('menus { m1 { -1 : "neg"; 2 : "pos"; } }')

    menu = Menu.menu_table["m1"]
    assert menu.options["neg"] == -1
    assert menu.options["pos"] == 2

    encoded = menu.to_bytes()

    # Layout: option_count (GQ_INT_SIZE), then per option: label
    # (GQ_STR_SIZE) + value (GQ_INT_SIZE), in declaration order.
    option_size = structs.GQ_STR_SIZE + structs.GQ_INT_SIZE
    count = int.from_bytes(encoded[: structs.GQ_INT_SIZE], "little")
    assert count == 2

    neg_value_bytes = encoded[
        structs.GQ_INT_SIZE + structs.GQ_STR_SIZE : structs.GQ_INT_SIZE + option_size
    ]
    assert neg_value_bytes == (-1 & 0xFFFFFFFF).to_bytes(structs.GQ_INT_SIZE, "little")
    assert struct.unpack(structs.GQ_INT_FORMAT, neg_value_bytes)[0] == -1

    pos_value_bytes = encoded[
        structs.GQ_INT_SIZE + option_size + structs.GQ_STR_SIZE :
        structs.GQ_INT_SIZE + option_size * 2
    ]
    assert struct.unpack(structs.GQ_INT_FORMAT, pos_value_bytes)[0] == 2


def test_menu_negative_value_distinguishes_from_unsigned_bit_pattern():
    # -100 (unlike -1) doesn't happen to share its two's-complement bit
    # pattern with any other plausible unsigned encoding, so this pins down
    # that the encoding is genuinely signed two's complement.
    _compile_in_process('menus { m1 { -100 : "neg"; } }')

    menu = Menu.menu_table["m1"]
    encoded = menu.to_bytes()
    value_bytes = encoded[structs.GQ_INT_SIZE + structs.GQ_STR_SIZE:]
    assert struct.unpack(structs.GQ_INT_FORMAT, value_bytes)[0] == -100


def test_menu_positive_value_still_encodes_unsigned():
    # Regression guard: non-negative menu option values must keep encoding
    # exactly as they did before this fix.
    _compile_in_process('menus { m1 { 4000 : "pos"; } }')

    menu = Menu.menu_table["m1"]
    encoded = menu.to_bytes()
    value_bytes = encoded[structs.GQ_INT_SIZE + structs.GQ_STR_SIZE:]
    assert value_bytes == (4000).to_bytes(structs.GQ_INT_SIZE, "little")
