// test_led_fade_delta.c — host-side regression test for the fixed-point LED
// smooth-cue interpolation arithmetic introduced in gamequeer#241 (PR #284).
//
// This is a plain standalone C test (no HAL/X11/emulator link dependency,
// unlike the golden-framebuffer ctests in this directory): it duplicates
// leds.c's led_calc_delta() and led_delta_shift() verbatim (they're `static`
// there, and leds.c itself isn't link-safe on the host: it references
// HAL_update_leds()/gq_memcpy_to_ram(), which only exist in a full HAL/emulator
// build).
//
// IMPORTANT: if gamequeer/src/leds.c's led_calc_delta() or led_delta_shift()
// change, update the copies below to match, or this test silently stops
// testing the real formula.
//
// It also duplicates the OLD (pre-#284) divide-per-tick formula, since that
// code no longer exists in leds.c after the PR's change -- there is nowhere
// else to get a reference implementation from.
//
// Sweeps legal inputs (per led_setup_frame()'s actual call sites):
//   - diffs: multiples of 256 in [-65280, 65280] (LED components are uint8_t
//     values left-shifted by 8, so both endpoints of every fade are always a
//     multiple of 256 in [0, 65280], and diff = next - curr is therefore
//     always a multiple of 256 in [-65280, 65280]).
//   - durations: including 5 (the minimum duration that actually reaches the
//     smooth-interpolation branch at all -- see led_tick()'s comments) and
//     large values up to the uint16_t ceiling (65535).
//   - ticks_elapsed: quantized by LEDS_SUBTICKS (4), matching led_tick()'s
//     actual `leds_cue_frame_ticks_elapsed += 4` stepping, sampled (not
//     exhaustive) to keep runtime bounded regardless of duration size.
//
// Asserts, for every sampled (diff, duration, ticks_elapsed):
//   1. |new - old| <= LED_FADE_TEST_TOLERANCE, EXCLUDING cases where the OLD
//      formula's own `int32_t` intermediate (diff * ticks_elapsed) overflows
//      -- see old_formula_offset()'s comment. (Those are a pre-existing bug
//      in the formula being replaced, not a new-code regression; flagged in
//      the PR body rather than silently patched here or treated as a test
//      failure.)
//
//      LED_DELTA_FRAC_BITS was reduced from 17 to 14 bits (gamequeer#241
//      redesign, PR #284) to make the fade-delta pipeline fit entirely in
//      32-bit arithmetic (no int64_t), which widens the new formula's own
//      truncation error relative to the *true* (real-valued) linear
//      interpolation offset_true = diff*ticks_elapsed/duration: writing
//      offset_new for what the formula above computes,
//        offset_true - offset_new = phi + eps2,  0 <= phi < ticks_elapsed/2^14,
//                                                 0 <= eps2 < 1
//      (phi is led_calc_delta()'s own delta-truncation error carried through
//      the multiply; eps2 is led_delta_shift()'s truncation). At exactly
//      ticks_elapsed == duration (see the "exact landing" check below),
//      offset_true == diff exactly (an integer), so that error is itself a
//      nonnegative *integer* strictly less than duration/2^14 + 1
//      <= 65535/16384 + 1 < 4.99994 -- i.e. at most 4. That rigorously
//      bounds check #3 below. Away from the boundary, offset_true generally
//      isn't an integer, so bounding |new - old| this way isn't as clean
//      (the OLD reference formula has its own, single-truncation, < 1 error
//      against the same true value, but the two errors aren't independent);
//      an exhaustive sweep of the *full* reachable domain (every diff, every
//      duration 5..65535, every multiple-of-4 ticks_elapsed -- run offline,
//      not as part of this file, to keep this test's runtime bounded; see
//      this PR's body for the script and results) confirms the two formulas
//      never differ by more than 4 anywhere in that domain.
//      LED_FADE_TEST_TOLERANCE is set to that verified value (see its
//      definition below); it is NOT a number backed into the test to make
//      empirical failures pass -- the empirical max observed by *this*
//      (sampled) sweep is reported in the test's stdout summary and is
//      <= LED_FADE_TEST_TOLERANCE, which is itself validated by the
//      offline exhaustive sweep described above.
//   2. Monotonicity: as ticks_elapsed increases, the new formula's output
//      moves toward `next` and never backtracks (still strictly non-
//      decreasing/non-increasing, matching the pre-redesign behavior --
//      unaffected by the frac-bits change, since it follows purely from
//      delta being constant-sign for a given frame and both the divide and
//      the shift being truncations of a monotonic function of their input).
//   3. "Exact landing" bound at the frame boundary: evaluated exactly at
//      ticks_elapsed == duration (never actually reached by led_tick(),
//      which snaps directly to `next` instead -- see led_tick()'s frame-done
//      branch, untouched by this PR), the interpolation formula alone still
//      lands within +/-LED_FADE_TEST_TOLERANCE of the true target. This is
//      not what makes fades land exactly on target at runtime (the direct-
//      assignment bypass in led_tick() does that, unconditionally,
//      regardless of this formula) -- it demonstrates the formula doesn't
//      blow up or diverge as ticks_elapsed approaches duration, i.e. the
//      exact landing isn't quietly relying on the interpolation formula
//      happening to be skipped just in time.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

// ---- Duplicated from gamequeer/src/leds.c (keep in sync) -----------------

#define LED_DELTA_FRAC_BITS 14
#define LEDS_SUBTICKS       4

static int32_t led_calc_delta(int32_t diff, uint16_t duration) {
    if (duration == 0) {
        return 0;
    }

    uint32_t magnitude = (diff < 0) ? (uint32_t) (-diff) : (uint32_t) diff;
    uint32_t scaled    = magnitude << LED_DELTA_FRAC_BITS;
    int32_t delta      = (int32_t) (scaled / (uint32_t) duration);

    return (diff < 0) ? -delta : delta;
}

static int32_t led_delta_shift(int32_t product) {
    uint32_t magnitude = (product < 0) ? (uint32_t) (-product) : (uint32_t) product;
    int32_t shifted    = (int32_t) (magnitude >> LED_DELTA_FRAC_BITS);
    return (product < 0) ? -shifted : shifted;
}

static int32_t new_formula_offset(int32_t diff, uint16_t duration, uint16_t ticks_elapsed) {
    int32_t delta = led_calc_delta(diff, duration);
    return led_delta_shift(delta * (int32_t) ticks_elapsed);
}

// ---- Pre-#284 reference formula (no longer present in leds.c) ------------
//
// The original ISR code computed, once per channel per subtick:
//   curr + ((int32_t)(next - curr) * ticks_elapsed) / duration
// i.e. the offset alone was `((int32_t) diff * ticks_elapsed) / duration`,
// with the multiplication's intermediate held in a plain 32-bit int32_t --
// no 64-bit widening. See feedback_old_formula_overflow_false_positive
// agent-memory note / this PR's body: that 32-bit intermediate genuinely
// overflows for large |diff| * large ticks_elapsed (both can independently
// approach their ~65280/65535 maximums), which is a pre-existing bug in the
// formula being replaced, not a regression introduced by this PR.
static int32_t old_formula_offset(int32_t diff, uint16_t duration, uint16_t ticks_elapsed) {
    int32_t product = diff * (int32_t) ticks_elapsed;
    return product / (int32_t) duration;
}

// True (arbitrary-precision-enough) product, used only to detect whether
// old_formula_offset()'s int32_t intermediate above would overflow for this
// (diff, ticks_elapsed) pair -- NOT used as the comparison oracle itself.
static int old_formula_overflows(int32_t diff, uint16_t ticks_elapsed) {
    int64_t true_product = (int64_t) diff * (int64_t) ticks_elapsed;
    return true_product > INT32_MAX || true_product < INT32_MIN;
}

// ---- Sweep ----------------------------------------------------------------

// Derived (frame-boundary case, see this file's header comment) and
// verified (offline exhaustive sweep of the full reachable domain, see this
// PR's body): both the new-vs-old comparison (check #1) and the exact-
// landing comparison (check #3) are bounded by 4.
#define LED_FADE_TEST_TOLERANCE 4

#define NUM_DURATIONS 14
static const uint16_t k_durations[NUM_DURATIONS] = {
    5,
    8,
    12,
    16,
    20,
    100,
    255,
    256,
    1000,
    4096,
    20000,
    60000,
    65532,
    65535,
};

// Number of ticks_elapsed samples per (diff, duration) pair. Sampled (not
// exhaustive) so total runtime stays bounded regardless of how large
// `duration` is -- see file header.
#define NUM_TICK_SAMPLES 32

static int g_failures = 0;

static void check(
    int cond,
    const char *what,
    int32_t diff,
    uint16_t duration,
    uint16_t ticks_elapsed,
    int32_t new_val,
    int32_t old_val) {
    if (!cond) {
        g_failures++;
        fprintf(
            stderr,
            "FAIL %s: diff=%d duration=%u ticks_elapsed=%u new=%d old=%d\n",
            what,
            diff,
            duration,
            ticks_elapsed,
            new_val,
            old_val);
    }
}

int main(void) {
    long checked        = 0;
    long compared       = 0;
    long skipped_old_ov = 0;

    for (int32_t diff = -65280; diff <= 65280; diff += 256) {
        for (int di = 0; di < NUM_DURATIONS; di++) {
            uint16_t duration = k_durations[di];

            // ticks_elapsed values actually reachable by led_tick()'s subtick
            // stepping (multiples of LEDS_SUBTICKS, strictly less than
            // duration -- once ticks_elapsed >= duration, led_tick() takes
            // the frame-done branch instead of interpolating).
            uint16_t last_reachable = (uint16_t) (((duration - 1) / LEDS_SUBTICKS) * LEDS_SUBTICKS);

            int32_t prev_new = 0;
            int have_prev    = 0;

            for (int s = 0; s < NUM_TICK_SAMPLES; s++) {
                // Evenly sample multiples of LEDS_SUBTICKS across
                // [LEDS_SUBTICKS, last_reachable], always including both ends.
                uint32_t span = last_reachable > LEDS_SUBTICKS ? (last_reachable - LEDS_SUBTICKS) : 0;
                uint32_t raw  = LEDS_SUBTICKS +
                    (NUM_TICK_SAMPLES > 1 ? (span * (uint32_t) s) / (NUM_TICK_SAMPLES - 1) : 0);
                uint16_t ticks_elapsed = (uint16_t) ((raw / LEDS_SUBTICKS) * LEDS_SUBTICKS);
                if (ticks_elapsed < LEDS_SUBTICKS || ticks_elapsed >= duration) {
                    continue;
                }

                int32_t new_val = new_formula_offset(diff, duration, ticks_elapsed);
                checked++;

                if (old_formula_overflows(diff, ticks_elapsed)) {
                    skipped_old_ov++;
                } else {
                    int32_t old_val = old_formula_offset(diff, duration, ticks_elapsed);
                    int32_t err     = new_val - old_val;
                    if (err < 0) {
                        err = -err;
                    }
                    compared++;
                    check(
                        err <= LED_FADE_TEST_TOLERANCE,
                        "new-vs-old within tolerance",
                        diff,
                        duration,
                        ticks_elapsed,
                        new_val,
                        old_val);
                }

                if (have_prev) {
                    if (diff > 0) {
                        check(
                            new_val >= prev_new,
                            "monotonic non-decreasing (diff>0)",
                            diff,
                            duration,
                            ticks_elapsed,
                            new_val,
                            prev_new);
                    } else if (diff < 0) {
                        check(
                            new_val <= prev_new,
                            "monotonic non-increasing (diff<0)",
                            diff,
                            duration,
                            ticks_elapsed,
                            new_val,
                            prev_new);
                    } else {
                        check(new_val == 0, "zero diff stays zero", diff, duration, ticks_elapsed, new_val, 0);
                    }
                }
                prev_new  = new_val;
                have_prev = 1;
            }

            // "Exact landing" bound: evaluate the interpolation formula
            // exactly at the frame boundary (ticks_elapsed == duration),
            // even though led_tick() never actually does this (it snaps
            // directly to `next` instead -- see led_tick()'s frame-done
            // branch). At this exact point, offset_true == diff (an
            // integer), so the rigorous bound derived in this file's header
            // comment applies directly: the formula's output must land
            // within LED_FADE_TEST_TOLERANCE of `diff`, confirming it
            // doesn't diverge as ticks_elapsed approaches duration.
            int32_t at_boundary  = new_formula_offset(diff, duration, duration);
            int32_t boundary_err = at_boundary - diff;
            if (boundary_err < 0) {
                boundary_err = -boundary_err;
            }
            check(
                boundary_err <= LED_FADE_TEST_TOLERANCE,
                "exact landing at frame end within tolerance",
                diff,
                duration,
                duration,
                at_boundary,
                diff);
            checked++;
        }
    }

    printf(
        "test_led_fade_delta: checked=%ld compared=%ld skipped(old int32 overflow)=%ld failures=%d\n",
        checked,
        compared,
        skipped_old_ov,
        g_failures);

    if (g_failures > 0) {
        return 1;
    }
    if (compared == 0) {
        fprintf(stderr, "test_led_fade_delta: no cases were actually compared -- sweep is broken\n");
        return 1;
    }
    return 0;
}
