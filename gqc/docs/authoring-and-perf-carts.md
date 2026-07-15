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

### Stage options

- `bganim <anim>;` — background animation for the stage.
- `bgcue <cue>;` — background LED cue.
- `menu <menu> [prompt <str>];` / `textmenu [prompt <str>];`
- `event <type> <statement-or-block>` — event handlers.

### Events

`enter`, `bgdone`, `fgdone(N)` (foreground slot N finished), `timer`, `menu`,
`refresh`, and `input(BTN)` where `BTN` ∈ `A`, `B`, `<-`, `->`, `-` (click).
(`EventType` in `structs.py` is the on-cart ordering; must match the C VM's
`gq_event_type`.)

### Event-body statements

`play`, `cue`, `gostage`, `timer <expr>`, `if (…) … else …`, `loop { … }`
with `continue` / `break`, `badge_set/badge_clear/badge_get`, and assignments
(`x = expr;` int, `s := expr;` string with `+` concat and `str(int)` cast).
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

**A long chain of `<<`/`|` literal-shift terms in one expression can exhaust
the compiler's register pool.** `IntExpression`'s allocator has only 4 int
registers (`GQ_REGISTERS_INT` in `structs.py`); a 5-term chain like
`(1<<0)|(1<<1)|(1<<9)|(1<<16)|(1<<17)` fails to compile with `No free
registers available`, while a 2-3 term chain is fine. Precompute a literal
for wide bitmasks instead.

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
  Animation/cue source files are resolved **relative to the current working
  directory** as `assets/animations/<file>` and `assets/lighting/<file>` — so
  always run `compile` from the workspace dir that has an `assets/` tree.
- **`mkanim -i <src> -o <dir> [-d <dither>] [-f <fps>]`** — standalone
  GIF/video/image → dithered 1-bit frames (writes `anim.gif` + `frame*.bmp`).
  Note: the `compile` pipeline runs this conversion **internally** per
  `animations{}` entry, so you rarely call `mkanim` directly.
- **`mkcue -i <src> -o <dir>`** — build an LED lighting cue.
- `init-dir` / `update-makefile-local` — scaffold a workspace + Makefile that
  auto-discovers `games/**/*.gq`.

## 5. How animations bind and get encoded

An `animations{}` entry (`Animation` in `datamodel.py`) takes options:
`frame_rate`, `dithering := "…"`, `w`, `h`, `duration`.

- **`w` / `h` default to 128** and the source is **resized** (not cropped) to
  `w×h`. Max 128 each (they're `uint8_t` on-cart).
- **`frame_rate`** must be a factor of 100 (`ticks_per_frame = 100/rate`);
  non-factors are rounded with a warning. On the badge every frame is clamped
  to a **minimum 20 ticks (5 FPS)** duration (`GQ_MIN_FRAME_DURATION`), so
  `frame_rate` above 5 buys nothing on hardware.
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

From a workspace with `assets/animations/` present (e.g. `examples/`), inside
the builder container:

```bash
docker run --rm --workdir /workspaces/gamequeer \
  -v "$PWD":/workspaces/gamequeer --user $(id -u):$(id -g) \
  gamequeer-builder:latest \
  /bin/bash -c "cd examples && \
    PYTHONPATH=/workspaces/gamequeer/gqc/src python -m gqc \
      compile -o build/<name> games/<path>/<name>.gq"
```

The flashable cart is `examples/build/<name>/<name>.gqgame`.

### Validate rendering headlessly (emulator)

Build the emulator with `-DGQ_HEADLESS=ON` and dump a framebuffer PGM:

```bash
cd gamequeer && cmake -B build-headless -DGQ_HEADLESS=ON && cmake --build build-headless
build-headless/gamequeer --ticks <N> --dump out.pgm <cart>.gqgame
```

(This is exactly what the `tests/` golden-framebuffer harness does;
`make test-headless` runs the whole ctest suite in the container.)

## 8. Gotchas found

- **Asset paths are CWD-relative** (`assets/animations/<file>`). Compile from
  the workspace root, not from `games/`.
- **`w`/`h` default to 128 and *resize*** — a small source is scaled up, a
  wide source is distorted (no aspect preservation, no crop).
- **Hand-authored GIFs can silently collapse to one frame** through gqc's
  internal ffmpeg `fps` resample. Always confirm the frame count in `map.txt`.
  (Our 8-frame source GIFs land as 7 frames after resampling at 5 FPS — still
  multi-frame, but don't assume 1:1.)
- **Frame duration is clamped to 20 ticks (5 FPS)** on the badge regardless of
  `frame_rate`.
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
- **A wide `<<`/`|` literal expression can exhaust the 4-register compiler
  pool** (`No free registers available`) — precompute a literal instead (see
  "Labels" above).
- **RLE4 is unreachable** via the public pipeline (commented out in `Frame`).
- Encoding is decided **per frame**, not per animation — a mixed-content
  animation can contain both RLE7 and UNCOMPRESSED frames.
- **`gostage` defers the new stage's `enter` code by one tick** — see
  "Driving menu navigation headlessly" above; applies to any headless
  `--ticks`/`--input` planning, not just menus.
- **Non-opaque + color-inverted label text can render invisible** on an
  untouched black canvas (black-on-black) — see "Labels" above.
- The OLED framebuffer is **127×127**, not 128×128 (`OLED_HORIZONTAL_MAX` /
  `OLED_VERTICAL_MAX` in `gamequeer.h`), even though animation `w`/`h` cap at
  128 and the golden-test harness's `--dump` PGM header reads `P5\n127
  127\n255\n`. This is being fixed by duplico/gamequeer#297 (emulator-canvas
  fix) to 128×128 — **do not commit golden PGMs against the carts in this
  doc until #297 lands**, or they'll be 127×127 and need regenerating.

## 9. The committed perf / regression-content test carts

Under `examples/games/perf/` (assets under `examples/assets/animations/`,
regenerable with `games/perf/gen_perf_assets.py`). All six compiled with
`gqc` and confirmed rendering correctly in the headless emulator
(`--dump`/`--input`); image-cart frame encodings additionally confirmed via
`map.txt`.

| Cart | Path drives | Notes |
|------|-------------|-------|
| `perf_mask.gq` | Full-screen **masked** fg blit (`gq_draw_image_with_mask`), animated | pulsing circle + marching band mask, 5 frames each (post-resample), all RLE7; loops via `fgdone(1)` replay so it redraws continuously — perf-usable, not a one-shot static draw |
| `perf_flat.gq` | Full-screen **flat / RLE7 fast** decode | 7 frames, all RLE7 |
| `perf_dither.gq` | Full-screen **dithered / UNCOMPRESSED slow** decode | 7 frames, all UNCOMPRESSED (cart ~2× larger) |
| `perf_text.gq` | Label path (`Graphics_drawString`), 3 stages | `start`: 4 labels — top-left max-length string, `str(x)`-cast+concat+persistent-str-var content, an off-canvas-clipped opaque/inverted box (edge case), a negative `str(x)` cast. `glyphs1`/`glyphs2`: full printable-ASCII glyph sweep (0x20-0x7E minus `"`/`\`, an authoring-format limitation not a font one) |
| `perf_menu_choice.gq` | Choice-menu chrome (`draw_menu_choice`) | 6 options (the max), varying label lengths incl. one 21-char label clipped off the right edge; navigate + confirm updates a label from `GQI_MENU_VALUE` |
| `perf_menu_text.gq` | Text-entry menu chrome (`draw_menu_text`) | full navigation surface: char cycle, symbol-class cycle, position-select toggle, confirm; confirmed text lands in `GQS_TEXTMENU_RESULT` and updates a label |

`perf_flat` and `perf_dither` are the same shape (full-screen looping bganim)
with opposite content, so the pair isolates rendering's content-dependence.

### Recommendation: Stage-2 golden fixtures (post duplico/gamequeer#297)

Once the emulator canvas fix (duplico/gamequeer#297) lands and goldens can
be committed at the corrected 128×128, wire these as `tests/golden/`
fixtures (following the `mask_encoding_{a,b}.gq` / `anim_advance.gq`
pattern: compiled `.gqgame` + committed golden PGM(s) + `add_golden_test()`
entries in `tests/CMakeLists.txt`) to protect Stage 2 (grlib row-major
rewrite, epic duplico/qc2024#47):

1. **`perf_text.gq`'s `start` stage is the single highest-value fixture.**
   It packs the two regression shapes a row-major rewrite is most likely to
   get subtly wrong into one frame: label3's off-canvas opaque/inverted box
   (background-fill clipping *and* glyph clipping together, at both the
   right *and* bottom edges simultaneously) and label1's top-left
   zero-origin max-length string (the opposite corner). Recommend a golden
   at `--ticks 1` (pristine `enter`) and a second at the post-`input(A)`
   state (proves dynamic `str(x)`+concat content, not just static text).
2. **`perf_text.gq`'s `glyphs1`/`glyphs2` stages** for full glyph-shape
   coverage — a row-major rewrite could plausibly corrupt only specific
   glyph bit patterns (e.g. glyphs with lone pixels in the last column/row
   of their 6×8 cell), which a small hand-picked string would likely miss.
   Recommend goldens at `--ticks 2` (glyphs1) and `--ticks 3` (glyphs2) —
   see "Driving menu navigation headlessly" above for why the tick counts
   aren't 1/2 (the `gostage` one-tick defer).
3. **`perf_menu_choice.gq`'s pristine render** (`--ticks 1`) — full menu
   chrome (prompt, 6 options at the max-option boundary, the clipped
   21-char option, cursor arrow, hint bar/icons) in one frame; a second
   golden after 2×`R` + `A` (`--ticks 3`, script above) to also cover the
   confirm → label-redraw transition.
4. **`perf_menu_text.gq`'s pristine render** (`--ticks 1`) — prompt, seeded
   char, cursor box, mode hint icons; a second golden mid-edit in
   position-select mode (`--ticks 4`, `menu_text_mid.txt`-style script
   above) to cover the alternate cursor-hint icon set
   (`draw_hint_dial_leftright`/`draw_hint_click_updown` vs the CHAR-mode
   icons), since that's a visually distinct render path most other content
   never reaches.
5. `perf_mask.gq` is primarily a **perf** fixture (Stage 1 already has
   dedicated golden coverage for the masked-blit path via
   `mask_encoding_{a,b}.gq`), but its animated multi-frame form could be
   added as a golden too if Stage 2 perf work wants continuous-redraw
   masked-blit coverage in the same harness — lower priority than 1-4 above.

`perf_flat.gq`/`perf_dither.gq` are pure perf fixtures (no text/menu
surface) and are not Stage-2-relevant.
