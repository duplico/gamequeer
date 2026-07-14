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
