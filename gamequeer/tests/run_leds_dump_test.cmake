# run_leds_dump_test.cmake — CTest script for the headless --dump-leds
# golden CSV test (gamequeer#339).
#
# Complements run_golden_test.cmake: LED state isn't part of the OLED
# framebuffer, so a pixel golden gives no coverage of leds.c's redraw
# cadence or cue frame-advance/loop behavior. This runs the emulator with
# --dump-leds and byte-compares the resulting CSV against a committed
# golden.
#
# Parameters (passed via -D):
#   EXE      — path to the headless gamequeer binary
#   FIXTURE  — path to the .gqgame cart fixture
#   ACTUAL   — path where the actual CSV will be written
#   GOLDEN   — path to the committed golden CSV
#   TICKS    — number of system_tick iterations to run
#
# Exits with FATAL_ERROR if the emulator fails or the CSVs differ.

cmake_minimum_required(VERSION 3.18)

# ---- 1. Run the headless emulator ----------------------------------------

execute_process(
    COMMAND "${EXE}" --ticks "${TICKS}" --dump-leds "${ACTUAL}" "${FIXTURE}"
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

# ---- 2. Verify the actual CSV was produced --------------------------------

if(NOT EXISTS "${ACTUAL}")
    message(FATAL_ERROR "Emulator did not produce output CSV: ${ACTUAL}")
endif()

# ---- 3. Check the golden exists ------------------------------------------

if(NOT EXISTS "${GOLDEN}")
    message(FATAL_ERROR
        "Golden LED CSV not found: ${GOLDEN}\n"
        "Run: cmake --build <build_dir> --target update-golden"
    )
endif()

# ---- 4. Byte compare ------------------------------------------------------

execute_process(
    COMMAND "${CMAKE_COMMAND}" -E compare_files "${ACTUAL}" "${GOLDEN}"
    RESULT_VARIABLE cmp_result
)

if(NOT cmp_result EQUAL 0)
    file(READ "${ACTUAL}" actual_contents)
    file(READ "${GOLDEN}" golden_contents)
    message(FATAL_ERROR
        "Golden LED CSV mismatch!\n"
        "  actual: ${ACTUAL}\n"
        "  golden: ${GOLDEN}\n"
        "--- actual ---\n${actual_contents}\n"
        "--- golden ---\n${golden_contents}\n"
        "If the change is intentional, regenerate with:\n"
        "  cmake --build <build_dir> --target update-golden"
    )
endif()

message(STATUS "Golden LED CSV test PASSED")
