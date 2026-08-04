"""Linker / cart-image test suite for gqc (gamequeer#335, epic gamequeer#329).

Every byte-layout assertion in this file was derived by actually compiling a
game with `gqc compile` and hex-inspecting the resulting `.gqgame` (cross
referenced against `map.txt` and `linker.py`), not by reading `linker.py` and
assuming its comments are accurate -- two of them (see
`test_persistent_var_ptr_omits_its_namespace_byte` and
`test_section_order_matches_actual_layout` below) turned out not to be.

The CLI (black-box) cases use the `compile_gq` fixture from conftest.py, like
test_grammar.py. The `gq_ptr_*` pure-function cases run in-process (see
tests/support.py) since they don't need a full compile at all.
"""

import pathlib
import re
import struct

import pytest

from gqc import structs

from .support import reset_compiler_state

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ANIM_GIF = REPO_ROOT / "examples" / "assets" / "animations" / "perf_mask_mask.gif"
CUE_FILE = REPO_ROOT / "examples" / "assets" / "lighting" / "test.gqcue"

GAME_HEADER = 'game {{ id = {id}; title := "{title}"; author := "A"; starting_stage = start; }}\n'


MINIMAL_STAGE = "stage start { event enter { } }\n"


def game_header(id: int = 1, title: str = "T") -> str:
    return GAME_HEADER.format(id=id, title=title)


def minimal_game(id: int = 1, title: str = "T") -> str:
    """A minimal, otherwise-empty compilable game: just the `game{}` header
    plus a single stage with an empty `enter` event."""
    return f"{game_header(id=id, title=title)}{MINIMAL_STAGE}"


# --- map.txt parsing ---------------------------------------------------------
# create_symbol_table() (linker.py) emits map.txt with `tabulate`, as a
# section-header line (`.section  0xSTART  0xSIZE`) followed by one indented
# line per symbol in that section (`  0xADDR  0xSIZE  repr(symbol)`). These
# helpers parse that text back out so tests can cross-check the compiled
# `.gqgame` bytes against it without hand-computing offsets.

_SECTION_RE = re.compile(r"^(\.\w+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)$", re.MULTILINE)
_SYMBOL_RE = re.compile(r"^[ \t]+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(.*)$", re.MULTILINE)


def _parse_map_txt(map_text: str):
    """Return `(sections, symbols)`: `sections` maps section name (e.g.
    `.var`) to `(start_addr, size)`; `symbols` is a list of
    `(addr, size, repr_str)` for every individual symbol line, in file
    order."""
    sections = {
        m.group(1): (int(m.group(2), 16), int(m.group(3), 16))
        for m in _SECTION_RE.finditer(map_text)
    }
    symbols = [
        (int(m.group(1), 16), int(m.group(2), 16), m.group(3))
        for m in _SYMBOL_RE.finditer(map_text)
    ]
    return sections, symbols


def _section_order(map_text: str) -> list:
    return [m.group(1) for m in _SECTION_RE.finditer(map_text)]


def _find_symbol_addr(symbols, needle: str) -> int:
    matches = [addr for addr, _size, repr_str in symbols if needle in repr_str]
    assert len(matches) == 1, f"expected exactly one symbol matching {needle!r}, got {matches}"
    return matches[0]


def _compile_and_read(compile_gq, source: str, game_name: str = "game", assets=None):
    """Compile `source` via the CLI and return `(gqgame_bytes, map_text)`,
    asserting a clean (exit 0) compile first."""
    exit_code, stderr, out_dir = compile_gq(source, game_name=game_name, assets=assets)
    assert exit_code == 0, stderr
    gqgame_bytes = (out_dir / f"{game_name}.gqgame").read_bytes()
    map_text = (out_dir / "map.txt").read_text()
    return gqgame_bytes, map_text


def _unpack_header(gqgame_bytes: bytes) -> structs.GqHeader:
    return structs.GqHeader._make(
        struct.unpack(structs.GQ_HEADER_FORMAT, gqgame_bytes[: structs.GQ_HEADER_SIZE])
    )


# --- header: magic / id / title NUL-padding ---------------------------------


def test_header_magic_and_id(compile_gq):
    gqgame_bytes, _ = _compile_and_read(compile_gq, minimal_game(id=1234))
    header = _unpack_header(gqgame_bytes)
    assert header.magic == structs.GQ_MAGIC
    assert header.id == 1234


def test_header_title_is_nul_padded_to_fixed_width(compile_gq):
    gqgame_bytes, _ = _compile_and_read(compile_gq, minimal_game(title="Test Game"))
    header = _unpack_header(gqgame_bytes)
    assert len(header.title) == structs.GQ_STR_SIZE
    assert header.title == b"Test Game" + b"\x00" * (structs.GQ_STR_SIZE - len(b"Test Game"))


def test_header_title_at_max_length_has_single_nul_terminator(compile_gq):
    title = "a" * (structs.GQ_STR_SIZE - 1)
    gqgame_bytes, _ = _compile_and_read(compile_gq, minimal_game(title=title))
    header = _unpack_header(gqgame_bytes)
    assert header.title == title.encode("ascii") + b"\x00"


def test_header_overlong_title_is_silently_truncated(compile_gq):
    # Unlike volatile/persistent `str` variables (Variable.__init__ rejects
    # any value longer than GQ_STR_SIZE-1, see test_grammar.py's
    # test_22_char_string_rejects), the game{} block's `title` has no such
    # check anywhere in parser.py/datamodel.py -- Game.to_bytes() just
    # truncates it. Pinning this as observed behavior: an overlong title
    # compiles cleanly (exit 0) rather than being rejected.
    title = "a" * (structs.GQ_STR_SIZE + 8)
    gqgame_bytes, _ = _compile_and_read(compile_gq, minimal_game(title=title))
    header = _unpack_header(gqgame_bytes)
    assert header.title == (title.encode("ascii")[: structs.GQ_STR_SIZE - 1] + b"\x00")


# --- header pointers vs. map.txt ---------------------------------------------

POINTERS_SOURCE = (
    f"{game_header()}"
    'menus { m { 1: "One"; 2: "Two"; } }\n'
    "persistent { int score = 7; }\n"
    "stage start { menu m; event enter { } }\n"
)


def test_starting_stage_and_startup_code_pointers_match_map_txt(compile_gq):
    gqgame_bytes, map_text = _compile_and_read(compile_gq, POINTERS_SOURCE, game_name="pointers")
    header = _unpack_header(gqgame_bytes)
    sections, _symbols = _parse_map_txt(map_text)

    stage_addr, _ = sections[".stage"]
    init_addr, _ = sections[".init"]

    assert header.starting_stage_ptr == stage_addr
    assert header.startup_code_ptr == init_addr
    # Both are CART-namespaced pointers (top byte == GQ_PTR_NS_CART).
    assert structs.gq_ptr_get_ns(header.starting_stage_ptr) == structs.GQ_PTR_NS_CART
    assert structs.gq_ptr_get_ns(header.startup_code_ptr) == structs.GQ_PTR_NS_CART


def test_persistent_var_ptr_omits_its_namespace_byte(compile_gq):
    # linker.py assigns `Game.game.persistent_var_ptr = vars_ptr_start`
    # directly (a bare offset), unlike every other header pointer field,
    # which goes through Variable/Stage/Event.set_addr() -> gq_ptr_apply_ns()
    # and so carries GQ_PTR_NS_CART in its top byte. This is not a bug: the
    # cart-load path in gamequeer/src/gamequeer.c unconditionally re-applies
    # the namespace to both `persistent_vars` and `persistent_crc16`
    # (`game.persistent_vars = GQ_PTR(GQ_PTR_NS_CART, game.persistent_vars)`),
    # so it works regardless of whether the stored field already has a
    # namespace byte set. Pinning the observed (inconsistent-looking, but
    # harmless) representation here rather than assuming it matches
    # persistent_crc16_ptr's.
    gqgame_bytes, map_text = _compile_and_read(compile_gq, POINTERS_SOURCE, game_name="pointers2")
    header = _unpack_header(gqgame_bytes)
    sections, _symbols = _parse_map_txt(map_text)

    var_addr, _ = sections[".var"]
    assert structs.gq_ptr_get_ns(var_addr) == structs.GQ_PTR_NS_CART

    assert structs.gq_ptr_get_ns(header.persistent_var_ptr) == structs.GQ_PTR_NS_NULL
    assert header.persistent_var_ptr == structs.gq_ptr_get_addr(var_addr)


def test_persistent_crc16_ptr_matches_map_txt_and_carries_cart_namespace(compile_gq):
    gqgame_bytes, map_text = _compile_and_read(compile_gq, POINTERS_SOURCE, game_name="pointers3")
    header = _unpack_header(gqgame_bytes)
    _sections, symbols = _parse_map_txt(map_text)

    crc16_addr = _find_symbol_addr(symbols, "'__crc16.builtin'")
    assert header.persistent_crc16_ptr == crc16_addr
    assert structs.gq_ptr_get_ns(header.persistent_crc16_ptr) == structs.GQ_PTR_NS_CART


# --- persistent-section layout: 4 KB alignment, 0xFF padding, CRC16 ----------


def test_persistent_section_starts_at_next_4kb_boundary(compile_gq):
    gqgame_bytes, map_text = _compile_and_read(compile_gq, POINTERS_SOURCE, game_name="align")
    header = _unpack_header(gqgame_bytes)
    sections, _symbols = _parse_map_txt(map_text)

    assert header.persistent_var_ptr % 0x1000 == 0
    # And it's genuinely *after* the init code, not just coincidentally
    # aligned -- the boundary is the first one at or after the init table's
    # end (linker.py's `init_ptr_start + init_ptr_offset + (0x1000 - ...)`).
    init_addr, init_size = sections[".init"]
    init_end = structs.gq_ptr_get_addr(init_addr) + init_size
    assert init_end <= header.persistent_var_ptr


def test_persistent_section_padded_with_actual_0xff_bytes(compile_gq):
    gqgame_bytes, map_text = _compile_and_read(compile_gq, POINTERS_SOURCE, game_name="padding")
    header = _unpack_header(gqgame_bytes)
    _sections, symbols = _parse_map_txt(map_text)

    pad_addrs = sorted(
        structs.gq_ptr_get_addr(addr) for addr, _size, repr_str in symbols if "'__pad." in repr_str
    )
    assert pad_addrs, "expected at least one __pad.* sentinel in this layout"

    pad_start = pad_addrs[0]
    pad_end = header.persistent_var_ptr + 0x1000
    pad_region = gqgame_bytes[pad_start:pad_end]

    assert len(pad_region) > 0
    assert len(pad_region) % structs.GQ_INT_SIZE == 0
    assert pad_region == b"\xff" * len(pad_region)


def test_persistent_crc16_matches_recomputed_crc16_buf(compile_gq):
    gqgame_bytes, _map_text = _compile_and_read(compile_gq, POINTERS_SOURCE, game_name="crccheck")
    header = _unpack_header(gqgame_bytes)

    p_start = header.persistent_var_ptr
    crc_addr = structs.gq_ptr_get_addr(header.persistent_crc16_ptr)

    persistent_bytes = gqgame_bytes[p_start:crc_addr]
    recomputed = structs.crc16_buf(persistent_bytes)

    stored = struct.unpack("<I", gqgame_bytes[crc_addr : crc_addr + structs.GQ_INT_SIZE])[0]
    assert stored == recomputed


def test_cache_region_is_byte_identical_to_persistent_region(compile_gq):
    gqgame_bytes, _map_text = _compile_and_read(compile_gq, POINTERS_SOURCE, game_name="cachecheck")
    header = _unpack_header(gqgame_bytes)

    p_start = header.persistent_var_ptr
    cache_start = p_start + 0x1000

    persistent_region = gqgame_bytes[p_start : p_start + 0x1000]
    cache_region = gqgame_bytes[cache_start : cache_start + 0x1000]

    assert len(persistent_region) == 0x1000
    assert len(cache_region) == 0x1000
    assert persistent_region == cache_region


# --- documented section order ------------------------------------------------


@pytest.mark.ffmpeg
def test_section_order_matches_actual_layout(compile_gq):
    # linker.py's create_symbol_table() docstring comment claims the output
    # order is:
    #   header, animations, stages, frames, frame data, menus,
    #   read-only string constant pool, variable area, initialization code,
    #   events code
    # The actual order (both in map.txt and in the emitted .gqgame bytes,
    # driven by the `symbol_table` dict built at the end of that function)
    # omits lightcues from the comment entirely, and places the variable
    # area *last* rather than before init/events code. Pinning the observed
    # order here instead of the stale comment. map.txt also documents a
    # trailing `.heap` section (the volatile/register heap, GQ_PTR_NS_HEAP)
    # -- that one is informational only, since generate_code() skips any
    # symbol whose namespace isn't GQ_PTR_NS_CART when emitting .gqgame
    # bytes, so it's never actually part of the cart image.
    # `.const` (gamequeer#418) always appears, even with no author-written
    # string literals: GQ_REGISTERS_STR's `.init` shadows live there too,
    # and those 4 string registers are always reserved.
    source = (
        f"{game_header()}"
        'animations { pmm <- "perf_mask_mask.gif"; }\n'
        'lightcues { tc <- "test.gqcue"; }\n'
        'menus { m { 1: "One"; 2: "Two"; } }\n'
        "persistent { int score = 7; }\n"
        "stage start { menu m; event enter { } }\n"
    )
    _gqgame_bytes, map_text = _compile_and_read(
        compile_gq,
        source,
        game_name="order",
        assets={
            "assets/animations/perf_mask_mask.gif": ANIM_GIF,
            "assets/lighting/test.gqcue": CUE_FILE,
        },
    )

    assert _section_order(map_text) == [
        ".game",
        ".anim",
        ".stage",
        ".frame",
        ".framedata",
        ".cues",
        ".cuedata",
        ".menu",
        ".const",
        ".event",
        ".init",
        ".var",
        ".heap",
    ]


# --- size-limit exits ---------------------------------------------------------


def test_volatile_table_over_512_bytes_exits_2(compile_gq):
    # GQ_REGISTERS_INT/STR already reserve 4*GQ_INT_SIZE + 4*GQ_STR_SIZE
    # bytes of heap; 150 additional 4-byte ints comfortably pushes the total
    # over the 512-byte hardware limit.
    decls = "\n".join(f"int v{i} = 0;" for i in range(150))
    source = f"{game_header()}volatile {{ {decls} }}\nstage start {{ event enter {{ }} }}\n"
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 2
    assert "Volatile variable table size exceeds maximum size of 512 bytes" in stderr


def test_persistent_section_over_4kb_exits_2(compile_gq):
    # 1200 declared ints (4 bytes each) plus the 10 reserved
    # GQ_PERSISTENT_BADGES_* ints and the CRC16 var comfortably clears the
    # 4096-byte sector on its own. (Pre-gamequeer#418, 1000 was enough
    # because GQ_REGISTERS_STR's `.init` shadows also shared this sector;
    # they've since moved to the read-only `.const` pool, which no longer
    # counts against this limit -- exactly the property #418 exists for.)
    decls = "\n".join(f"int p{i} = 0;" for i in range(1200))
    source = f"{game_header()}persistent {{ {decls} }}\nstage start {{ event enter {{ }} }}\n"
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 2
    assert "Persistent variable section exceeds 4 KB sector boundary" in stderr
    assert "hardware limitation" in stderr


# --- read-only string constant pool (gamequeer#418) ---------------------------
# String literals (Variable.get_str_literal) and the volatile-str `.init`
# initialization shadows it also backs are never write targets after link
# time (no literal lvalue exists in the grammar; a `.init` var is only ever
# a CommandSetStr *source*), so they're placed in their own `.const`
# section -- a plain, unconstrained read-only region -- instead of the
# 4 KB-limited mutable persistent sector. See the gamequeer#418 issue
# comment for the full frozen-VM-contract justification: nothing in the
# read path (old or new firmware) distinguishes a persistent-sector address
# from any other GQ_PTR_NS_CART address.


def test_string_literal_lands_in_const_section_not_var(compile_gq):
    # A game's first user-authored string literal is always named
    # `S0.strlit` (Variable.get_str_literal's per-process dedup counter --
    # GQ_REGISTERS_STR's `.init` shadows are named `GQ_RSn.reg.init`, a
    # disjoint namespace, so they never collide with this).
    source = (
        f"{game_header()}"
        'volatile { str x := ""; }\n'
        'stage start { event enter { x := "hello there"; } }\n'
    )
    gqgame_bytes, map_text = _compile_and_read(compile_gq, source, game_name="litplace")
    del gqgame_bytes
    sections, symbols = _parse_map_txt(map_text)

    const_addr = _find_symbol_addr(symbols, "'S0.strlit'")
    var_start, var_size = sections[".var"]
    const_start, const_size = sections[".const"]

    # The literal lives inside the .const section's address range...
    assert const_start <= const_addr < const_start + const_size
    # ...and nowhere inside .var (the persistent/cache/pad region).
    assert not (var_start <= const_addr < var_start + var_size)

    repr_str = next(r for a, _s, r in symbols if a == const_addr)
    assert "storageclass='const'" in repr_str
    assert "hello there" in repr_str


def test_duplicate_string_literals_deduplicate_to_one_const_entry(compile_gq):
    source = (
        f"{game_header()}"
        'volatile { str x := ""; }\n'
        'stage start { event enter { x := "dup"; x := "dup"; x := "dup"; } }\n'
    )
    _gqgame_bytes, map_text = _compile_and_read(compile_gq, source, game_name="litdup")
    _sections, symbols = _parse_map_txt(map_text)

    matches = [addr for addr, _size, repr_str in symbols if "'S0.strlit'" in repr_str]
    assert len(matches) == 1


def test_volatile_str_init_shadow_lands_in_const_section(compile_gq):
    # The compiler-generated `<name>.init` shadow that backs a volatile str
    # variable's startup value is exactly as read-only as a literal (it's
    # only ever a CommandSetStr source, in the init table) -- it belongs in
    # the same pool, not the persistent sector.
    source = (
        f"{game_header()}"
        'volatile { str greeting := "hi there"; }\n'
        "stage start { event enter { } }\n"
    )
    _gqgame_bytes, map_text = _compile_and_read(compile_gq, source, game_name="initshadow")
    _sections, symbols = _parse_map_txt(map_text)

    repr_str = next(r for _a, _s, r in symbols if "'greeting.init'" in r)
    assert "storageclass='const'" in repr_str


def test_menu_prompt_literal_lands_in_const_section(compile_gq):
    # `menu <name> prompt "...";` routes its prompt through the same
    # string_operand -> get_str_literal() grammar path as any other string
    # literal (Stage.resolve() looks the prompt up by name in
    # Variable.var_table, same as a CommandSetStr operand) -- it's not a
    # special case, but it's a distinct grammar rule from a plain
    # assignment RHS, so pin it directly rather than relying on golden/
    # ctest coverage (menu_choice.gq) alone.
    source = (
        f"{game_header()}"
        'menus { m { 1: "One"; 2: "Two"; } }\n'
        'stage start { menu m prompt "Pick one:"; event enter { } }\n'
    )
    gqgame_bytes, map_text = _compile_and_read(compile_gq, source, game_name="menuprompt")
    del gqgame_bytes
    sections, symbols = _parse_map_txt(map_text)

    const_start, const_size = sections[".const"]
    # Not just "'S0.strlit'" -- the Stage's own repr also names it (as
    # BoundMenu(..., menu_prompt='S0.strlit')), so that needle matches two
    # symbols (the Stage and the Variable). Anchor on the Variable repr.
    prompt_addr = _find_symbol_addr(symbols, "Variable('str', 'S0.strlit'")
    assert const_start <= prompt_addr < const_start + const_size

    repr_str = next(r for a, _s, r in symbols if a == prompt_addr)
    assert "storageclass='const'" in repr_str
    assert "Pick one:" in repr_str


def test_empty_string_literal_assignment_rhs_lands_in_const_section(compile_gq):
    # gamequeer#418 named `x := "";` (an *empty* literal used as an
    # assignment RHS, not a declaration default) as an edge case distinct
    # from test_volatile_str_init_shadow_lands_in_const_section's `str x :=
    # "";` default-value form -- that one never calls get_str_literal() at
    # all (the default value is stored directly on the `.init` shadow), so
    # it doesn't exercise the same path this test does.
    source = (
        f"{game_header()}"
        'volatile { str x := "nonempty"; }\n'
        'stage start { event enter { x := ""; } }\n'
    )
    _gqgame_bytes, map_text = _compile_and_read(compile_gq, source, game_name="emptylit")
    sections, symbols = _parse_map_txt(map_text)

    const_start, const_size = sections[".const"]
    empty_lit_addr = _find_symbol_addr(symbols, "'S0.strlit'")
    assert const_start <= empty_lit_addr < const_start + const_size

    repr_str = next(r for a, _s, r in symbols if a == empty_lit_addr)
    # Variable.__repr__ doesn't repr() the value field, so an empty string
    # shows up as nothing between the two commas either side of it.
    assert repr_str == "Variable('str', 'S0.strlit', , storageclass='const')"


def test_reserved_persistent_badges_offset_is_unchanged_by_literal_count(compile_gq):
    # GQP_OFFSET_BADGES (gamequeer_bytecode.h) hardcodes offset 0 from
    # persistent_var_ptr for the reserved badge-bitfield ints. Nothing about
    # #418's placement of literals/`.init` shadows in the separate `.const`
    # section may perturb that -- prove it holds both with zero literals and
    # with a few dozen, not just by inspection.
    def badges_offset(source, game_name):
        _gqgame_bytes, map_text = _compile_and_read(compile_gq, source, game_name=game_name)
        header = _unpack_header(_gqgame_bytes)
        _sections, symbols = _parse_map_txt(map_text)
        badges_addr = _find_symbol_addr(symbols, "'GQ_PERSISTENT_BADGES_0.builtin'")
        # header.persistent_var_ptr is a bare offset (no namespace byte --
        # see test_persistent_var_ptr_omits_its_namespace_byte above), but
        # map.txt addresses always carry one; strip it before diffing.
        return structs.gq_ptr_get_addr(badges_addr) - header.persistent_var_ptr

    no_literals_source = f"{game_header()}stage start {{ event enter {{ }} }}\n"

    literal_assigns = "\n".join(f'x := "lit{i}";' for i in range(40))
    many_literals_source = (
        f"{game_header()}"
        'volatile { str x := ""; }\n'
        f"stage start {{ event enter {{ {literal_assigns} }} }}\n"
    )

    offset_a = badges_offset(no_literals_source, "badges_a")
    offset_b = badges_offset(many_literals_source, "badges_b")

    assert offset_a == 0
    assert offset_b == 0


def test_literal_heavy_cart_keeps_persistent_sector_under_4kb(compile_gq):
    # The Skippy-unblocking property (gamequeer#418): a cart with hundreds
    # of distinct string literals and *no* author-declared persistent
    # variables must still compile, because literals no longer live in the
    # 4 KB-limited persistent sector at all.
    #
    # Pre-#418, every distinct literal cost a 22-byte (GQ_STR_SIZE)
    # persistent slot alongside the 10 reserved GQ_PERSISTENT_BADGES_* ints
    # (40 bytes) + the CRC16 var (4 bytes) + GQ_REGISTERS_STR's 4 `.init`
    # shadows (88 bytes): a 300-literal cart would have needed
    # 40 + 4 + 88 + 300*22 = 6732 bytes, comfortably over the 4096-byte
    # sector and a hard compile error (see
    # test_persistent_section_over_4kb_exits_2 above, and gamequeer#418's
    # issue comment). This is exactly the cart shape that used to be
    # unbuildable.
    n_literals = 300
    assert structs.GQ_STR_SIZE * n_literals + 40 + 4 + 4 * structs.GQ_STR_SIZE > 0x1000

    literal_assigns = "\n".join(f'x := "literal number {i}";' for i in range(n_literals))
    source = (
        f"{game_header()}"
        'volatile { str x := ""; }\n'
        f"stage start {{ event enter {{ {literal_assigns} }} }}\n"
    )
    gqgame_bytes, map_text = _compile_and_read(compile_gq, source, game_name="litheavy")
    header = _unpack_header(gqgame_bytes)
    sections, symbols = _parse_map_txt(map_text)

    # The persistent sector's *real* (non-pad, non-cache) content is
    # unchanged by the literal count: just the 10 reserved badge ints + the
    # CRC16 var. (`.var`'s other entries are `__pad.*` sentinels and the
    # `__cache.*` write-through mirror, both storageclass='persistent' too.)
    real_persistent = [
        r for _a, _s, r in symbols
        if "storageclass='persistent'" in r
        and "'__pad." not in r
        and "'__cache." not in r
    ]
    assert len(real_persistent) == 11  # 10 GQ_PERSISTENT_BADGES_* + __crc16.builtin

    var_start, var_size = sections[".var"]
    assert var_size == 0x2000  # persistent sector (0x1000) + its cache, unchanged
    assert header.persistent_var_ptr % 0x1000 == 0

    # The const pool, meanwhile, is free to grow past 4 KB with the literal
    # count -- it holds all 300 literals, GQ_REGISTERS_STR's 4 `.init`
    # shadows, and `x`'s own `.init` shadow (its `""` starting value),
    # uncapped.
    const_start, const_size = sections[".const"]
    assert const_size == (n_literals + 4 + 1) * structs.GQ_STR_SIZE
    assert const_size > 0x1000
    del var_start, const_start


# --- same-source recompile determinism ---------------------------------------


def test_same_source_recompiles_are_byte_identical(compile_gq):
    source = (
        f"{game_header()}"
        'menus { m { 1: "One"; 2: "Two"; } }\n'
        "persistent { int score = 7; }\n"
        "volatile { int x = 3; }\n"
        "stage start { menu m; event enter { x = x + 1; } }\n"
    )
    exit_a, stderr_a, out_dir_a = compile_gq(source, game_name="det_a")
    exit_b, stderr_b, out_dir_b = compile_gq(source, game_name="det_b")
    assert exit_a == 0, stderr_a
    assert exit_b == 0, stderr_b

    gqgame_a = (out_dir_a / "det_a.gqgame").read_bytes()
    gqgame_b = (out_dir_b / "det_b.gqgame").read_bytes()
    assert gqgame_a == gqgame_b

    map_a = (out_dir_a / "map.txt").read_text()
    map_b = (out_dir_b / "map.txt").read_text()
    assert map_a == map_b


# --- crc16_update fixed vectors -----------------------------------------------
# Cross-checked once against `HAL_crc16_update()` in
# ccs_workspace/qc2024/HAL_badge.c (whose comment states it was ported from
# this exact Python), by compiling that C function standalone and running it
# over the same byte sequences.


@pytest.mark.parametrize(
    "buf, expected",
    [
        (b"", 0x9F2A),
        (b"\x00", 0x5856),
        (bytes([0x01, 0x02, 0x03, 0x04]), 0x5E75),
        (b"hello world!", 0x712E),
    ],
)
def test_crc16_update_fixed_vectors(buf, expected):
    assert structs.crc16_buf(buf) == expected
    assert structs.crc16_update(structs.GQ_CRC_SEED, buf) == expected


# --- gq_ptr_apply_ns / gq_ptr_get_ns / gq_ptr_get_addr round trips -----------


@pytest.mark.parametrize(
    "namespace",
    [
        structs.GQ_PTR_NS_CART,
        structs.GQ_PTR_NS_SAVE,
        structs.GQ_PTR_NS_HEAP,
        structs.GQ_PTR_BUILTIN_INT,
        structs.GQ_PTR_BUILTIN_STR,
    ],
)
def test_gq_ptr_apply_ns_round_trips_through_get_ns_and_get_addr(namespace):
    reset_compiler_state()
    addr = 0x001234
    ptr = structs.gq_ptr_apply_ns(namespace, addr)

    assert structs.gq_ptr_get_ns(ptr) == namespace
    assert structs.gq_ptr_get_addr(ptr, expected_namespace=namespace) == addr
    # No warning should fire for a well-formed round trip.
    assert structs.namespace_overflow_warned is False
    assert structs.addr_wrong_namespace_warned is False


@pytest.mark.parametrize("bad_namespace", [-1, 0x100, 0x1FFFF])
def test_gq_ptr_apply_ns_rejects_invalid_namespace(bad_namespace):
    reset_compiler_state()
    with pytest.raises(ValueError, match="Invalid namespace"):
        structs.gq_ptr_apply_ns(bad_namespace, 0x1234)


def test_gq_ptr_apply_ns_overwrites_a_pre_existing_namespace_byte(capsys):
    # gq_ptr_apply_ns masks off whatever's already in the top byte of `ptr`
    # and replaces it with `ns` -- it doesn't reject or OR onto an
    # already-namespaced pointer, it just warns (once) that this happened,
    # since in practice it usually indicates an address-space overflow
    # elsewhere in the linker (see the printed message).
    reset_compiler_state()

    ptr = structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_CART, 0x02000001)
    assert ptr == structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_CART, 0x000001)
    assert structs.gq_ptr_get_ns(ptr) == structs.GQ_PTR_NS_CART
    assert structs.gq_ptr_get_addr(ptr) == 0x000001

    out = capsys.readouterr().out
    assert "namespace already set" in out
    assert structs.namespace_overflow_warned is True

    # The warning is only emitted once per process.
    capsys.readouterr()
    structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_CART, 0x03000002)
    assert capsys.readouterr().out == ""


def test_gq_ptr_get_addr_warns_once_on_namespace_mismatch_but_still_returns_addr(capsys):
    reset_compiler_state()

    ptr = structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_HEAP, 0x000055)
    addr = structs.gq_ptr_get_addr(ptr, expected_namespace=structs.GQ_PTR_NS_CART)
    assert addr == 0x000055

    err = capsys.readouterr().err
    assert "INTERNAL COMPILER WARNING" in err
    assert structs.addr_wrong_namespace_warned is True

    # Suppressed on subsequent mismatches.
    capsys.readouterr()
    structs.gq_ptr_get_addr(ptr, expected_namespace=structs.GQ_PTR_NS_SAVE)
    assert capsys.readouterr().err == ""
