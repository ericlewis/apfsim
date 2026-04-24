#pragma once

#include "sim_time.hpp"

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace apfsim {

enum class Button {
    Up, Down, Left, Right,
    A, B, X, Y,
    L1, R1, L2, R2,
    Select, Start
};

inline Button parse_button(const std::string& raw) {
    std::string s = raw;
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (s == "up") return Button::Up;
    if (s == "down") return Button::Down;
    if (s == "left") return Button::Left;
    if (s == "right") return Button::Right;
    if (s == "a") return Button::A;
    if (s == "b") return Button::B;
    if (s == "x") return Button::X;
    if (s == "y") return Button::Y;
    if (s == "l1" || s == "l") return Button::L1;
    if (s == "r1" || s == "r") return Button::R1;
    if (s == "l2") return Button::L2;
    if (s == "r2") return Button::R2;
    if (s == "select" || s == "coin") return Button::Select;
    if (s == "start") return Button::Start;
    throw std::runtime_error("unknown button " + raw);
}

inline uint32_t button_mask(Button b) {
    switch (b) {
        case Button::Up: return 1u << 0;
        case Button::Down: return 1u << 1;
        case Button::Left: return 1u << 2;
        case Button::Right: return 1u << 3;
        case Button::A: return 1u << 4;
        case Button::B: return 1u << 5;
        case Button::X: return 1u << 6;
        case Button::Y: return 1u << 7;
        case Button::L1: return 1u << 8;
        case Button::R1: return 1u << 9;
        case Button::L2: return 1u << 10;
        case Button::R2: return 1u << 11;
        case Button::Select: return 1u << 12;
        case Button::Start: return 1u << 13;
    }
    return 0;
}

struct InputEvent {
    uint64_t frame = 0;
    int player = 1;
    Button button = Button::A;
    uint64_t hold_frames = 1;
};

class InputDriver {
public:
    void add_event(InputEvent event) { events_.push_back(event); }
    bool has_events() const { return !events_.empty(); }
    bool ever_active() const { return ever_active_; }

    void set_controller_type(int player, uint8_t type) {
        if (player < 1 || player > 4) return;
        controller_type_[player - 1] = type;
    }

    void on_frame(uint64_t frame) {
        current_frame_ = frame;
        recompute();
    }

    template <typename Top>
    void drive(Top* top) const {
        top->cont1_key = keys_[0] | (static_cast<uint32_t>(controller_type_[0]) << 24);
        top->cont2_key = keys_[1] | (static_cast<uint32_t>(controller_type_[1]) << 24);
        top->cont3_key = keys_[2] | (static_cast<uint32_t>(controller_type_[2]) << 24);
        top->cont4_key = keys_[3] | (static_cast<uint32_t>(controller_type_[3]) << 24);
        top->cont1_joy = joy_[0];
        top->cont2_joy = joy_[1];
        top->cont3_joy = joy_[2];
        top->cont4_joy = joy_[3];
        top->cont1_trig = trig_[0];
        top->cont2_trig = trig_[1];
        top->cont3_trig = trig_[2];
        top->cont4_trig = trig_[3];
    }

private:
    void recompute() {
        keys_[0] = keys_[1] = keys_[2] = keys_[3] = 0;
        for (const auto& event : events_) {
            if (event.player < 1 || event.player > 4) continue;
            if (current_frame_ >= event.frame && current_frame_ < event.frame + event.hold_frames) {
                keys_[event.player - 1] |= button_mask(event.button);
                ever_active_ = true;
            }
        }
    }

    std::vector<InputEvent> events_;
    uint64_t current_frame_ = 0;
    uint32_t keys_[4] = {0, 0, 0, 0};
    uint32_t joy_[4] = {0x80808080u, 0x80808080u, 0x80808080u, 0x80808080u};
    uint32_t trig_[4] = {0, 0, 0, 0};
    uint8_t controller_type_[4] = {1, 1, 1, 1};
    bool ever_active_ = false;
};

} // namespace apfsim
