# tests/CMakeLists.txt — Golden framebuffer regression tests
#
# Requires: parent CMakeLists.txt built with -DGQ_HEADLESS=ON.
# Each test builds headless, runs a fixture .gqgame for a fixed number of
# ticks, dumps the framebuffer as a PGM, and compares it to a committed golden.
#
# Regen goldens:
#   cmake -B build -DGQ_HEADLESS=ON && cmake --build build
#   cmake --build build --target update-golden

if(NOT GQ_HEADLESS)
    message(STATUS "GQ_HEADLESS is OFF — skipping golden tests (re-run with -DGQ_HEADLESS=ON)")
    return()
endif()

set(GOLDEN_DIR "${CMAKE_CURRENT_SOURCE_DIR}/golden")

# Number of ticks to run: enough for the enter event to fire and the
# framebuffer to be populated (1 tick loads the stage + runs enter; a few more
# for the renderer to flush).
set(GOLDEN_TICKS 5)

# ---- helper: register a golden-compare test + its update-golden target ---
# NAME       — ctest test name / update-golden sub-target suffix
# FIXTURE    — fixture base name (expects golden/<FIXTURE>.gqgame)
# Optional keyword args (cmake_parse_arguments):
#   TICKS         — override the default GOLDEN_TICKS tick count for this
#                   test (e.g. to land at a specific point in a fixture's
#                   own internal timeline).
#   GOLDEN_SUFFIX — override the golden/actual PGM basename (defaults to
#                   FIXTURE). Two tests can intentionally share a golden
#                   PGM (same GOLDEN_SUFFIX, different TICKS) to assert
#                   byte-identical output at two different tick counts --
#                   e.g. "many ticks of no-op writes changed nothing".
function(add_golden_test NAME FIXTURE)
    cmake_parse_arguments(GT "" "TICKS;GOLDEN_SUFFIX" "" ${ARGN})
    if(NOT GT_TICKS)
        set(GT_TICKS ${GOLDEN_TICKS})
    endif()
    if(NOT GT_GOLDEN_SUFFIX)
        set(GT_GOLDEN_SUFFIX ${FIXTURE})
    endif()

    set(fixture_cart "${GOLDEN_DIR}/${FIXTURE}.gqgame")
    set(golden_pgm   "${GOLDEN_DIR}/${GT_GOLDEN_SUFFIX}_golden.pgm")
    set(actual_pgm   "${CMAKE_CURRENT_BINARY_DIR}/${NAME}_actual.pgm")

    add_test(
        NAME ${NAME}
        COMMAND
            ${CMAKE_COMMAND}
            -DEXE=$<TARGET_FILE:gamequeer>
            -DFIXTURE=${fixture_cart}
            -DACTUAL=${actual_pgm}
            -DGOLDEN=${golden_pgm}
            -DTICKS=${GT_TICKS}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/run_golden_test.cmake"
    )

    # Only one update-golden regeneration target may own a given golden PGM
    # path. Two tests intentionally sharing a GOLDEN_SUFFIX (to assert
    # byte-identical output at two different tick counts) must not each get
    # their own custom target writing the same output file -- a parallel
    # `make`/`ninja` build has no ordering guarantee between independent
    # custom targets and could interleave the writes. The first
    # add_golden_test() call for a given GOLDEN_SUFFIX registers the
    # regeneration target; later calls sharing that suffix reuse it.
    get_property(regen_owned GLOBAL PROPERTY "GQ_GOLDEN_REGEN_${GT_GOLDEN_SUFFIX}" SET)
    if(NOT regen_owned)
        set_property(GLOBAL PROPERTY "GQ_GOLDEN_REGEN_${GT_GOLDEN_SUFFIX}" ${NAME})
        add_custom_target(
            update-golden-${NAME}
            COMMAND
                $<TARGET_FILE:gamequeer>
                --ticks ${GT_TICKS}
                --dump  "${golden_pgm}"
                "${fixture_cart}"
            DEPENDS gamequeer
            COMMENT "Regenerating golden PGM: ${golden_pgm}"
            VERBATIM
        )
        add_dependencies(update-golden update-golden-${NAME})
    endif()
endfunction()

# `update-golden` regenerates every registered golden PGM.
# Usage: cmake --build build --target update-golden
add_custom_target(update-golden)

# ---- golden_framebuffer: hello.gq (text render, no animations) ----------

add_golden_test(golden_framebuffer hello)

# ---- golden_framebuffer_mask_encoding_{a,b}: masked-sprite (fganim/fgmask)
# regression coverage for gamequeer#262/PR#272 (removed vestigial unmasked
# pre-draw in gq_draw_image_with_mask). Together, the two fixtures exercise
# all four (image encoding x mask encoding) combinations gqc's Frame cooker
# can currently produce (UNCOMPRESSED, RLE7); see mask_encoding_a.gq's header
# comment for why RLE4 isn't reachable through the public compile pipeline.

add_golden_test(golden_framebuffer_mask_encoding_a mask_encoding_a)
add_golden_test(golden_framebuffer_mask_encoding_b mask_encoding_b)

# ---- golden_framebuffer_rowmajor_byte_blit: unmasked byte-aligned
# uncompressed fast path (duplico/qc2024#45 Stage 1 / duplico/gamequeer#295,
# row-major framebuffer render rework). gq_draw_image()'s new byte-blit fast
# path (HAL_oled_blit_byte()) is incidentally reachable via anim_advance.gq's
# bwcircles.gif frames (confirmed by negative-control: deliberately breaking
# HAL_oled_blit_byte()'s bit order fails anim_advance's goldens too, not just
# this one) but that coverage is opportunistic and undocumented; this fixture
# is the dedicated, purpose-built case. mask_encoding_a/b above only ever
# reach the *masked* draw function. See rowmajor_byte_blit.gq's header for
# the three placements (byte-aligned, dest-unaligned, right-edge-clipped)
# this locks in.

add_golden_test(golden_framebuffer_rowmajor_byte_blit rowmajor_byte_blit)

# ---- golden_framebuffer_mask_encoding_c: masked byte-parallel fast path
# alignment/clip edge cases (duplico/qc2024#45 Stage 1 / duplico/gamequeer#295).
# Companion to mask_encoding_a/b: those already cover all four (image x mask)
# encoding combinations at one fully on-screen, byte-aligned position, which
# also happens to be the new byte-parallel masked fast path's easy case (see
# mask_encoding_c.gq's header -- mask_encoding_b's checker.png/checker.png
# pair is unchanged by this rework, itself strong pixel-identity evidence).
# This fixture adds the dest-unaligned and right-edge-clip-mid-row cases
# mask_encoding_a/b don't reach.

add_golden_test(golden_framebuffer_mask_encoding_c mask_encoding_c)

# ---- golden_framebuffer_redundant_write_{initial,phase_a,phase_b}: SETVAR
# redundant-refresh regression coverage for gamequeer#265/PR#274 (GQ_OP_SETVAR
# now only raises GQ_EVENT_REFRESH when a write to a visual builtin var
# actually changes its value). See redundant_write.gq's header comment for
# the fixture's internal timeline and exactly what each tick count lands on.
#
# `initial` and `phase_a` intentionally share one golden PGM (via
# GOLDEN_SUFFIX) despite running for a different number of ticks: this
# directly asserts that many ticks of redundant, unchanged SETVAR writes
# (the #265 pattern) produce byte-identical output to the frame immediately
# after the one real write -- i.e. suppression is not itself a rendering
# change. `phase_b` runs long enough to pass the fixture's one real value
# change (plus several more redundant writes of the *new* value) and gets
# its own golden, which must differ from `initial`/`phase_a`'s -- i.e. the
# real change is never swallowed by the suppression logic.

add_golden_test(golden_framebuffer_redundant_write_initial redundant_write
    TICKS 3 GOLDEN_SUFFIX redundant_write_unchanged)
add_golden_test(golden_framebuffer_redundant_write_phase_a redundant_write
    TICKS 20 GOLDEN_SUFFIX redundant_write_unchanged)
add_golden_test(golden_framebuffer_redundant_write_phase_b redundant_write
    TICKS 30 GOLDEN_SUFFIX redundant_write_changed)

# ---- helper: register a draw_oled_stack() invocation-count test ----------
# NAME     — ctest test name
# FIXTURE  — fixture base name (expects golden/<FIXTURE>.gqgame)
# TICKS    — number of system_tick iterations to run
# EXPECTED — expected exact draw_oled_stack() invocation count
#
# Complements add_golden_test: a pixel golden can't distinguish "1 draw"
# from "20 identical redundant draws" of the same pixels, which is the
# actual behavior #265/PR#274 changed. No committed golden file is needed;
# EXPECTED is a plain literal in the add_draw_count_test() call site below.
function(add_draw_count_test NAME FIXTURE TICKS EXPECTED)
    set(fixture_cart "${GOLDEN_DIR}/${FIXTURE}.gqgame")
    set(actual_txt   "${CMAKE_CURRENT_BINARY_DIR}/${NAME}_actual.txt")

    add_test(
        NAME ${NAME}
        COMMAND
            ${CMAKE_COMMAND}
            -DEXE=$<TARGET_FILE:gamequeer>
            -DFIXTURE=${fixture_cart}
            -DACTUAL=${actual_txt}
            -DTICKS=${TICKS}
            -DEXPECTED=${EXPECTED}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/run_draw_count_test.cmake"
    )
endfunction()

# ---- golden_framebuffer_redundant_write_draw_count_{phase_a,phase_b} -----
# Exact draw_oled_stack() invocation counts for the same redundant_write.gq
# timeline used by the golden tests above:
#   TICKS=20 (deep into the redundant "COUNT: A" phase, before the one real
#             change) -> exactly 1 draw (the initial enter draw only; the
#             18 redundant timer-driven rewrites in between are suppressed).
#   TICKS=30 (well after the one real change to "COUNT: B", plus several
#             more redundant rewrites of the *new* value) -> exactly 2
#             draws (the initial draw, plus the one draw for the real
#             change; the trailing redundant "COUNT: B" rewrites are also
#             suppressed).
# These are the emulator-measurable form of the instrumented 500-tick ->
# 1-draw validation cited in the PR body (that measurement used a temporary,
# uncommitted counter; these tests commit the same style of assertion).

add_draw_count_test(golden_framebuffer_redundant_write_draw_count_phase_a redundant_write 20 1)
add_draw_count_test(golden_framebuffer_redundant_write_draw_count_phase_b redundant_write 30 2)

# ---- led_fade_delta: fixed-point LED interpolation arithmetic regression -
# gamequeer#241/PR#284 replaced a per-subtick divide with a precomputed
# fixed-point delta + multiply/shift. Unlike the golden-framebuffer tests
# above, this doesn't need the emulator (LED state isn't part of the OLED
# framebuffer): it's a small standalone host executable, built independently
# of the ${PROJECT_NAME} emulator target (which has X11/HAL link
# dependencies not needed here), that sweeps legal (diff, duration,
# ticks_elapsed) triples and checks the new arithmetic against the pre-#284
# reference formula. See test_led_fade_delta.c's header for the full sweep
# domain and what's asserted.

add_executable(test_led_fade_delta test_led_fade_delta.c)
target_compile_options(test_led_fade_delta PRIVATE -Wall -Wextra -Wpedantic)

add_test(NAME led_fade_delta COMMAND test_led_fade_delta)

# ---- golden_framebuffer_anim_advance_{frame0,frame1,frame2}: animation
# frame-metadata cache regression coverage for gamequeer#264/PR#282
# (draw_animation_stack() caches the current frame's gq_anim_frame instead of
# re-reading it from cart on every redraw, invalidating on every real frame
# advance). None of the other fixtures above ever advance an animation frame,
# so this is the first golden coverage of that invalidation path. See
# anim_advance.gq's header comment for the full tick-timing derivation and
# the negative-control result (frame1/frame2 both go stale at frame 0's
# pixels if the cache-invalidation writes are reverted).

add_golden_test(golden_framebuffer_anim_advance_frame0 anim_advance
    TICKS 1  GOLDEN_SUFFIX anim_advance_frame0)
add_golden_test(golden_framebuffer_anim_advance_frame1 anim_advance
    TICKS 22 GOLDEN_SUFFIX anim_advance_frame1)
add_golden_test(golden_framebuffer_anim_advance_frame2 anim_advance
    TICKS 43 GOLDEN_SUFFIX anim_advance_frame2)

# ---- golden_framebuffer_edge_coverage: true-display-edge oracle coverage
# gamequeer#297 fixed the emulator canvas (OLED_HORIZONTAL_MAX/
# OLED_VERTICAL_MAX) from 127x127 to 128x128, matching the badge's real
# LCD_X_SIZE/LCD_Y_SIZE -- prior to that fix, x=127 and y=127 could never
# be stored in frame_buffer or golden-tested at all. This fixture
# deliberately draws content all the way to the display's true
# bottom-right corner (both the byte-aligned fast path and the generic
# clipped path) so the golden suite has dedicated, hand-verifiable
# coverage of the extreme edge, not just incidental reach from other
# fixtures' clip placements. See edge_coverage.gq's header comment for the
# full expected-pixel derivation.

add_golden_test(golden_framebuffer_edge_coverage edge_coverage)

# ---- perf_draw_count_cross_check: GQ_PERF_INSTRUMENT-only ----------------
# Only registered when this build is ALSO configured with
# -DGQ_PERF_INSTRUMENT=ON (a plain -DGQ_HEADLESS=ON build has no --perf-dump
# flag at all -- see main.c's GQ_PERF_INSTRUMENT-gated CLI parsing). Cross-
# checks gq_perf_stats's DRAW_OLED_STACK section count against the existing,
# independently-implemented gq_draw_oled_stack_count (--draw-count-out) for
# the same run: two different instrumentation mechanisms measuring the same
# event, which is a cheap sanity check that GQ_PERF_ENTER/EXIT is wired up
# correctly around draw_oled_stack(). See run_perf_draw_count_cross_check.cmake.
# EXPECT_RUNS_INSTRUMENTED also tells the script whether to additionally
# assert on the draw_decode section's zero/nonzero state, which is a direct
# check that GQ_PERF_INSTRUMENT_RUNS (see include/gq_perf.h) is wired up:
# draw_decode must be all-zero when GQ_PERF_INSTRUMENT_RUNS is OFF (its
# GQ_PERF_ENTER_RUNS/EXIT_RUNS calls compile out) and nonzero when it's ON,
# for the same anim_advance.gqgame fixture, which does draw RLE-encoded
# content and so is guaranteed to hit the run loop at least once.
if(GQ_PERF_INSTRUMENT)
    if(GQ_PERF_INSTRUMENT_RUNS)
        set(_expect_runs_instrumented ON)
    else()
        set(_expect_runs_instrumented OFF)
    endif()
    add_test(
        NAME perf_draw_count_cross_check
        COMMAND
            ${CMAKE_COMMAND}
            -DEXE=$<TARGET_FILE:gamequeer>
            -DFIXTURE=${GOLDEN_DIR}/anim_advance.gqgame
            -DDRAW_COUNT=${CMAKE_CURRENT_BINARY_DIR}/perf_draw_count_cross_check_drawcount.txt
            -DPERF_DUMP=${CMAKE_CURRENT_BINARY_DIR}/perf_draw_count_cross_check_perfdump.txt
            -DTICKS=43
            -DEXPECT_RUNS_INSTRUMENTED=${_expect_runs_instrumented}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/run_perf_draw_count_cross_check.cmake"
    )
endif()
