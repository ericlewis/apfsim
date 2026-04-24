#pragma once

#include "data_slots.hpp"
#include "input_driver.hpp"
#include "interact_model.hpp"
#include "sim_time.hpp"

#include <filesystem>
#include <string>
#include <vector>

namespace apfsim {

struct Scenario {
    std::string name = "apfsim";
    std::vector<DataSlot> slots;
    std::vector<InputEvent> inputs;
    InteractModel interact;
    uint64_t frames = 3;
    uint64_t timeout_cycles = 50000000;
    size_t expected_width = 0;
    size_t expected_height = 0;
};

inline int leading_spaces(const std::string& line) {
    int n = 0;
    while (n < static_cast<int>(line.size()) && line[n] == ' ') ++n;
    return n;
}

inline Scenario parse_scenario(const std::filesystem::path& path) {
    Scenario scenario;
    if (path.empty()) return scenario;
    std::ifstream in(path);
    if (!in) throw std::runtime_error("failed to open scenario " + path.string());

    enum class Section { None, DataSlots, Inputs, InteractWrites, Run, ExpectVideo, ExpectAudio };
    Section section = Section::None;
    DataSlot* current_slot = nullptr;
    InputEvent* current_input = nullptr;
    bool in_interact = false;
    bool in_expect = false;
    uint32_t pending_interact_address = 0;

    std::string line;
    while (std::getline(in, line)) {
        const auto no_comment = strip_comment(line);
        const auto trimmed = trim(no_comment);
        if (trimmed.empty()) continue;
        const int indent = leading_spaces(no_comment);

        if (indent == 0) {
            in_interact = false;
            in_expect = false;
            current_slot = nullptr;
            current_input = nullptr;
            if (trimmed == "data_slots:") { section = Section::DataSlots; continue; }
            if (trimmed == "inputs:") { section = Section::Inputs; continue; }
            if (trimmed == "interact:") { section = Section::None; in_interact = true; continue; }
            if (trimmed == "run:") { section = Section::Run; continue; }
            if (trimmed == "expect:") { section = Section::None; in_expect = true; continue; }
            if (auto kv = parse_key_value(trimmed)) {
                if (kv->first == "name") scenario.name = unquote(kv->second);
            }
            continue;
        }

        if (in_interact && trimmed == "writes:") { section = Section::InteractWrites; continue; }
        if (in_expect && trimmed == "video:") { section = Section::ExpectVideo; continue; }

        if (section == Section::DataSlots && trimmed.rfind("-", 0) == 0) {
            scenario.slots.push_back({});
            current_slot = &scenario.slots.back();
        } else if (section == Section::Inputs && trimmed.rfind("-", 0) == 0) {
            scenario.inputs.push_back({});
            current_input = &scenario.inputs.back();
        }

        const auto kv = parse_key_value(trimmed);
        if (!kv) continue;
        const auto& key = kv->first;
        const auto& value = kv->second;

        if (section == Section::DataSlots && current_slot) {
            if (key == "id") current_slot->id = static_cast<uint16_t>(parse_u64(value));
            else if (key == "name") current_slot->name = unquote(value);
            else if (key == "file") current_slot->file = unquote(value);
            else if (key == "address") current_slot->address = static_cast<uint32_t>(parse_u64(value));
            else if (key == "required") current_slot->required = parse_bool(value);
            else if (key == "nonvolatile") current_slot->nonvolatile = parse_bool(value);
            else if (key == "deferload") current_slot->deferload = parse_bool(value);
            else if (key == "size_exact") current_slot->size_exact = static_cast<size_t>(parse_u64(value));
            else if (key == "size_maximum") current_slot->size_maximum = static_cast<size_t>(parse_u64(value));
        } else if (section == Section::Inputs && current_input) {
            if (key == "frame") current_input->frame = parse_u64(value);
            else if (key == "player") current_input->player = static_cast<int>(parse_u64(value));
            else if (key == "button" || key == "press") current_input->button = parse_button(unquote(value));
            else if (key == "hold_frames" || key == "frames") current_input->hold_frames = parse_u64(value);
        } else if (section == Section::InteractWrites) {
            // Small YAML subset: address and value may be supplied on following lines.
            // The current InteractModel stores writes internally, so line-oriented edits are appended below.
            if (key == "address") pending_interact_address = static_cast<uint32_t>(parse_u64(value));
            else if (key == "value") {
                scenario.interact.add_write(pending_interact_address, static_cast<uint32_t>(parse_u64(value)), true);
                pending_interact_address = 0;
            }
        } else if (section == Section::Run) {
            if (key == "until_frames" || key == "frames") scenario.frames = parse_u64(value);
            else if (key == "timeout_cycles") scenario.timeout_cycles = parse_u64(value);
        } else if (section == Section::ExpectVideo) {
            if (key == "active_width" || key == "width") scenario.expected_width = static_cast<size_t>(parse_u64(value));
            else if (key == "active_height" || key == "height") scenario.expected_height = static_cast<size_t>(parse_u64(value));
        }
    }

    return scenario;
}

} // namespace apfsim
