"""`fw_version()` intrinsic suite for gqc (gamequeer#411, successor to
gamequeer#410).

`fw_version()` lets cart code branch on the host firmware's identity: 0 on
original 2024 fleet firmware, otherwise the value of the new `GQI_FW_VERSION`
reserved int (populated by firmware that defines it -- see
`structs.GQ_RESERVED_INTS`). GQI_FW_VERSION is *undefined* on original
firmware -- gamequeer#410 established that reading it there returns
unspecified adjacent RAM, not 0, and that *writing* it corrupts RAM -- so
`fw_version()` can't just be a bare reference to that reserved int. Instead,
it's sugar for a hidden variable that a compiler-injected probe stage
populates once, at cart boot, via the gamequeer#410 timer-vs-bganim race (a
1-frame background animation clamped to 5 ticks/frame vs. a 13-tick timer;
whichever fires first -- BGDONE or TIMER -- distinguishes post-original
firmware from original firmware without ever touching GQI_FW_VERSION on
firmware that might not define it). See `linker.inject_fw_version_probe`'s
docstring for the full design, including why the probe stage is injected
unconditionally ahead of the game's *declared* starting stage rather than
requiring an author-designated probe window, and why that injection only
happens (Game.needs_fw_probe) for games that actually call fw_version().

test_grammar.py covers accept/reject parsing; test_constant_folding.py pins
that fw_version() never folds (it's a variable reference, not a literal).
This module covers what it actually lowers to: the probe stage's shape, its
zero footprint when unused, and the GQI_FW_VERSION write-protection its
correctness depends on.
"""

import struct

from gqc import structs

from .opstream import parse_gqasm

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'


def game_with_stage(body: str, decls: str = "") -> str:
    """A minimal valid game with a single stage `start` whose `enter` event
    runs `body`, optionally preceded by top-level declarations (e.g. a
    `volatile { ... }` block)."""
    return f"{GAME_HEADER}{decls}\nstage start {{ event enter {{ {body} }} }}\n"


def _compile_and_read(compile_gq, source: str, game_name: str = "game"):
    """Compile `source` via the CLI and return `(gqgame_bytes, cmds_text,
    map_text)`, asserting a clean (exit 0) compile first."""
    exit_code, stderr, out_dir = compile_gq(source, game_name=game_name)
    assert exit_code == 0, stderr
    gqgame_bytes = (out_dir / f"{game_name}.gqgame").read_bytes()
    cmds_text = (out_dir / "cmds.gqasm").read_text()
    map_text = (out_dir / "map.txt").read_text()
    return gqgame_bytes, cmds_text, map_text


def _unpack_header(gqgame_bytes: bytes) -> structs.GqHeader:
    return structs.GqHeader._make(
        struct.unpack(structs.GQ_HEADER_FORMAT, gqgame_bytes[: structs.GQ_HEADER_SIZE])
    )


def _author_enter_ops(cmds_text: str) -> list:
    """The ops of the *first* ENTER event block in a cmds.gqasm listing --
    the author's own `start` stage. Needed instead of
    opstream.one_event("ENTER") whenever the game calls fw_version(): the
    probe stage (linker.inject_fw_version_probe) has its own ENTER event
    too, and its Stage is always registered after every author-defined
    stage (see that function's docstring), so the author's own ENTER event
    is always the first ENTER block."""
    return next(b for b in parse_gqasm(cmds_text) if b.event_type == "ENTER").ops


GQI_FW_VERSION_ADDR = structs.gq_ptr_apply_ns(
    structs.GQ_PTR_BUILTIN_INT,
    next(v.addr for v in structs.GQ_RESERVED_INTS if v.name == "GQI_FW_VERSION"),
)


# --- GQI_FW_VERSION reserved word ---------------------------------------------


def test_gqi_fw_version_is_next_free_reserved_int_slot():
    # GQI_PLAYER_ID (the last pre-existing entry) sits at 0x5C; GQI_FW_VERSION
    # must be the very next 4-byte-aligned slot, matching the C VM's
    # GQI_COUNT * GQ_INT_SIZE (gamequeer.h) -- this is the exact address the
    # downstream C-side task (gamequeer.h/gamequeer.c/badge firmware) has to
    # agree on.
    player_id = next(v for v in structs.GQ_RESERVED_INTS if v.name == "GQI_PLAYER_ID")
    fw_version = next(v for v in structs.GQ_RESERVED_INTS if v.name == "GQI_FW_VERSION")
    assert fw_version.addr == player_id.addr + structs.GQ_INT_SIZE
    assert fw_version.addr == 0x60


def test_gqi_fw_version_is_read_only():
    fw_version = next(v for v in structs.GQ_RESERVED_INTS if v.name == "GQI_FW_VERSION")
    assert fw_version.writable is False


def test_gqi_fw_version_write_rejects_as_compile_error(compile_gq):
    source = game_with_stage("GQI_FW_VERSION = 5;")
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code != 0
    assert "Cannot assign to read-only variable GQI_FW_VERSION" in stderr


def test_gqi_fw_version_read_is_allowed(compile_gq):
    # Reading it directly (as opposed to through fw_version()) isn't
    # forbidden by gqc -- only writes are. Whether it's *meaningful* to read
    # directly (without the probe having run first) is an authoring concern
    # documented in authoring-and-perf-carts.md, not something gqc enforces.
    source = game_with_stage("x = GQI_FW_VERSION;", "volatile { int x = 0; }")
    exit_code, stderr, _out_dir = compile_gq(source)
    assert exit_code == 0, stderr


# --- zero footprint when unused -----------------------------------------------


def test_fw_version_unused_injects_no_probe_stage(compile_gq):
    source = game_with_stage("badge_set 1;")
    _gqgame_bytes, cmds_text, map_text = _compile_and_read(compile_gq, source)
    assert structs.GQ_FW_PROBE_STAGE_NAME not in map_text
    assert structs.GQ_FW_PROBE_RESULT_VAR not in map_text
    assert "EVENT:BGDONE" not in cmds_text
    assert "EVENT:TIMER" not in cmds_text


def test_fw_version_unused_starting_stage_is_the_authors_own(compile_gq):
    source = game_with_stage("badge_set 1;")
    gqgame_bytes, _cmds_text, map_text = _compile_and_read(compile_gq, source)
    header = _unpack_header(gqgame_bytes)
    stage_start = int(
        next(line for line in map_text.splitlines() if line.startswith(".stage")).split()[1],
        16,
    )
    assert header.starting_stage_ptr == stage_start


# --- probe injection when used ------------------------------------------------


def test_fw_version_used_makes_probe_stage_the_entry_point(compile_gq):
    source = game_with_stage("x = fw_version();", "volatile { int x = 0; }")
    gqgame_bytes, _cmds_text, map_text = _compile_and_read(compile_gq, source)
    header = _unpack_header(gqgame_bytes)
    probe_line = next(
        line for line in map_text.splitlines() if structs.GQ_FW_PROBE_STAGE_NAME in line
    )
    probe_addr = int(probe_line.split()[0], 16)
    assert header.starting_stage_ptr == probe_addr
    # The probe is a real cart-namespaced stage pointer, not left as a null
    # or heap/save pointer.
    assert structs.gq_ptr_get_ns(header.starting_stage_ptr) == structs.GQ_PTR_NS_CART


def test_fw_version_probe_enter_event_arms_a_13_tick_timer(compile_gq):
    source = game_with_stage("x = fw_version();", "volatile { int x = 0; }")
    _gqgame_bytes, cmds_text, _map_text = _compile_and_read(compile_gq, source)
    blocks = parse_gqasm(cmds_text)
    enter_blocks = [b for b in blocks if b.event_type == "ENTER"]
    assert len(enter_blocks) == 2  # the author's own start stage, and the probe's
    probe_enter = enter_blocks[1]
    timer_op = next(op for op in probe_enter.ops if op.name == "TIMER")
    assert timer_op.flags & structs.OpFlags.LITERAL_ARG2
    assert timer_op.arg2 == structs.GQ_FW_PROBE_TIMER_TICKS == 13


def test_fw_version_probe_bgdone_reads_gqi_fw_version_into_hidden_var(compile_gq):
    source = game_with_stage("x = fw_version();", "volatile { int x = 0; }")
    _gqgame_bytes, cmds_text, _map_text = _compile_and_read(compile_gq, source)
    blocks = parse_gqasm(cmds_text)
    bgdone = next(b for b in blocks if b.event_type == "BGDONE")
    setvar = next(op for op in bgdone.ops if op.name == "SETVAR")
    # Non-literal: this is a variable-to-variable copy (a read), never a
    # literal write.
    assert not (setvar.flags & structs.OpFlags.LITERAL_ARG2)
    assert setvar.arg2 == GQI_FW_VERSION_ADDR
    assert any(op.name == "GOSTAGE" for op in bgdone.ops)


def test_fw_version_probe_timer_branch_sets_zero(compile_gq):
    source = game_with_stage("x = fw_version();", "volatile { int x = 0; }")
    _gqgame_bytes, cmds_text, _map_text = _compile_and_read(compile_gq, source)
    blocks = parse_gqasm(cmds_text)
    timer_block = next(b for b in blocks if b.event_type == "TIMER")
    setvar = next(op for op in timer_block.ops if op.name == "SETVAR")
    assert setvar.flags & structs.OpFlags.LITERAL_ARG2
    assert setvar.arg2 == 0
    assert any(op.name == "GOSTAGE" for op in timer_block.ops)


def test_fw_version_probe_both_branches_gostage_to_the_authors_stage(compile_gq):
    source = game_with_stage("x = fw_version();", "volatile { int x = 0; }")
    gqgame_bytes, cmds_text, map_text = _compile_and_read(compile_gq, source)
    del gqgame_bytes
    author_stage_addr = int(
        next(
            line
            for line in map_text.splitlines()
            if "Stage(start," in line
        ).split()[0],
        16,
    )
    blocks = parse_gqasm(cmds_text)
    bgdone = next(b for b in blocks if b.event_type == "BGDONE")
    timer_block = next(b for b in blocks if b.event_type == "TIMER")
    bgdone_gostage = next(op for op in bgdone.ops if op.name == "GOSTAGE")
    timer_gostage = next(op for op in timer_block.ops if op.name == "GOSTAGE")
    assert bgdone_gostage.arg1 == author_stage_addr
    assert timer_gostage.arg1 == author_stage_addr


def test_fw_version_reads_the_hidden_result_variable(compile_gq):
    # fw_version() itself, wherever it's called, is just a read of the
    # hidden variable the probe populates -- not the probe machinery again.
    source = game_with_stage("x = fw_version();", "volatile { int x = 0; }")
    _gqgame_bytes, cmds_text, _map_text = _compile_and_read(compile_gq, source)
    ops = _author_enter_ops(cmds_text)
    assert [op.name for op in ops] == ["SETVAR", "DONE"]
    setvar = ops[0]
    assert not (setvar.flags & structs.OpFlags.LITERAL_ARG2)


def test_fw_version_hidden_result_variable_zero_initialized(compile_gq):
    # Every volatile variable (the hidden result variable included) gets a
    # literal-zero SETVAR in the init table (linker.create_symbol_table),
    # which runs before the probe stage -- the cart's actual entry point --
    # ever does. Belt-and-suspenders with the probe's own TIMER-branch
    # explicit zero-set (test_fw_version_probe_timer_branch_sets_zero).
    source = game_with_stage("x = fw_version();", "volatile { int x = 0; }")
    gqgame_bytes, _cmds_text, map_text = _compile_and_read(compile_gq, source)
    del gqgame_bytes
    result_var_addr = int(
        next(
            line for line in map_text.splitlines()
            if structs.GQ_FW_PROBE_RESULT_VAR in line and "Variable(" in line
        ).split()[0],
        16,
    )
    init_lines = map_text.split(".init", 1)[1].split(".var", 1)[0]
    matches = [
        line for line in init_lines.splitlines()
        if "SETVAR" in line and f"{result_var_addr:#0{10}x}" in line
    ]
    assert len(matches) == 1
    assert matches[0].rstrip().endswith("0x00000000)")


# --- never emits a write to GQI_FW_VERSION ------------------------------------


def test_fw_version_never_emits_a_write_to_gqi_fw_version(compile_gq):
    # The hard requirement (gamequeer#411/gamequeer#410): no op gqc emits
    # for fw_version() may ever target GQI_FW_VERSION as a *destination* --
    # writing an undefined reserved int corrupts adjacent RAM on firmware
    # that predates it. Scan every op in the whole compiled program, not
    # just the probe's own events, since this has to hold no matter what
    # else the game does.
    source = game_with_stage(
        "x = fw_version(); y = fw_version() + 1; if (fw_version() == 0) { badge_set 1; }",
        "volatile { int x = 0; int y = 0; }",
    )
    _gqgame_bytes, cmds_text, _map_text = _compile_and_read(compile_gq, source)
    for block in parse_gqasm(cmds_text):
        for op in block.ops:
            assert op.arg1 != GQI_FW_VERSION_ADDR, (
                f"op {op} targets GQI_FW_VERSION ({GQI_FW_VERSION_ADDR:#x}) as a "
                "destination"
            )


def test_fw_version_called_multiple_times_shares_one_probe(compile_gq):
    # Calling fw_version() more than once must not inject the probe stage
    # more than once (which would be a duplicate-stage-name compile error)
    # -- every call reads the same hidden variable.
    source = game_with_stage(
        "x = fw_version(); y = fw_version();",
        "volatile { int x = 0; int y = 0; }",
    )
    _gqgame_bytes, cmds_text, map_text = _compile_and_read(compile_gq, source)
    assert map_text.count(structs.GQ_FW_PROBE_STAGE_NAME) == 1
    ops = _author_enter_ops(cmds_text)
    setvars = [op for op in ops if op.name == "SETVAR"]
    assert len(setvars) == 2
    assert all(not (op.flags & structs.OpFlags.LITERAL_ARG2) for op in setvars)
    assert setvars[0].arg2 == setvars[1].arg2  # both read the same hidden var
