cmake_minimum_required(VERSION 3.16)
project(pvm_harmony_bridge LANGUAGES CXX)

set(PVM_USE_OPENSSL OFF CACHE BOOL "" FORCE)
set(PVM_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    add_compile_options(-Qunused-arguments)
endif()
add_subdirectory(../../../../../.. "${CMAKE_CURRENT_BINARY_DIR}/pvm-core")

add_library(pvm_harmony SHARED pvm_napi.cpp)
target_compile_features(pvm_harmony PRIVATE cxx_std_17)
target_include_directories(pvm_harmony PRIVATE ../../../../../../include)
target_compile_definitions(pvm_harmony PRIVATE NODE_GYP_MODULE_NAME=pvm_harmony)
target_compile_options(
    pvm_harmony
    PRIVATE -Wall -Wextra -Wpedantic -Werror
)
target_link_libraries(pvm_harmony PRIVATE pvm_runtime libace_napi.z.so)
