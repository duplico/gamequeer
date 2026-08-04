# Authoring GameQueer games with `gqc`, and generating perf test carts

This is a practical reference for authoring `.gq` games for the GameQueer
console, compiling them with `gqc`, and — the reason this doc exists —
deterministically producing carts that exercise specific renderer paths
(masked blit, flat/RLE fast path, dithered/uncompressed slow path, label
text, choice/text-entry menus) for hardware performance profiling (epic
duplico/qc2024#45) and for pre-authoring Stage-2 (grlib row-major rewrite,
epic duplico/qc2024#47) regression content.

> Authorship: this document was written with AI assistance (per the repo's
> AI-authorship convention).

## 1. The `.gq` language

The authoritative grammar is the pyparsing definition in
`gqc/src/gqc/grammar.py` (its module docstring is a full BNF). A program is one
`game { ... }` block followed by any number of declaration sections.

### Top-level blocks

| Block | Purpose |
|-------|---------|
| `game { id=…; title:=…; author:=…; starting_stage=…; }` | Required. Exactly one of each assignment, any order. |
| `volatile { … }` / `persistent { … }` | Variable declarations (see Types). Volatile lives in RAM/heap and is re-initialized each boot; persistent lives in a 4 KB cart sector with a CRC. |
| `animations { name <- "file"; … }` | Bind an animation name to a source asset, with optional per-animation options. |
| `lightcues { name <- "file.gqcue"; … }` | Bind an LED lighting cue (authored separately, see `mkcue`). |
| `menus { name { INT: "Label"; … } … }` | Selectable menus (max 6 options, `GQ_MENU_MAX_OPTIONS`). |
| `stage name { … }` | A screen/state: a background animation + cue, an optional menu or textmenu, and event handlers. |

### Types

Only two: `int` (32-bit signed, `GQ_INT_SIZE`) and `str` (fixed 22-byte
buffer, `GQ_STR_SIZE` — **21 usable chars** + NUL). Declarations:

```
int  score   = 0;      // '=' for ints
str  name    := "ME";  // ':=' for strings
```

### Named constants and enums

`const NAME = <int-expr>;` and `enum Name { A, B, C }` (gamequeer#421) are
compile-time-only sugar for magic numbers — every reference is substituted
with a literal int at parse time (reusing the same constant folding a
literal-only expression gets, so `const MAX_HP = 20 + 1;` never emits a
runtime add), so there's no register/opcode cost and no on-cart trace of
the name at all:

```
const MAX_HP = 21;
enum Difficulty { Easy, Medium, Hard }   // auto-numbered 0, 1, 2

stage start {
    event enter {
        hp = MAX_HP;
        if (difficulty == Difficulty.Hard) { hp = hp - 5; }
    }
}
```

**Declare before use.** Unlike variables/stages/animations (which resolve
forward references at link time), a `const`/`enum` has no runtime
representation to stay "unresolved" as — it must already be a literal by
the time its use is parsed, so it has to appear earlier in the file than
any reference to it. A single flat, file-global namespace covers both
forms; an enum member is referenced as `Name.Member`.

### Stage options

- `bganim <anim>;` — background animation for the stage.
- `bgcue <cue>;` — background LED cue.
- `menu <menu> [prompt <str>];` / `textmenu [prompt <str>];`
- `event <type> <statement-or-block>` — event handlers.

### Events

`enter`, `bgdone`, `fgdone(N)` (foreground slot N finished), `timer`, `menu`,
and `input(BTN)` where `BTN` ∈ `A`, `B`, `<-`, `->`, `-` (click).
(`EventType` in `structs.py` is the on-cart ordering; must match the C VM's
`gq_event_type`.)

### Event-body statements

`play`, `cue`, `gostage`, `timer <expr>`, `if (…) … else …`, `loop { … }`
with `continue` / `break`, `badge_set`/`badge_clear`/`seen_self()`
(gamequeer#423 sugar -- see "Social vocabulary" below), and assignments
(`x = expr;` int, `s := expr;` string with `+` concat and `str(int)` cast);
`badge_get` is not a statement but a unary operator usable inside int
expressions (e.g. `x = badge_get(5) + 1;`); `badge_count()` (nullary,
parens mandatory) is a popcount over the whole badges-seen bitfield, e.g.
`if (badge_count() >= 5) { ... }`. `random(lo, hi)`, `min(a, b)`, `max(a,
b)`, `clamp(x, lo, hi)`, `abs(x)` (gamequeer#422), and `have_met(id)`/
`in_cohort(NAME, id)`/`count_seen([NAME])` (gamequeer#423) are also
int-expression intrinsics, each taking one or more full `int_expression`
arguments -- see "Randomness" and "Social vocabulary" below for detail.

**`badge_count()` is heavy -- a ~9-op runtime loop over all 320 badge
slots, not an O(1) lookup.** Call it once (e.g. on a stage's `enter` event)
and cache the result in a variable rather than re-evaluating it from a
per-tick or per-frame handler. It also holds 3 of gqc's 4 int registers
(`GQ_REGISTERS_INT`) for the duration of that loop -- an enclosing
expression has at most 1 register free while it's evaluating (3 again once
it returns); a second `badge_count()` in the *same* expression (or any
other expression that needs 2+ registers concurrently with the first
one's still-live result) can hit `No free registers available`.
The `play` forms are:

```
play bganim  <anim>;      // background slot
play fganim(N) <anim>;    // foreground image slot N (1 or 2)
play fgmask(N) <mask>;    // foreground mask slot N — pairs with fganim(N)
```

Foreground sprite/mask **position** is set through reserved builtin int vars:
`GQI_FGANIM1_X/Y`, `GQI_FGMASK1_X/Y`, `GQI_FGANIM2_X/Y`, `GQI_FGMASK2_X/Y`
(and `GQI_BGANIM_X/Y`). See `GQ_RESERVED_INTS` in `structs.py` for the full
list of builtins (`GQI_*` ints, `GQS_*` strings such as `GQS_PLAYER_HANDLE`).

**`str(x)` casts cannot be composed inline in a `+` chain** — the grammar
only allows `str(x)` as the *entire* right-hand side of a `:=` (`string_cast`
is a top-level alternative to `string_expression`, not embeddable inside
one; see `grammar.py`'s `string_assignment`). To build `"score=" +
str(score)`, cast into an intermediate str var first:

```
score_str := str(score);
GQS_LABEL2 := "score=" + score_str;
```

### Randomness

**`random(lo, hi)`** (gamequeer#422) returns a pseudo-random int in the
*inclusive* range `[lo, hi]` (both full `int_expression`s, so e.g.
`random(1, max_hp)` is valid):

```
roll = random(1, 6);          // 1..6 inclusive, like a d6
dmg = random(low_dmg, high_dmg);
```

Its *multiplicative core* is the same Park-Miller "minimal standard" LCG
the game corpus already hand-rolled before this existed (see e.g.
`gq-games/donsol/donsol.gq`'s card-shuffle `lcg`), advanced one Schrage-method
step on every call. Its *seeding* is NOT the same as donsol.gq's: the state
is perturbed on every call with `GQI_PLAYER_ID` and a hidden counter that
increments once per `random()` *call* (zero at boot) -- not donsol.gq's own
`ctr`, which is sampled from a free-running timer counter for real
wall-clock entropy. That means **the first `random()` call after a fresh
cart boot is fully determined by the badge's `GQI_PLAYER_ID`** and repeats
identically on every reboot of the same badge; only later calls within the
same boot session diverge from each other. No setup required either way:
the first call anywhere in a game lazily creates the hidden state; a game
that never calls `random()` pays nothing for it. See
`IntExpression._emit_random` (`gqc/src/gqc/datamodel.py`) for the full
derivation.

Also available: `min(a, b)`, `max(a, b)`, `clamp(x, lo, hi)` (`=
min(max(x, lo), hi)`), and `abs(x)` -- all full `int_expression` arguments,
all fold to a single literal at compile time when every argument is one
(unlike `random()`, which never folds -- it reads live state).

**If a game needs its first draw to actually vary from boot to boot**
(e.g. a card shuffle that shouldn't replay identically every time the same
badge boots the cart), `random()` alone doesn't provide that -- hand-roll
real entropy the same way donsol.gq does, with the recipe below: arm a
`timer` event on a menu/title screen so a counter free-runs while the
player is looking at the screen, and salt an int variable with it (or feed
it straight into your own LCG state) before relying on any random draw.
The recipe is also useful for driving a full shuffle from one
manually-managed seed, or matching a specific published LCG for
cross-checking against another implementation. Note it predates `random()`
and uses a *different* multiplier (16807, the original 1969 Lehmer/
Park-Miller constant) than `random()`'s own (48271, the 1993 revised
"minimal standard" constant, also used by donsol.gq) -- the two aren't
interchangeable mid-sequence, but both are valid, full-period generators on
their own terms.

Build one from two pieces: an entropy source sampled at a human input event,
and a deterministic generator.

**Entropy**: run a self-re-arming counter while waiting for the player, and
sample it the moment they act:

```
event timer {
    c = c + 1;
    timer 1;
}
```

The VM timer is a single global one-shot (see `timer_active` in
`gamequeer.c`), so this pattern monopolizes it for as long as it runs — don't
also rely on `timer` for anything else (e.g. a periodic scripted behavior
you built with `timer`) while this is armed.

**Generation**: seed a Park-Miller LCG from the sampled counter (fold in
`GQI_PLAYER_ID`, or another badge word, first if per-cart variation across
badges is wanted), clamp into `[1, 2147483646]`, and step it with the
**Schrage-form** update below. This is the only LCG form to use: the VM's
arithmetic is plain signed `int32` C arithmetic, and a naive LCG like
`state = state * 1103515245 + 12345` relies on signed-overflow wraparound,
which is undefined behavior in C and not guaranteed to produce identical
results between the emulator (gcc/clang) and the badge (`cl430
--opt_level=3`).

**Clamp the seed as two separate statements, mask before modulo**: C's `%`
takes the sign of the dividend, so if the folded-in badge word can be
negative (bit 31 set), `seed % 2147483646 + 1` can land on `state = 0` —
which is an absorbing fixed point of the Schrage step below (`0 →
2147483647 → 2147483647 …`, a permanently stuck generator). Mask to
non-negative *before* the modulo clamp:

```
seed = seed & 2147483647;
state = seed % 2147483646 + 1;
```

After masking, `seed` ∈ `[0, 2^31-1]`; `% 2147483646` gives `[0,
2147483645]`; `+1` gives `[1, 2147483646]` — `state` can never be `0` or
`2147483647`. Keep the mask and the modulo/`+1` clamp as separate
statements as shown, not combined into one mixed `%`/`&`/`+` expression.

```
// state must be a volatile int, seeded to 1..2147483646 before first use
hi = state / 127773;
lo = state % 127773;
state = 16807 * lo - 2836 * hi;
if (state <= 0) {
    state = state + 2147483647;
}
// roll: r = state % N; for a 0..N-1 result
```

### Social vocabulary: badge-tracking sugar

`gamequeer#423` adds a first-class vocabulary over the same 320-bit
badges-seen bitfield (`BADGES_ALLOWED = 320`) that `badge_get`/`badge_set`/
`badge_count()` already expose, replacing hand-rolled range-compare chains
and a copy-pasted new-badge-detection idiom.

**`cohort NAME = <lo>..<hi>;`** — a top-level declaration (same
declare-before-use rule as `const`/`enum`: it must appear earlier in the
file than any `in_cohort`/`count_seen` reference to it) naming an inclusive
player-ID range. `lo` must be `<= hi`, and both must fall within
`0..BADGES_ALLOWED-1` (0..319), or the compile fails with a pointed error
(`datamodel.Cohort.__init__`). Purely compile-time bookkeeping
(`Cohort.cohort_table`) — no on-cart footprint of its own.

```
cohort Staff = 1..50;
cohort Attendees = 51..319;
```

**`seen_self();`** (event-body statement) — new-badge detection in one
call, desugaring exactly to the idiom it replaces:

```
if (badge_get(GQI_PLAYER_ID) == 0) { badge_set GQI_PLAYER_ID; }
```

**`have_met(id)`** — a bare rename of `badge_get(id)`; same O(1) single-bit
read (`QCGET`), same int-expression usage (e.g.
`if (have_met(other_id)) { ... }`).

**`in_cohort(NAME, id)`** — desugars to `(id >= NAME.lo) && (id <= NAME.hi)`
over the existing `GE`/`LE`/`AND` ops; O(1), and folds to a compile-time
constant when `id` itself does (`NAME`'s own bounds always are).

**`count_seen()`** / **`count_seen(NAME)`** — the bare, no-argument form is
`badge_count()` itself (a popcount over the full `[0, BADGES_ALLOWED)`
range); `count_seen(NAME)` is the same popcount loop, bounded to `NAME`'s
declared range instead (`IntExpression._emit_count_seen_range`). **Same
cost profile as `badge_count()`, not O(1)**: a runtime loop over
`badge_get`, holding 3 of gqc's 4 int registers (`GQ_REGISTERS_INT`) for its
duration — call once and cache the result rather than re-evaluating from a
per-tick or per-frame handler, same advice as `badge_count()` above.

All five forms lower entirely to *existing* opcodes -- `QCGET`/`QCSET` for
the bit read/write, `GE`/`LE`/`AND` for the range compare, the same
loop-over-`badge_get` shape `badge_count()` already used -- FROZEN VM
CONTRACT: no new opcode, ever.

```
cohort Staff = 1..50;

volatile { int met_count = 0; int in_staff = 0; }

stage start {
    event enter {
        seen_self();
        in_staff = in_cohort(Staff, GQI_PLAYER_ID);
        met_count = count_seen(Staff);
    }
}
```

(Compiles clean against tip `gqc`; disassembly confirms only existing
opcodes, no new one.)

### Firmware detection: `fw_version()`

`fw_version()` (nullary, parens mandatory, like `badge_count()`) returns an
int: `0` on the original 2024 fleet firmware, otherwise the value of the
`GQI_FW_VERSION` reserved builtin int on firmware that defines it. Use it to
gate content on a firmware capability instead of assuming every badge in the
field is running the same build:

```
if (fw_version() == 0) {
    // original 2024 firmware: don't rely on feature X
} else {
    // firmware that defines GQI_FW_VERSION: feature X is available
}
```

Calling `fw_version()` anywhere in a game makes `gqc` splice a hidden probe
stage in ahead of the game's declared `starting_stage` — the compiled cart's
actual entry point becomes the probe, which falls through to the declared
starting stage as soon as it's done. This is fully automatic: nothing to
declare, no extra stage to author, no reference to the probe anywhere in
source. A game that never calls `fw_version()` gets none of this: no probe
stage, no extra boot delay, no probe animation asset.

**The probe costs up to ~1s (21 ticks) of boot delay, but only on original
2024 firmware, and only for a game that calls `fw_version()` at all.** On any
firmware that clamps background-animation frames to 5 ticks (the 20 FPS
line and later), the probe resolves in ~5 ticks (about 50ms) instead. It
works by racing a 1-frame background animation against a 13-tick timer, both
armed the instant the probe stage is entered, and — like the global-timer
monopolization the Randomness recipe above calls out — the probe is the only
thing running a timer while it's armed. See
`linker.inject_fw_version_probe`'s docstring (`gqc/src/gqc/linker.py`), and
gamequeer#410, for the full mechanism and tick-margin derivation.

**Never write `GQI_FW_VERSION` from cart code.** It's undefined on original
2024 firmware — writing it there corrupts whatever adjacent RAM the linker
happened to place next, since that firmware has no bounds check for a
reserved-int offset it's never heard of. `gqc` refuses to compile a write to
it (`Cannot assign to read-only variable GQI_FW_VERSION`). Read it only
through `fw_version()`, not directly: on original 2024 firmware — which
never populates `GQI_FW_VERSION` at all — a direct read returns unspecified
adjacent RAM, not `0`. Firmware that defines it populates it unconditionally
at cart boot, so a direct read is well-defined there regardless of probe
state — but a cart has no way to know which firmware it's on without
running the probe, which is exactly the problem `fw_version()` exists to
solve.

## 2. Labels (on-screen text)

Four label slots (`GQI_LABEL{1..4}_X/Y` position, `GQS_LABEL{1..4}` text,
shared `GQI_LABEL_FLAGS` int) render via `draw_label_stack()` ->
`Graphics_drawString()` (`gamequeer.c`/`grlib`). A label only draws if its
string's first byte is non-zero. `GQI_LABEL_FLAGS` packs two bits per label
at `label_index * 8`: bit 0 = color-invert (white background / black text
instead of the default black background / white text), bit 1 = opaque
(fill the background rectangle; if unset, only the glyph foreground pixels
are drawn and the existing background shows through untouched).

**Non-opaque + color-inverted text on an untouched black canvas is
invisible** — color-invert alone sets the foreground to *black*, and with
opaque unset nothing paints the background, so black-on-black renders
nothing (found while authoring `perf_text.gq`'s edge-case label — fixed by
also setting the opaque bit).

**Deeply nested parenthesized `|`-of-shifts subexpressions can exhaust the
compiler's register pool** — each level of `(term | (term | …))` nesting
holds one more register live while codegen recurses into the next, and
`IntExpression`'s allocator has only 4 int registers (`GQ_REGISTERS_INT` in
`structs.py`), so a handful of nested levels fail with `No free registers
available`. A flat chain like `(1<<0)|(1<<1)|(1<<9)|(1<<16)|(1<<17)`
left-folds into a single accumulator (~2 registers) and is fine at any
length. Restructure into a flat chain, or precompute a literal.

The font is `g_sFontFixed6x8` (`grlib/fonts/fontfixed6x8.c`): fixed 6×8px
glyphs, covering printable ASCII **0x20 (space) .. 0x7E (`~`)**, 95 glyphs.

## 3. Menus (choice + text-entry)

A stage binds **one** of:
- `menu <name> [prompt "…"];` — a choice menu (`menus { name { N: "Label";
  … } }` block, max 6 options / `GQ_MENU_MAX_OPTIONS`). Renders via
  `draw_menu_choice()` (`menu.c`).
- `textmenu [prompt "…"];` — free text entry (internally a special
  `GQ_PTR_BUILTIN_MENU_FLAGS` sentinel menu pointer). Renders via
  `draw_menu_text()`. Result lands in the builtin `GQS_TEXTMENU_RESULT`
  string once confirmed.

Both auto-load on the stage's `enter` event (no explicit `play`-style
statement). **While a menu is active, `handle_events()` hijacks button
input before it reaches the stage's own `event input(...)` handlers**
(`gamequeer.c`): a choice menu intercepts `A` (confirm), `L`/`R` (move
selection); a text-entry menu intercepts `A` (confirm), `B` (cycle symbol
class: CAPS → lower → NUM → SPECIAL), `L`/`R` (cycle current char, or move
the cursor in position-select mode), and `CLICK` (toggle
per-character/position-select mode). **`input(B)` is *not* consumed by a
choice menu** (`handle_event_menu_choice()` has no `BUTTON_B` case), so a
stage's own `input(B)` handler still fires even with a choice menu open —
everything else is fully hijacked. On confirm, the `menu` event fires with
`GQI_MENU_VALUE` (choice) or `GQS_TEXTMENU_RESULT` (text entry) set.

### Driving menu navigation headlessly

The headless emulator's `--input FILE` flag replays one button per tick
from a newline-delimited script of `A`, `B`, `L`, `R`, `CLICK` tokens
(`HAL.c`'s `HAL_input_load()`/`HAL_event_poll()`) — this is how to exercise
menu navigation deterministically without hardware. Example (navigate down
twice, confirm):

```
R
R
A
```

```bash
build-headless/gamequeer --ticks 3 --input nav.txt --dump out.pgm cart.gqgame
```

**`gostage` defers the new stage's `enter` code to the *next* tick** —
`handle_events()` is a single linear pass over event types in a fixed order
(`ENTER=0, BUTTON_A=1, …, MENU=7, …, FGDONE1=9, FGDONE2=10, REFRESH=11`); a
`gostage` inside e.g. an `input(B)` handler (index 2) sets the `ENTER` flag
(index 0) too late for that same pass, so the new stage's `enter` block
only runs on the tick *after* the button that triggered `gostage`. Plan
`--ticks` counts accordingly (one extra tick per stage transition). Plain
button-driven state changes that don't call `gostage` (e.g. menu navigation,
a `SETVAR` to a visual builtin) apply and redraw within the same tick they
were polled.

## 4. The `gqc` compiler

`python -m gqc <subcommand>` (`gqc/src/gqc/gqc.py`):

- **`compile <input.gq> -o <out_dir>`** — produces `<out_dir>/<name>.gqgame`
  (the flashable cart), plus `map.txt` (linker/symbol summary) and
  `cmds.gqasm` (disassembled event bytecode) unless `--no-mem-map` is given.
  Animation/cue source files are resolved **relative to `<input.gq>`'s own
  parent directory** as `assets/animations/<file>` and `assets/lighting/<file>`
  — not the process CWD — so `<input.gq>` must be a self-contained game
  directory's entry file, `<name>/<name>.gq` (see `new`/`migrate` below).
- **`new <name> [-o <out-dir>] [--force]`** — scaffold a new game in the
  game-as-directory layout: `<name>/<name>.gq` (a starter `game{}` block +
  `start` stage) plus `<name>/assets/animations/` and `<name>/assets/lighting/`,
  under `--out-dir` (default: CWD).
- **`mkanim -i <src> -o <dir> [-d <dither>] [-f <fps>]`** — standalone
  GIF/video/image → dithered 1-bit frames (writes `anim.gif` + `frame*.bmp`).
  Note: the `compile` pipeline runs this conversion **internally** per
  `animations{}` entry, so you rarely call `mkanim` directly.
- **`mkcue -i <src> -o <dir>`** — build an LED lighting cue.
- **`migrate <name> [-w <workspace>] [--dry-run]`** — re-layout a flat
  `games/<name>.gq` (+ shared workspace `assets/`) game onto its own
  self-contained `<name>/<name>.gq` directory: copies only the assets it
  actually references and rewrites their path literals to match. Verifies the
  migrated game compiles to a byte-identical `.gqgame` before committing
  anything; on any mismatch the original flat game is left untouched.
- **`init-dir <dir>`** — scaffold a fresh workspace at `<dir>`: a `build/`
  output directory, a `.gitignore`, and a self-sufficient `Makefile`
  (`makefile_src.py`) that discovers the game-as-directory convention
  directly in GNU Make (`$(wildcard)`/`$(foreach)`/`$(eval)`, the same
  pattern `gq-games`'s own hand-maintained `Makefile` uses): any top-level
  `<name>/<name>.gq` under the workspace root becomes a `make` target,
  live, with no separate regeneration step to re-run when a game is added
  or removed. There's no top-level `games/` or shared `assets/` directory
  — add a game with `gqc new <name>` (each game brings its own
  `<name>/assets/`), then just run `make`. Like `gq-games`'s Makefile, this
  one is **asset-blind**: it only tracks a game's entry `.gq` file, not its
  `assets/` subtree, so an asset-only edit needs `make clean` (or deleting
  that game's `build/<name>/`) to force a rebuild.
- **`update-makefile-local <dir>`** — regenerates `<dir>/Makefile.local`
  using the same top-level `<name>/<name>.gq` discovery, for a
  hand-maintained Makefile that still wants to `-include` a
  Python-generated fragment instead of computing the game list itself. The
  `Makefile` `init-dir` scaffolds doesn't call or need this — it discovers
  games live. Sane on a workspace with no games (writes an empty `all:`
  target).

## 5. How animations bind and get encoded

An `animations{}` entry (`Animation` in `datamodel.py`) takes options:
`frame_rate`, `dithering := "…"`, `w`, `h`, `duration`.

- **`w` / `h` default to 128** and the source is **resized** (not cropped) to
  `w×h`. Max 128 each (they're `uint8_t` on-cart).
- **`frame_rate`** must be a factor of 100 (`ticks_per_frame = 100/rate`);
  non-factors are rounded with a warning. On the badge every frame is clamped
  to a **minimum 5 ticks (20 FPS)** duration (`GQ_MIN_FRAME_DURATION`), so
  `frame_rate` above 20 buys nothing on hardware. Badges running older
  shipped firmware clamp at 20 ticks (5 FPS) instead, so a cart authored
  above 5 FPS degrades to that rate there.
- A single-frame source uses `duration` (default 100) as its tick count.

### Frame encoding is chosen automatically by size

`Frame.__init__` (`datamodel.py`) encodes each quantized frame **both** as
RLE7 and as UNCOMPRESSED (1bpp, row-padded) and keeps whichever is **smaller**:

- `IMAGE_FMT_1BPP_COMP_RLE7` (`0x71`) — run-length; **fast** decode path.
- `IMAGE_FMT_1BPP_UNCOMP` (`0x01`) — raw bitmap; **slow** decode path.

(`IMAGE_FMT_1BPP_COMP_RLE4` exists in the enum but is commented out of both the
size-comparison and the format lookup, so **RLE4 is not reachable** through the
public compile pipeline today — noted in the mask golden fixtures too.)

**Verify the chosen encoding** after compiling by reading the `.frame` section
of `map.txt` — each frame prints as e.g.
`Frame(128x128:IMAGE_FMT_1BPP_COMP_RLE7)`:

```
grep -A40 '^\.frame ' build/<name>/map.txt | grep 'Frame('
```

### Deterministic knobs: flat/RLE vs dithered/UNCOMPRESSED

Encoding is **content-driven**, so control it via content + dithering choice:

| Want | Content | `dithering :=` | Result |
|------|---------|----------------|--------|
| **RLE7 (fast)** | Solid / large flat regions | `"none"` | Few long runs → RLE7 wins. |
| **UNCOMPRESSED (slow)** | Continuous-tone gradient / photo | `"floyd_steinberg"` (or `bayer`, `sierra2`, `sierra2_4a`, `heckbert`) | Dense per-pixel noise → RLE7 blows up, raw bitmap wins. |

`DITHER_CHOICES` = `none, bayer, heckbert, floyd_steinberg, sierra2,
sierra2_4a`. **All six** are available for **GIF/video** sources (they go
through ffmpeg's `paletteuse`). A **static image** source (`.png/.bmp/.jpg`)
only supports `none` or `floyd_steinberg` (`anim.py:make_animation_from_image`).

## 6. Masks (fg + fgmask pairs)

A masked foreground sprite is two same-slot animations: `play fganim(N) img;`
plus `play fgmask(N) msk;`. The mask is a 1-bit image where white = draw the
sprite pixel, black = leave the background. The mask and the sprite are each
encoded independently (either can be RLE7 or UNCOMPRESSED). Study the golden
fixtures `gamequeer/tests/golden/mask_encoding_{a,b}.gq`, which between them
cover all four (image-encoding × mask-encoding) combinations gqc can produce.

## 7. Compile → flashable cart (the exact command)

From a game-as-directory workspace — each game self-contained at
`<workspace>/<name>/<name>.gq` plus its own `assets/` — inside the builder
container:

```bash
docker run --rm --workdir /workspaces/gamequeer \
  -v "$PWD":/workspaces/gamequeer --user $(id -u):$(id -g) \
  gamequeer-builder:latest \
  /bin/bash -c "cd <workspace> && \
    PYTHONPATH=/workspaces/gamequeer/gqc/src python -m gqc \
      compile -o build/<name> <name>/<name>.gq"
```

The flashable cart is `<workspace>/build/<name>/<name>.gqgame`.

This repo's own `examples/` hasn't been moved onto this layout yet
(gamequeer#440) and won't compile as shown above until it is; `gq-games`
(a separate repo, the actual game library) is the current worked reference.

### Validate rendering headlessly (emulator)

Build the emulator with `-DGQ_HEADLESS=ON` and dump a framebuffer PGM:

```bash
cd gamequeer && cmake -B build-headless -DGQ_HEADLESS=ON && cmake --build build-headless
build-headless/gamequeer --ticks <N> --dump out.pgm <cart>.gqgame
```

(This is exactly what the `tests/` golden-framebuffer harness does;
`make test-headless` runs the whole ctest suite in the container.)

### From `.gqgame` to a physical cartridge

A badge boots a game from a **cartridge** carrying a W25Q128JV 16 MB SPI
flash. The `.gqgame` that `compile` emits is **already the raw cart image** —
byte-for-byte what belongs at flash address 0, no transformation:

- The linker lays the cart out from `cart_ptr_start = 0`, header first
  (`linker.py`), then animations, stages, frames, frame-data, cues, menus,
  variables, startup code, and events. Sections that the hardware must be
  able to sector-erase independently are padded with `0xFF` to the next
  4 KB boundary (`linker.py` — matches the W25Q128JV's 4 KB sector
  granularity). `compile` writes the linker's byte buffer verbatim to the
  file (`gqc.py`).
- Offset 0 holds `gq_header`: magic `GQ_MAGIC = "GQ01"`, id, 22-byte title,
  `starting_stage`, `startup_code`, `persistent_vars`, `persistent_crc16`,
  color, flags, CRC16 (`gamequeer/include/gamequeer.h`).
- On-cart pointers are 32-bit with the namespace in the top byte
  (`GQ_PTR_NS_CART = 0x01`, address in the low 24 bits — `gamequeer.h`). The
  VM's `load_game()` reads the header from cart address 0 under the CART
  namespace and then follows the cart-namespaced pointers baked in by the
  linker (`gamequeer/src/gamequeer.c`). The `persistent_vars` block is
  4 KB-aligned and padded to a full 4 KB sector (`linker.py`) so a running
  game can rewrite just that sector.

The emulator consumes the identical layout: it `fread`s the `.gqgame` straight
into a `CART_FLASH_SIZE_MBYTES` (16 MB) `flash_cart[]` buffer at index 0 and
resolves CART reads as `flash_cart[GQ_PTR_ADDR(ptr)]` (`gamequeer/src/HAL.c`).
So a headless-emulator run at `flash[0]` is byte-equivalent to a real cart
programmed at flash address 0 — which is why the emulator validation above is
a faithful proxy for on-badge behavior.

Nothing in either repo burns the image onto the cart: `gqc` has no
`flash`/`burn`/`write` subcommand (it stops at emitting the `.gqgame`); the
badge firmware (`qc2024` repo, `ccs_workspace/qc2024/flash.c`, `HAL_badge.c`)
is a cart **reader** whose only cart write path rewrites the game's own 4 KB
`persistent_vars` save sector (a direct full-cart write is refused —
`HAL_badge.c`: `GQ_PTR_NS_CART` write returns 0); and `qc2024`'s
`flashing/flash.py` provisions the 2-byte badge ID into MSP430 FRAM at
`0x1800`, not the cart. The image is programmed onto the cartridge flash
out-of-band with an external SPI programmer, as follows.

**Burning a `.gqgame` onto a cartridge (external SPI programmer).**

Hardware: a CH341A USB SPI programmer plus the cart-slot fixture. The
W25Q128JV is a **3.3 V** part — the CH341A board must be 3.3 V-safe on its
data lines. flashrom detects the chip as `W25Q128.V` (16384 kB).

Software: distro `flashrom` (v1.3.0) and `usbutils`; run `flashrom` with
`sudo`.

**Recommended: `qc2024`'s `flashing/cart_flash.py`.** It automates all of
padding, layout-file generation, and the flashrom invocations below —
region-limited erase/program/verify by default (`--full` for a whole-chip
write), with a `--dry-run` that prints the exact commands without touching
hardware. Run it from the root of a `qc2024` checkout (a separate repo from
`gamequeer`; the path below is relative to it):

```bash
python3 flashing/cart_flash.py write <name>.gqgame
python3 flashing/cart_flash.py verify <name>.gqgame   # optional, independent read-back check
```

See `flashing/cart_flash.py --help` (or its module docstring) in the
`qc2024` repo for the full flag set, including the WSL2/usbipd pre-flight
check and `--programmer`/`--expect-chip` overrides.

On WSL2 the CH341A enumerates Windows-side and is attached into the distro
with [usbipd-win](https://github.com/dorssel/usbipd-win). From an elevated
Windows shell, `usbipd bind --busid <id>` once, then
`usbipd attach --wsl --busid <id>`; it then appears in the distro as USB ID
`1a86:5512` (verify with `lsusb`).

**Manual fallback**, for when the wrapper isn't available. This is the exact
sequence `cart_flash.py` automates — its flashrom invocations use
`-c "W25Q128.V"` to pin the expected chip on every call, and `-N`
(`--noverify-all`) on region-limited writes so `-w`'s own auto-verify reads
back only the written region instead of the whole 16 MiB chip:

1. **Probe** the programmer and chip:

   ```bash
   sudo flashrom -p ch341a_spi -c "W25Q128.V"
   ```

   It must print `Found Winbond flash chip "W25Q128.V" (16384 kB, SPI)`. A
   no-chip-found or all-`0xFF` probe with a known-good programmer means the
   cartridge is bad or unseated (a factory-blank chip still answers RDID with
   its JEDEC ID), so reseat or swap the cart.

2. **Pad** the `.gqgame` to the full 16 MiB chip size with `0xFF` — flashrom
   requires a chip-sized image, and `0xFF` bytes over already-erased flash
   are skipped rather than written:

   ```bash
   cp <name>.gqgame cart_padded.bin
   truncate -s 16M cart_padded.bin
   ```

3. **Write a layout file** confining the operation to the image's extent,
   its end rounded up to a 4 KiB sector boundary. For a 12288-byte image
   (`perf_flat.gqgame`), the extent `0x0..0x2fff` is already sector-aligned:

   ```
   00000000:00002fff game
   ```

4. **Program** (region-limited erase + program + verify, completes in
   seconds):

   ```bash
   sudo flashrom -p ch341a_spi -c "W25Q128.V" --layout cart.layout --include game -N -w cart_padded.bin
   ```

5. Optionally **read back** the same region and byte-compare the image
   extent for an independent verification:

   ```bash
   sudo flashrom -p ch341a_spi -c "W25Q128.V" --layout cart.layout --include game -r cart_readback.bin
   ```

The burned cart boots and renders on a physical badge. A region-limited write
leaves any data past the new image's end intact — harmless, since the VM
follows the header's cart pointers and never reads past them, but if the cart
previously held a larger game and you want the tail scrubbed, drop
`--layout`/`--include`/`-N` (keep `-c "W25Q128.V"`) and write the full
16 MiB `cart_padded.bin` (matching `cart_flash.py`'s own `--full`).

The recipe above assumes the cart is pulled and seated directly in the
CH341A. An **in-system** variant also exists: the cart stays seated in the
badge's cart slot, with the CH341A driving it through a pass-through
fixture while the badge itself is held in a debug-controlled reset (GPIOs
high-impedance) via qc2024's `cart-bus-hold.sh` tooling, so the burn
happens without unseating the cart between burn and play. See qc2024's
[`docs/bench-workflow.md`](https://github.com/duplico/qc2024/blob/default/docs/bench-workflow.md)
for the full in-system procedure.

## 8. Gotchas found

- **`animations{}`/`lightcues{}` source literals are bare filenames**,
  resolved against the game's own directory as `assets/animations/<file>` /
  `assets/lighting/<file>`, not the process CWD. A "does not exist" asset
  error against a game still living flat under `games/<name>.gq` means it
  needs `gqc migrate <name>` first, not a path fix.
- **`w`/`h` default to 128 and *resize*** — a small source is scaled up, a
  wide source is distorted (no aspect preservation, no crop).
- **Hand-authored GIFs can silently collapse to one frame** through gqc's
  internal ffmpeg `fps` resample. Always confirm the frame count in `map.txt`.
  (Our 8-frame source GIFs land as 7 frames after resampling at 5 FPS — still
  multi-frame, but don't assume 1:1.)
- **Frame duration is clamped to 5 ticks (20 FPS)** on the badge regardless of
  `frame_rate`. Badges running older shipped firmware clamp at 20 ticks
  (5 FPS) instead — carts degrade to that rate there.
- **A masked fg/mask pair must resample to the *same* frame count.**
  `gq_draw_image_with_mask()` only composites while both the sprite slot and
  its mask slot are `in_use` with matching width/height
  (`draw_animation_stack()` in `gamequeer.c`); if one GIF resamples to fewer
  frames than its pair, the shorter one goes `in_use=0` first and the
  renderer silently falls back to an *unmasked* draw for the remaining
  frames. Give both source GIFs identical frame timing/count and the same
  `frame_rate` option so they resample in lockstep (verify via `map.txt`'s
  `.anim` section — both animations' frame-table spans should be equal).
- **Strings are 21 usable chars**; overlong values raise at compile time.
- **`str(x)` casts can't be composed inline in a `+` chain** — cast into an
  intermediate str var first (see "Event-body statements" above).
- **A deeply *nested* parenthesized `|`-of-shifts expression can exhaust the
  4-register compiler pool** (`No free registers available`) — a flat `|`
  chain is fine at any length; restructure or precompute a literal instead
  (see "Labels" above).
- **Integer division/modulo by a zero divisor is unguarded.**
  `run_arithmetic()`'s `GQ_OP_DIVBY`/`GQ_OP_MODBY` cases (`bytecode.c`) are
  bare C `/` and `%` with no zero check — a zero divisor is undefined
  behavior/a trap on both the emulator and the badge. Guard any divisor that
  can be zero with an `if` before dividing.
- **`random(lo, hi)`/`clamp(x, lo, hi)` with `hi < lo` is unguarded** — same
  "author's responsibility, not gqc's" contract as the zero-divisor case
  above. `random()` maps into the range via `% (hi - lo + 1)`, an
  unguarded runtime divide if `hi - lo + 1 <= 0`; `clamp()` still compiles
  and runs (it's `min(max(x, lo), hi)`, no division), just returns
  whatever that composition works out to for an inverted range, not a
  "clamp failed" signal.
- **`random()`/`min()`/`max()`/`clamp()` each briefly hold 2-3 of gqc's 4
  int registers** while evaluating (see `IntExpression._emit_random`/
  `_emit_minmax` in `datamodel.py`) — same register-pressure caveat as
  `badge_count()` above; combining two or more of these (or nesting them
  inside an already register-heavy expression) can hit `No free registers
  available`.
- **RLE4 is unreachable** via the public pipeline (commented out in `Frame`).
- Encoding is decided **per frame**, not per animation — a mixed-content
  animation can contain both RLE7 and UNCOMPRESSED frames.
- **`gostage` defers the new stage's `enter` code by one tick** — see
  "Driving menu navigation headlessly" above; applies to any headless
  `--ticks`/`--input` planning, not just menus.
- **Non-opaque + color-inverted label text can render invisible** on an
  untouched black canvas (black-on-black) — see "Labels" above.
- The OLED framebuffer is **128×128** (`OLED_HORIZONTAL_MAX` /
  `OLED_VERTICAL_MAX` in `grlib_gfx.h`), matching the animation `w`/`h` cap;
  the golden-test harness's `--dump` PGM header reads `P5\n128 128\n255\n`.

## 9. The committed perf / regression-content test carts

Under `examples/games/perf/` (assets under `examples/assets/animations/`,
regenerable with `examples/games/perf/gen_perf_assets.py`). `examples/` is
still on the flat layout and doesn't currently compile against tip `gqc`
(gamequeer#440) — the table below describes each cart's content and render
path, not a live, re-runnable recipe. Once `examples/` is migrated, verify a
cart the same way as any other game: compile, check `map.txt` for frame
encoding, and render it in the headless emulator (`--dump`/`--input`).

| Cart | Path drives | Notes |
|------|-------------|-------|
| `perf_mask.gq` | Full-screen **masked** fg blit (`gq_draw_image_with_mask`), animated | pulsing circle + marching band mask, 5 frames each (post-resample), all RLE7; loops via `fgdone(1)` replay so it redraws continuously — perf-usable, not a one-shot static draw |
| `perf_mask_dither.gq` | Full-screen **masked + UNCOMPRESSED** fg blit — per-byte cost on **two** image streams | dithered-gradient sprite + dithered-gradient mask, 5 frames each (post-resample), all UNCOMPRESSED; same `fgdone(1)` replay pairing as `perf_mask.gq`; the steady-state animation worst-case probe for duplico/gamequeer#309 |
| `perf_flat.gq` | Full-screen **flat / RLE7 fast** decode | 7 frames, all RLE7 |
| `perf_dither.gq` | Full-screen **dithered / UNCOMPRESSED slow** decode | 7 frames, all UNCOMPRESSED (cart ~2× larger) |
| `perf_save.gq` | **Persistent-var save during active animation** (4 KB sector erase + CRC copy-back on the badge) | flat/RLE7 bganim baseline + a self-re-arming 5 s `timer` that assigns to a `persistent` int; on-screen `saves=N` label proves the timer/SETVAR plumbing headlessly; fully unattended on hardware (duplico/gamequeer#309 save-hitch probe) |
| `perf_text.gq` | Label path (`Graphics_drawString`), 3 stages | `start`: 4 labels — top-left max-length string, `str(x)`-cast+concat+persistent-str-var content, an off-canvas-clipped opaque/inverted box (edge case), a negative `str(x)` cast. `glyphs1`/`glyphs2`: full printable-ASCII glyph sweep (0x20-0x7E minus `"`/`\`, an authoring-format limitation not a font one) |
| `perf_menu_choice.gq` | Choice-menu chrome (`draw_menu_choice`) | 6 options (the max), varying label lengths incl. one 21-char label clipped off the right edge; navigate + confirm updates a label from `GQI_MENU_VALUE` |
| `perf_menu_text.gq` | Text-entry menu chrome (`draw_menu_text`) | full navigation surface: char cycle, symbol-class cycle, position-select toggle, confirm; confirmed text lands in `GQS_TEXTMENU_RESULT` and updates a label |

`perf_flat` and `perf_dither` are the same shape (full-screen looping bganim)
with opposite content, so the pair isolates rendering's content-dependence;
`perf_mask` and `perf_mask_dither` mirror the same pairing on the masked-blit
path.

### Stage-2 golden fixtures

The text/menu render paths these carts exercise are now covered by committed
`tests/golden/` pixel-identity fixtures at 128×128, protecting Stage 2 (grlib
row-major rewrite, epic duplico/qc2024#47). The golden fixtures live under
`gamequeer/tests/golden/` and are self-contained (they do not depend on this
`examples/` content); they were adapted from the carts here:

- **`label_text.gq`** ← `perf_text.gq`. Four goldens
  (`add_golden_test(golden_framebuffer_label_text_{start,start_scored,glyphs1,glyphs2} …)`
  in `tests/CMakeLists.txt`): pristine `start` (zero-origin max-length label
  + off-canvas-clipped opaque/inverted box — the highest-value clipping case,
  both right and bottom edges at once), post-`input(A)` `start_scored`
  (dynamic `str(x)`+concat content), and `glyphs1`/`glyphs2` (full
  printable-ASCII glyph sweep). Tick counts account for the `gostage`
  one-tick defer (see "Driving menu navigation headlessly").
- **`menu_choice.gq`** ← `perf_menu_choice.gq`. Pristine (6 options at the
  max, one edge-clipped, cursor arrow, hint bar) plus confirmed (after
  scripted `2×R + A`, covering the menu-close → label-redraw transition).
- **`menu_text.gq`** ← `perf_menu_text.gq`. Pristine plus a mid-edit
  position-select state, which covers the alternate cursor-hint icon set
  (`draw_hint_dial_leftright`/`draw_hint_click_updown` vs the CHAR-mode
  icons) — a visually distinct path most other content never reaches.

The golden harness gained an optional `INPUT` parameter to `add_golden_test()`
(a scripted button-input file replayed via `--input`) so button-driven states
can be captured, not just fixed tick counts.

The carts under `examples/games/perf/` remain the **perf** fixtures (animated,
full-screen, run continuously). `perf_mask.gq` in particular has no golden
counterpart — Stage 1's masked-blit path is golden-covered by
`mask_encoding_{a,b,c}.gq`, but the animated full-screen masked-blit form
here is perf-only. `perf_flat.gq`/`perf_dither.gq` are pure perf fixtures (no text/menu
surface) and are not Stage-2-relevant.
