#pragma once

#include "data_slots.hpp"
#include "input_driver.hpp"
#include "interact_model.hpp"
#include "sim_time.hpp"

#include <filesystem>
#include <string>
#include <vector>

namespace apfsim {

struct VideoExpect {
    size_t active_width = 0;
    size_t active_height = 0;
    uint64_t min_frames = 0;
    uint64_t max_errors = 0;
    bool require_rgb_zero_when_de_low = true;
    bool require_single_cycle_sync = true;
    bool require_skip_only_during_de = true;
    uint64_t min_hs_after_vs_cycles = 0;
    uint64_t min_hs_to_de_gap_cycles = 0;
    uint64_t min_de_to_hs_gap_cycles = 0;
    double pixel_clock_hz = 0.0;
    double min_refresh_hz = 0.0;
    double max_refresh_hz = 0.0;
    uint64_t min_unique_colors = 0;
    uint64_t min_nonzero_pixels = 0;
    uint64_t min_changed_pixels = 0;
};

struct AudioExpect {
    size_t min_samples = 1;
    bool require_changing = false;
    int min_peak_to_peak = 0;
    size_t max_clipped_samples = 0;
    double max_abs_dc_offset = 0.0;
};

struct DataExpect {
    bool require_required_slots = true;
    bool require_all_file_slots_loaded = true;
    uint64_t expected_total_loaded_bytes = 0;
};

struct ResetExpect {
    bool require_reset_enter = true;
    bool require_reset_exit = true;
    bool require_ready_to_run = true;
    uint64_t max_setup_cycles = 0;
    uint64_t max_boot_cycles = 0;
    uint64_t min_reset_hold_cycles = 0;
    uint64_t max_reset_hold_cycles = 0;
    uint64_t max_reset_exit_to_running_cycles = 0;
};

struct SaveExpect {
    bool require_nonvolatile_unload = false;
    bool require_roundtrip_match = false;
};

struct InputExpect {
    bool require_scripted_activity = true;
};

struct InteractExpect {
    size_t min_persistent_writes = 0;
};

struct BridgeReadbackExpect {
    std::string name;
    uint32_t address = 0;
    uint32_t value = 0;
    uint32_t mask = 0xFFFFFFFFu;
};

struct Scenario {
    std::string name = "apfsim";
    std::vector<DataSlot> slots;
    std::vector<InputEvent> inputs;
    InteractModel interact;
    uint64_t frames = 3;
    uint64_t timeout_cycles = 50000000;
    size_t expected_width = 0;
    size_t expected_height = 0;
    VideoExpect video_expect;
    AudioExpect audio_expect;
    DataExpect data_expect;
    ResetExpect reset_expect;
    SaveExpect save_expect;
    InputExpect input_expect;
    InteractExpect interact_expect;
    std::vector<BridgeReadbackExpect> readbacks;
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

    enum class Section {
        None,
        DataSlots,
        Inputs,
        InteractWrites,
        Run,
        ExpectVideo,
        ExpectAudio,
        ExpectData,
        ExpectReset,
        ExpectSave,
        ExpectInput,
        ExpectInteract,
        ExpectBridge,
        ExpectBridgeReadbacks
    };
    Section section = Section::None;
    DataSlot* current_slot = nullptr;
    InputEvent* current_input = nullptr;
    BridgeReadbackExpect* current_readback = nullptr;
    bool in_interact = false;
    bool in_expect = false;
    bool in_expect_bridge = false;
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
            in_expect_bridge = false;
            current_slot = nullptr;
            current_input = nullptr;
            current_readback = nullptr;
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
        if (in_expect && indent == 2) {
            in_expect_bridge = false;
            current_readback = nullptr;
            if (trimmed == "video:") { section = Section::ExpectVideo; continue; }
            if (trimmed == "audio:") { section = Section::ExpectAudio; continue; }
            if (trimmed == "data:") { section = Section::ExpectData; continue; }
            if (trimmed == "reset:" || trimmed == "boot:") { section = Section::ExpectReset; continue; }
            if (trimmed == "save:" || trimmed == "saves:") { section = Section::ExpectSave; continue; }
            if (trimmed == "input:" || trimmed == "inputs:") { section = Section::ExpectInput; continue; }
            if (trimmed == "interact:") { section = Section::ExpectInteract; continue; }
            if (trimmed == "bridge:") { section = Section::ExpectBridge; in_expect_bridge = true; continue; }
        }
        if (in_expect_bridge && trimmed == "readbacks:") { section = Section::ExpectBridgeReadbacks; continue; }

        if (section == Section::DataSlots && trimmed.rfind("-", 0) == 0) {
            scenario.slots.push_back({});
            current_slot = &scenario.slots.back();
        } else if (section == Section::Inputs && trimmed.rfind("-", 0) == 0) {
            scenario.inputs.push_back({});
            current_input = &scenario.inputs.back();
        } else if (section == Section::ExpectBridgeReadbacks && trimmed.rfind("-", 0) == 0) {
            scenario.readbacks.push_back({});
            current_readback = &scenario.readbacks.back();
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
            else if (key == "expected_checksum" || key == "checksum" || key == "fnv1a64") {
                current_slot->expected_checksum = parse_u64(value);
                current_slot->has_expected_checksum = true;
            }
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
            if (key == "active_width" || key == "width") {
                scenario.expected_width = static_cast<size_t>(parse_u64(value));
                scenario.video_expect.active_width = scenario.expected_width;
            } else if (key == "active_height" || key == "height") {
                scenario.expected_height = static_cast<size_t>(parse_u64(value));
                scenario.video_expect.active_height = scenario.expected_height;
            } else if (key == "min_frames") scenario.video_expect.min_frames = parse_u64(value);
            else if (key == "max_errors") scenario.video_expect.max_errors = parse_u64(value);
            else if (key == "rgb_zero_when_de_low" || key == "require_rgb_zero_when_de_low") scenario.video_expect.require_rgb_zero_when_de_low = parse_bool(value);
            else if (key == "single_cycle_sync" || key == "require_single_cycle_sync") scenario.video_expect.require_single_cycle_sync = parse_bool(value);
            else if (key == "skip_only_during_de" || key == "require_skip_only_during_de") scenario.video_expect.require_skip_only_during_de = parse_bool(value);
            else if (key == "min_hs_after_vs_cycles") scenario.video_expect.min_hs_after_vs_cycles = parse_u64(value);
            else if (key == "min_hs_to_de_gap_cycles") scenario.video_expect.min_hs_to_de_gap_cycles = parse_u64(value);
            else if (key == "min_de_to_hs_gap_cycles") scenario.video_expect.min_de_to_hs_gap_cycles = parse_u64(value);
            else if (key == "pixel_clock_hz") scenario.video_expect.pixel_clock_hz = parse_double(value);
            else if (key == "min_refresh_hz") scenario.video_expect.min_refresh_hz = parse_double(value);
            else if (key == "max_refresh_hz") scenario.video_expect.max_refresh_hz = parse_double(value);
            else if (key == "min_unique_colors") scenario.video_expect.min_unique_colors = parse_u64(value);
            else if (key == "min_nonzero_pixels") scenario.video_expect.min_nonzero_pixels = parse_u64(value);
            else if (key == "min_changed_pixels") scenario.video_expect.min_changed_pixels = parse_u64(value);
        } else if (section == Section::ExpectAudio) {
            if (key == "min_samples") scenario.audio_expect.min_samples = static_cast<size_t>(parse_u64(value));
            else if (key == "require_changing") scenario.audio_expect.require_changing = parse_bool(value);
            else if (key == "min_peak_to_peak") scenario.audio_expect.min_peak_to_peak = static_cast<int>(parse_u64(value));
            else if (key == "max_clipped_samples") scenario.audio_expect.max_clipped_samples = static_cast<size_t>(parse_u64(value));
            else if (key == "max_abs_dc_offset") scenario.audio_expect.max_abs_dc_offset = parse_double(value);
        } else if (section == Section::ExpectData) {
            if (key == "require_required_slots") scenario.data_expect.require_required_slots = parse_bool(value);
            else if (key == "require_all_file_slots_loaded") scenario.data_expect.require_all_file_slots_loaded = parse_bool(value);
            else if (key == "expected_total_loaded_bytes") scenario.data_expect.expected_total_loaded_bytes = parse_u64(value);
        } else if (section == Section::ExpectReset) {
            if (key == "require_reset_enter") scenario.reset_expect.require_reset_enter = parse_bool(value);
            else if (key == "require_reset_exit") scenario.reset_expect.require_reset_exit = parse_bool(value);
            else if (key == "require_ready_to_run") scenario.reset_expect.require_ready_to_run = parse_bool(value);
            else if (key == "max_setup_cycles") scenario.reset_expect.max_setup_cycles = parse_u64(value);
            else if (key == "max_boot_cycles") scenario.reset_expect.max_boot_cycles = parse_u64(value);
            else if (key == "min_reset_hold_cycles" || key == "min_reset_enter_to_exit_cycles") scenario.reset_expect.min_reset_hold_cycles = parse_u64(value);
            else if (key == "max_reset_hold_cycles" || key == "max_reset_enter_to_exit_cycles") scenario.reset_expect.max_reset_hold_cycles = parse_u64(value);
            else if (key == "max_reset_exit_to_running_cycles") scenario.reset_expect.max_reset_exit_to_running_cycles = parse_u64(value);
        } else if (section == Section::ExpectSave) {
            if (key == "require_nonvolatile_unload") scenario.save_expect.require_nonvolatile_unload = parse_bool(value);
            else if (key == "require_roundtrip_match" || key == "roundtrip") scenario.save_expect.require_roundtrip_match = parse_bool(value);
        } else if (section == Section::ExpectInput) {
            if (key == "require_scripted_activity") scenario.input_expect.require_scripted_activity = parse_bool(value);
        } else if (section == Section::ExpectInteract) {
            if (key == "min_persistent_writes") scenario.interact_expect.min_persistent_writes = static_cast<size_t>(parse_u64(value));
        } else if (section == Section::ExpectBridgeReadbacks && current_readback) {
            if (key == "name") current_readback->name = unquote(value);
            else if (key == "address") current_readback->address = static_cast<uint32_t>(parse_u64(value));
            else if (key == "value" || key == "expected") current_readback->value = static_cast<uint32_t>(parse_u64(value));
            else if (key == "mask") current_readback->mask = static_cast<uint32_t>(parse_u64(value));
        }
    }

    return scenario;
}

} // namespace apfsim
