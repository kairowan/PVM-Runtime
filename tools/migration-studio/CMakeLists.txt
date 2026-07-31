cmake_minimum_required(VERSION 3.21)
project(pvm_migration_studio VERSION 0.5.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Qt6 6.10 REQUIRED COMPONENTS Widgets)
qt_standard_project_setup()

get_filename_component(PVM_REPO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(PVM_STUDIO_BACKEND_DIR "" CACHE PATH
    "Optional PyInstaller onedir package for the migration backend")
set(PVM_STUDIO_THIRD_PARTY_LICENSE_DIR "" CACHE PATH
    "Optional directory containing bundled runtime license notices")
if(WIN32)
    set(PVM_RUNTIME_CLI_DEFAULT
        "${PVM_REPO_ROOT}/build/client/Release/pvm_cli.exe")
else()
    set(PVM_RUNTIME_CLI_DEFAULT "${PVM_REPO_ROOT}/build/client/pvm_cli")
endif()
set(PVM_RUNTIME_CLI "${PVM_RUNTIME_CLI_DEFAULT}" CACHE FILEPATH
    "pvm_cli executable bundled with Migration Studio")

qt_add_executable(PVMMigrationStudio
    MACOSX_BUNDLE
    src/main.cpp
    src/main_window.cpp
    src/main_window.h
)
target_link_libraries(PVMMigrationStudio PRIVATE Qt6::Widgets)
target_compile_definitions(PVMMigrationStudio PRIVATE
    PVM_STUDIO_VERSION="${PROJECT_VERSION}"
)
target_compile_options(PVMMigrationStudio PRIVATE
    $<$<CXX_COMPILER_ID:AppleClang,Clang,GNU>:-Wall;-Wextra;-Wpedantic;-Werror>
)

set_target_properties(PVMMigrationStudio PROPERTIES
    MACOSX_BUNDLE_BUNDLE_NAME "PVM Migration Studio"
    MACOSX_BUNDLE_GUI_IDENTIFIER "dev.pvm.migration-studio"
    MACOSX_BUNDLE_SHORT_VERSION_STRING "${PROJECT_VERSION}"
    MACOSX_BUNDLE_BUNDLE_VERSION "${PROJECT_VERSION}"
    WIN32_EXECUTABLE TRUE
)

enable_testing()
add_test(NAME migration-studio-self-test COMMAND PVMMigrationStudio --self-test)
set_tests_properties(migration-studio-self-test PROPERTIES TIMEOUT 15)

if(APPLE)
    set(PVM_STUDIO_RESOURCES "PVMMigrationStudio.app/Contents/Resources")
    set(PVM_STUDIO_SPEC_DESTINATION "PVMMigrationStudio.app/Contents/spec")
    install(TARGETS PVMMigrationStudio BUNDLE DESTINATION .)
else()
    set(PVM_STUDIO_RESOURCES ".")
    set(PVM_STUDIO_SPEC_DESTINATION "spec")
    install(TARGETS PVMMigrationStudio RUNTIME DESTINATION .)
endif()

install(
    DIRECTORY "${PVM_REPO_ROOT}/server/src/pvm_server"
    DESTINATION "${PVM_STUDIO_RESOURCES}/python"
    FILES_MATCHING
    PATTERN "*.py"
    PATTERN "__pycache__" EXCLUDE
)
install(
    DIRECTORY "${PVM_REPO_ROOT}/spec/"
    DESTINATION "${PVM_STUDIO_SPEC_DESTINATION}"
    FILES_MATCHING PATTERN "*.json"
)
install(PROGRAMS "${PVM_RUNTIME_CLI}"
    DESTINATION "${PVM_STUDIO_RESOURCES}/bin")
if(PVM_STUDIO_BACKEND_DIR)
    install(DIRECTORY "${PVM_STUDIO_BACKEND_DIR}/"
        DESTINATION "${PVM_STUDIO_RESOURCES}/bin"
        USE_SOURCE_PERMISSIONS)
endif()
install(
    DIRECTORY "${PVM_REPO_ROOT}/third_party/qt/licenses/"
    DESTINATION "${PVM_STUDIO_RESOURCES}/licenses/qt"
)
if(PVM_STUDIO_THIRD_PARTY_LICENSE_DIR)
    install(
        DIRECTORY "${PVM_STUDIO_THIRD_PARTY_LICENSE_DIR}/"
        DESTINATION "${PVM_STUDIO_RESOURCES}/licenses/runtime"
    )
endif()

qt_generate_deploy_app_script(
    TARGET PVMMigrationStudio
    OUTPUT_SCRIPT deploy_script
    NO_UNSUPPORTED_PLATFORM_ERROR
)
install(SCRIPT "${deploy_script}")
