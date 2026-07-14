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
function(add_golden_test NAME FIXTURE)
    set(fixture_cart "${GOLDEN_DIR}/${FIXTURE}.gqgame")
    set(golden_pgm   "${GOLDEN_DIR}/${FIXTURE}_golden.pgm")
    set(actual_pgm   "${CMAKE_CURRENT_BINARY_DIR}/${FIXTURE}_actual.pgm")

    add_test(
        NAME ${NAME}
        COMMAND
            ${CMAKE_COMMAND}
            -DEXE=$<TARGET_FILE:gamequeer>
            -DFIXTURE=${fixture_cart}
            -DACTUAL=${actual_pgm}
            -DGOLDEN=${golden_pgm}
            -DTICKS=${GOLDEN_TICKS}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/run_golden_test.cmake"
    )

    add_custom_target(
        update-golden-${NAME}
        COMMAND
            $<TARGET_FILE:gamequeer>
            --ticks ${GOLDEN_TICKS}
            --dump  "${golden_pgm}"
            "${fixture_cart}"
        DEPENDS gamequeer
        COMMENT "Regenerating golden PGM: ${golden_pgm}"
        VERBATIM
    )
    add_dependencies(update-golden update-golden-${NAME})
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
