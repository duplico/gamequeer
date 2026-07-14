cmake_minimum_required(VERSION 3.18)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

project(
    gamequeer
    VERSION 0.1
    DESCRIPTION "Dummy - A dummy library"
    LANGUAGES C
    )

set_property(
    TARGET ${PROJECT}
    PROPERTY C_STANDARD 99
)

# Headless build option: swaps X11 gfx backend for a no-op stub so the
# emulator builds and runs without a DISPLAY.  The grlib→frame_buffer render
# path stays fully intact; only the X11 sink is replaced.
option(GQ_HEADLESS "Build without X11 display (headless mode)" OFF)

# Perf-instrumentation build option: adds a small RAM stats struct (see
# include/gq_perf.h) with per-section count/duration/min/max timing, updated
# by GQ_PERF_ENTER/EXIT macros around a handful of hot-path functions in
# gamequeer.c. OFF by default and independent of GQ_HEADLESS (either can be
# combined with the other), so a normal (non-instrumented) build never
# compiles src/gq_perf.c and never defines GQ_PERF_INSTRUMENT -- see
# gq_perf.h for why that matters for the zero-cost claim.
option(GQ_PERF_INSTRUMENT "Build with GQ_PERF_INSTRUMENT performance stats (see include/gq_perf.h)" OFF)

if(GQ_HEADLESS)
    message(STATUS "GQ_HEADLESS=ON: building without X11")
    set(GFX_SOURCE src/gfx/gfx_headless.c)
else()
    # Find X11:
    find_package(X11 REQUIRED)
    message(STATUS "X11_FOUND = ${X11_FOUND}")
    message(STATUS "X11_INCLUDE_DIR = ${X11_INCLUDE_DIR}")
    message(STATUS "X11_LIBRARIES = ${X11_LIBRARIES}")
    include_directories(${X11_INCLUDE_DIR})
    set(GFX_SOURCE src/gfx/gfx.c)
endif()

# Main sources:
add_executable(
    ${PROJECT_NAME}
    # Main sources:
    src/main.c
    src/gamequeer.c
    src/HAL.c
    src/leds.c
    src/oled.c
    src/bytecode.c
    src/menu.c
    # Graphics driver:
    src/grlib_gfx_driver/grlib_gfx_driver.c
    # gfx (Linux graphics library) sources:
    ${GFX_SOURCE}
    # grlib sources:
    src/grlib/grlib/context.c
    src/grlib/grlib/circle.c
    src/grlib/grlib/display.c
    src/grlib/grlib/image.c
    src/grlib/grlib/line.c
    src/grlib/grlib/rectangle.c
    src/grlib/grlib/string.c
    src/grlib/fonts/fontfixed6x8.c
)

if(GQ_HEADLESS)
    target_compile_definitions(${PROJECT_NAME} PRIVATE GQ_HEADLESS)
else()
    # Link X11:
    target_link_libraries(
        ${PROJECT_NAME}
        ${X11_LIBRARIES}
    )
endif()

if(GQ_PERF_INSTRUMENT)
    message(STATUS "GQ_PERF_INSTRUMENT=ON: building with performance instrumentation (see include/gq_perf.h)")
    target_sources(${PROJECT_NAME} PRIVATE src/gq_perf.c)
    target_compile_definitions(${PROJECT_NAME} PRIVATE GQ_PERF_INSTRUMENT)
endif()

# Link math:
target_link_libraries(
    ${PROJECT_NAME}
    m
)

target_include_directories(
    ${PROJECT_NAME}
    PUBLIC
    include
)

target_compile_options(${PROJECT_NAME} PUBLIC -Wall -Wextra -Wpedantic)

# Testing (CTest): only register the test tree in the headless build.
# A plain X11 build does not have the golden-test infrastructure,
# so we avoid the confusing "No tests were found" ctest output.
if(GQ_HEADLESS)
    enable_testing()
    add_subdirectory(tests)
endif()
