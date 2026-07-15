# Authoring GameQueer games with `gqc`, and generating perf test carts

This is a practical reference for authoring `.gq` games for the GameQueer
console, compiling them with `gqc`, and — the reason this doc exists —
deterministically producing carts that exercise specific renderer paths
(masked blit, flat/RLE fast path, dithered/uncompressed slow path) for
hardware performance profiling (epic duplico/qc2024#45).

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

## 2. The `gqc` compiler

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

## 3. How animations bind and get encoded

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

## 4. Masks (fg + fgmask pairs)

A masked foreground sprite is two same-slot animations: `play fganim(N) img;`
plus `play fgmask(N) msk;`. The mask is a 1-bit image where white = draw the
sprite pixel, black = leave the background. The mask and the sprite are each
encoded independently (either can be RLE7 or UNCOMPRESSED). Study the golden
fixtures `gamequeer/tests/golden/mask_encoding_{a,b}.gq`, which between them
cover all four (image-encoding × mask-encoding) combinations gqc can produce.

## 5. Compile → flashable cart (the exact command)

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

## 6. Gotchas found

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
- **Strings are 21 usable chars**; overlong values raise at compile time.
- **RLE4 is unreachable** via the public pipeline (commented out in `Frame`).
- Encoding is decided **per frame**, not per animation — a mixed-content
  animation can contain both RLE7 and UNCOMPRESSED frames.

## 7. The committed perf test carts

Under `examples/games/perf/` (assets under `examples/assets/animations/`,
regenerable with `games/perf/gen_perf_assets.py`). All three verified: frame
encodings from `map.txt`, rendering confirmed in the headless emulator.

| Cart | Path drives | Frames / encoding |
|------|-------------|-------------------|
| `perf_mask.gq` | Full-screen **masked** fg blit (`gq_draw_image_with_mask`) | fg circle + band mask, both RLE7 |
| `perf_flat.gq` | Full-screen **flat / RLE7 fast** decode | 7 frames, all RLE7 |
| `perf_dither.gq` | Full-screen **dithered / UNCOMPRESSED slow** decode | 7 frames, all UNCOMPRESSED (cart ~2× larger) |

`perf_flat` and `perf_dither` are the same shape (full-screen looping bganim)
with opposite content, so the pair isolates rendering's content-dependence.
