#include <optional>
#include <string>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "token_bucket.hpp"

namespace py = pybind11;
using fastbucket::Decision;
using fastbucket::Limiter;

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

    py::class_<Decision>(m, "Decision")
        .def_readonly("allowed", &Decision::allowed)
        .def_readonly("remaining", &Decision::remaining)
        .def_readonly("retry_after", &Decision::retry_after)
        .def("__repr__", [](const Decision& d) {
            return py::str("Decision(allowed={}, remaining={}, retry_after={})")
                .format(d.allowed, d.remaining, d.retry_after);
        });

    py::class_<Limiter>(m, "Limiter")
        .def(py::init<double, double>(), py::arg("capacity"), py::arg("rate"))
        .def("consume",
            [](Limiter& self, const std::string& key, double cost, std::optional<double> now) {
                 return now ? self.consume(key, cost, *now) : self.consume(key, cost);
            },
            py::arg("key"), py::arg("cost") = 1.0, py::kw_only(), py::arg("now") = py::none())
        .def("allow",
            [](Limiter& self, const std::string& key, double cost, std::optional<double> now) {
                return now ? self.consume(key, cost, *now).allowed : self.consume(key, cost).allowed;
            },
            py::arg("key"), py::arg("cost") = 1.0, py::kw_only(), py::arg("now") = py::none())
        .def("peek",
            [](const Limiter& self, const std::string& key, std::optional<double> now) {
                return now ? self.peek(key, *now) : self.peek(key);
            },
            py::arg("key"), py::kw_only(), py::arg("now") = py::none())
        .def("purge",
            [](Limiter& self, double idle, std::optional<double> now) {
                return now ? self.purge(idle, *now) : self.purge(idle);
            },
            py::arg("idle"), py::kw_only(), py::arg("now") = py::none())
        .def("reset", &Limiter::reset, py::arg("key"))
        .def_property_readonly("capacity", &Limiter::capacity)
        .def_property_readonly("rate", &Limiter::rate)
        .def("__len__", &Limiter::size)
        .def("__repr__", [](const Limiter& l) {
            return py::str("Limiter(capacity={}, rate={}, size={})")
                .format(l.capacity(), l.rate(), l.size());
        });
}
