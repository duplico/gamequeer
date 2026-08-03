# DEF CON authoring sprint — plan & handoff record

**Status:** active. **Tracking epic:** [duplico/gamequeer#419](https://github.com/duplico/gamequeer/issues/419).
This document is a durable, hand-off-able snapshot of the language/toolchain-DX plan so any
session (local, web, or a human picking up) can resume from GitHub + commits alone. The epic
and its sub-issues are the live source of truth; this doc preserves the *rationale and the
grounded facts* that would otherwise have to be re-derived.

_AI-drafted via Claude Code at George's request, as part of the pre-DEF CON authoring push._

## Goal

DEF CON is ~2 weeks out. The pitch to the community has two legs:

1. **"Bring your gamequeers — we'll fix performance with a quick field-firmware upgrade."**
   This is the perf saga + `flashing/field_update.py`, which largely *exists*; it's a
   package-and-release task, not part of this sprint's build.
2. **"We have a dramatically improved game-author experience — you've got a week to write
   something and we'll flash it onto carts for you."** This sprint is leg 2: ship enough
   author-facing DX in ~1 week that an outside author can write a game in the following week.

## Ranking function (drives every prioritization call)

- **Favor social games and expressive-while-idle ("lanyard") games; disfavor heads-down
  button-mashing.** Make the favored modes the *easy* path — carrot, not stick. Heads-down
  stays possible but unsugared. This is a thumb on the scale + a spotlight, **not a gate**: a
  rising tide that also lifts heads-down is a pure win. (The formatter/linter, PRNG, etc. are
  mode-agnostic universal wins and rank on their own merits.)
- **Frozen VM.** Everything desugars to today's bytecode / frame format unless a *critical*
  bug forces a change. The badge VM interpreter does not move.
- **The brakes make us faster.** Formatter + linter + codemods are a *front-loaded
  accelerant*, not overhead: they speed up the sprint's own remaining work and carry the
  existing game corpus forward instead of leaving it behind.

## The three concurrent thrusts (→ sub-issues of #419)

1. **Layout convention — do first** (#420): game-as-directory (`<name>/<name>.gq` entry),
   `game{}`-anywhere grammar relaxation (exactly-one, anywhere), game-dir-relative asset
   resolution, `gqc new` emits it. It's the structural half of multi-file (#401) and it's
   what's actively hurting in-flight games.
2. **Foundation, front-loaded — the brakes** (#424): CST/provenance-preserving parse →
   formatter (`gqc fmt`) → linter (`gqc lint`) + modernization codemods. Engine lives in gqc
   (authoritative AST), surfaced in the editor via the hybrid path (#409). Build the CST for
   the game-as-directory structure so multi-file's merge and the linter's whole-program
   analysis aren't reworked later. Also here: conformance gate (#405) + closing live
   gqc↔Langium divergences (#406, #407, and now `fw_version`/#411).
3. **Language features, in parallel — structure-independent:** social layer/cohorts (#423,
   the headline), constants + enums (#421), PRNG + math intrinsics (#422); plus onboarding
   (docs / examples / `gqc new`). Related: range-stages #399, unary #400, ergonomics #402.

## Parked (deferred)

Firmware-side favored modes — **system ambient display** and **badge-global identity store**
(`qc2024`) — deferred. The "launch an ambient app and leave it running" pattern (à la
`glowdeck`) delivers the lanyard experience app-side without them. Working handles are landing
soon, which softens this. App-side ambient/flair sugar is a **stretch** goal for this sprint.

## Decisions on the record

- **#409:** lean **hybrid LSP** — Langium = syntactic layer (coloring, cheap completion), gqc
  = authoritative semantics (diagnostics/lints) — plus **gqc-in-WASM** as one artifact that
  powers editor diagnostics + browser compile + web-play (#404). Do *not* reimplement lint
  semantics in Langium.
- **Variants** (queersafe vs queersafe-lite) are solved by the **`abstract` primitive**
  (declare slots in a base, fill them per-variant) — same primitive as stage
  inheritance/templates. Multi-file concat handles *splitting*; `abstract` handles
  *overriding*. Keep them distinct.
- **Cue language:** effect-primitives (`pulse`/`strobe`/`chase`/`cycle`) desugar to a
  keyframe+easing core; single-timeline + overlay modifiers before layered tracks.
- **Shared asset store** (#403) = the console design system; search-path resolution (game dir
  → blessed `std/console`), version-pinned per game.

## Grounded facts worth not re-deriving (from investigations this planning cycle)

- **No runtime pointer math / computed jump in the VM.** Every memory operand is a
  compile-time-baked pointer (`bytecode.c`); `GOTO` targets are baked. ⇒ all collections are
  **compile-time fixed families** (constant/foldable indices, unrolled); a *runtime*-selected
  index must desugar to a compare-chain. The **one** runtime-indexed structure is the
  badges-seen bitfield via `QCGET`/`QCSET`/`QCCLR` (`badge_get`/`set`/`count`).
- **Compile-time index arithmetic is fine** (relative nav, wrap/clamp) as long as inputs are
  statically known — and "the current stage" is a *lexical* fact, so `help[$i+1]`-style
  navigation folds to concrete targets.
- **LED cue desugar target (frozen):** `gq_ledcue_frame_t` = `uint16 duration` (10ms ticks,
  compiler floors to multiples of 4 → 40ms grid) + 1 `transition_smooth` bit + `rgbcolor8 leds[5]`.
  `smooth` = **VM-native per-channel linear tween** to the next frame; non-linear easing must
  be **baked** into ≤ **50 frames/cue** (`GQ_CUE_MAX_FRAMES`; VM silently truncates beyond —
  compiler must self-limit). Loop/bgcue are set by *how a cue is invoked*, not encodable in
  `.gqcue`: foreground cues are one-shot, only a stage's background cue loops. A non-looping
  `smooth` final frame fades to **black** (#353) — emit terminal `none` to hold.
- **Stage-transition-from-`enter` regime = B+C:** a `gostage` in an `enter` handler consumes
  **one main-loop tick per hop AND flushes the passed-through stage's background** (iterative,
  not recursive; no stack-blow risk). ⇒ the auto-advance "dynamic stage family" trick is only
  valid as *visible staged iteration*, never as invisible random-access indexing.
- **Identity/persistence layers:** badge-global identity is an 8-byte FRAM `t_badge_id_record`
  (numeric id only). `GQS_PLAYER_HANDLE` is a **RAM builtin** (`gq_builtin_strs[]`) with no
  confirmed badge-global persistent backing → **system/badge-global flair is firmware
  greenfield** (`qc2024`), hence parked. Per-game `persistent {}` lives in the per-cart SAVE
  region (CRC16'd). The seen-bitfield is persistent.

## Current state

- Branch `claude/language-features-np8ywf` reset to latest `origin/default`.
- Landed in gqc on `default` (post-audit): `#385` const-fold, `#386` inline-`str()`-concat,
  `#387` `badge_count()`, `#411` `fw_version()`+`GQI_FW_VERSION`. The latter three are **live
  Langium divergences** (in gqc, not the editor grammar) — `#406`/`#407` open, `fw_version` to
  be folded in.
- Foundation issues `#405`–`#409` open, unworked.

## How to resume

1. Read epic **#419** and its five sub-issues (#420 layout, #421 constants, #422 PRNG/math,
   #423 social, #424 substrate).
2. Each feature is being built by a `gqc-developer` agent in its own worktree → discrete PR
   referencing its issue. Check open PRs on `duplico/gamequeer`.
3. Integration note: the feature PRs each touch `gqc/src/gqc/grammar.py` — expect to rebase/
   merge them sequentially. The CST/substrate work (#424) is intentionally sequenced
   deliberately (not in the parallel spray) because everything rebases onto it.
4. Per-feature discipline (#408): each language feature lands in gqc + a fixture + a Langium
   grammar update (conformance batch #405).
