cmake_minimum_required(VERSION 3.21)
project(pvm_migration_studio VERSION 0.5.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Qt6 6.12 REQUIRED COMPONENTS Widgets)
qt_standard_project_setup()

get_filename_component(PVM_REPO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)

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

install(TARGETS PVMMigrationStudio
    BUNDLE DESTINATION .
    RUNTIME DESTINATION bin
)

if(APPLE)
    set(PVM_STUDIO_RESOURCES "PVMMigrationStudio.app/Contents/Resources")
    install(
        DIRECTORY "${PVM_REPO_ROOT}/server/src/pvm_server"
        DESTINATION "${PVM_STUDIO_RESOURCES}/python"
        FILES_MATCHING
        PATTERN "*.py"
        PATTERN "__pycache__" EXCLUDE
    )
    install(
        DIRECTORY "${PVM_REPO_ROOT}/spec/"
        DESTINATION "PVMMigrationStudio.app/Contents/spec"
        FILES_MATCHING PATTERN "*.json"
    )
    install(
        PROGRAMS "${PVM_REPO_ROOT}/build/client/pvm_cli"
        DESTINATION "${PVM_STUDIO_RESOURCES}/bin"
    )
    install(
        DIRECTORY "${PVM_REPO_ROOT}/third_party/qt/licenses/"
        DESTINATION "${PVM_STUDIO_RESOURCES}/licenses/qt"
    )
endif()

qt_generate_deploy_app_script(
    TARGET PVMMigrationStudio
    OUTPUT_SCRIPT deploy_script
    NO_UNSUPPORTED_PLATFORM_ERROR
)
install(SCRIPT "${deploy_script}")
