/* GQ_PERF_INSTRUMENT support code. See include/gq_perf.h for the full
 * design note (struct layout, timer-width rationale, HAL_perf_now()
 * firmware-implementation requirements).
 *
 * This translation unit is only added to the build when GQ_PERF_INSTRUMENT
 * is ON (see CMakeLists.txt) -- a normal build never compiles or links it,
 * which is part of the zero-cost claim: not just "the macros expand to
 * nothing" but "this object file doesn't exist in a normal build".
 */

#include "gq_perf.h"

#ifdef GQ_PERF_INSTRUMENT

gq_perf_stats_t gq_perf_stats = {
    .magic    = GQ_PERF_MAGIC,
    .version  = GQ_PERF_VERSION,
    .reserved = 0,
    .sections = {{0}},
};

const char *const gq_perf_section_names[GQ_PERF_SEC_COUNT] = {
#define GQ_PERF_NAME_ENTRY(NAME, STR) STR,
    GQ_PERF_SECTION_LIST(GQ_PERF_NAME_ENTRY)
#undef GQ_PERF_NAME_ENTRY
};

void gq_perf_record(gq_perf_section_id_t sec, gq_perf_time_t duration_us) {
    /* Defense-in-depth: drop implausible samples (e.g. a garbage
     * HAL_perf_now() delta from a firmware timing-source race) before they
     * can poison this section's accumulators. See gq_perf.h's
     * implausible-sample-drop NOTE and GQ_PERF_MAX_PLAUSIBLE_US for the
     * threshold and rationale. Dropped, not clamped: count/total_us/min_us/
     * max_us are all left untouched for this call. */
    if (duration_us > GQ_PERF_MAX_PLAUSIBLE_US) {
        return;
    }

    gq_perf_section_t *s = &gq_perf_stats.sections[sec];
    s->count++;
    s->total_us += duration_us;
    /* s->count == 1 is the first sample for this section: min_us/max_us
     * both start at the struct's zero-init value, which is not a valid
     * "no samples yet" sentinel for min (0 would never be beaten by a real
     * duration), so seed both from the first sample explicitly. */
    if (s->count == 1 || duration_us < s->min_us) {
        s->min_us = duration_us;
    }
    if (s->count == 1 || duration_us > s->max_us) {
        s->max_us = duration_us;
    }
}

#endif /* GQ_PERF_INSTRUMENT */
