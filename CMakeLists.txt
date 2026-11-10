cmake_minimum_required(VERSION 3.15...3.30)

# Имя и версию берём из pyproject.toml, их передаёт scikit-build-core.
# При прямом запуске CMake (CLion) их нет — ставим значения по умолчанию.
if(NOT DEFINED SKBUILD_PROJECT_NAME)
  set(SKBUILD_PROJECT_NAME fastbucket)
endif()
if(NOT DEFINED SKBUILD_PROJECT_VERSION)
  set(SKBUILD_PROJECT_VERSION 0.0.0)
endif()
project(${SKBUILD_PROJECT_NAME} VERSION ${SKBUILD_PROJECT_VERSION} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Сначала Python, потом pybind11 в режиме FindPython
set(PYBIND11_FINDPYTHON ON)
find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
# Вне scikit-build pybind11 не в путях CMake — спрашиваем у самого Python
if(NOT DEFINED pybind11_DIR OR NOT pybind11_DIR)
  execute_process(
    COMMAND "${Python_EXECUTABLE}" -m pybind11 --cmakedir
    OUTPUT_VARIABLE pybind11_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET)
endif()
find_package(pybind11 CONFIG REQUIRED)

# Цель _core -> файл _core.cpython-312-x86_64-linux-gnu.so
pybind11_add_module(_core MODULE src/cpp/bindings.cpp)
target_include_directories(_core PRIVATE src/cpp)
target_compile_definitions(_core PRIVATE VERSION_INFO=${PROJECT_VERSION})

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Кладём .so внутрь пакета fastbucket/ в колесе
install(TARGETS _core LIBRARY DESTINATION ${SKBUILD_PROJECT_NAME})