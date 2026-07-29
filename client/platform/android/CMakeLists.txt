cmake_minimum_required(VERSION 3.22)
project(pvm_android_bridge LANGUAGES CXX)

set(PVM_USE_OPENSSL OFF CACHE BOOL "" FORCE)
set(PVM_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
add_subdirectory(../.. "${CMAKE_CURRENT_BINARY_DIR}/pvm-core")

add_library(pvm_android SHARED src/main/cpp/pvm_jni.cpp)
target_compile_features(pvm_android PRIVATE cxx_std_17)
target_include_directories(pvm_android PRIVATE ../../include)
target_compile_options(pvm_android PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_link_libraries(pvm_android PRIVATE pvm_runtime)
