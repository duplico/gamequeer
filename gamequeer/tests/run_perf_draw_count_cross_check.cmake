# run_perf_draw_count_cross_check.cmake — CTest script asserting that
# GQ_PERF_INSTRUMENT's draw_oled_stack section count matches the (separate,
# independently-implemented) --draw-count-out instrumentation for the same
# run. These are two different counters, incremented in two different
# places (gq_draw_oled_stack_count in gamequeer.c vs.
# gq_perf_stats.sections[GQ_PERF_SEC_DRAW_OLED_STACK].count via
# GQ_PERF_ENTER/EXIT in the same function) -- agreement is a cheap
# cross-check that the perf-instrumentation macros are firing exactly once
# per draw_oled_stack() call, no more and no less. Only meaningful (and
# only registered) in a build configured with both GQ_HEADLESS=ON and
# GQ_PERF_INSTRUMENT=ON.
#
# Parameters (passed via -D):
#   EXE          — path to the headless+perf-instrumented gamequeer binary
#   FIXTURE      — path to the .gqgame cart fixture
#   DRAW_COUNT   — path where the --draw-count-out output will be written
#   PERF_DUMP    — path where the --perf-dump output will be written
#   TICKS        — number of system_tick iterations to run
#
# Exits with FATAL_ERROR if the emulator fails, either output is missing,
# the perf-dump's draw_oled_stack count line can't be parsed, or the two
# counts disagree.

cmake_minimum_required(VERSION 3.18)

# ---- 1. Run the headless+perf-instrumented emulator, both flags at once --

execute_process(
    COMMAND "${EXE}" --ticks "${TICKS}" --draw-count-out "${DRAW_COUNT}" --perf-dump "${PERF_DUMP}" "${FIXTURE}"
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

# ---- 2. Read the --draw-count-out count -----------------------------------

if(NOT EXISTS "${DRAW_COUNT}")
    message(FATAL_ERROR "Emulator did not produce draw-count output: ${DRAW_COUNT}")
endif()

file(READ "${DRAW_COUNT}" draw_count)
string(STRIP "${draw_count}" draw_count)

# ---- 3. Read and parse the --perf-dump draw_oled_stack count --------------

if(NOT EXISTS "${PERF_DUMP}")
    message(FATAL_ERROR "Emulator did not produce perf-dump output: ${PERF_DUMP}")
endif()

file(READ "${PERF_DUMP}" perf_dump_contents)

# Each section line looks like:
#   draw_oled_stack          count=2        total_us=77 ...
# Match the draw_oled_stack line specifically and capture its count value.
string(REGEX MATCH "draw_oled_stack[ \t]+count=([0-9]+)" perf_match "${perf_dump_contents}")
if(NOT perf_match)
    message(FATAL_ERROR
        "Could not find a 'draw_oled_stack count=<N>' line in perf-dump output:\n"
        "${perf_dump_contents}"
    )
endif()
set(perf_count "${CMAKE_MATCH_1}")

# ---- 4. Compare ------------------------------------------------------------

if(NOT draw_count EQUAL perf_count)
    message(FATAL_ERROR
        "draw_oled_stack count mismatch between the two independent counters!\n"
        "  --draw-count-out (gq_draw_oled_stack_count): ${draw_count}\n"
        "  --perf-dump (GQ_PERF_SEC_DRAW_OLED_STACK):    ${perf_count}\n"
        "These are incremented in different places for different purposes; "
        "disagreement suggests GQ_PERF_ENTER/EXIT(DRAW_OLED_STACK) is not "
        "firing exactly once per draw_oled_stack() call."
    )
endif()

message(STATUS "Perf/draw-count cross-check PASSED (both report ${draw_count} draw_oled_stack() call(s))")
