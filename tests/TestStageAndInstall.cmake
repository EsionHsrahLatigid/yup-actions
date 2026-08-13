cmake_minimum_required(VERSION 3.25)

foreach(required_var EHL_TEST_ROOT EHL_STAGE_SCRIPT)
    if(NOT DEFINED ${required_var} OR "${${required_var}}" STREQUAL "")
        message(FATAL_ERROR "TestStageAndInstall requires ${required_var}")
    endif()
endforeach()

set(slug "fixture")
set(build_dir "${EHL_TEST_ROOT}/build")
set(output_root "${EHL_TEST_ROOT}/artifacts")
set(vst3_dir "${EHL_TEST_ROOT}/Library/Audio/Plug-Ins/VST3")
set(au_dir "${EHL_TEST_ROOT}/Library/Audio/Plug-Ins/Components")

file(REMOVE_RECURSE "${EHL_TEST_ROOT}")
file(MAKE_DIRECTORY
    "${build_dir}/${slug}_standalone_plugin.app/Contents"
    "${build_dir}/${slug}_vst3_plugin.vst3/Contents"
    "${build_dir}/${slug}_au_plugin.component/Contents"
    "${vst3_dir}/${slug}_vst3_plugin.vst3"
    "${au_dir}/${slug}_au_plugin.component")
file(WRITE "${build_dir}/${slug}_standalone_plugin.app/Contents/marker" "standalone")
file(WRITE "${build_dir}/${slug}_vst3_plugin.vst3/Contents/marker" "vst3")
file(WRITE "${build_dir}/${slug}_au_plugin.component/Contents/marker" "au")
file(WRITE "${vst3_dir}/${slug}_vst3_plugin.vst3/stale" "stale")
file(WRITE "${au_dir}/${slug}_au_plugin.component/stale" "stale")

execute_process(
    COMMAND "${CMAKE_COMMAND}"
        "-DEHL_BUILD_DIR=${build_dir}"
        "-DEHL_OUTPUT_ROOT=${output_root}"
        "-DEHL_PRODUCT=Fixture"
        "-DEHL_SLUG=${slug}"
        "-DEHL_PROFILE=plugin-release"
        "-DEHL_SYSTEM_NAME=Darwin"
        "-DEHL_SYSTEM_PROCESSOR=arm64"
        "-DEHL_CONFIG=Release"
        "-DEHL_EXPECT_AU=ON"
        "-DEHL_COPY_PLUGIN_AFTER_BUILD=ON"
        "-DEHL_USER_VST3_DIR=${vst3_dir}"
        "-DEHL_USER_AU_DIR=${au_dir}"
        -P "${EHL_STAGE_SCRIPT}"
    RESULT_VARIABLE stage_result
    OUTPUT_VARIABLE stage_output
    ERROR_VARIABLE stage_error)
if(NOT stage_result EQUAL 0)
    message(FATAL_ERROR "Stage/install fixture failed:\n${stage_output}\n${stage_error}")
endif()

set(stage_dir "${output_root}/plugin-release/macos-arm64")
foreach(expected_file
        "${stage_dir}/standalone/${slug}_standalone_plugin.app/Contents/marker"
        "${stage_dir}/vst3/${slug}_vst3_plugin.vst3/Contents/marker"
        "${stage_dir}/au/${slug}_au_plugin.component/Contents/marker"
        "${vst3_dir}/${slug}_vst3_plugin.vst3/Contents/marker"
        "${au_dir}/${slug}_au_plugin.component/Contents/marker")
    if(NOT EXISTS "${expected_file}")
        message(FATAL_ERROR "Expected copied fixture file: ${expected_file}")
    endif()
endforeach()
foreach(stale_file
        "${vst3_dir}/${slug}_vst3_plugin.vst3/stale"
        "${au_dir}/${slug}_au_plugin.component/stale")
    if(EXISTS "${stale_file}")
        message(FATAL_ERROR "Exact bundle replacement left stale content: ${stale_file}")
    endif()
endforeach()

file(READ "${stage_dir}/ARTIFACTS.txt" manifest)
foreach(expected_line
        "installed_vst3=${vst3_dir}/${slug}_vst3_plugin.vst3"
        "installed_au=${au_dir}/${slug}_au_plugin.component")
    string(FIND "${manifest}" "${expected_line}" line_index)
    if(line_index EQUAL -1)
        message(FATAL_ERROR "Manifest is missing: ${expected_line}")
    endif()
endforeach()

set(disabled_output "${EHL_TEST_ROOT}/artifacts-disabled")
set(disabled_vst3_dir "${EHL_TEST_ROOT}/disabled/VST3")
set(disabled_au_dir "${EHL_TEST_ROOT}/disabled/Components")
execute_process(
    COMMAND "${CMAKE_COMMAND}"
        "-DEHL_BUILD_DIR=${build_dir}"
        "-DEHL_OUTPUT_ROOT=${disabled_output}"
        "-DEHL_PRODUCT=Fixture"
        "-DEHL_SLUG=${slug}"
        "-DEHL_PROFILE=plugin-release"
        "-DEHL_SYSTEM_NAME=Darwin"
        "-DEHL_SYSTEM_PROCESSOR=arm64"
        "-DEHL_CONFIG=Release"
        "-DEHL_EXPECT_AU=ON"
        "-DEHL_COPY_PLUGIN_AFTER_BUILD=OFF"
        "-DEHL_USER_VST3_DIR=${disabled_vst3_dir}"
        "-DEHL_USER_AU_DIR=${disabled_au_dir}"
        -P "${EHL_STAGE_SCRIPT}"
    RESULT_VARIABLE disabled_result
    OUTPUT_VARIABLE disabled_output_text
    ERROR_VARIABLE disabled_error)
if(NOT disabled_result EQUAL 0)
    message(FATAL_ERROR "Disabled install fixture failed:\n${disabled_output_text}\n${disabled_error}")
endif()
if(EXISTS "${EHL_TEST_ROOT}/disabled")
    message(FATAL_ERROR "EHL_COPY_PLUGIN_AFTER_BUILD=OFF created an install destination")
endif()

file(REMOVE_RECURSE "${EHL_TEST_ROOT}")
message(STATUS "Stage and local plugin copy contract passed")
