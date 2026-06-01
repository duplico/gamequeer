# run_golden_test.cmake — CTest script for the headless golden framebuffer test.
#
# Parameters (passed via -D):
#   EXE      — path to the headless gamequeer binary
#   FIXTURE  — path to the .gqgame cart fixture
#   ACTUAL   — path where the actual PGM will be written
#   GOLDEN   — path to the committed golden PGM
#   TICKS    — number of system_tick iterations to run
#
# Exits with FATAL_ERROR if the emulator fails or the PGMs differ.

cmake_minimum_required(VERSION 3.18)

# ---- 1. Run the headless emulator ----------------------------------------

execute_process(
    COMMAND "${EXE}" --ticks "${TICKS}" --dump "${ACTUAL}" "${FIXTURE}"
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

# ---- 2. Verify the actual PGM was produced --------------------------------

if(NOT EXISTS "${ACTUAL}")
    message(FATAL_ERROR "Emulator did not produce output PGM: ${ACTUAL}")
endif()

# ---- 3. Check the golden exists ------------------------------------------

if(NOT EXISTS "${GOLDEN}")
    message(FATAL_ERROR
        "Golden PGM not found: ${GOLDEN}\n"
        "Run: cmake --build <build_dir> --target update-golden"
    )
endif()

# ---- 4. Binary compare ---------------------------------------------------

execute_process(
    COMMAND "${CMAKE_COMMAND}" -E compare_files "${ACTUAL}" "${GOLDEN}"
    RESULT_VARIABLE cmp_result
)

if(NOT cmp_result EQUAL 0)
    message(FATAL_ERROR
        "Golden framebuffer mismatch!\n"
        "  actual: ${ACTUAL}\n"
        "  golden: ${GOLDEN}\n"
        "If the change is intentional, regenerate with:\n"
        "  cmake --build <build_dir> --target update-golden"
    )
endif()

message(STATUS "Golden framebuffer test PASSED")
