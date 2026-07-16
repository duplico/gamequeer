# run_perf_section_count_test.cmake — CTest script asserting an exact
# gq_perf_stats section invocation count via --perf-dump.
#
# Complements run_draw_count_test.cmake (which checks draw_oled_stack()
# invocations) and run_perf_draw_count_cross_check.cmake (which cross-checks
# two independent draw_oled_stack() counters): this one asserts an exact
# count for an arbitrary GQ_PERF_INSTRUMENT section by name, e.g. proving a
# fast path actually engaged rather than silently falling back to a slower
# path with pixel-identical output. A pixel golden alone cannot distinguish
# "128 row-level HAL_oled_blit_row() calls" from "2048 byte-level
# HAL_oled_blit_byte() calls" -- both draw the same pixels -- which is
# exactly the gap this closes for gamequeer#303's row-level blit fast path
# (golden_framebuffer_full_frame_row_blit's fixture is drawn via 128
# HAL_oled_blit_row() calls, one per row, when the fast path is engaged;
# 2048 HAL_oled_blit_byte() calls if it silently fell back to the per-byte
# path instead).
#
# Only meaningful (and only registered by tests/CMakeLists.txt) in a build
# configured with GQ_HEADLESS=ON, GQ_PERF_INSTRUMENT=ON, and
# GQ_PERF_INSTRUMENT_RUNS=ON -- DRAW_DECODE/DRAW_WRITE's
# GQ_PERF_ENTER_RUNS/EXIT_RUNS calls compile out entirely (count always 0)
# without GQ_PERF_INSTRUMENT_RUNS.
#
# Parameters (passed via -D):
#   EXE       — path to the headless+perf-instrumented gamequeer binary
#   FIXTURE   — path to the .gqgame cart fixture
#   PERF_DUMP — path where the --perf-dump output will be written
#   TICKS     — number of system_tick iterations to run
#   SECTION   — gq_perf_stats section name to check (e.g. "draw_write";
#               see gq_perf_section_names[] / GQ_PERF_SECTION_LIST in
#               include/gq_perf.h for the full list of valid names)
#   EXPECTED  — expected exact count for that section (integer)
#
# Exits with FATAL_ERROR if the emulator fails, the perf-dump is missing,
# the requested section's count line can't be parsed, or the count doesn't
# match EXPECTED.

cmake_minimum_required(VERSION 3.18)

# ---- 1. Run the headless+perf-instrumented emulator -----------------------

execute_process(
    COMMAND "${EXE}" --ticks "${TICKS}" --perf-dump "${PERF_DUMP}" "${FIXTURE}"
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

# ---- 2. Read and parse the requested section's count -----------------------

if(NOT EXISTS "${PERF_DUMP}")
    message(FATAL_ERROR "Emulator did not produce perf-dump output: ${PERF_DUMP}")
endif()

file(READ "${PERF_DUMP}" perf_dump_contents)

# Each section line looks like:
#   draw_write                count=128       total_us=... ...
string(REGEX MATCH "${SECTION}[ \t]+count=([0-9]+)" section_match "${perf_dump_contents}")
if(NOT section_match)
    message(FATAL_ERROR
        "Could not find a '${SECTION} count=<N>' line in perf-dump output:\n"
        "${perf_dump_contents}"
    )
endif()
set(actual_count "${CMAKE_MATCH_1}")

# ---- 3. Compare -------------------------------------------------------------

if(NOT actual_count EQUAL EXPECTED)
    message(FATAL_ERROR
        "${SECTION} count mismatch!\n"
        "  actual:   ${actual_count}\n"
        "  expected: ${EXPECTED}\n"
        "If this is an intentional behavior change (e.g. a fast path no "
        "longer engages, or engages at a different granularity), update the "
        "EXPECTED argument in tests/CMakeLists.txt -- but treat a lower "
        "count than expected as a strong signal a fast path silently "
        "stopped engaging, not just a number to bump."
    )
endif()

message(STATUS "Perf section count test PASSED (${SECTION} count=${actual_count})")
