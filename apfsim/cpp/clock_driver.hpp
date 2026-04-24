#pragma once

#include <cstdint>

namespace apfsim {

struct Clock {
    uint64_t half_period_ps = 1;
    uint64_t next_toggle_ps = 0;
    bool value = false;

    bool tick(uint64_t now_ps) {
        if (now_ps < next_toggle_ps) return false;
        value = !value;
        next_toggle_ps += half_period_ps;
        return true;
    }
};

inline uint64_t half_period_from_hz(uint64_t hz) {
    return hz == 0 ? 1 : (500000000000ULL / hz);
}

} // namespace apfsim
