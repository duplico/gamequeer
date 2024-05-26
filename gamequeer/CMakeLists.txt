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

# Find X11:
find_package(X11 REQUIRED)
message(STATUS "X11_FOUND = ${X11_FOUND}")
message(STATUS "X11_INCLUDE_DIR = ${X11_INCLUDE_DIR}")
message(STATUS "X11_LIBRARIES = ${X11_LIBRARIES}")
include_directories(${X11_INCLUDE_DIR})
link_directories(${X11_LIBRARIES})

# Main sources:
add_executable(
    ${PROJECT_NAME}
    # Main sources:
    src/main.c
    # Graphics driver:
    src/grlib_gfx_driver/grlib_gfx_driver.c
    # gfx (Linux graphics library) sources:
    src/gfx/gfx.c
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

# Link X11:
target_link_libraries(
    ${PROJECT_NAME}
    ${X11_LIBRARIES}
)

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
