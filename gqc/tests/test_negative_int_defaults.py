"""Regression coverage for gamequeer#359: a negative default value on an
`int` variable used to crash `gqc compile` with an `OverflowError`, but only
for `persistent` variables -- the equivalent `volatile` variable already
compiled correctly.

The end-to-end (CLI) cases below use the `compile_gq` fixture from
conftest.py, matching the accept/reject style of test_grammar.py. The
byte-level cases drive gqc in-process (see tests/support.py) so they can
inspect the actual on-cart encoding of the variable's default value instead
of just the exit code, without needing to reverse-engineer file offsets out
of the compiled `.gqgame` binary.
"""

import io
import struct

import pytest

from gqc import linker, parser, structs
from gqc.datamodel import Variable
from gqc.structs import OpCode

from .support import reset_compiler_state

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def _compile_in_process(decls: str):
    """Compile a minimal game with the given top-level `decls` (e.g. a
    `persistent { ... }` or `volatile { ... }` block) in-process, and return
    the full symbol table dict (keyed by section name, e.g. `.init`/`.var`)
    for inspection."""
    reset_compiler_state()
    linker.create_reserved_variables()
    source = f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ }} }}\n"
    parser.parse(io.StringIO(source))
    symbol_table = linker.create_symbol_table(table_dest=io.StringIO(), cmd_dest=io.StringIO())
    return symbol_table


# --- CLI (black-box) cases --------------------------------------------------


@pytest.mark.parametrize("storageclass", ["persistent", "volatile"])
def test_negative_int_default_compiles(compile_gq, storageclass):
    source = (
        f"{GAME_HEADER}"
        f"{storageclass} {{ int best_diff = -1; }}\n"
        "stage start { event enter { } }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


# --- in-process (white-box) cases -------------------------------------------


def test_persistent_negative_int_default_encodes_twos_complement():
    _compile_in_process("persistent { int best_diff = -1; }")

    var = Variable.var_table["best_diff"]
    assert var.value == -1

    encoded = var.to_bytes()
    assert len(encoded) == structs.GQ_INT_SIZE
    assert encoded == (-1 & 0xFFFFFFFF).to_bytes(structs.GQ_INT_SIZE, "little")
    assert struct.unpack(structs.GQ_INT_FORMAT, encoded)[0] == -1


def test_persistent_negative_int_default_distinguishes_from_pad_sentinel():
    # -100 (unlike -1) doesn't happen to share its two's-complement bit
    # pattern with the linker's 0xFFFFFFFF padding sentinel (linker.py's
    # `__pad.*` variables), so this pins down that the encoding is genuinely
    # signed two's complement and not just an accidental all-ones match.
    _compile_in_process("persistent { int best_diff = -100; }")

    var = Variable.var_table["best_diff"]
    encoded = var.to_bytes()
    assert struct.unpack(structs.GQ_INT_FORMAT, encoded)[0] == -100


def test_persistent_positive_int_default_still_encodes_unsigned():
    # Regression guard: non-negative persistent int defaults (including the
    # linker's own 0xFFFFFFFF padding sentinel, which is *not* a valid
    # signed int32) must keep encoding exactly as they did before this fix.
    _compile_in_process("persistent { int best_diff = 4000; }")

    var = Variable.var_table["best_diff"]
    encoded = var.to_bytes()
    assert encoded == (4000).to_bytes(structs.GQ_INT_SIZE, "little")

    pad_vars = [
        v for v in Variable.storageclass_table["persistent"].values()
        if v.name.startswith("__pad.")
    ]
    if pad_vars:
        for pad_var in pad_vars:
            assert pad_var.value == 0xFFFFFFFF
            assert pad_var.to_bytes() == b"\xff\xff\xff\xff"
    else:
        # The current layout always needs padding, but that's a property of
        # today's fixed-size header/reserved-variable layout, not something
        # this test should assume forever (a layout that lands exactly on
        # the 0x1000 boundary wouldn't generate any `__pad.*` variables).
        # Exercise the same unsigned-sentinel property directly instead of
        # skipping the assertion.
        sentinel_var = Variable("int", "__pad.sentinel_fallback", 0xFFFFFFFF, "persistent")
        assert sentinel_var.to_bytes() == b"\xff\xff\xff\xff"


def test_volatile_negative_int_default_encodes_as_literal_two_complement():
    symbol_table = _compile_in_process("volatile { int best_diff = -1; }")

    var = Variable.var_table["best_diff"]
    assert var.value == -1

    init_cmds = [
        cmd for cmd in symbol_table[".init"].values()
        if getattr(cmd, "dst_name", None) == "best_diff"
    ]
    assert len(init_cmds) == 1
    init_cmd = init_cmds[0]
    assert init_cmd.command_type == OpCode.SETVAR
    assert init_cmd.arg2 == -1

    # And it must actually serialize (this is the path the pre-fix bug
    # report said already worked; keep it covered so a future change to
    # Variable.to_bytes can't silently break it instead).
    encoded = init_cmd.to_bytes()
    assert len(encoded) == structs.GQ_OP_SIZE
