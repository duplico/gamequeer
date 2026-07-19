#include <stdint.h>
#include <string.h>

#include "HAL.h"
#include "gamequeer.h"

rgbcolor16_t gq_leds[5] = {
    0,
};

#define LEDS_SUBTICKS 4

// Number of fractional bits used to represent the per-tick interpolation
// deltas computed in led_setup_frame() and consumed in led_tick(). This
// lets led_tick() replace a 32-bit divide (done every smooth-cue subtick,
// in RTC ISR context) with a precomputed reciprocal and a multiply+shift.
//
// Deliberately 14 (not a wider value like the 17 originally used): every
// step of the fade-delta pipeline -- the shift in led_calc_delta(), the
// divide in led_calc_delta(), and the multiply+shift in led_tick() -- is
// required to fit in plain 32-bit arithmetic, with no int64_t anywhere.
// The first cut of this optimization (gamequeer#241, PR #284 initial
// version) used 17 fractional bits and int64_t intermediates throughout;
// that pulled in ~1.5 KB of 64-bit RTS helper objects on the MSP430FR2476
// link (__mspabi_divlli/divull/srall/sllll/srlll/mpysll, etc.) that the
// firmware doesn't otherwise need. 32-bit shifts/multiplies/divides, by
// contrast, are either inlined by the compiler or satisfied by helper
// objects (div32s/div32u/mult32-class) that were already linked in before
// this optimization, so this version costs (see git history for the
// measured .map delta) far less FRAM.
//
// Bound derivation (see led_calc_delta()'s comment for the full
// no-overflow argument, and led_tick()'s comment for the product bound):
// every gq_ledcue_frame_t.leds[] channel value is an 8-bit source value
// left-shifted by 8 (see led_setup_frame()), so diff = next - curr is
// always a multiple of 256 in [-65280, 65280]. |diff << 14| <=
// 65280 * 16384 = 1,069,547,520, which is ~2x under INT32_MAX
// (2,147,483,647) for every duration >= 1 -- so led_calc_delta() never
// saturates (the int64_t version's saturating clamp has been removed as
// dead code), and the same bound carries through the per-tick multiply
// (see led_tick()).
//
// Precision: reducing the fraction from 17 to 14 bits widens the per-tick
// truncation error (relative to the true, real-valued linear interpolation
// offset_true = diff * ticks_elapsed / duration). Writing offset_new for
// what led_calc_delta()+led_delta_shift() actually compute:
//   offset_true - offset_new = phi + eps2,   0 <= phi < ticks_elapsed/2^14,
//                                             0 <= eps2 < 1
// (phi is the delta-truncation error in led_calc_delta() carried through
// the multiply; eps2 is led_delta_shift()'s own truncation). At exactly
// ticks_elapsed == duration (the frame-boundary case), offset_true == diff
// exactly (an integer), so the error there is itself a nonnegative
// *integer* strictly less than duration/2^14 + 1 <= 65535/16384 + 1 <
// 4.99994 -- i.e. at most 4. Away from the boundary, offset_true generally
// isn't an integer, so this doesn't reduce to as clean a bound against the
// old (pre-#284) single-divide-per-tick reference formula (which has its
// own, single-truncation, < 1 error against the same true value) -- an
// exhaustive sweep of the full reachable domain (all diffs, all
// durations 5..65535, every multiple-of-LEDS_SUBTICKS ticks_elapsed) finds
// the two formulas never differ by more than LED_FADE_TEST_TOLERANCE (4);
// see test_led_fade_delta.c's header comment for the full derivation and
// verification. That's a visually negligible fraction of the 16-bit LED
// channel range (4 / 65280, well under 0.01%); monotonicity and the exact
// frame-boundary landing (led_tick()'s unconditional snap-to-`next` on
// frame completion, untouched by this PR) are unaffected.
#define LED_DELTA_FRAC_BITS 14

// volatile: layered on top of the HAL_critical_enter()/HAL_critical_exit()
// masked windows below (matching this file's own gq_game_unload_flag in
// gamequeer.c, and the badge firmware's analogous tlc_send_type/
// rtc_ticks_pending -- see docs/led-tlc-concurrency.md's I5 in the qc2024
// repo) so the leds_animating = 0 -> ... -> leds_animating = 1 ordering
// those windows rely on (I11) doesn't depend on HAL_critical_enter()/
// HAL_critical_exit() staying opaque to the compiler (e.g. under a future
// whole-program-optimized build that inlines them across translation
// units).
volatile uint8_t leds_animating = 0;
gq_ledcue_frame_t leds_cue_fg_frames[GQ_CUE_MAX_FRAMES];
gq_ledcue_frame_t leds_cue_bg_frames[GQ_CUE_MAX_FRAMES];
gq_ledcue_frame_t leds_cue_frame_curr;
rgbcolor16_t leds_cue_color_curr[5];
rgbcolor16_t leds_cue_color_next[5];
// Precomputed per-tick interpolation deltas for the current frame's smooth
// transition, in LED_DELTA_FRAC_BITS fixed point. Computed once per frame in
// led_setup_frame(); consumed (add-and-shift only, no divide) every smooth-cue
// subtick in led_tick(). rgbdelta_t is deliberately not persisted anywhere
// (not part of the on-cart cue format), so it costs RAM only, not FRAM/flash.
rgbdelta_t leds_cue_color_delta[5];
gq_ledcue_t leds_cue;
uint16_t leds_cue_frame_index         = 0;
uint16_t leds_cue_frame_ticks_elapsed = 0;

gq_ledcue_t leds_cue_bg;
uint8_t leds_cue_bg_saved                = 0;
uint16_t leds_cue_bg_frame_index         = 0;
uint16_t leds_cue_bg_frame_ticks_elapsed = 0;

void led_setup_frame();

// Precompute the fixed-point per-tick interpolation delta for one channel of
// one LED, given the signed distance to travel (diff = next - curr) and the
// frame duration (in ticks) over which to travel it.
//
// This is the one 32-bit divide per channel that used to happen every smooth
// subtick in led_tick() (in RTC ISR context); it now happens once per frame,
// in led_setup_frame(), instead.
//
// duration == 0 is guarded against (returns 0): gqc's cue parser (cues.py)
// rounds every frame duration down to a multiple of LEDS_SUBTICKS, which
// means an authored duration of 1-3 ticks is rounded down to 0 (with a
// compiler warning) rather than rejected outright. So duration == 0 is not
// just a malformed-cart concern -- a legitimately-compiled cart can produce
// it -- and nothing on this side of the cart format previously guarded
// against the resulting divide-by-zero.
//
// diff is always a multiple of 256 in [-65280, 65280] (see
// LED_DELTA_FRAC_BITS's comment for why), so |diff << LED_DELTA_FRAC_BITS|
// <= 1,069,547,520 -- comfortably within int32_t (INT32_MAX is
// 2,147,483,647, ~2x headroom) for every duration >= 1. That means, unlike
// an int64_t-intermediate version of this function, the shift+divide below
// can never overflow, so no saturating clamp is needed.
//
// The shift is done on the *magnitude* of diff, not the signed value
// itself, with the sign reapplied afterward: C leaves left-shifting a
// negative signed integer undefined behavior (unlike the right-shift case
// in led_delta_shift() below, which is merely implementation-defined), so
// shifting a possibly-negative diff directly would be UB even though every
// real target computes the "obviously intended" answer for it.
static int32_t led_calc_delta(int32_t diff, uint16_t duration) {
    if (duration == 0) {
        return 0;
    }

    uint32_t magnitude = (diff < 0) ? (uint32_t) (-diff) : (uint32_t) diff;
    uint32_t scaled    = magnitude << LED_DELTA_FRAC_BITS;
    int32_t delta      = (int32_t) (scaled / (uint32_t) duration);

    return (diff < 0) ? -delta : delta;
}

// Right-shift a (possibly negative) delta*ticks_elapsed product by
// LED_DELTA_FRAC_BITS to recover the interpolated offset, without relying on
// right-shift-of-a-negative-value, which C leaves implementation-defined
// (and which, on the common arithmetic-shift implementation, rounds toward
// -infinity instead of toward zero like the `/` it replaces). Shifting the
// magnitude and reapplying the sign keeps this a truncate-toward-zero
// operation on every compiler, matching the old divide-based formula's
// rounding exactly instead of merely approximately.
//
// product = delta * ticks_elapsed is plain int32_t (see led_tick()'s call
// site comment for the bound showing this can't overflow): |delta| <=
// |diff << LED_DELTA_FRAC_BITS| / duration (led_calc_delta() truncates
// toward zero, so this is a strict upper bound), and ticks_elapsed <=
// duration whenever this function is actually reached (led_tick()'s
// frame-done branch fires once ticks_elapsed >= duration, before any
// interpolation step), so |product| <= |diff << LED_DELTA_FRAC_BITS| <=
// 1,069,547,520 -- the same ~2x-under-INT32_MAX bound as led_calc_delta().
static inline int32_t led_delta_shift(int32_t product) {
    uint32_t magnitude = (product < 0) ? (uint32_t) (-product) : (uint32_t) product;
    int32_t shifted    = (int32_t) (magnitude >> LED_DELTA_FRAC_BITS);
    return (product < 0) ? -shifted : shifted;
}

// Publish gq_leds for whatever cue/frame state is currently loaded
// (leds_cue_frame_curr / leds_cue_color_curr / leds_cue_color_delta, at
// leds_cue_frame_ticks_elapsed). Doesn't touch leds_cue_frame_ticks_elapsed
// and doesn't flush (callers decide whether/when to call HAL_update_leds()).
//
// This is the one place that turns "which subtick of which frame are we on"
// into a color, shared between led_tick()'s per-subtick advance and
// led_anim_done()'s one-shot handback publish below -- so the two can't
// drift apart the way they did before gamequeer#347 (the handback path used
// to publish leds_cue_color_next, the *next* frame's colors, instead of
// rendering the resumed frame's actual current state).
//
// led_tick()'s own per-subtick call site only ever reaches this with
// leds_cue_frame_ticks_elapsed < duration (it's guarded by the frame-done
// branch above it). led_anim_done()'s handback call site can't rely on
// that: led_play_cue() can capture leds_cue_frame_ticks_elapsed mid-tick,
// after led_tick() has already incremented it to exactly the saved frame's
// duration but *before* led_tick()'s own next call would process that as
// "frame done" and advance -- so the resumed elapsed can legitimately equal
// (never exceed) duration. Handle that case explicitly rather than
// re-displaying (or interpolating within) a frame that's actually already
// over.
static void led_render_frame() {
    if (leds_cue_frame_ticks_elapsed >= leds_cue_frame_curr.duration) {
        // The frame is already done as of the saved elapsed: show the
        // completed transition's destination, exactly as led_tick()'s own
        // frame-done branch would (leds_cue_color_next was computed for
        // this outcome by whichever led_setup_frame() call loaded this
        // frame). The real index advance/loop-wrap still happens on the
        // *next* ordinary led_tick() call, once leds_cue_frame_ticks_elapsed
        // (credited below) reaches duration again -- this only fixes what
        // gets displayed in the meantime.
        for (uint8_t i = 0; i < 5; i++) {
            gq_leds[i] = leds_cue_color_next[i];
        }
        return;
    }

    if (leds_cue_frame_ticks_elapsed == 0 || !leds_cue_frame_curr.transition_smooth) {
        // First subtick of the frame, or a hold (non-smooth) transition:
        // display the frame's starting colors outright.
        for (uint8_t i = 0; i < 5; i++) {
            gq_leds[i].r = leds_cue_color_curr[i].r;
            gq_leds[i].g = leds_cue_color_curr[i].g;
            gq_leds[i].b = leds_cue_color_curr[i].b;
        }
    } else {
        // Mid-frame smooth transition: interpolate at the current elapsed
        // ticks, using the per-tick deltas precomputed in led_setup_frame().
        // See led_delta_shift()'s comment for why this can't overflow.
        for (uint8_t i = 0; i < 5; i++) {
            gq_leds[i].r = leds_cue_color_curr[i].r +
                led_delta_shift(leds_cue_color_delta[i].r * (int32_t) leds_cue_frame_ticks_elapsed);
            gq_leds[i].g = leds_cue_color_curr[i].g +
                led_delta_shift(leds_cue_color_delta[i].g * (int32_t) leds_cue_frame_ticks_elapsed);
            gq_leds[i].b = leds_cue_color_curr[i].b +
                led_delta_shift(leds_cue_color_delta[i].b * (int32_t) leds_cue_frame_ticks_elapsed);
        }
    }
}

// Shared bookkeeping for led_stop() and led_anim_done()'s non-bg-cue stop
// branch: clears animation/color state but doesn't flush -- callers decide
// which HAL flush variant is safe for their context (see led_stop() vs.
// led_anim_done() below).
//
// Tiny masked window (I9): from led_anim_done() this is already inside
// RTC_ISR, so the HAL_critical_enter() token here just captures
// "already disabled" and HAL_critical_exit() correctly restores that (see
// HAL.h); from led_stop() (MAIN, GIE=1) it closes the same ordering gap
// led_play_cue() does -- leds_animating = 0 must land before
// leds_cue_bg_saved/gq_leds are cleared, or a tick landing between those
// stores could still observe leds_animating == 1 with only some of this
// state reset.
static void led_stop_state() {
    uint16_t crit_state = HAL_critical_enter();
    // Stop the animation flag.
    leds_animating = 0;
    // Unsave any background cue.
    leds_cue_bg_saved = 0;

    // Clear the current LED colors.
    for (uint8_t i = 0; i < 5; i++) {
        gq_leds[i] = (rgbcolor16_t) {.r = 0, .g = 0, .b = 0};
    }
    HAL_critical_exit(crit_state);
}

void led_stop() {
    led_stop_state();
    // Flush the LEDs. This flush's only callers (gamequeer.c's load_stage()
    // and unload_game()) run from ordinary main-loop context, never from
    // the RTC ISR, so it's safe -- and needs to actually take effect rather
    // than possibly get dropped -- to block until any in-flight transfer
    // completes.
    HAL_update_leds();
}

// Only ever called from led_tick(), i.e. from the RTC ISR: every flush in
// this function must therefore use HAL_update_leds_nonblocking(), not
// HAL_update_leds() -- a blocking wait here for an in-flight transfer could
// deadlock, since the transfer's own completion interrupt can't run until
// the RTC ISR returns (see HAL_update_leds_nonblocking()'s declaration).
void led_anim_done() {
    // If we just completed a non-background cue, and we have a background cue saved, restore it.
    if (leds_cue_bg_saved && !leds_cue.bgcue) {
        leds_cue             = leds_cue_bg;
        leds_cue_frame_index = leds_cue_bg_frame_index;
        leds_cue_bg_saved    = 0;
        led_setup_frame(); // Zeroes leds_cue_frame_ticks_elapsed; restored below.
        // Resume the bg cue's saved *intra-frame* progress, not a fresh
        // frame start. led_setup_frame() above unconditionally zeroes
        // leds_cue_frame_ticks_elapsed, so the saved value has to be written
        // back afterward, not before: assigning it before the call (as this
        // used to) was a dead store, silently discarded by the call, which
        // made the bg cue restart the resumed frame from its beginning
        // instead of resuming mid-frame (gamequeer#347).
        leds_cue_frame_ticks_elapsed = leds_cue_bg_frame_ticks_elapsed;
        // Publish the resumed frame's actual colors right now, atomically
        // with the state swap above, instead of leaving it to the generic
        // "publish leds_cue_color_next" step in led_tick()'s caller (which
        // by this point would be the *bg* cue's freshly-loaded next-frame
        // colors -- not the fg cue's destination, and not the bg cue's
        // resumed color either). That mismatch was gamequeer#347's
        // wrong-palette glitch row. Rendering here makes the handback
        // gap-free: the fg cue's final frame row is followed directly by
        // the bg cue's correct, fully resumed (possibly mid-fade) color.
        led_render_frame();
        HAL_update_leds_nonblocking();
        // Credit this display the same way led_tick()'s own per-subtick
        // advance does (render, then bump leds_cue_frame_ticks_elapsed by
        // LEDS_SUBTICKS): this render just showed the resumed elapsed value,
        // so the *next* led_tick() call needs to move past it, not
        // re-render the same color again -- otherwise the resumed frame
        // would show one redundant repeated-color tick here, the exact same
        // class of uncounted-subtick fencepost gamequeer#350 fixed for the
        // ordinary frame-advance case.
        leds_cue_frame_ticks_elapsed += LEDS_SUBTICKS;
    } else {
        // Otherwise, just stop the animation. Inlined rather than calling
        // led_stop(): this function only ever runs from the RTC ISR (see
        // the function comment above), so it needs led_stop()'s bookkeeping
        // with a non-blocking flush, not led_stop()'s own blocking one.
        led_stop_state();
        HAL_update_leds_nonblocking();
    }
}

void led_setup_frame() {
    // If we're not currently animating, there's nothing to do.
    if (!leds_animating) {
        return;
    }

    if (leds_cue.bgcue) {
        // If this is a background cue, load the frame from the bgcue buffer.
        leds_cue_frame_curr = leds_cue_bg_frames[leds_cue_frame_index];
    } else {
        // If this is a foreground cue, load the frame from the fgcue buffer.
        leds_cue_frame_curr = leds_cue_fg_frames[leds_cue_frame_index];
    }

    // And then add it to the left-shifted 16-bit version:
    for (uint8_t i = 0; i < 5; i++) {
        leds_cue_color_curr[i].r = leds_cue_frame_curr.leds[i].r << 8;
        leds_cue_color_curr[i].g = leds_cue_frame_curr.leds[i].g << 8;
        leds_cue_color_curr[i].b = leds_cue_frame_curr.leds[i].b << 8;
    }

    // Load the next frame, if there is one, and put its colors into leds_cue_color_next.
    // Note that we don't store the entire frame, just the colors. We don't need the metadata.
    if (leds_cue_frame_index + 1 < leds_cue.frame_count || leds_cue.loop) {
        // We can load the next frame sequentially if the current frame isn't the last frame;
        // otherwise, we need to go back to the start if we're looping.
        gq_ledcue_frame_t leds_cue_frame_next;
        if (leds_cue.bgcue) {
            leds_cue_frame_next = leds_cue_bg_frames[(leds_cue_frame_index + 1) % leds_cue.frame_count];
        } else {
            leds_cue_frame_next = leds_cue_fg_frames[(leds_cue_frame_index + 1) % leds_cue.frame_count];
        }
        for (uint8_t i = 0; i < 5; i++) {
            leds_cue_color_next[i].r = leds_cue_frame_next.leds[i].r << 8;
            leds_cue_color_next[i].g = leds_cue_frame_next.leds[i].g << 8;
            leds_cue_color_next[i].b = leds_cue_frame_next.leds[i].b << 8;
        }
    } else {
        // If there is no next frame, then load a dummy all-black frame.
        for (uint8_t i = 0; i < 5; i++) {
            leds_cue_color_next[i] = (rgbcolor16_t) {.r = 0, .g = 0, .b = 0};
        }
    }

    // Set up the frame transition deltas: one 32-bit divide per channel here,
    // instead of one per channel on every smooth-cue subtick in led_tick().
    //
    // Only worth doing when led_tick() will actually read the result:
    //   - A non-smooth frame never reads leds_cue_color_delta at all (see
    //     led_tick()'s non-smooth branch).
    //   - A frame with duration <= LEDS_SUBTICKS never reaches a nonzero,
    //     not-yet-done ticks_elapsed: the first subtick (ticks_elapsed == 0)
    //     uses leds_cue_color_curr directly, and by the next subtick
    //     (ticks_elapsed == LEDS_SUBTICKS) the frame-done check
    //     (ticks_elapsed >= duration) already fires instead. So its delta,
    //     even if computed, would never be consumed.
    // Skipping both cases avoids an unnecessary per-channel divide in
    // led_setup_frame()'s ISR-reachable call path (it's called from
    // led_tick(), i.e. the RTC ISR, on every frame advance) for the common
    // non-smooth/short-frame case. The array is explicitly zeroed in the
    // skipped case, defensively, in case some future caller ever reads it
    // out of band; current callers don't.
    if (leds_cue_frame_curr.transition_smooth && leds_cue_frame_curr.duration > LEDS_SUBTICKS) {
        for (uint8_t i = 0; i < 5; i++) {
            leds_cue_color_delta[i].r = led_calc_delta(
                (int32_t) leds_cue_color_next[i].r - leds_cue_color_curr[i].r, leds_cue_frame_curr.duration);
            leds_cue_color_delta[i].g = led_calc_delta(
                (int32_t) leds_cue_color_next[i].g - leds_cue_color_curr[i].g, leds_cue_frame_curr.duration);
            leds_cue_color_delta[i].b = led_calc_delta(
                (int32_t) leds_cue_color_next[i].b - leds_cue_color_curr[i].b, leds_cue_frame_curr.duration);
        }
    } else {
        memset(leds_cue_color_delta, 0, sizeof(leds_cue_color_delta));
    }

    leds_cue_frame_ticks_elapsed = 0;
}

// Quiesce-stage-commit: led_play_cue() is the only main-loop mutator of the
// cue-active group (leds_cue, leds_cue_fg_frames, leds_cue_bg_frames),
// leds_animating, and the cue-bg-save group, but RTC_ISR's led_tick() /
// led_anim_done() / led_setup_frame() read *and write* the same state
// (gamequeer#366). The old version wrote leds_cue and leds_animating = 1
// before the (multi-hundred-microsecond, flash-reading) frame-array copies
// below had even started, so an RTC tick landing mid-copy could act on a
// torn leds_cue -- including re-reading a torn frame_count *after* the
// clamp below to size a gq_memcpy_to_ram, i.e. a possible RAM overflow past
// leds_cue_fg_frames/leds_cue_bg_frames.
//
// Fixed by making every context an exclusive owner of this state at every
// instant, gated by one flag (leds_animating), per
// docs/led-tlc-concurrency.md (qc2024 repo) I9/§7 rule 5:
//   1. Tiny masked window: snapshot the bg-save decision inputs (reading
//      the *old* live cue, which RTC_ISR could otherwise still be
//      advancing) and clear leds_animating -- RTC_ISR's consumer is now
//      off: led_tick()/led_anim_done()/led_setup_frame() are all gated by
//      `if (leds_animating)` (or, for led_setup_frame(), an early return),
//      so nothing else touches the cue-active or cue-bg-save groups from
//      here until step 3 turns leds_animating back on.
//   2. GIE on: do the flash reads (gq_memcpy_to_ram) and the frame-count
//      clamp into a *local* cue header (new_cue lives on this call's
//      stack, so it can't be torn by anything else, and its clamped
//      frame_count can't be re-read stale by a concurrent writer -- there
//      isn't one). Also apply the bg-save snapshot from step 1: safe now
//      that the consumer is quiesced. Deliberately not masked: these are
//      the multi-hundred-microsecond flash reads, and masking around them
//      would eat into main.c's 10 ms RTC single-pending-tick budget
//      (qc2024#68).
//   3. Tiny masked commit: publish the new cue header/frame index, turn
//      leds_animating back on, and call led_setup_frame() -- all in the
//      same window. led_setup_frame() only touches RAM already fully
//      populated by step 2 (no flash I/O), the same work RTC_ISR already
//      does unmasked-from-its-own-perspective every frame boundary via
//      led_tick(), so folding it into this window is no more expensive
//      than what already runs under GIE=0 today, and it closes the
//      remaining hazard of RTC_ISR racing this call's own
//      led_setup_frame() against its own led_tick()/led_anim_done() (the
//      interpolation-state tearing described in gamequeer#366).
void led_play_cue(t_gq_pointer cue_ptr, uint8_t background) {
    // --- 1. Quiesce (tiny masked window; O(instructions), no I/O) ---
    uint8_t save_bg                 = 0;
    gq_ledcue_t bg_cue_snapshot     = {0};
    uint16_t bg_frame_index         = 0;
    uint16_t bg_frame_ticks_elapsed = 0;

    uint16_t crit_state = HAL_critical_enter();
    if (leds_animating && !background && leds_cue.bgcue) {
        // Currently playing a background cue and this isn't itself a
        // background cue: save it for later before interrupting it.
        save_bg                = 1;
        bg_cue_snapshot        = leds_cue;
        bg_frame_index         = leds_cue_frame_index;
        bg_frame_ticks_elapsed = leds_cue_frame_ticks_elapsed;
    }
    leds_animating = 0;
    HAL_critical_exit(crit_state);

    // --- 2. Stage (GIE on; the flash reads live here) ---
    if (save_bg) {
        // RTC_ISR's consumer is off (leds_animating == 0), so the
        // cue-bg-save group is exclusively ours until step 3.
        leds_cue_bg                     = bg_cue_snapshot;
        leds_cue_bg_saved               = 1;
        leds_cue_bg_frame_index         = bg_frame_index;
        leds_cue_bg_frame_ticks_elapsed = bg_frame_ticks_elapsed;
    }

    // Load the new cue header into a local: nothing else can write this
    // copy, so its frame_count can't be re-read torn or stale by anyone,
    // clamped or not.
    gq_ledcue_t new_cue;
    gq_memcpy_to_ram((uint8_t *) &new_cue, cue_ptr, sizeof(gq_ledcue_t));

    uint16_t new_frame_count = new_cue.frame_count;
    if (new_frame_count > GQ_CUE_MAX_FRAMES) {
        // If the cue has too many frames, truncate it.
        new_frame_count = GQ_CUE_MAX_FRAMES;
    }
    new_cue.frame_count = new_frame_count;

    // If this is a background cue, we set it to loop.
    if (background) {
        new_cue.bgcue = 1;
        new_cue.loop  = 1;

        // Load the frames into RAM, sized from the local (already-clamped,
        // untorn) count above -- never from the shared leds_cue.
        gq_memcpy_to_ram((uint8_t *) leds_cue_bg_frames, new_cue.frames, new_frame_count * sizeof(gq_ledcue_frame_t));
    } else {
        gq_memcpy_to_ram((uint8_t *) leds_cue_fg_frames, new_cue.frames, new_frame_count * sizeof(gq_ledcue_frame_t));
    }

    // --- 3. Commit (tiny masked window; RAM-only work, no I/O) ---
    crit_state           = HAL_critical_enter();
    leds_cue             = new_cue;
    leds_cue_frame_index = 0;
    leds_animating       = 1;      // Before led_setup_frame(): it early-returns on !leds_animating.
    led_setup_frame();             // Consumes leds_cue/leds_cue_frame_index set just above.
    HAL_critical_exit(crit_state); // Only past this point can RTC_ISR observe any of this state.
}

// Runs from the RTC ISR in every build that defines GQ_SUPPRESS_LED_TICK
// (all builds as of this writing); when that's absent it instead runs from
// system_tick() in ordinary main-loop context (see gamequeer.c). Either
// way, its own flush and every flush reachable only through it (see
// led_anim_done()'s comment) must be non-blocking: a bail-if-busy flush is
// harmless main-loop-context too (it just drops a redraw), so this doesn't
// need to detect which context it's actually running in.
void led_tick() {
    uint8_t need_to_redraw = 0;
    static uint8_t subtick = LEDS_SUBTICKS - 1;

    // We'll run our LED animations at 25 Hz instead of the full system tick rate of 100 Hz.
    if (subtick) {
        subtick--;
        return;
    }
    subtick = LEDS_SUBTICKS - 1;

    if (leds_animating) {
        // If the current frame is done, move to the next frame.
        if (leds_cue_frame_ticks_elapsed >= leds_cue_frame_curr.duration) {
            // Current frame is done. Next frame!
            leds_cue_frame_index++;
            if (leds_cue_frame_index >= leds_cue.frame_count && !leds_cue.loop) {
                // End of a non-looping cue: led_anim_done() owns the entire
                // handoff -- publishing the correct colors (bg restore or
                // stop) and flushing them itself -- because it may swap in a
                // completely different cue/frame instead of simply advancing
                // within this one. Piling the generic "publish next, call
                // led_setup_frame()" steps below on top of that (as this used
                // to do unconditionally) was gamequeer#347's wrong-palette
                // glitch: they'd run against the state led_anim_done() had
                // just loaded for the *bg* cue, not the fg cue's own
                // completion.
                led_anim_done();
            } else {
                if (leds_cue_frame_index >= leds_cue.frame_count) {
                    // End of a looping cue: wrap back to the start.
                    leds_cue_frame_index = 0;
                }

                // Either way, display the destination color of the completed
                // transition -- already computed as "next" by the previous
                // call to led_setup_frame().
                for (uint8_t i = 0; i < 5; i++) {
                    gq_leds[i] = leds_cue_color_next[i];
                }
                need_to_redraw = 1;
                led_setup_frame(); // leds_cue_frame_ticks_elapsed is reset inside the function.
                // Credit the boundary subtick displayed just above as the new
                // frame's first counted subtick, instead of leaving it at
                // led_setup_frame()'s internal 0. Left at 0, the very next
                // active subtick would re-display these same colors -- a
                // redundant tick counted nowhere, i.e. gamequeer#350's
                // uncounted-boundary-subtick fencepost (every frame rendering
                // for duration+LEDS_SUBTICKS ticks instead of duration).
                // Contrast led_play_cue()'s own led_setup_frame() call, which
                // deliberately leaves this at 0: a freshly played cue hasn't
                // displayed anything yet, so its first frame still needs the
                // ticks_elapsed==0 branch below to fire on the next tick.
                leds_cue_frame_ticks_elapsed = LEDS_SUBTICKS;
            }
        } else {
            // The current frame is not done. Redraw only if something is
            // actually changing: the first subtick of the frame, or an
            // in-progress smooth transition (led_render_frame() handles both
            // -- see its comment). A mid-frame hold transition is already
            // displaying the right colors from a previous subtick, so there's
            // nothing to redraw.
            if (leds_cue_frame_ticks_elapsed == 0 || leds_cue_frame_curr.transition_smooth) {
                led_render_frame();
                need_to_redraw = 1;
            }
            leds_cue_frame_ticks_elapsed += LEDS_SUBTICKS;
        }
    }

    if (need_to_redraw) {
        HAL_update_leds_nonblocking();
    }
}
