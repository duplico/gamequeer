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
#   INPUT         — (optional) filename, relative to GOLDEN_DIR, of a
#                   scripted button-input file (one of A/B/L/R/CLICK per
#                   line; see HAL.c's HAL_input_load()) replayed one event
#                   per tick via --input. Omit for fixtures that don't need
#                   scripted navigation.
function(add_golden_test NAME FIXTURE)
    cmake_parse_arguments(GT "" "TICKS;GOLDEN_SUFFIX;INPUT" "" ${ARGN})
    if(NOT GT_TICKS)
        set(GT_TICKS ${GOLDEN_TICKS})
    endif()
    if(NOT GT_GOLDEN_SUFFIX)
        set(GT_GOLDEN_SUFFIX ${FIXTURE})
    endif()

    set(fixture_cart "${GOLDEN_DIR}/${FIXTURE}.gqgame")
    set(golden_pgm   "${GOLDEN_DIR}/${GT_GOLDEN_SUFFIX}_golden.pgm")
    set(actual_pgm   "${CMAKE_CURRENT_BINARY_DIR}/${NAME}_actual.pgm")

    if(GT_INPUT)
        set(input_script "${GOLDEN_DIR}/${GT_INPUT}")
        set(_test_input_arg -DINPUT=${input_script})
        set(_regen_input_arg --input "${input_script}")
    else()
        set(_test_input_arg "")
        set(_regen_input_arg "")
    endif()

    add_test(
        NAME ${NAME}
        COMMAND
            ${CMAKE_COMMAND}
            -DEXE=$<TARGET_FILE:gamequeer>
            -DFIXTURE=${fixture_cart}
            -DACTUAL=${actual_pgm}
            -DGOLDEN=${golden_pgm}
            -DTICKS=${GT_TICKS}
            ${_test_input_arg}
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
                ${_regen_input_arg}
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

# ---- golden_framebuffer_full_frame_row_blit: row-level uncompressed blit
# fast path (duplico/gamequeer#303, HAL_oled_blit_row()) -- the batched
# replacement for #295's per-byte HAL_oled_blit_byte() fast path.
# rowmajor_byte_blit.gq's bgsprite placement (32x32, byte-aligned, fully
# on-screen) already incidentally exercises the row path, but this fixture
# is the dedicated, purpose-built case: a genuinely full-screen 128x128
# uncompressed image, chosen specifically so its 2048 bytes span exactly two
# IMAGE_BUFFER_SIZE (1024-byte) cart-read chunks -- the row loop crosses an
# image_buffer reload boundary exactly once (between row 63 and row 64),
# regression-locking the fast path's read-before-decode-advance ordering.
# See full_frame_row_blit.gq's header for the full rationale.

add_golden_test(golden_framebuffer_full_frame_row_blit full_frame_row_blit)

# ---- golden_framebuffer_full_frame_mask_row_blit: masked row-level
# uncompressed blit fast path (duplico/gamequeer#311,
# HAL_oled_blit_row_masked()) -- the masked counterpart of
# full_frame_row_blit above, applying #303/#308's row blit + row-level
# decode advance to BOTH the image and mask streams of
# gq_draw_image_with_mask() simultaneously. Genuinely full-screen 128x128
# image+mask pair, each exactly 2048 bytes uncompressed (two
# IMAGE_BUFFER_SIZE chunks), so EACH stream (image_frame's
# image_buffer_main and mask_frame's image_buffer_mask -- two independent
# buffers) crosses its own reload boundary once, between row 63 and row
# 64. See full_frame_mask_row_blit.gq's header for the full rationale,
# including why mask128.png is asymmetric (not a 50/50 checkerboard) and
# how it independently catches a reload-ordering violation on the mask
# stream specifically.

add_golden_test(golden_framebuffer_full_frame_mask_row_blit full_frame_mask_row_blit)

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
    TICKS 21 GOLDEN_SUFFIX anim_advance_frame1)
add_golden_test(golden_framebuffer_anim_advance_frame2 anim_advance
    TICKS 41 GOLDEN_SUFFIX anim_advance_frame2)

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

# ---- golden_framebuffer_label_text_{start,start_scored,glyphs1,glyphs2}:
# label/text render-path (draw_label_stack() -> Graphics_drawString(),
# gamequeer.c/grlib) pixel-identity baseline, authored ahead of the Stage 2
# render rework (duplico/qc2024#47, grlib row-major rewrite) so Stage 2 can
# be asserted pixel-for-pixel identical to today's known-correct rendering.
# No prior golden fixture exercises the label path at all. See
# label_text.gq's header comment for the full per-stage content derivation
# and why `start_scored`/`glyphs1`/`glyphs2` need the TICKS they do (a
# `gostage` inside a later-processed event handler defers the new stage's
# `enter` code to the *next* tick -- see gqc/docs/authoring-and-perf-carts.md
# §3's "Driving menu navigation headlessly").

add_golden_test(golden_framebuffer_label_text_start label_text
    TICKS 1 GOLDEN_SUFFIX label_text_start)
add_golden_test(golden_framebuffer_label_text_start_scored label_text
    TICKS 3 INPUT label_text_score_bump.txt GOLDEN_SUFFIX label_text_start_scored)
add_golden_test(golden_framebuffer_label_text_glyphs1 label_text
    TICKS 2 INPUT label_text_to_glyphs1.txt GOLDEN_SUFFIX label_text_glyphs1)
add_golden_test(golden_framebuffer_label_text_glyphs2 label_text
    TICKS 3 INPUT label_text_to_glyphs2.txt GOLDEN_SUFFIX label_text_glyphs2)

# ---- golden_framebuffer_menu_choice_{pristine,confirmed}: choice-menu
# render path (draw_menu_choice(), menu.c) pixel-identity baseline, same
# Stage-2 motivation as label_text.gq above. No prior golden fixture opens
# a menu at all. See menu_choice.gq's header comment for the full content
# derivation; internal menu-button handling (no `gostage` involved) applies
# within the same tick it's polled, so `confirmed`'s TICKS matches its
# INPUT script's line count exactly (unlike label_text's gostage-driven
# transitions).

add_golden_test(golden_framebuffer_menu_choice_pristine menu_choice
    TICKS 1 GOLDEN_SUFFIX menu_choice_pristine)
add_golden_test(golden_framebuffer_menu_choice_confirmed menu_choice
    TICKS 3 INPUT menu_choice_nav.txt GOLDEN_SUFFIX menu_choice_confirmed)

# ---- golden_framebuffer_menu_text_{pristine,mid}: text-entry menu render
# path (draw_menu_text(), menu.c) pixel-identity baseline, same Stage-2
# motivation as label_text.gq above. No prior golden fixture opens a
# text-entry menu at all. `mid` lands in position-select mode specifically
# to cover the alternate cursor-hint icon set
# (draw_hint_dial_leftright()/draw_hint_click_updown() vs the CHAR-mode
# icons) -- see menu_text.gq's header comment for the full derivation and
# why a `confirmed` golden isn't also wired here (menu_choice.gq's
# `confirmed` already covers the menu-close -> label-redraw sequence).

add_golden_test(golden_framebuffer_menu_text_pristine menu_text
    TICKS 1 GOLDEN_SUFFIX menu_text_pristine)
add_golden_test(golden_framebuffer_menu_text_mid menu_text
    TICKS 4 INPUT menu_text_mid.txt GOLDEN_SUFFIX menu_text_mid)

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

    # ---- perf_row_blit_draw_write_count: GQ_PERF_INSTRUMENT_RUNS-only -----
    # Only registered when GQ_PERF_INSTRUMENT_RUNS is ALSO ON (see above --
    # DRAW_WRITE's count is always 0 otherwise, which would make this
    # assertion meaningless). A pixel-level golden (golden_framebuffer_
    # full_frame_row_blit above) proves gamequeer#303's row-level blit fast
    # path produces byte-identical output to the pre-#303 per-byte path, but
    # cannot distinguish "the fast path engaged" from "it silently fell back
    # to the byte-level path and happened to draw the same pixels" -- e.g. a
    # regression that defeats the fast path's guard condition (frame.width %
    # 8 == 0, full row in clip, etc.) would still pass every golden test with
    # zero signal. full_frame_row_blit.gqgame's 128x128 image draws via
    # exactly 128 HAL_oled_blit_row() calls (one per row) when the fast path
    # engages, or 2048 HAL_oled_blit_byte() calls if it doesn't -- both wrap
    # GQ_PERF_ENTER_RUNS(DRAW_WRITE)/EXIT_RUNS(DRAW_WRITE), so the DRAW_WRITE
    # section's count directly distinguishes the two. TICKS matches
    # GOLDEN_TICKS (the fixture draws once on enter and never again -- see
    # golden_framebuffer_redundant_write_draw_count_* above for the same
    # "no further SETVAR/frame-advance activity" pattern -- so the count is
    # stable across any TICKS >= 1).
    if(GQ_PERF_INSTRUMENT_RUNS)
        add_test(
            NAME perf_row_blit_draw_write_count
            COMMAND
                ${CMAKE_COMMAND}
                -DEXE=$<TARGET_FILE:gamequeer>
                -DFIXTURE=${GOLDEN_DIR}/full_frame_row_blit.gqgame
                -DPERF_DUMP=${CMAKE_CURRENT_BINARY_DIR}/perf_row_blit_draw_write_count_perfdump.txt
                -DTICKS=${GOLDEN_TICKS}
                -DSECTION=draw_write
                -DEXPECTED=128
                -P "${CMAKE_CURRENT_SOURCE_DIR}/run_perf_section_count_test.cmake"
        )

        # ---- perf_row_blit_draw_decode_count: same idea, DRAW_DECODE ------
        # gamequeer#308 replaced the row fast path's per-byte
        # gq_image_advance_byte() loop with a single gq_image_advance_row()
        # call, but GQ_PERF_ENTER_RUNS(DRAW_DECODE)/EXIT_RUNS(DRAW_DECODE)
        # already wrapped that whole loop (once per row, not once per byte)
        # even before #308 -- so DRAW_DECODE's *count* doesn't drop from
        # this change (only its accumulated total_us does, since there's
        # much less to do inside each row's single ENTER/EXIT interval).
        # What EXPECTED=128 (matching DRAW_WRITE, not 2048) still proves is
        # engagement of the row path at all: if the row path's guard ever
        # regresses and every row silently falls back to the byte-aligned
        # fast path just below it (gamequeer#295), THAT path wraps
        # GQ_PERF_ENTER_RUNS(DRAW_DECODE)/EXIT_RUNS(DRAW_DECODE) once per
        # BYTE, so full_frame_row_blit.gqgame's 128x128 image (16 bytes/row)
        # would drive the count to 2048 instead of 128 -- the same
        # row-vs-byte-granularity signal DRAW_WRITE already gives, just
        # from the decode side instead of the write side.
        add_test(
            NAME perf_row_blit_draw_decode_count
            COMMAND
                ${CMAKE_COMMAND}
                -DEXE=$<TARGET_FILE:gamequeer>
                -DFIXTURE=${GOLDEN_DIR}/full_frame_row_blit.gqgame
                -DPERF_DUMP=${CMAKE_CURRENT_BINARY_DIR}/perf_row_blit_draw_decode_count_perfdump.txt
                -DTICKS=${GOLDEN_TICKS}
                -DSECTION=draw_decode
                -DEXPECTED=128
                -P "${CMAKE_CURRENT_SOURCE_DIR}/run_perf_section_count_test.cmake"
        )

        # ---- perf_mask_row_blit_draw_{write,decode}_count: same idea, for
        # gq_draw_image_with_mask()'s masked row fast path (gamequeer#311).
        # full_frame_mask_row_blit.gqgame's 128x128 image+mask pair takes
        # the masked row path (HAL_oled_blit_row_masked() +
        # gq_image_advance_row() x2) once per row when it engages -- 128
        # DRAW_WRITE/DRAW_DECODE section entries, one each per row, same
        # single-ENTER/EXIT-wraps-the-whole-row-iteration shape as the
        # unmasked perf_row_blit_* tests above. If the row path's guard
        # ever regresses (either stream failing to qualify), every row
        # falls back to the byte-aligned masked fast path just below it
        # (gamequeer#295), which wraps DRAW_WRITE/DRAW_DECODE once per BYTE
        # instead -- 128 rows * 16 bytes/row = 2048 -- so EXPECTED=128 is a
        # real discriminator between "masked row path engaged" and
        # "silently fell back to the byte-level masked path", exactly like
        # the unmasked case. A pixel golden alone (golden_framebuffer_
        # full_frame_mask_row_blit above) cannot tell those two apart,
        # since both paths are pixel-identical by construction.
        add_test(
            NAME perf_mask_row_blit_draw_write_count
            COMMAND
                ${CMAKE_COMMAND}
                -DEXE=$<TARGET_FILE:gamequeer>
                -DFIXTURE=${GOLDEN_DIR}/full_frame_mask_row_blit.gqgame
                -DPERF_DUMP=${CMAKE_CURRENT_BINARY_DIR}/perf_mask_row_blit_draw_write_count_perfdump.txt
                -DTICKS=${GOLDEN_TICKS}
                -DSECTION=draw_write
                -DEXPECTED=128
                -P "${CMAKE_CURRENT_SOURCE_DIR}/run_perf_section_count_test.cmake"
        )

        add_test(
            NAME perf_mask_row_blit_draw_decode_count
            COMMAND
                ${CMAKE_COMMAND}
                -DEXE=$<TARGET_FILE:gamequeer>
                -DFIXTURE=${GOLDEN_DIR}/full_frame_mask_row_blit.gqgame
                -DPERF_DUMP=${CMAKE_CURRENT_BINARY_DIR}/perf_mask_row_blit_draw_decode_count_perfdump.txt
                -DTICKS=${GOLDEN_TICKS}
                -DSECTION=draw_decode
                -DEXPECTED=128
                -P "${CMAKE_CURRENT_SOURCE_DIR}/run_perf_section_count_test.cmake"
        )
    endif()
endif()
