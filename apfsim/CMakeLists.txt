cmake_minimum_required(VERSION 3.20)
project(apfsim LANGUAGES CXX)

set(APFSIM_TOP core_top CACHE STRING "Verilog top module")
set(APFSIM_FILELIST examples/mock/filelist.f CACHE STRING "Verilator filelist")
set(APFSIM_MDIR ${CMAKE_BINARY_DIR}/obj CACHE STRING "Verilator output directory")

find_program(VERILATOR_BIN verilator REQUIRED)

add_custom_target(apfsim_lint
    COMMAND ${VERILATOR_BIN} --lint-only --top-module ${APFSIM_TOP} -f ${APFSIM_FILELIST} -Irtl_shims -Wno-fatal --assert
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    VERBATIM)

add_custom_target(apfsim_build
    COMMAND ${CMAKE_COMMAND} -E make_directory ${APFSIM_MDIR}
    COMMAND ${VERILATOR_BIN} --cc --exe cpp/main.cpp --top-module ${APFSIM_TOP}
            --Mdir ${APFSIM_MDIR} -f ${APFSIM_FILELIST} -Irtl_shims -Wno-fatal --assert
            -CFLAGS "-std=c++20 -O2 -I${CMAKE_CURRENT_SOURCE_DIR}/cpp" --build
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    VERBATIM)

add_custom_target(apfsim_build_waves
    COMMAND ${CMAKE_COMMAND} -E make_directory ${APFSIM_MDIR}
    COMMAND ${VERILATOR_BIN} --cc --exe cpp/main.cpp --top-module ${APFSIM_TOP}
            --Mdir ${APFSIM_MDIR} -f ${APFSIM_FILELIST} -Irtl_shims -Wno-fatal --assert
            --trace --trace-fst --trace-structs
            -CFLAGS "-std=c++20 -O2 -I${CMAKE_CURRENT_SOURCE_DIR}/cpp" --build
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    VERBATIM)
