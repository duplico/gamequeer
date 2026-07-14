# tests/CMakeLists.txt — Golden framebuffer regression tests
#
# Requires: parent CMakeLists.txt built with -DGQ_HEADLESS=ON.
# The test builds headless, runs the hello.gq fixture for a fixed number of
# ticks, dumps the framebuffer as a PGM, and compares it to a committed golden.
#
# Regen goldens:
#   cmake -B build -DGQ_HEADLESS=ON && cmake --build build
#   cmake --build build --target update-golden

if(NOT GQ_HEADLESS)
    message(STATUS "GQ_HEADLESS is OFF — skipping golden tests (re-run with -DGQ_HEADLESS=ON)")
    return()
endif()

set(GOLDEN_DIR    "${CMAKE_CURRENT_SOURCE_DIR}/golden")
set(FIXTURE_CART  "${GOLDEN_DIR}/hello.gqgame")
set(GOLDEN_PGM    "${GOLDEN_DIR}/hello_golden.pgm")
set(ACTUAL_PGM    "${CMAKE_CURRENT_BINARY_DIR}/hello_actual.pgm")

# Number of ticks to run: enough for the enter event to fire and the
# framebuffer to be populated (1 tick loads the stage + runs enter; a few more
# for the renderer to flush).
set(GOLDEN_TICKS 5)

# ---- golden-compare test ------------------------------------------------

add_test(
    NAME golden_framebuffer
    COMMAND
        ${CMAKE_COMMAND}
        -DEXE=$<TARGET_FILE:gamequeer>
        -DFIXTURE=${FIXTURE_CART}
        -DACTUAL=${ACTUAL_PGM}
        -DGOLDEN=${GOLDEN_PGM}
        -DTICKS=${GOLDEN_TICKS}
        -P "${CMAKE_CURRENT_SOURCE_DIR}/run_golden_test.cmake"
)

# ---- update-golden target -----------------------------------------------
# Usage: cmake --build build --target update-golden
# Runs the emulator and overwrites the committed golden PGM.

add_custom_target(
    update-golden
    COMMAND
        $<TARGET_FILE:gamequeer>
        --ticks ${GOLDEN_TICKS}
        --dump  "${GOLDEN_PGM}"
        "${FIXTURE_CART}"
    DEPENDS gamequeer
    COMMENT "Regenerating golden PGM: ${GOLDEN_PGM}"
    VERBATIM
)
