"""`random(lo, hi)` intrinsic suite for gqc (gamequeer#422, part of epic
gamequeer#419).

`random(lo, hi)` desugars to a Park-Miller "minimal standard" LCG (seed =
GQI_PLAYER_ID * 7919 + a per-*call* counter, normalized into
[1, modulus - 1], then advanced one step via Schrage's method) mapped into
the caller's inclusive `[lo, hi]` range. FROZEN VM CONTRACT: every step is
an *existing* `CommandArithmetic`/`CommandIf` op (`SETVAR`/`ADDBY`/`SUBBY`/
`MULBY`/`DIVBY`/`MODBY`/`LT`/`LE`/`NEG`/`GOTOIFN`); there's no dedicated
opcode.

Only the *multiplicative core* (same modulus/multiplier/Schrage advance)
matches the LCG the game corpus already hand-rolls at the source level --
e.g. gq-games/games/donsol.gq's card-shuffle `lcg`. The *seeding* does NOT:
donsol.gq's own per-call counter (`ctr`) is sampled from a free-running
`timer` event for real wall-clock entropy, while `random()`'s hidden
`structs.GQ_RANDOM_CTR_VAR` only increments once per `random()` call and is
zero-initialized at boot -- so **the first `random()` call after a fresh
cart boot is a deterministic function of `GQI_PLAYER_ID` alone**, identical
on every reboot of the same badge. See `IntExpression._emit_random`
(`gqc/src/gqc/datamodel.py`) for the full derivation and the donsol-style
timer-salt workaround for authors who need real per-boot entropy.

The LCG state (`structs.GQ_RANDOM_STATE_VAR`) and per-call counter
(`structs.GQ_RANDOM_CTR_VAR`) are hidden volatile variables, created lazily
-- only for a game that actually calls random() somewhere -- by
`linker.create_random_state_variables`.

`test_grammar.py` covers accept/reject grammar forms; `test_constant_folding.py`
pins that `random()` never folds. This module covers the op-stream shape,
value-level correctness of the emitted arithmetic (against a Python
reference implementation of the documented recurrence, executed via a small
op interpreter -- `_execute_ops` below), the hidden state's zero footprint
when unused, and register-pressure/re-entrancy when combined with other
expressions.
"""

from gqc import structs
from gqc.datamodel import _c_truncating_divmod

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


# --- value-level correctness (executes the actual emitted ops) ----------------
#
# The op-stream-shape tests below (`test_random_op_stream_shape` etc.) only
# ever assert on op *names* -- that's exactly how a previous version of this
# module's own docstring, `_emit_random`'s docstring, and the PR body could
# all confidently (and wrongly) claim random() emits "the exact hand-rolled
# Park-Miller LCG donsol.gq already hand-rolls": the seeding-scheme mismatch
# (see module docstring above) doesn't change a single op *name* in the
# sequence, only the *values* flowing through it. `_execute_ops` is a tiny,
# faithful-enough interpreter for exactly the op subset `_emit_random` emits
# (SETVAR/ADDBY/SUBBY/MULBY/DIVBY/MODBY/LT/LE/NEG/GOTOIFN/DONE), so these
# tests can check actual output values against `_reference_random_sequence`,
# an independent Python reimplementation of the documented recurrence.


def _wrap_t_gq_int(value: int) -> int:
    """Truncate `value` into `t_gq_int`'s signed-32-bit range, the same
    wraparound the VM's native `int32` arithmetic performs (see
    `_c_truncating_divmod`'s own docstring for why this module can't just
    use Python's unbounded ints throughout). Not expected to actually
    trigger for the player-id/lo/hi values these tests exercise -- Schrage's
    method is specifically chosen so the Schrage step never does -- but
    applied after every write anyway so `_execute_ops` stays a faithful
    mini-VM rather than one that silently diverges from real hardware
    behavior if a future test ever does push a value that far."""
    return ((value + 2 ** 31) % 2 ** 32) - 2 ** 31


def _execute_ops(ops: list, memory: dict) -> dict:
    """Interpret `ops` (an `EventBlock.ops` list from `opstream.one_event`)
    against `memory` (address -> `t_gq_int`, mutated in place and returned;
    unwritten addresses read as 0, matching the VM's zero-initialized RAM),
    applying the same per-op semantics as the C VM's `run_arithmetic`/main
    dispatch loop (`gamequeer/src/bytecode.c`): every binary op computes
    `result = arg1 <op> arg2` and writes it back to arg1's address; `arg2`
    is `memory[op.arg2]` unless `OpFlags.LITERAL_ARG2` is set, in which case
    it's `op.arg2` itself; `NEG` is unary (`arg1 = -arg2`, no read of
    arg1's prior value); `GOTOIFN` jumps to the address in `op.arg1` when
    its condition (`arg2`, same literal-or-address rule as any other op)
    is falsy.

    Deliberately narrow: raises on any opcode `_emit_random` doesn't
    itself emit, rather than silently no-op'ing an unhandled one -- this is
    a test double for one specific op subset, not a general bytecode VM.
    """
    addr_index = {op.addr: i for i, op in enumerate(ops)}
    i = 0
    while i < len(ops):
        op = ops[i]
        arg2 = op.arg2 if (op.flags & structs.OpFlags.LITERAL_ARG2) else memory.get(op.arg2, 0)

        if op.name == "DONE":
            break
        elif op.name == "SETVAR":
            memory[op.arg1] = arg2
        elif op.name == "NEG":
            memory[op.arg1] = _wrap_t_gq_int(-arg2)
        elif op.name == "GOTOIFN":
            if not arg2:
                i = addr_index[op.arg1]
                continue
        else:
            arg1 = memory.get(op.arg1, 0)
            if op.name == "ADDBY":
                result = arg1 + arg2
            elif op.name == "SUBBY":
                result = arg1 - arg2
            elif op.name == "MULBY":
                result = arg1 * arg2
            elif op.name == "DIVBY":
                result, _ = _c_truncating_divmod(arg1, arg2)
            elif op.name == "MODBY":
                _, result = _c_truncating_divmod(arg1, arg2)
            elif op.name == "LT":
                result = int(arg1 < arg2)
            elif op.name == "LE":
                result = int(arg1 <= arg2)
            else:
                raise AssertionError(
                    f"_execute_ops doesn't model {op.name!r} -- either "
                    "_emit_random grew a new op this interpreter needs to "
                    "learn, or this test is being reused outside its "
                    "intended (random()-only) scope"
                )
            memory[op.arg1] = _wrap_t_gq_int(result)
        i += 1
    return memory


def _reference_random_sequence(player_id: int, lo: int, hi: int, n: int) -> list:
    """Independent Python reimplementation of the *documented* random()
    recurrence (see `IntExpression._emit_random`'s docstring and this
    module's own docstring above): a Park-Miller LCG state, zero at boot,
    perturbed on every call by `player_id * GQ_RANDOM_SEED_MULTIPLIER +
    ctr` (`ctr` incrementing once per call, starting at 0 -- NOT
    donsol.gq's free-running-timer `ctr`), then advanced one Schrage step
    and mapped into the caller's inclusive `[lo, hi]` range.

    Deliberately written from the recurrence's math, not by transcribing
    `_emit_random`'s own op sequence -- it needs to be an independent
    oracle, not a restatement of the code under test."""
    modulus = structs.GQ_RANDOM_LCG_MODULUS
    multiplier = structs.GQ_RANDOM_LCG_MULTIPLIER
    q = structs.GQ_RANDOM_LCG_Q
    r = structs.GQ_RANDOM_LCG_R
    seed_multiplier = structs.GQ_RANDOM_SEED_MULTIPLIER
    span = hi - lo + 1

    state = 0
    ctr = 0
    results = []
    for _ in range(n):
        ctr += 1
        state += player_id * seed_multiplier + ctr
        if state < 0:
            state = -state
        state = state % (modulus - 1) + 1
        # One Schrage step for state = (multiplier * state) mod modulus.
        # state/q are both positive here, so plain Python `//`/`%` already
        # agree with C's truncating division -- no need for
        # _c_truncating_divmod in this branch.
        t = state // q
        state = state % q
        state = state * multiplier - t * r
        if state <= 0:
            state += modulus
        results.append(state % span + lo)
    return results


def _var_addr(map_text: str, name: str) -> int:
    line = next(
        line for line in map_text.splitlines()
        if f"'{name}'," in line and "Variable(" in line
    )
    return int(line.split()[0], 16)


def test_random_bytecode_matches_reference_lcg_sequence(compile_gq):
    """Executes the actual emitted op-stream (not just op *names* -- see
    `test_random_op_stream_shape` below) for three back-to-back random()
    calls and checks the resulting sequence of *values* against
    `_reference_random_sequence`. This is the test that would have caught
    gamequeer#427's false parity claim: op-name-shape coverage alone can't
    distinguish "seeded the exact same way as donsol.gq" from "seeded a
    different (but equally shaped) way", since both compile to the same op
    mnemonics.
    """
    source = game_with_stage(
        "a = random(1, 1000); b = random(1, 1000); c = random(1, 1000);",
        "volatile { int a = 0; int b = 0; int c = 0; }",
    )
    cmds_text, map_text = _compile_and_read(compile_gq, source)
    ops = one_event(cmds_text).ops

    player_id_addr = structs.gq_ptr_apply_ns(
        structs.GQ_PTR_BUILTIN_INT,
        next(v.addr for v in structs.GQ_RESERVED_INTS if v.name == "GQI_PLAYER_ID"),
    )
    result_addrs = [_var_addr(map_text, name) for name in ("a", "b", "c")]

    for player_id in (0, 1, 12345, -7):
        memory = _execute_ops(ops, {player_id_addr: player_id})
        actual = [memory[addr] for addr in result_addrs]
        expected = _reference_random_sequence(player_id, 1, 1000, 3)
        assert actual == expected, f"player_id={player_id}"


def test_random_first_call_after_boot_is_deterministic_in_player_id(compile_gq):
    """Pins the actual, user-visible consequence of the seeding gap
    documented above: with `GQ_RANDOM_STATE_VAR`/`GQ_RANDOM_CTR_VAR` both
    zero-initialized at boot (`linker.create_random_state_variables`), the
    *first* `random()` call a freshly booted cart makes is a pure function
    of `GQI_PLAYER_ID` -- same badge, same draw, every single reboot. Two
    different player IDs must still diverge from each other (the seeding
    gap isn't degenerate across the whole badge population, just within
    one badge's own reboots)."""
    source = game_with_stage("x = random(1, 1000000);", "volatile { int x = 0; }")
    cmds_text, map_text = _compile_and_read(compile_gq, source)
    ops = one_event(cmds_text).ops

    player_id_addr = structs.gq_ptr_apply_ns(
        structs.GQ_PTR_BUILTIN_INT,
        next(v.addr for v in structs.GQ_RESERVED_INTS if v.name == "GQI_PLAYER_ID"),
    )
    x_addr = _var_addr(map_text, "x")

    # Two separate "boots" of the same badge -- a fresh `memory` dict each
    # time, exactly like a real cart's RAM coming back up zeroed.
    reboot_1 = _execute_ops(ops, {player_id_addr: 42})[x_addr]
    reboot_2 = _execute_ops(ops, {player_id_addr: 42})[x_addr]
    assert reboot_1 == reboot_2

    other_badge = _execute_ops(ops, {player_id_addr: 43})[x_addr]
    assert other_badge != reboot_1


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
