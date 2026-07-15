#ifndef GQ_PERF_H
#define GQ_PERF_H

#include <stdint.h>

/* -------------------------------------------------------------------------
 * GQ_PERF_INSTRUMENT -- opt-in, build-time performance instrumentation.
 * -------------------------------------------------------------------------
 * This is the emulator half of the instrumentation pass called for in
 * qc2024's docs/perf-investigation.md, "Before changing code": a way to get
 * real per-section timings instead of the static cycle estimates in that
 * doc's "End-to-end per-frame cost estimate" table.
 *
 * Undefined (default, all normal builds including the firmware): every
 * macro below expands to a no-op, and gq_perf_stats / gq_perf_record() /
 * HAL_perf_now() are not declared. This header can be #included
 * unconditionally from shared code with zero footprint -- no new symbols,
 * no new stack slots, no new branches. Verified by a byte-identical
 * before/after .map for a non-instrumented build (see the PR body for the
 * comparison).
 *
 * NOTE: a SECOND, separate flag, GQ_PERF_INSTRUMENT_RUNS, gates only the
 * two per-RUN sections (5 DRAW_DECODE, 6 DRAW_WRITE) independently of
 * GQ_PERF_INSTRUMENT's other five per-draw/per-tick sections -- see that
 * flag's own doc block further down for why (measurement-methodology tool:
 * isolates per-run instrumentation overhead from the outer sections it
 * would otherwise contaminate).
 *
 * Defined: adds a small RAM stats struct (gq_perf_stats, currently 120 B --
 * an 8 B header plus 7 sections * 16 B each; see layout below) with
 * per-section count / accumulated-duration / min / max, in microseconds,
 * updated by GQ_PERF_ENTER(SECTION) / GQ_PERF_EXIT(SECTION) pairs placed
 * around hot-path code in gamequeer.c and oled.c.
 *
 * Sections instrumented so far (see GQ_PERF_SECTION_LIST below to add
 * more; indices below match GQ_PERF_SECTION_LIST's declaration order,
 * which is also each section's position in gq_perf_stats.sections[] --
 * see the struct layout note below for the byte-offset math a raw-memory
 * reader needs):
 *   0 DRAW_OLED_STACK      draw_oled_stack() total (clear + animations +
 *                          labels + menu + flush)
 *   1 DRAW_ANIMATION_STACK draw_animation_stack() (subset of the above)
 *   2 HANDLE_EVENTS        handle_events(): the full event-dispatch pass,
 *                          which includes any run_code() calls it triggers
 *                          and (if GQ_EVENT_REFRESH fires) the nested
 *                          DRAW_OLED_STACK section. This is the
 *                          "handle_events/run_code aggregate" section:
 *                          reported as one number by design, not split,
 *                          because run_code() has no single entry/exit
 *                          point of its own outside of handle_events()'s
 *                          per-event dispatch loop.
 *   3 SYSTEM_TICK          system_tick() total (animation/timer bookkeeping
 *                          + led_tick(), unless GQ_SUPPRESS_LED_TICK)
 *   4 OLED_FLUSH           the Graphics_flushBuffer() call inside
 *                          draw_oled_stack() -- see the flush-hook design
 *                          note further down for why this is measured at
 *                          the shared-code call site rather than via a new
 *                          HAL primitive.
 *   5 DRAW_DECODE          issue #261's run-aware RLE decode: each call to
 *                          gq_image_peek_run()/gq_image_advance_run() (the
 *                          pair, together -- one section covers both) in
 *                          oled.c's gq_draw_image()/gq_draw_image_with_mask()
 *                          run loops. Includes any interleaved
 *                          gq_image_load_byte() cart reads triggered by a
 *                          run/buffer boundary. Per-RUN granularity, not
 *                          per-pixel -- see the observer-effect note below.
 *   6 DRAW_WRITE           issue #261's HAL_oled_fill_run() call, wrapped
 *                          at the same per-run granularity as DRAW_DECODE.
 *                          Only entered when a run actually reaches the
 *                          framebuffer write (a fully clipped or fully
 *                          transparent-masked run skips it, same as before
 *                          this instrumentation existed) -- so DRAW_WRITE's
 *                          count can be lower than DRAW_DECODE's count for
 *                          the same frame.
 *
 * NOTE (observer effect, DRAW_DECODE/DRAW_WRITE specifically): these two
 * sections are timed per RLE *run*, not per pixel -- that's the whole
 * point of issue #261's fix (few runs = cheap redraw), and it's also what
 * keeps the two extra HAL_perf_now() calls per run cheap relative to the
 * work being measured. Timing per *pixel* the way the old code drew them
 * would have made the measurement overhead comparable to (or larger than)
 * the thing being measured, especially for long runs where the batched
 * write is now very fast. Per-run timing avoids that trap by construction.
 *
 * NOTE: sections nest (DRAW_ANIMATION_STACK and OLED_FLUSH are both
 * sub-intervals of DRAW_OLED_STACK; HANDLE_EVENTS can contain a full
 * DRAW_OLED_STACK pass; DRAW_DECODE and DRAW_WRITE are both sub-intervals
 * of DRAW_ANIMATION_STACK, entered many times per DRAW_ANIMATION_STACK
 * call -- once per RLE run rather than once per call). Each section's
 * numbers are self-contained -- there is no double-counting *within* a
 * section's own count/total -- but a reader comparing sections should
 * remember the containment relationship rather than expecting them to sum
 * to an unrelated "everything" total.
 *
 * NOTE: GQ_PERF_ENTER/EXIT are matched pairs around straight-line code.
 * Functions with an early-return failure path between ENTER and EXIT (e.g.
 * draw_animation_stack()'s cart-read-failure returns) will simply not
 * record that call -- the section's count/total under-reports failure-path
 * calls. This is an accepted limitation for a profiling aid, not a
 * correctness issue: failure paths are rare (cart read failure) and are
 * not the hot path this instrumentation targets.
 *
 * NOTE (implausible-sample clamp): gq_perf_record() drops, rather than
 * clamps the value of, any single duration_us sample exceeding
 * GQ_PERF_MAX_PLAUSIBLE_US (defined just above gq_perf_time_t below) --
 * count/total_us/min_us/max_us are all left untouched for that call, same
 * as the early-return-failure-path case just above. This guards against a
 * garbage HAL_perf_now() delta (root-caused to a firmware timing-source
 * race, fixed separately) silently poisoning total_us/max_us with a
 * ~2^32 us outlier; the resulting under-report of that one call is the same
 * accepted limitation as the failure-path case, not a correctness issue.
 *
 * -------------------------------------------------------------------------
 * Struct layout (GQ_PERF_INSTRUMENT defined):
 * -------------------------------------------------------------------------
 *   gq_perf_stats_t (8 B header + N * 16 B sections; N=7 today -> 120 B):
 *     uint32_t magic;    -- GQ_PERF_MAGIC; sanity-check when read over SBW
 *                           at a known/discoverable symbol address (via the
 *                           .map file -- gq_perf_stats is a plain global,
 *                           deliberately not static, so it is visible
 *                           there).
 *     uint16_t version;  -- GQ_PERF_VERSION; bump whenever this layout
 *                           changes so an out-of-sync SBW reader script can
 *                           detect the mismatch instead of misparsing.
 *     uint16_t reserved; -- padding today; available for a future flags
 *                           field without changing the struct size.
 *     gq_perf_section_t sections[GQ_PERF_SEC_COUNT];
 *       each: uint32_t count, total_us, min_us, max_us (16 B).
 *
 * Adding a new section costs 16 B. The ~150 B RAM target in the design
 * discussion allowed roughly 4 more sections beyond the original 5; this
 * pass (issue #261's DRAW_DECODE/DRAW_WRITE) uses 2 of those, leaving
 * headroom for about 2 more before that budget is exhausted (120 B used of
 * ~150 B; each further section costs another 16 B).
 *
 * Byte-offset math for a raw-memory SBW reader (no source access to this
 * header): sections[i] starts at offset 8 + i*16 within gq_perf_stats
 * (8 B header, then 16 B per section in GQ_PERF_SECTION_LIST's declared
 * order -- see the section index list above for what each i is). With
 * N=7: DRAW_DECODE (index 5) is at byte offset 8 + 5*16 = 88; DRAW_WRITE
 * (index 6) is at byte offset 8 + 6*16 = 104. Each section's own layout is
 * count (offset +0), total_us (+4), min_us (+8), max_us (+12), all
 * uint32_t, all four bytes wide -- e.g. DRAW_DECODE's total_us is at
 * absolute offset 88 + 4 = 92 within gq_perf_stats.
 *
 * -------------------------------------------------------------------------
 * Timer width decision: gq_perf_time_t is uint32_t, holding microseconds.
 * -------------------------------------------------------------------------
 * Section durations range from ~50 us (a single small op) to ~50 ms (a
 * full-screen redraw with a masked sprite; see the per-frame cost table in
 * docs/perf-investigation.md). A 16-bit microsecond counter only covers
 * 65.535 ms before wrapping -- too tight a margin against the ~50 ms upper
 * end of a single measured interval (the *comparison* logic in
 * gq_perf_record() implicitly assumes a single delta never exceeds the
 * counter's wrap period; a 16-bit-us counter leaves under 15 ms of margin,
 * which a slow flush or a big masked-sprite frame could plausibly eat).
 * uint32_t microseconds wraps every ~71.6 minutes, giving enormous margin
 * for a single section, and is cheap to accumulate/compare on both a 64-bit
 * host and a 16-bit-native MSP430 (32-bit ops on MSP430 are 2-3 instructions
 * via the CPU's word ops, not emulated software math like 64-bit would be).
 * gq_perf_record()'s unsigned-subtraction delta math
 * (HAL_perf_now() - entry_time) is correct across exactly one wrap of the
 * *counter itself*, which is what matters here, not one wrap of the
 * accumulated `total_us` field (that field can itself wrap over a very long
 * run; see gq_perf_record()'s comment).
 *
 * -------------------------------------------------------------------------
 * HAL_perf_now() -- per-platform timing source.
 * -------------------------------------------------------------------------
 * Only the emulator side is implemented as of this header (see HAL.c,
 * clock_gettime(CLOCK_MONOTONIC) scaled to microseconds). The firmware
 * (ccs_workspace/qc2024/) implementation is a SEPARATE, NOT-YET-DONE task
 * in that repo -- do not assume it exists. Requirements for whoever
 * implements it there:
 *
 *   - Free-running, monotonically increasing, wrapping 32-bit counter in
 *     microseconds (matches gq_perf_time_t = uint32_t). Wraps every ~71.6
 *     minutes (2^32 us); fine, per the timer-width note above.
 *   - Must be safely callable from BOTH main-loop context and ISR context.
 *     A future extension may want to time led_tick(), which the RTC ISR
 *     calls directly (qc2024's main.c:627) -- so HAL_perf_now() itself must
 *     not require interrupts to be enabled, must not block, and must not
 *     race a concurrent read from interrupt level. A single free-running
 *     hardware counter register read is safe (MSP430 16-bit register reads
 *     are atomic). If the implementation software-extends a 16-bit hardware
 *     timer to 32 bits via an overflow ISR incrementing a
 *     `volatile uint16_t` high-word counter, HAL_perf_now() needs the
 *     standard "read high, read low, read high again, retry if the high
 *     word changed" pattern to avoid a torn read when preempted mid-read by
 *     its own overflow ISR.
 *   - Suggested timer: the RTC (100 Hz heartbeat, qc2024's main.c) and
 *     TA0/TA2 (TLC5948A grayscale clock, qc2024's tlc5948a.c/.h -- see
 *     TLC_GSCLK_TIMER_* macros and the TA2CTL setup in tlc5948a.c) are
 *     already committed as of this writing. TA1, TA3, and TB0 appear
 *     unused (grep qc2024's C sources and headers for "TA1"/"TA3"/"TB0" to reconfirm
 *     before implementing -- this comment is a starting point, not a
 *     verified-current fact, and firmware code changes independently of
 *     this submodule). Recommended approach: run one of the free 16-bit
 *     Timer_A/B blocks continuously in up mode from SMCLK (8 MHz) or ACLK,
 *     with its own overflow ISR incrementing the high-word counter above;
 *     HAL_perf_now() combines (high_word << 16 | TAxR) using the
 *     torn-read-safe pattern, then scales to microseconds by the timer's
 *     known tick period -- prefer a multiply (or a shift, if the tick
 *     period is chosen as a power-of-two divisor of 1 us) over a divide,
 *     since GQ_PERF_INSTRUMENT builds are a development/measurement
 *     flavor where extra cycles are acceptable but an actual hardware
 *     divide instruction cost is still worth avoiding by construction.
 *     Confirm the MSP430FR2476 family user's guide for the exact
 *     Timer_A/B inventory and capture/compare resource counts before
 *     committing to a specific block.
 *   - Resolution: microsecond resolution comfortably covers the documented
 *     section range (~50 us to ~50 ms). Do not narrow gq_perf_time_t to
 *     16 bits for the firmware side -- HAL_perf_now()'s return type and
 *     gq_perf_record()'s parameter type must stay in lockstep with this
 *     header's uint32_t choice, or the accumulation math silently
 *     truncates.
 *
 * -------------------------------------------------------------------------
 * Flush-section hook placement.
 * -------------------------------------------------------------------------
 * GQ_PERF_ENTER(OLED_FLUSH) / GQ_PERF_EXIT(OLED_FLUSH) are placed in shared
 * code (gamequeer.c, draw_oled_stack()) directly around the
 * Graphics_flushBuffer() call -- NOT inside qc2024's sh1107.c oled_flush().
 * Graphics_flushBuffer() (grlib/grlib/context.c) is already the single
 * dispatch point shared by both platforms: on the badge it calls through
 * the Graphics_Display's pfnFlush pointer to oled_flush() (see qc2024's
 * sh1107.c, the g_sh1107OledDisplay pfnFlush entry), and on the emulator it
 * dispatches to gfx_flush() via grlib_gfx_driver.c. That means no new HAL
 * notify functions are needed for this section -- the existing indirection
 * already gives a shared, platform-agnostic measurement point that brackets
 * the real flush cost on either target.
 *
 * If finer-grained timing *within* oled_flush() is wanted later (e.g.
 * separating the 16 page-address-set command sequences from the 2048 data
 * bytes -- relevant to Issue #16's proposed DMA/ISR-streaming flush), that
 * finer split is not visible from shared code and would need two new
 * HAL-callable notify functions (e.g. HAL_perf_flush_begin() /
 * HAL_perf_flush_end(), or more granular ones) called from inside
 * sh1107.c. Not implemented here; documented as a follow-up option.
 *
 * -------------------------------------------------------------------------
 * OPTIONAL extension points (documented only, NOT implemented here):
 * -------------------------------------------------------------------------
 *   - D0/D1 GPIO toggle hooks: add GQ_PERF_GPIO_ENTER(SEC)/_EXIT(SEC)
 *     variants (or extend the existing macros under a second build flag)
 *     that toggle a spare GPIO pin firmware-side, so section boundaries are
 *     visible on a scope/logic analyzer independent of reading the RAM
 *     struct over SBW. Needs a firmware-side pin assignment (D0/D1 or
 *     whichever header pins are free on the badge) and a HAL_perf_gpio_*()
 *     primitive; out of scope for the emulator-only pass this header is
 *     part of.
 *   - Exposing stats as GQI_* builtins: register new read-only builtin int
 *     variables (alongside GQI_GAME_ID etc. in gamequeer.h) that surface
 *     e.g. GQI_PERF_DRAW_OLED_STACK_COUNT / _AVG_US, so a game (an on-badge
 *     profiler cart) could display live stats without an SBW connection.
 *     Would need gqc-side symbol table changes (linker.py's
 *     create_reserved_variables()) to keep the compiler in lockstep --
 *     flagged here as compiler-impacting, not attempted in this pass.
 * ---------------------------------------------------------------------- */

/* ---- Section list (X-macro): add new sections here only. ----
 * X(ENUM_SUFFIX, "display name") -- ENUM_SUFFIX becomes GQ_PERF_SEC_<name>
 * and the token pasted into GQ_PERF_ENTER/EXIT's local variable name, so it
 * must be a valid identifier fragment (no spaces/quotes). "display name" is
 * the string used by tools reading the struct (e.g. the emulator's
 * --perf-dump text output). */
#define GQ_PERF_SECTION_LIST(X)                     \
    X(DRAW_OLED_STACK, "draw_oled_stack")           \
    X(DRAW_ANIMATION_STACK, "draw_animation_stack") \
    X(HANDLE_EVENTS, "handle_events")               \
    X(SYSTEM_TICK, "system_tick")                   \
    X(OLED_FLUSH, "oled_flush")                     \
    X(DRAW_DECODE, "draw_decode")                   \
    X(DRAW_WRITE, "draw_write")

typedef enum {
#define GQ_PERF_ENUM_ENTRY(NAME, STR) GQ_PERF_SEC_##NAME,
    GQ_PERF_SECTION_LIST(GQ_PERF_ENUM_ENTRY)
#undef GQ_PERF_ENUM_ENTRY
    GQ_PERF_SEC_COUNT
} gq_perf_section_id_t;

#ifdef GQ_PERF_INSTRUMENT

/* ASCII "QPFR" -- distinctive 4 bytes to scan for / sanity-check when the
 * struct is located and read over SBW by address. */
#define GQ_PERF_MAGIC   0x51504652u
#define GQ_PERF_VERSION 1u

/* Microseconds; see the timer-width design note above for why uint32_t. */
typedef uint32_t gq_perf_time_t;

/* Plausibility ceiling for a single gq_perf_record() sample, in
 * microseconds. Defense-in-depth against a garbage HAL_perf_now() delta
 * (e.g. a firmware timing-source race producing a near-2^32 us reading,
 * ~4.2e9 us) silently poisoning a section's total_us/max_us forever -- see
 * gq_perf_record()'s comment for how samples above this ceiling are
 * handled. 1 second is ~20x the largest plausible *real* interval (a
 * HANDLE_EVENTS section containing a full DRAW_OLED_STACK pass with a
 * masked-sprite redraw, per the ~50 ms upper end in the timer-width note
 * above) and ~4000x below a garbage ~2^32 us reading, leaving a wide,
 * unambiguous margin between the two. */
#define GQ_PERF_MAX_PLAUSIBLE_US 1000000u

typedef struct {
    uint32_t count;
    uint32_t total_us;
    uint32_t min_us;
    uint32_t max_us;
} gq_perf_section_t;

typedef struct {
    uint32_t magic;
    uint16_t version;
    uint16_t reserved;
    gq_perf_section_t sections[GQ_PERF_SEC_COUNT];
} gq_perf_stats_t;

/* Plain global (not static): must be a stable, .map-discoverable symbol so
 * it can be located and read by address over SBW. */
extern gq_perf_stats_t gq_perf_stats;

/* Display-name table, indexed by gq_perf_section_id_t; used by the
 * emulator's --perf-dump output. */
extern const char *const gq_perf_section_names[GQ_PERF_SEC_COUNT];

/* Per-platform timing source. Implemented for the emulator in HAL.c; the
 * firmware implementation is a separate task -- see the design note above. */
gq_perf_time_t HAL_perf_now(void);

/* Records one completed section measurement. Note: total_us accumulates
 * across the whole run and is itself a uint32_t, so it can in principle
 * wrap on an extremely long-running instrumented session (e.g. billions of
 * microseconds -- over an hour of continuous max-rate section entries);
 * this is a development/measurement build, not a production counter, so
 * that is treated as an accepted limitation rather than guarded against.
 *
 * duration_us above GQ_PERF_MAX_PLAUSIBLE_US is dropped, not clamped: the
 * sample is discarded and count/total_us/min_us/max_us are all left
 * unchanged, rather than folding an implausible value into the
 * accumulators at the ceiling. See the implausible-sample-clamp NOTE above
 * for the rationale and threshold. */
void gq_perf_record(gq_perf_section_id_t sec, gq_perf_time_t duration_us);

/* GQ_PERF_ENTER(SEC)/GQ_PERF_EXIT(SEC) must appear as a matched pair in the
 * same lexical scope (SEC's token-pasted local variable must stay in
 * scope), following the style of this header's un-parenthesized statement
 * macros (see GQ_EVENT_SET/_CLR in gamequeer.h) -- callers add the
 * trailing semicolon. */
#define GQ_PERF_ENTER(SEC) gq_perf_time_t _gq_perf_t0_##SEC = HAL_perf_now()
#define GQ_PERF_EXIT(SEC)  gq_perf_record(GQ_PERF_SEC_##SEC, (gq_perf_time_t) (HAL_perf_now() - _gq_perf_t0_##SEC))

/* -------------------------------------------------------------------------
 * GQ_PERF_INSTRUMENT_RUNS -- opt-in, SEPARATE from GQ_PERF_INSTRUMENT.
 * -------------------------------------------------------------------------
 * Gates ONLY the per-RUN DRAW_DECODE (5) / DRAW_WRITE (6) ENTER/EXIT pairs
 * in oled.c's gq_draw_image()/gq_draw_image_with_mask() run loops, via the
 * GQ_PERF_ENTER_RUNS/GQ_PERF_EXIT_RUNS macros below. It exists to answer a
 * measurement-methodology question that GQ_PERF_INSTRUMENT alone can't: how
 * much overhead do those two HAL_perf_now() calls per RLE run add, and do
 * they contaminate the ENCLOSING per-draw sections (0 DRAW_OLED_STACK, 1
 * DRAW_ANIMATION_STACK)? On real hardware the run loop fires ~10-100x per
 * tick and DRAW_DECODE/DRAW_WRITE can fire hundreds of thousands to
 * millions of times over a measurement window (see the perf-investigation
 * hardware notes), so their entry/exit overhead -- while individually tiny
 * -- is large in aggregate and sits entirely inside sections 0/1's timed
 * interval.
 *
 * This flag does NOT change gq_perf_stats's layout: it is still 8 B header
 * + 7 * 16 B sections = 120 B either way (GQ_PERF_SECTION_LIST is
 * unconditional -- see above), so a raw-memory SBW reader's byte-offset
 * math is unaffected by whether this flag is set. When
 * GQ_PERF_INSTRUMENT_RUNS is NOT defined, sections 5/6 simply never get a
 * GQ_PERF_ENTER/EXIT call and stay all-zero (count/total_us/min_us/max_us
 * == 0) for the life of the run -- easily distinguished in a dump from "ran
 * but recorded nothing".
 *
 * Meaningless (and silently a no-op, not an error) unless
 * GQ_PERF_INSTRUMENT is also defined: GQ_PERF_ENTER_RUNS/_EXIT_RUNS are
 * defined below, inside the `#ifdef GQ_PERF_INSTRUMENT` block, precisely so
 * that "RUNS but not INSTRUMENT" degrades to the same zero-cost no-op as
 * plain "neither defined", rather than needing its own separate guard at
 * every call site in oled.c.
 *
 * Two independent measurement configurations this enables, matching the
 * build system's two flags:
 *   GQ_PERF_INSTRUMENT only          -- sections 0-4 active, 5/6 compiled
 *                                       out of the run loop entirely (no
 *                                       HAL_perf_now() calls at all in the
 *                                       hot loop). CLEAN draw_oled_stack /
 *                                       draw_animation_stack timings, free
 *                                       of per-run instrumentation
 *                                       overhead.
 *   GQ_PERF_INSTRUMENT +
 *   GQ_PERF_INSTRUMENT_RUNS          -- all 7 sections active (today's
 *                                       behavior prior to this flag's
 *                                       introduction). Comparing this
 *                                       configuration's sections 0/1
 *                                       against the RUNS-off configuration's
 *                                       sections 0/1, on the same fixture,
 *                                       quantifies the per-run
 *                                       instrumentation's contamination of
 *                                       the enclosing per-draw timings.
 * ---------------------------------------------------------------------- */

#ifdef GQ_PERF_INSTRUMENT_RUNS
#define GQ_PERF_ENTER_RUNS(SEC) GQ_PERF_ENTER(SEC)
#define GQ_PERF_EXIT_RUNS(SEC)  GQ_PERF_EXIT(SEC)
#else /* !GQ_PERF_INSTRUMENT_RUNS */
#define GQ_PERF_ENTER_RUNS(SEC) ((void) 0)
#define GQ_PERF_EXIT_RUNS(SEC)  ((void) 0)
#endif /* GQ_PERF_INSTRUMENT_RUNS */

#else /* !GQ_PERF_INSTRUMENT */

/* Zero-cost: no declarations, no symbols, no stack slots. */
#define GQ_PERF_ENTER(SEC)      ((void) 0)
#define GQ_PERF_EXIT(SEC)       ((void) 0)

/* Same zero-cost no-op regardless of GQ_PERF_INSTRUMENT_RUNS: that flag is
 * only meaningful nested inside GQ_PERF_INSTRUMENT (see above). */
#define GQ_PERF_ENTER_RUNS(SEC) ((void) 0)
#define GQ_PERF_EXIT_RUNS(SEC)  ((void) 0)

#endif /* GQ_PERF_INSTRUMENT */

#endif /* GQ_PERF_H */
