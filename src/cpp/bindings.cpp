#include <pybind11/pybind11.h>

#include "token_bucket.hpp"

namespace py = pybind11;

// VERSION_INFO приходит из CMake как -DVERSION_INFO=0.1.0 (без кавычек).
// Превращаем токен 0.1.0 в строку "0.1.0" в два шага:
#define STRINGIFY(x) #x
#define MACRO_STRINGIFY(x) STRINGIFY(x)

PYBIND11_MODULE(_core, m) {
    m.doc() = "fastbucket C++ core: token bucket rate limiter";

#ifdef VERSION_INFO
    m.attr("__version__") = MACRO_STRINGIFY(VERSION_INFO);
#else
    m.attr("__version__") = "dev";
#endif
}