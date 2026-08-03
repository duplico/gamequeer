"""`random(lo, hi)` intrinsic suite for gqc (gamequeer#422, part of epic
gamequeer#419).

`random(lo, hi)` desugars to the exact hand-rolled Park-Miller "minimal
standard" LCG the game corpus already hand-rolls at the source level -- see
e.g. gq-games/games/donsol.gq's card-shuffle `lcg` (seed = GQI_PLAYER_ID *
7919 + a per-call counter, normalized into [1, modulus - 1], then advanced
one step via Schrage's method) -- mapped into the caller's inclusive
`[lo, hi]` range. FROZEN VM CONTRACT: every step is an *existing*
`CommandArithmetic`/`CommandIf` op (`SETVAR`/`ADDBY`/`SUBBY`/`MULBY`/
`DIVBY`/`MODBY`/`LT`/`LE`/`NEG`/`GOTOIFN`); there's no dedicated opcode.

The LCG state (`structs.GQ_RANDOM_STATE_VAR`) and per-call counter
(`structs.GQ_RANDOM_CTR_VAR`) are hidden volatile variables, created lazily
-- only for a game that actually calls random() somewhere -- by
`linker.create_random_state_variables` (see `IntExpression._emit_random`,
`gqc/src/gqc/datamodel.py`, for the full derivation).

`test_grammar.py` covers accept/reject grammar forms; `test_constant_folding.py`
pins that `random()` never folds. This module covers the op-stream shape,
the hidden state's zero footprint when unused, and register-pressure/
re-entrancy when combined with other expressions.
"""

from gqc import structs

from .opstream import one_event, parse_gqasm

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def game_with_stage(body: str, decls: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level declarations (e.g. a
    `volatile { ... }` block)."""
    return f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ {body} }} }}\n"


def assert_no_traceback(stderr: str):
    assert "Traceback" not in stderr, f"raw Python traceback leaked to stderr:\n{stderr}"


def _compile_and_read(compile_gq, source: str, game_name: str = "game"):
    exit_code, stderr, out_dir = compile_gq(source, game_name=game_name)
    assert exit_code == 0, stderr
    cmds_text = (out_dir / "cmds.gqasm").read_text()
    map_text = (out_dir / "map.txt").read_text()
    return cmds_text, map_text


# --- op-stream shape ----------------------------------------------------------


def test_random_op_stream_shape(compile_gq):
    source = game_with_stage("x = random(1, 10);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    # range = hi - lo + 1; ctr += 1; state += GQI_PLAYER_ID * 7919 + ctr;
    # if (state < 0) state = -state; state = state % (m-1) + 1; one Schrage
    # step; if (state <= 0) state += m; result = state % range + lo. See
    # IntExpression._emit_random for the full derivation.
    assert [op.name for op in ops] == [
        "SETVAR", "SUBBY", "ADDBY",  # range = hi; range -= lo; range += 1
        "ADDBY",  # ctr += 1
        "SETVAR", "MULBY", "ADDBY", "ADDBY",  # seed = player_id * 7919 + ctr; state += seed
        "SETVAR", "LT", "GOTOIFN", "NEG",  # if (state < 0) state = -state;
        "MODBY", "ADDBY",  # state = state % (m - 1) + 1
        "SETVAR", "DIVBY", "MODBY", "MULBY", "MULBY", "SUBBY",  # Schrage step
        "SETVAR", "LE", "GOTOIFN", "ADDBY",  # if (state <= 0) state += m;
        "SETVAR", "MODBY", "ADDBY",  # result = state % range + lo
        "SETVAR",  # x = result
        "DONE",
    ]


def test_random_bytecode_size_is_fixed(compile_gq):
    # Same "fixed size, not proportional to anything" property badge_count()
    # has (gamequeer#387): random()'s own bytecode is always the same 27 ops
    # (270 bytes at GQ_OP_SIZE=10) for a literal-argument call, regardless of
    # which lo/hi literals are passed.
    source = game_with_stage("x = random(1, 10);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    random_ops = ops[:-2]  # everything but the assignment's own SETVAR + DONE
    assert len(random_ops) == 27


def test_random_literal_bounds_are_baked_in(compile_gq):
    source = game_with_stage("x = random(3, 12);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    range_setup = ops[0]  # SETVAR range = hi (literal 12)
    range_sub = ops[1]  # SUBBY range -= lo (literal 3)
    result_add = ops[-3]  # ADDBY result += lo (literal 3); ops[-2]/[-1] are x = result / DONE

    assert range_setup.flags & structs.OpFlags.LITERAL_ARG2 and range_setup.arg2 == 12
    assert range_sub.flags & structs.OpFlags.LITERAL_ARG2 and range_sub.arg2 == 3
    assert result_add.flags & structs.OpFlags.LITERAL_ARG2 and result_add.arg2 == 3


def test_random_reads_gqi_player_id(compile_gq):
    source = game_with_stage("x = random(1, 10);", "volatile { int x = 0; }")
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    player_id_addr = structs.gq_ptr_apply_ns(
        structs.GQ_PTR_BUILTIN_INT,
        next(v.addr for v in structs.GQ_RESERVED_INTS if v.name == "GQI_PLAYER_ID"),
    )
    load_player_id = next(
        op for op in ops
        if op.name == "SETVAR" and not (op.flags & structs.OpFlags.LITERAL_ARG2) and op.arg2 == player_id_addr
    )
    seed_mul = next(op for op in ops if op.name == "MULBY" and op.arg1 == load_player_id.arg1)
    assert seed_mul.flags & structs.OpFlags.LITERAL_ARG2
    assert seed_mul.arg2 == structs.GQ_RANDOM_SEED_MULTIPLIER == 7919


def test_random_never_writes_a_literal_directly_into_state(compile_gq):
    # The hidden LCG state variable is only ever written by an
    # accumulating ADDBY/NEG/MODBY/MULBY/SUBBY op (i.e. state op= something),
    # never a plain literal SETVAR -- it must always evolve from its own
    # prior value, not get stomped with a constant.
    source = game_with_stage("x = random(1, 10);", "volatile { int x = 0; }")
    _cmds_text, map_text = _compile_and_read(compile_gq, source)
    ops = one_event(_cmds_text).ops
    state_addr = int(
        next(
            line for line in map_text.splitlines()
            if structs.GQ_RANDOM_STATE_VAR in line and "Variable(" in line
        ).split()[0],
        16,
    )
    for op in ops:
        if op.arg1 == state_addr:
            assert op.name != "SETVAR", f"state variable written by a plain SETVAR: {op}"


# --- hidden state: zero footprint when unused, shared across calls ------------


def test_random_unused_creates_no_hidden_state(compile_gq):
    source = game_with_stage("badge_set 1;")
    _cmds_text, map_text = _compile_and_read(compile_gq, source)
    assert structs.GQ_RANDOM_STATE_VAR not in map_text
    assert structs.GQ_RANDOM_CTR_VAR not in map_text


def test_random_called_multiple_times_shares_one_state_and_counter(compile_gq):
    source = game_with_stage(
        "x = random(1, 10); y = random(1, 10);",
        "volatile { int x = 0; int y = 0; }",
    )
    _cmds_text, map_text = _compile_and_read(compile_gq, source)
    assert map_text.count(f"'{structs.GQ_RANDOM_STATE_VAR}'") == 1
    assert map_text.count(f"'{structs.GQ_RANDOM_CTR_VAR}'") == 1

    ctr_addr = int(
        next(
            line for line in map_text.splitlines()
            if structs.GQ_RANDOM_CTR_VAR in line and "Variable(" in line
        ).split()[0],
        16,
    )
    ops = one_event(_cmds_text).ops
    ctr_bumps = [op for op in ops if op.name == "ADDBY" and op.arg1 == ctr_addr]
    # Both calls' own "ctr += 1" step target the same (shared) counter address.
    assert len(ctr_bumps) == 2
    assert all(op.flags & structs.OpFlags.LITERAL_ARG2 and op.arg2 == 1 for op in ctr_bumps)


def test_random_volatile_declared_after_a_call_site_still_compiles(compile_gq):
    # Regression pin: create_random_state_variables is deferred until after
    # parsing (see its own docstring in linker.py) specifically so this
    # doesn't false-positive the "one volatile section per game" check --
    # random() is called in a stage that's parsed *before* the author's own
    # volatile{} section appears later in the same source file.
    source = (
        GAME_HEADER
        + "stage start { event enter { x = random(1, 10); } }\n"
        + "volatile { int x = 0; }\n"
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


# --- register pressure / re-entrancy -------------------------------------------


def test_random_combined_with_binary_op_compiles(compile_gq):
    source = game_with_stage("x = random(1, 10) + y;", "volatile { int x = 0; int y = 0; }")
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


def test_random_used_twice_in_one_expression_compiles(compile_gq):
    source = game_with_stage(
        "x = random(1, 10) + random(1, 10);", "volatile { int x = 0; }"
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


def test_random_with_non_literal_bounds_compiles(compile_gq):
    source = game_with_stage(
        "x = random(lo, hi);", "volatile { int x = 0; int lo = 0; int hi = 20; }"
    )
    exit_code, stderr, out_dir = compile_gq(source)
    assert exit_code == 0, stderr

    ops = one_event((out_dir / "cmds.gqasm").read_text()).ops
    range_setup = ops[0]
    assert not (range_setup.flags & structs.OpFlags.LITERAL_ARG2)  # loaded hi, not a literal


def test_random_with_full_expression_bounds_compiles(compile_gq):
    source = game_with_stage(
        "x = random(base - 1, base + 10);",
        "volatile { int x = 0; int base = 5; }",
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


# --- realistic usage ------------------------------------------------------------


def test_random_in_if_condition_compiles(compile_gq):
    source = game_with_stage(
        "if (random(0, 1) == 1) { badge_set 1; }",
    )
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr
