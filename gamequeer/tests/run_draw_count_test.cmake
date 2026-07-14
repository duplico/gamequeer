# run_draw_count_test.cmake — CTest script asserting an exact
# draw_oled_stack() invocation count.
#
# Complements run_golden_test.cmake: a pixel-level golden can't tell "1
# draw" apart from "20 identical draws" of the same pixels, which is
# exactly the redundant-refresh regression gamequeer#265/PR#274 fixed. This
# script runs the (headless-only) emulator with --draw-count-out and
# compares the resulting count against an expected value.
#
# Parameters (passed via -D):
#   EXE      — path to the headless gamequeer binary
#   FIXTURE  — path to the .gqgame cart fixture
#   ACTUAL   — path where the actual draw-count file will be written
#   TICKS    — number of system_tick iterations to run
#   EXPECTED — expected draw_oled_stack() invocation count (integer)
#
# Exits with FATAL_ERROR if the emulator fails or the count doesn't match.

cmake_minimum_required(VERSION 3.18)

# ---- 1. Run the headless emulator ----------------------------------------

execute_process(
    COMMAND "${EXE}" --ticks "${TICKS}" --draw-count-out "${ACTUAL}" "${FIXTURE}"
    RESULT_VARIABLE run_result
    OUTPUT_VARIABLE run_stdout
    ERROR_VARIABLE  run_stderr
)

if(NOT run_result EQUAL 0)
    message(FATAL_ERROR
        "Emulator exited with code ${run_result}\n"
        "stdout: ${run_stdout}\n"
        "stderr: ${run_stderr}"
    )
endif()

# ---- 2. Read the actual count ---------------------------------------------

if(NOT EXISTS "${ACTUAL}")
    message(FATAL_ERROR "Emulator did not produce draw-count output: ${ACTUAL}")
endif()

file(READ "${ACTUAL}" actual_count)
string(STRIP "${actual_count}" actual_count)

# ---- 3. Compare --------------------------------------------------------

if(NOT actual_count EQUAL EXPECTED)
    message(FATAL_ERROR
        "Draw count mismatch!\n"
        "  actual:   ${actual_count}\n"
        "  expected: ${EXPECTED}\n"
        "If this is an intentional behavior change, update the EXPECTED "
        "argument in tests/CMakeLists.txt's add_draw_count_test() call."
    )
endif()

message(STATUS "Draw count test PASSED (${actual_count} draw_oled_stack() call(s))")
