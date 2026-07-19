"""Op-stream decoder for gqc's `cmds.gqasm` listing (gamequeer#334, epic
gamequeer#329). Test-only helper, private to `test_codegen.py` -- the other
Layer-2 suites (gamequeer#333/#335/#336/#337) write their own.

`cmds.gqasm` (see `create_symbol_table` in `gqc/src/gqc/linker.py`) is a
plain-text `tabulate()` dump built directly from the same `gqc.structs.GqOp`
namedtuple fields (`opcode`, `flags`, `arg1`, `arg2`) that
`Command.as_struct()`/`to_bytes()` serialize to the actual on-cart bytecode.
Decoding this listing therefore exercises the identical struct values a raw
byte disassembly would, without reimplementing `GQ_OP_FORMAT`'s
variable-width literal-arg layout a second time here -- and it's produced by
the same subprocess-per-test `compile_gq` fixture the rest of this package
already uses (see `conftest.py`), so there's no need for a second,
in-process compile path just to get at it.

The one thing gamequeer#334 asks for that *isn't* visible in `cmds.gqasm` at
all is the fixed-size `event_commands` pointer array inside `gq_stage` (only
the compiled `.gqgame` binary or an in-process `Stage` object has it) --
`decode_stage_event_table` below decodes that directly from the real
`.gqgame` bytes using `gqc.structs.GQ_STAGE_FORMAT`, keeping that one case
anchored to the actual on-cart struct layout instead of a text listing.
"""

from dataclasses import dataclass, field

from gqc import structs


@dataclass(frozen=True)
class Op:
    """One decoded row of `cmds.gqasm`: an emitted `gq_op` (see
    `gqc.structs.GqOp`), with its on-cart address and mnemonic."""

    addr: int
    name: str
    opcode: int
    flags: int
    arg1: int
    arg2: int


@dataclass
class EventBlock:
    """The ops compiled for one `EVENT:<type>` block, in on-cart address
    order (matches source-statement order within the event)."""

    event_type: str
    addr: int
    ops: list = field(default_factory=list)

    def names(self) -> list:
        return [op.name for op in self.ops]


def parse_gqasm(text: str) -> list:
    """Parse a `cmds.gqasm` listing into a list of `EventBlock`s.

    Lines are whitespace-delimited; the header/separator rows tabulate()
    emits don't start with a hex address and are skipped. An `EVENT:<type>`
    row has just an address and label (no opcode columns); every other
    address-prefixed row is a decoded `Op`.
    """
    blocks = []
    current = None

    for line in text.splitlines():
        tokens = line.split()
        if not tokens or not tokens[0].startswith("0x"):
            continue  # header / separator row

        addr = int(tokens[0], 16)

        if len(tokens) == 2 and tokens[1].startswith("EVENT:"):
            current = EventBlock(event_type=tokens[1][len("EVENT:"):], addr=addr)
            blocks.append(current)
            continue

        if len(tokens) != 6:
            raise ValueError(f"Unrecognized cmds.gqasm row: {line!r}")

        if current is None:
            raise ValueError(f"Op row before any EVENT: header: {line!r}")

        _addr, name, opcode, flags, arg1, arg2 = tokens
        current.ops.append(
            Op(
                addr=addr,
                name=name,
                opcode=int(opcode, 16),
                flags=int(flags, 16),
                arg1=int(arg1, 16),
                arg2=int(arg2, 16),
            )
        )

    return blocks


def one_event(text: str, event_type: str = "ENTER") -> EventBlock:
    """Parse `text` and return the single `EventBlock` for `event_type`,
    asserting there's exactly one -- the common case for these tests (one
    stage, one relevant event)."""
    blocks = parse_gqasm(text)
    matches = [b for b in blocks if b.event_type == event_type]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one {event_type!r} event block, found "
            f"{len(matches)} (event types present: "
            f"{[b.event_type for b in blocks]})"
        )
    return matches[0]


def decode_stage_event_table(gqgame_bytes: bytes, anim_count: int = 0) -> tuple:
    """Decode the first `gq_stage`'s `event_commands` pointer array (see
    `structs.GQ_STAGE_FORMAT` / `Stage.to_bytes`) directly out of a compiled
    `.gqgame` binary.

    `anim_count` must match the number of `animations { ... }` entries
    actually declared by the compiled game -- the stage table is laid out
    immediately after the fixed-size header and the (also fixed-size)
    animation table (see `create_symbol_table` in `gqc/src/gqc/linker.py`).
    Pass 0 (the default) for games with no animations.

    Returns the `event_commands` tuple, indexed by `structs.EventType`
    value -- i.e. `result[EventType.ENTER]` is that event's resolved
    on-cart address, or 0 if the stage has no such event.
    """
    stage_start = structs.GQ_HEADER_SIZE + anim_count * structs.GQ_ANIM_SIZE
    stage_bytes = gqgame_bytes[stage_start : stage_start + structs.GQ_STAGE_SIZE]
    fields = struct_unpack_stage(stage_bytes)
    return fields[5:]


def struct_unpack_stage(stage_bytes: bytes) -> tuple:
    """Thin wrapper around `struct.unpack(structs.GQ_STAGE_FORMAT, ...)` so
    callers that only need the leading scalar fields (id, anim/cue/menu/
    prompt pointers) don't have to import `struct` themselves too."""
    import struct

    return struct.unpack(structs.GQ_STAGE_FORMAT, stage_bytes)
