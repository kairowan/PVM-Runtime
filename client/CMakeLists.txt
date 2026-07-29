cmake_minimum_required(VERSION 3.16)
project(protected_vm VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(PVM_USE_OPENSSL "Use OpenSSL as the default Ed25519 verifier" ON)
option(PVM_BUILD_TOOLS "Build desktop CLI and smoke tools" ON)
option(PVM_ENABLE_SANITIZERS "Build with AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
option(PVM_BUILD_FUZZER "Build the Clang libFuzzer package target" OFF)

if(PVM_ENABLE_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "AppleClang|Clang|GNU")
    if(APPLE)
        # ponytail: macOS 26 ASan currently spins during dyld initialization; Linux CI keeps
        # ASan+UBSan, and this branch can be removed once Apple's runtime supports that dyld.
        add_compile_options(-fsanitize=undefined -fno-omit-frame-pointer)
        add_link_options(-fsanitize=undefined)
    else()
        add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
        add_link_options(-fsanitize=address,undefined)
    endif()
endif()

if(PVM_USE_OPENSSL)
    find_package(OpenSSL REQUIRED COMPONENTS Crypto)
endif()

add_library(pvm_runtime STATIC
    src/runtime.cpp
    src/c_api.cpp
)
target_include_directories(pvm_runtime PUBLIC include)
if(PVM_USE_OPENSSL)
    target_link_libraries(pvm_runtime PUBLIC OpenSSL::Crypto)
    target_compile_definitions(pvm_runtime PRIVATE PVM_USE_OPENSSL=1)
else()
    target_compile_definitions(pvm_runtime PRIVATE PVM_USE_OPENSSL=0)
endif()
target_compile_options(pvm_runtime PRIVATE
    $<$<CXX_COMPILER_ID:AppleClang,Clang,GNU>:-Wall;-Wextra;-Wpedantic;-Werror>
)
set_target_properties(pvm_runtime PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)

if(PVM_BUILD_TOOLS)
    add_executable(pvm_cli src/console_main.cpp)
    target_link_libraries(pvm_cli PRIVATE pvm_runtime)

    add_executable(pvm_c_api_smoke tests/c_api_smoke.cpp)
    target_link_libraries(pvm_c_api_smoke PRIVATE pvm_runtime)

    install(TARGETS pvm_runtime pvm_cli)
else()
    install(TARGETS pvm_runtime)
endif()

if(PVM_BUILD_FUZZER)
    if(NOT CMAKE_CXX_COMPILER_ID MATCHES "AppleClang|Clang")
        message(FATAL_ERROR "PVM_BUILD_FUZZER requires Clang")
    endif()
    add_executable(pvm_package_fuzz tests/package_fuzz.cpp)
    target_link_libraries(pvm_package_fuzz PRIVATE pvm_runtime)
    target_compile_options(pvm_runtime PRIVATE -fsanitize=fuzzer-no-link,undefined)
    target_compile_options(pvm_package_fuzz PRIVATE -fsanitize=fuzzer,undefined)
    target_link_options(pvm_package_fuzz PRIVATE -fsanitize=fuzzer,undefined)
endif()
install(DIRECTORY include/ DESTINATION include)
