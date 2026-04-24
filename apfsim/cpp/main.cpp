#include "Vcore_top.h"

#include "assertions.hpp"
#include "audio_capture.hpp"
#include "bridge_host.hpp"
#include "data_slots.hpp"
#include "input_driver.hpp"
#include "interact_model.hpp"
#include "scenario_runner.hpp"
#include "sim_time.hpp"
#include "video_capture.hpp"

#include <verilated.h>
#if VM_TRACE
#include <verilated_fst_c.h>
#endif
#if APFSIM_ENABLE_SDL
#define SDL_MAIN_HANDLED
#include <SDL.h>
#endif

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;
using namespace apfsim;

struct CliOptions {
    fs::path scenario_path;
    fs::path data_json;
    fs::path video_json;
    fs::path interact_json;
    fs::path dump_frames;
    fs::path dump_audio;
    fs::path audio_stats;
    fs::path dump_saves;
    fs::path dump_savestates;
    fs::path result_json;
    fs::path bridge_log;
    fs::path bridge_summary;
    fs::path bridge_trace;
    fs::path video_shape_json;
    std::vector<std::pair<uint16_t, fs::path>> slot_overrides;
    uint64_t frames_override = 0;
    uint64_t timeout_cycles_override = 0;
    uint64_t write_idle_cycles = 0;
    uint64_t bridge_read_latency_cycles = UINT64_MAX;
    uint64_t bridge_write_strobe_cycles = 0;
    uint64_t target_service_interval_cycles = 0;
    std::string bridge_endian = "little";
    bool verbose_bridge = false;
    bool no_boot = false;
    bool interact_verify_readback = true;
    bool interactive = false;
    int play_scale = 3;
    int play_speed_percent = 100;
};

static void usage(const char* argv0) {
    std::cerr << "usage: " << argv0 << " [--scenario file.yml] [--frames n] [--slot id=file] "
              << "[--data data.json] [--video video.json] [--interact interact.json] "
              << "[--dump-frames dir] [--dump-audio out.wav] [--audio-stats stats.json] "
              << "[--dump-saves dir] [--result-json result.json] [--bridge-log bridge.log] "
              << "[--bridge-summary bridge_summary.json] [--bridge-trace bridge_transactions.jsonl] "
              << "[--video-shape-json video_shape.json] "
              << "[--bridge-read-latency-cycles n] [--bridge-write-strobe-cycles n] [--bridge-endian little|big] "
              << "[--target-service-interval-cycles n] [--dump-savestates dir] "
              << "[--interact-no-verify] [--interactive] [--play-scale n] [--play-speed-percent n]\n";
}

static CliOptions parse_args(int argc, char** argv) {
    CliOptions opt;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        auto need_value = [&](const char* name) -> std::string {
            if (i + 1 >= argc) throw std::runtime_error(std::string("missing value for ") + name);
            return argv[++i];
        };
        if (arg == "--scenario") opt.scenario_path = need_value("--scenario");
        else if (arg == "--data") opt.data_json = need_value("--data");
        else if (arg == "--video") opt.video_json = need_value("--video");
        else if (arg == "--interact") opt.interact_json = need_value("--interact");
        else if (arg == "--dump-frames") opt.dump_frames = need_value("--dump-frames");
        else if (arg == "--dump-audio") opt.dump_audio = need_value("--dump-audio");
        else if (arg == "--audio-stats") opt.audio_stats = need_value("--audio-stats");
        else if (arg == "--dump-saves") opt.dump_saves = need_value("--dump-saves");
        else if (arg == "--dump-savestates") opt.dump_savestates = need_value("--dump-savestates");
        else if (arg == "--result-json") opt.result_json = need_value("--result-json");
        else if (arg == "--bridge-log") opt.bridge_log = need_value("--bridge-log");
        else if (arg == "--bridge-summary") opt.bridge_summary = need_value("--bridge-summary");
        else if (arg == "--bridge-trace") opt.bridge_trace = need_value("--bridge-trace");
        else if (arg == "--video-shape-json") opt.video_shape_json = need_value("--video-shape-json");
        else if (arg == "--frames") opt.frames_override = parse_u64(need_value("--frames"));
        else if (arg == "--timeout-cycles") opt.timeout_cycles_override = parse_u64(need_value("--timeout-cycles"));
        else if (arg == "--write-idle-cycles") opt.write_idle_cycles = parse_u64(need_value("--write-idle-cycles"));
        else if (arg == "--bridge-read-latency-cycles") opt.bridge_read_latency_cycles = parse_u64(need_value("--bridge-read-latency-cycles"));
        else if (arg == "--bridge-write-strobe-cycles") opt.bridge_write_strobe_cycles = parse_u64(need_value("--bridge-write-strobe-cycles"));
        else if (arg == "--bridge-endian") opt.bridge_endian = need_value("--bridge-endian");
        else if (arg == "--target-service-interval-cycles") opt.target_service_interval_cycles = parse_u64(need_value("--target-service-interval-cycles"));
        else if (arg == "--slot") {
            const auto spec = need_value("--slot");
            const auto eq = spec.find('=');
            if (eq == std::string::npos) throw std::runtime_error("slot override must be id=file");
            opt.slot_overrides.emplace_back(static_cast<uint16_t>(parse_u64(spec.substr(0, eq))), spec.substr(eq + 1));
        } else if (arg == "--verbose-bridge") opt.verbose_bridge = true;
        else if (arg == "--no-boot") opt.no_boot = true;
        else if (arg == "--interact-no-verify") opt.interact_verify_readback = false;
        else if (arg == "--interactive") opt.interactive = true;
        else if (arg == "--play-scale") opt.play_scale = static_cast<int>(parse_u64(need_value("--play-scale")));
        else if (arg == "--play-speed-percent") opt.play_speed_percent = static_cast<int>(parse_u64(need_value("--play-speed-percent")));
        else if (arg == "--help" || arg == "-h") {
            usage(argv[0]);
            std::exit(0);
        } else {
            throw std::runtime_error("unknown argument " + arg);
        }
    }
    return opt;
}

static std::string json_escape(const std::string& text) {
    std::string out;
    out.reserve(text.size() + 8);
    for (char c : text) {
        switch (c) {
            case '\\': out += "\\\\"; break;
            case '"': out += "\\\""; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default: out += c; break;
        }
    }
    return out;
}

static void write_failure_result(const fs::path& path, const std::string& phase, const std::string& message) {
    if (path.empty()) return;
    if (!path.parent_path().empty()) fs::create_directories(path.parent_path());
    std::ofstream out(path);
    if (!out) return;
    out << "{\n";
    out << "  \"ok\": false,\n";
    out << "  \"status\": \"failed\",\n";
    out << "  \"artifact_dir\": \"" << json_escape(path.parent_path().string()) << "\",\n";
    out << "  \"failed_phase\": \"" << json_escape(phase) << "\",\n";
    out << "  \"message\": \"" << json_escape(message) << "\",\n";
    out << "  \"phases\": {\n";
    out << "    \"boot\": { \"ok\": false },\n";
    out << "    \"reset\": { \"ok\": false },\n";
    out << "    \"data\": { \"ok\": false },\n";
    out << "    \"video\": { \"ok\": false },\n";
    out << "    \"audio\": { \"ok\": false },\n";
    out << "    \"interact\": { \"ok\": false },\n";
    out << "    \"input\": { \"ok\": false },\n";
    out << "    \"save\": { \"ok\": false }\n";
    out << "  }\n";
    out << "}\n";
}

struct ReadbackObservation {
    BridgeReadbackExpect expect;
    uint32_t observed = 0;
    bool ok = false;
};

struct MemoryCounterObservation {
    std::string name;
    std::string class_name;
    uint64_t value = 0;
    bool error = false;
    std::string error_code;
};

struct MemoryActivitySnapshot {
    bool observed = false;
    std::vector<MemoryCounterObservation> counters;
};

template <typename Top>
static MemoryActivitySnapshot capture_memory_activity(Top* top) {
    MemoryActivitySnapshot snapshot;
    (void)top;
#if APFSIM_MEMORY_COUNTER_SRAM
    snapshot.observed = true;
    snapshot.counters.push_back({"sram_read_count", "sram", static_cast<uint64_t>(top->apfsim_sram_read_count), false, ""});
    snapshot.counters.push_back({"sram_write_count", "sram", static_cast<uint64_t>(top->apfsim_sram_write_count), false, ""});
    snapshot.counters.push_back({"sram_bus_contention_error", "sram", static_cast<uint64_t>(top->apfsim_sram_bus_contention_error), top->apfsim_sram_bus_contention_error != 0, "SRAM_BUS_CONTENTION"});
    snapshot.counters.push_back({"sram_byte_enable_error", "sram", static_cast<uint64_t>(top->apfsim_sram_byte_enable_error), top->apfsim_sram_byte_enable_error != 0, "MEMORY_BYTE_ENABLE_MISMATCH"});
#endif
#if APFSIM_MEMORY_COUNTER_PSRAM
    snapshot.observed = true;
    snapshot.counters.push_back({"psram_read_count", "psram", static_cast<uint64_t>(top->apfsim_psram_read_count), false, ""});
    snapshot.counters.push_back({"psram_write_count", "psram", static_cast<uint64_t>(top->apfsim_psram_write_count), false, ""});
    snapshot.counters.push_back({"psram_overrun_error", "psram", static_cast<uint64_t>(top->apfsim_psram_overrun_error), top->apfsim_psram_overrun_error != 0, "MEMORY_STALL_TIMEOUT"});
    snapshot.counters.push_back({"psram_byte_enable_error", "psram", static_cast<uint64_t>(top->apfsim_psram_byte_enable_error), top->apfsim_psram_byte_enable_error != 0, "MEMORY_BYTE_ENABLE_MISMATCH"});
#endif
#if APFSIM_MEMORY_COUNTER_CRAM
    snapshot.observed = true;
    snapshot.counters.push_back({"cram_read_count", "cram", static_cast<uint64_t>(top->apfsim_cram_read_count), false, ""});
    snapshot.counters.push_back({"cram_write_count", "cram", static_cast<uint64_t>(top->apfsim_cram_write_count), false, ""});
    snapshot.counters.push_back({"cram_overrun_error", "cram", static_cast<uint64_t>(top->apfsim_cram_overrun_error), top->apfsim_cram_overrun_error != 0, "MEMORY_STALL_TIMEOUT"});
    snapshot.counters.push_back({"cram_byte_enable_error", "cram", static_cast<uint64_t>(top->apfsim_cram_byte_enable_error), top->apfsim_cram_byte_enable_error != 0, "MEMORY_BYTE_ENABLE_MISMATCH"});
#endif
#if APFSIM_MEMORY_COUNTER_SDRAM
    snapshot.observed = true;
    snapshot.counters.push_back({"sdram_read_count", "sdram", static_cast<uint64_t>(top->apfsim_sdram_read_count), false, ""});
    snapshot.counters.push_back({"sdram_write_count", "sdram", static_cast<uint64_t>(top->apfsim_sdram_write_count), false, ""});
    snapshot.counters.push_back({"sdram_activate_count", "sdram", static_cast<uint64_t>(top->apfsim_sdram_activate_count), false, ""});
    snapshot.counters.push_back({"sdram_refresh_count", "sdram", static_cast<uint64_t>(top->apfsim_sdram_refresh_count), false, ""});
    snapshot.counters.push_back({"sdram_rom_preload_count", "sdram", static_cast<uint64_t>(top->apfsim_sdram_rom_preload_count), false, ""});
    snapshot.counters.push_back({"sdram_rom_coverage_gap_count", "sdram", static_cast<uint64_t>(top->apfsim_sdram_rom_coverage_gap_count), false, ""});
    snapshot.counters.push_back({"sdram_rom_mismatch_count", "sdram", static_cast<uint64_t>(top->apfsim_sdram_rom_mismatch_count), top->apfsim_sdram_rom_mismatch_count != 0, "MEMORY_ROM_WRITE_MISMATCH"});
    snapshot.counters.push_back({"sdram_rom_unwritten_read_count", "sdram", static_cast<uint64_t>(top->apfsim_sdram_rom_unwritten_read_count), top->apfsim_sdram_rom_unwritten_read_count != 0, "MEMORY_UNINITIALIZED_READ"});
    snapshot.counters.push_back({"sdram_first_coverage_gap_addr", "sdram", static_cast<uint64_t>(top->apfsim_sdram_first_coverage_gap_addr), false, ""});
    snapshot.counters.push_back({"sdram_first_rom_mismatch_addr", "sdram", static_cast<uint64_t>(top->apfsim_sdram_first_rom_mismatch_addr), false, ""});
    snapshot.counters.push_back({"sdram_first_rom_unwritten_read_addr", "sdram", static_cast<uint64_t>(top->apfsim_sdram_first_rom_unwritten_read_addr), false, ""});
    snapshot.counters.push_back({"sdram_command_error", "sdram", static_cast<uint64_t>(top->apfsim_sdram_command_error), top->apfsim_sdram_command_error != 0, "SDRAM_COMMAND_ERROR"});
    snapshot.counters.push_back({"sdram_bus_contention_error", "sdram", static_cast<uint64_t>(top->apfsim_sdram_bus_contention_error), top->apfsim_sdram_bus_contention_error != 0, "MEMORY_BUS_CONTENTION"});
    snapshot.counters.push_back({"sdram_byte_enable_error", "sdram", static_cast<uint64_t>(top->apfsim_sdram_byte_enable_error), top->apfsim_sdram_byte_enable_error != 0, "MEMORY_BYTE_ENABLE_MISMATCH"});
    snapshot.counters.push_back({"sdram_rom_mismatch_error", "sdram", static_cast<uint64_t>(top->apfsim_sdram_rom_mismatch_error), false, ""});
    snapshot.counters.push_back({"sdram_uninitialized_read_error", "sdram", static_cast<uint64_t>(top->apfsim_sdram_uninitialized_read_error), false, ""});
#endif
    return snapshot;
}

static void write_memory_activity_object(std::ostream& out, const MemoryActivitySnapshot& memory, int indent) {
    const std::string pad(static_cast<size_t>(indent), ' ');
    out << pad << "{\n";
    out << pad << "  \"schema\": \"apfsim.memory_activity.runtime.v1\",\n";
    out << pad << "  \"observed\": " << (memory.observed ? "true" : "false") << ",\n";
    out << pad << "  \"counter_status\": \"" << (memory.observed ? "observed" : "none") << "\",\n";
    out << pad << "  \"counters\": [\n";
    for (size_t i = 0; i < memory.counters.size(); ++i) {
        const auto& counter = memory.counters[i];
        out << pad << "    { \"name\": \"" << json_escape(counter.name)
            << "\", \"class\": \"" << json_escape(counter.class_name)
            << "\", \"value\": " << counter.value
            << ", \"error\": " << (counter.error ? "true" : "false");
        if (!counter.error_code.empty()) out << ", \"error_code\": \"" << json_escape(counter.error_code) << "\"";
        out << " }";
        out << (i + 1 == memory.counters.size() ? "\n" : ",\n");
    }
    out << pad << "  ],\n";
    out << pad << "  \"errors\": [\n";
    bool wrote_error = false;
    for (const auto& counter : memory.counters) {
        if (!counter.error) continue;
        if (wrote_error) out << ",\n";
        out << pad << "    { \"code\": \"" << json_escape(counter.error_code)
            << "\", \"severity\": \"error\", \"counter\": \"" << json_escape(counter.name)
            << "\", \"class\": \"" << json_escape(counter.class_name)
            << "\", \"value\": " << counter.value
            << ", \"observed\": true }";
        wrote_error = true;
    }
    if (wrote_error) out << "\n";
    out << pad << "  ]\n";
    out << pad << "}";
}

static std::string format_failure_summary(const Assertions& asserts) {
    std::ostringstream ss;
    const auto& failures = asserts.failures();
    for (size_t i = 0; i < failures.size(); ++i) {
        if (i) ss << "; ";
        ss << failures[i];
    }
    return ss.str();
}

static bool phase_has_no_failure(const std::vector<std::string>& failures, const std::string& prefix) {
    for (const auto& failure : failures) {
        if (failure.rfind(prefix, 0) == 0) return false;
    }
    return true;
}

static void write_video_shape_object(std::ostream& out, const Scenario& scenario, const VideoCapture& video, int indent) {
    const auto& meta = video.last_metadata();
    const auto agg = video.aggregate_after_startup_frames(scenario.video_expect.ignore_startup_frames);
    const size_t active_width = agg.frames ? agg.active_width_max : meta.active_width;
    const size_t active_height = agg.frames ? agg.active_height_max : meta.active_height;
    const uint64_t total_width_min = agg.frames ? agg.total_width_min : meta.pixels_per_line_min;
    const uint64_t total_width_max = agg.frames ? agg.total_width_max : meta.pixels_per_line_max;
    const uint64_t hs_after_vs_gap_min = agg.frames ? agg.hs_after_vs_gap_min : meta.hs_after_vs_gap_min;
    const uint64_t hs_to_de_gap_min = agg.frames ? agg.hs_to_de_gap_min : meta.hs_to_de_gap_min;
    const uint64_t de_to_hs_gap_min = agg.frames ? agg.de_to_hs_gap_min : meta.de_to_hs_gap_min;
    const uint64_t vs_to_first_de_lines = agg.frames ? agg.vs_to_first_de_lines_min : meta.vs_to_first_de_lines;
    const bool stable_dimensions = agg.frames != 0 &&
                                   agg.active_width_min == agg.active_width_max &&
                                   agg.active_height_min == agg.active_height_max &&
                                   agg.unstable_dimension_frames == 0;
    const bool protocol_valid = agg.total_errors == 0;
    const std::string pad(static_cast<size_t>(indent), ' ');
    out << pad << "{\n";
    out << pad << "  \"active_width\": " << active_width << ",\n";
    out << pad << "  \"active_height\": " << active_height << ",\n";
    out << pad << "  \"active_width_min\": " << agg.active_width_min << ",\n";
    out << pad << "  \"active_width_max\": " << agg.active_width_max << ",\n";
    out << pad << "  \"active_height_min\": " << agg.active_height_min << ",\n";
    out << pad << "  \"active_height_max\": " << agg.active_height_max << ",\n";
    out << pad << "  \"total_width_min\": " << total_width_min << ",\n";
    out << pad << "  \"total_width_max\": " << total_width_max << ",\n";
    out << pad << "  \"pixels_per_line_min\": " << total_width_min << ",\n";
    out << pad << "  \"pixels_per_line_max\": " << total_width_max << ",\n";
    out << pad << "  \"hs_after_vs_gap_min\": " << hs_after_vs_gap_min << ",\n";
    out << pad << "  \"hs_to_de_gap_min\": " << hs_to_de_gap_min << ",\n";
    out << pad << "  \"de_to_hs_gap_min\": " << de_to_hs_gap_min << ",\n";
    out << pad << "  \"vs_to_first_de_lines\": " << vs_to_first_de_lines << ",\n";
    out << pad << "  \"vs_to_first_de_lines_min\": " << agg.vs_to_first_de_lines_min << ",\n";
    out << pad << "  \"vs_to_first_de_lines_max\": " << agg.vs_to_first_de_lines_max << ",\n";
    out << pad << "  \"hs_pulses_min\": " << agg.hs_pulses_min << ",\n";
    out << pad << "  \"hs_pulses_max\": " << agg.hs_pulses_max << ",\n";
    out << pad << "  \"de_errors\": " << agg.de_errors << ",\n";
    out << pad << "  \"rgb_when_de_low_errors\": " << agg.rgb_when_de_low_errors << ",\n";
    out << pad << "  \"pulse_width_errors\": " << agg.pulse_width_errors << ",\n";
    out << pad << "  \"skip_errors\": " << agg.skip_errors << ",\n";
    out << pad << "  \"errors\": " << agg.total_errors << ",\n";
    out << pad << "  \"stable_dimensions\": " << (stable_dimensions ? "true" : "false") << ",\n";
    out << pad << "  \"protocol_valid\": " << (protocol_valid ? "true" : "false") << ",\n";
    out << pad << "  \"frames_measured\": " << agg.frames << ",\n";
    out << pad << "  \"frames_considered\": " << agg.frames << ",\n";
    out << pad << "  \"frames_completed\": " << video.frames_completed() << ",\n";
    out << pad << "  \"ignored_startup_frames\": " << scenario.video_expect.ignore_startup_frames << ",\n";
    out << pad << "  \"startup_frames_ignored\": " << scenario.video_expect.ignore_startup_frames << ",\n";
    out << pad << "  \"first_error_cycle\": " << video.first_error_cycle() << ",\n";
    out << pad << "  \"first_error_frame\": " << video.first_error_frame() << ",\n";
    out << pad << "  \"first_error_pixel\": " << video.first_error_pixel() << ",\n";
    out << pad << "  \"first_error_code\": \"" << json_escape(video.first_error_code()) << "\",\n";
    const uint64_t trace_start = video.first_error_cycle() > 2048 ? video.first_error_cycle() - 2048 : 0;
    const uint64_t trace_end = video.first_error_cycle() ? video.first_error_cycle() + 2048 : 0;
    out << pad << "  \"trace_window\": { \"start_cycle\": " << trace_start
        << ", \"end_cycle\": " << trace_end << " },\n";
    out << pad << "  \"source_signals\": [\"video_rgb\", \"video_de\", \"video_hs\", \"video_vs\", \"video_skip\"]\n";
    out << pad << "}";
}

static void write_video_shape_json(
    const fs::path& path,
    const fs::path& result_path,
    bool ok,
    const Scenario& scenario,
    const VideoCapture& video) {
    if (path.empty()) return;
    if (!path.parent_path().empty()) fs::create_directories(path.parent_path());
    std::ofstream out(path);
    if (!out) return;
    out << "{\n";
    out << "  \"schema\": \"apfsim.video_shape.v1\",\n";
    out << "  \"source_result\": \"" << json_escape(result_path.string()) << "\",\n";
    out << "  \"result_ok\": " << (ok ? "true" : "false") << ",\n";
    out << "  \"video_shape\": ";
    write_video_shape_object(out, scenario, video, 2);
    out << "\n}\n";
}

static std::string normalized_event_name(std::string value) {
    value = unquote(trim(value));
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        if (c == '-' || c == ' ' || c == ':') return '_';
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

static bool is_savestate_save_event(const HostCommandEvent& event) {
    const auto name = normalized_event_name(event.command_name);
    return event.command == apf::kSavestateStartQuery && (name == "savestate" || name == "savestate_save");
}

static bool is_dataslot_update_event(const HostCommandEvent& event) {
    return event.command == apf::kDataSlotUpdate && event.slot_id != 0;
}

static bool host_event_due(const HostCommandEvent& event, uint64_t frame, uint64_t cycle) {
    if (event.executed) return false;
    if (event.has_cycle) return cycle >= event.cycle;
    if (event.has_frame) return frame >= event.frame;
    return frame == 0;
}

template <typename Bridge>
static void execute_host_command_event(
    Bridge& bridge,
    Scenario& scenario,
    HostCommandEvent& event,
    std::vector<SavestateReport>& savestates,
    const fs::path& savestate_dir,
    size_t event_index) {
    if (event.command == 0 && !event.command_name.empty()) event.command = parse_host_command_name(event.command_name);
    if (event.command == 0 && event.command_name.empty()) throw std::runtime_error("host command event missing command");

    if (is_dataslot_update_event(event)) {
        bridge.runtime_data_slot_update(scenario.slots, event.slot_id, event.file, event.size, event.has_size, event.update_slot_table);
        event.result = bridge.last_host_result();
        event.responses = bridge.read_host_responses(4);
        if (const auto* slot = find_slot(scenario.slots, event.slot_id)) event.bytes = slot->loaded_size;
    } else if (is_savestate_save_event(event)) {
        fs::path out = event.output_path;
        if (out.empty() && !savestate_dir.empty()) {
            std::ostringstream name;
            name << "state_" << std::setw(3) << std::setfill('0') << event_index << ".sta";
            out = savestate_dir / name.str();
        } else if (!out.empty() && out.is_relative() && !savestate_dir.empty()) {
            out = savestate_dir / out;
        }
        const auto report = bridge.save_savestate(out, event.name.empty() ? event.command_name : event.name, event.has_size ? event.size : 256);
        event.result = report.final_result;
        event.responses = {report.supported ? 1u : 0u, report.address, report.size, 0u};
        event.bytes = report.bytes;
        event.output_path = report.path;
        savestates.push_back(report);
    } else {
        event.result = bridge.host_command(event.command, event.params[0], event.params[1], event.params[2], event.params[3]);
        event.responses = bridge.read_host_responses(4);
    }

    event.executed = true;
    event.executed_cycle = bridge.stats().last_cycle;
    std::cout << "PASS host-command: " << apf::command_name(event.command) << " result=" << hex32(event.result) << "\n";
}

template <typename Bridge>
static void execute_due_host_commands(
    Bridge& bridge,
    Scenario& scenario,
    std::vector<SavestateReport>& savestates,
    const fs::path& savestate_dir,
    uint64_t frame,
    uint64_t cycle) {
    for (size_t i = 0; i < scenario.host_commands.size(); ++i) {
        auto& event = scenario.host_commands[i];
        if (host_event_due(event, frame, cycle)) {
            execute_host_command_event(bridge, scenario, event, savestates, savestate_dir, i);
        }
    }
}

template <typename Bridge>
static void print_failure_diagnostics(
    const std::string& failed_phase,
    const fs::path& result_path,
    const VideoCapture& video,
    const AudioCapture& audio,
    const Bridge& bridge,
    uint64_t cycles_74a) {
    std::cerr << "FAIL diagnostics: phase=" << failed_phase
              << " cycles_74a=" << cycles_74a
              << " frames_completed=" << video.frames_completed()
              << " frames_started=" << video.frames_started()
              << " audio_samples=" << audio.stats().samples
              << " last_host_command=" << hex32(bridge.last_host_command())
              << " last_host_result=" << hex32(bridge.last_host_result())
              << " last_host_status_word=" << hex32(bridge.last_host_status_word())
              << " last_target_word=" << hex32(bridge.last_target_word())
              << " last_target_command=" << hex32(bridge.last_target_command())
              << " last_target_result=" << hex32(bridge.last_target_result());
    if (!result_path.empty()) std::cerr << " artifact_dir=" << result_path.parent_path().string();
    std::cerr << "\n";
}

template <typename Bridge>
static void write_result_json(
    const fs::path& path,
    bool ok,
    const std::string& failed_phase,
    const std::string& message,
    const Scenario& scenario,
    const std::vector<DataSlot>& slots,
    const VideoCapture& video,
    const AudioCapture& audio,
    const InputDriver& inputs,
    const Bridge& bridge,
    const BootTrace& boot_trace,
    const std::vector<SaveReport>& save_reports,
    const std::vector<SavestateReport>& savestate_reports,
    const std::vector<ReadbackObservation>& readbacks,
    const MemoryActivitySnapshot& memory_activity,
    const std::vector<std::string>& failures,
    size_t interact_writes,
    bool interact_verify_readback,
    uint64_t cycles_74a) {
    if (path.empty()) return;
    if (!path.parent_path().empty()) fs::create_directories(path.parent_path());
    std::ofstream out(path);
    if (!out) return;
    const auto& meta = video.last_metadata();
    const auto video_agg = video.aggregate_after_startup_frames(scenario.video_expect.ignore_startup_frames);
    const auto& astats = audio.stats();
    const uint64_t validated_video_errors = video.errors_after_startup_frames(scenario.video_expect.ignore_startup_frames);
    const bool boot_ok = boot_trace.running_cycle != 0;
    const bool reset_ok = phase_has_no_failure(failures, "reset:");
    const bool data_ok = phase_has_no_failure(failures, "data:");
    const bool video_ok = phase_has_no_failure(failures, "video:");
    const bool audio_ok = phase_has_no_failure(failures, "audio:");
    const bool interact_ok = phase_has_no_failure(failures, "interact:");
    const bool input_ok = phase_has_no_failure(failures, "input:");
    const bool save_ok = phase_has_no_failure(failures, "save:");
    const uint64_t loaded_bytes_total = host_loaded_bytes(slots);
    out << "{\n";
    out << "  \"ok\": " << (ok ? "true" : "false") << ",\n";
    out << "  \"scenario\": \"" << json_escape(scenario.name) << "\",\n";
    out << "  \"artifact_dir\": \"" << json_escape(path.parent_path().string()) << "\",\n";
    out << "  \"failed_phase\": \"" << json_escape(failed_phase) << "\",\n";
    out << "  \"message\": \"" << json_escape(message) << "\",\n";
    out << "  \"status\": \"" << (ok ? "running" : "failed") << "\",\n";
    out << "  \"cycles_74a\": " << cycles_74a << ",\n";
    out << "  \"phases\": {\n";
    out << "    \"boot\": { \"ok\": " << (boot_ok ? "true" : "false") << " },\n";
    out << "    \"reset\": { \"ok\": " << (reset_ok ? "true" : "false") << " },\n";
    out << "    \"data\": { \"ok\": " << (data_ok ? "true" : "false") << " },\n";
    out << "    \"video\": { \"ok\": " << (video_ok ? "true" : "false") << " },\n";
    out << "    \"audio\": { \"ok\": " << (audio_ok ? "true" : "false") << " },\n";
    out << "    \"interact\": { \"ok\": " << (interact_ok ? "true" : "false") << " },\n";
    out << "    \"input\": { \"ok\": " << (input_ok ? "true" : "false") << " },\n";
    out << "    \"save\": { \"ok\": " << (save_ok ? "true" : "false") << " }\n";
    out << "  },\n";
    out << "  \"boot\": { \"ok\": " << (boot_ok ? "true" : "false")
        << ", \"last_host_command\": \"" << hex32(bridge.last_host_command())
        << "\", \"last_host_result\": \"" << hex32(bridge.last_host_result())
        << "\", \"last_host_status_word\": \"" << hex32(bridge.last_host_status_word())
        << "\", \"last_target_word\": \"" << hex32(bridge.last_target_word())
        << "\", \"last_target_command\": \"" << hex32(bridge.last_target_command())
        << "\", \"last_target_result\": \"" << hex32(bridge.last_target_result())
        << "\", \"start_cycle\": " << boot_trace.start_cycle
        << ", \"setup_cycle\": " << boot_trace.setup_cycle
        << ", \"reset_enter_cycle\": " << boot_trace.reset_enter_cycle
        << ", \"slot_table_cycle\": " << boot_trace.slot_table_cycle
        << ", \"data_load_complete_cycle\": " << boot_trace.data_load_complete_cycle
        << ", \"data_all_complete_cycle\": " << boot_trace.data_all_complete_cycle
        << ", \"rtc_cycle\": " << boot_trace.rtc_cycle
        << ", \"target_ready_cycle\": " << boot_trace.target_ready_cycle
        << ", \"before_reset_exit_cycle\": " << boot_trace.before_reset_exit_cycle
        << ", \"reset_exit_cycle\": " << boot_trace.reset_exit_cycle
        << ", \"running_cycle\": " << boot_trace.running_cycle
        << ", \"reset_hold_cycles\": "
        << (boot_trace.reset_enter_cycle && boot_trace.reset_exit_cycle && boot_trace.reset_exit_cycle >= boot_trace.reset_enter_cycle
                ? boot_trace.reset_exit_cycle - boot_trace.reset_enter_cycle
                : 0)
        << ", \"reset_exit_to_running_cycles\": "
        << (boot_trace.reset_exit_cycle && boot_trace.running_cycle && boot_trace.running_cycle >= boot_trace.reset_exit_cycle
                ? boot_trace.running_cycle - boot_trace.reset_exit_cycle
                : 0)
        << ", \"events\": [";
    for (size_t i = 0; i < boot_trace.events.size(); ++i) {
        out << (i ? ", " : "") << "\"" << json_escape(boot_trace.events[i]) << "\"";
    }
    out << "] },\n";
    out << "  \"data\": { \"slots\": [\n";
    for (size_t i = 0; i < slots.size(); ++i) {
        const auto& slot = slots[i];
        out << "    { \"id\": " << slot.id
            << ", \"name\": \"" << json_escape(slot.name)
            << "\", \"address\": \"" << hex32(slot.address)
            << "\", \"loaded_last_address\": \"" << hex32(slot.loaded_last_address)
            << "\", \"file\": \"" << json_escape(slot.file.string())
            << "\", \"loaded_size\": " << slot.loaded_size
            << ", \"loaded_words\": " << slot.loaded_words
            << ", \"observed_write_words\": " << slot.observed_write_words
            << ", \"observed_first_write_address\": \"" << hex32(slot.observed_first_write_address)
            << "\", \"observed_last_write_address\": \"" << hex32(slot.observed_last_write_address)
            << "\", \"observed_write_address_errors\": " << slot.observed_write_address_errors
            << ", \"loaded_checksum\": \"" << hex64(slot.loaded_checksum) << "\""
            << ", \"loaded_crc32\": \"" << hex32(slot.loaded_crc32) << "\""
            << ", \"expected_checksum\": ";
        if (slot.has_expected_checksum) out << "\"" << hex64(slot.expected_checksum) << "\"";
        else out << "null";
        out
            << ", \"nonvolatile\": " << (slot.nonvolatile ? "true" : "false")
            << ", \"deferload\": " << (slot.deferload ? "true" : "false")
            << ", \"verify_readback\": " << (slot.verify_readback ? "true" : "false")
            << ", \"readback_attempted\": " << (slot.readback_attempted ? "true" : "false")
            << ", \"readback_matches\": ";
        if (slot.readback_attempted) out << (slot.readback_matches ? "true" : "false");
        else out << "null";
        out << ", \"readback_bytes\": " << slot.readback_bytes
            << ", \"readback_crc32\": \"" << hex32(slot.readback_crc32)
            << "\", \"readback_checksum\": \"" << hex64(slot.readback_checksum)
            << "\", \"readback_mismatch_count\": " << slot.readback_mismatch_count
            << ", \"readback_first_mismatch_offset\": ";
        if (slot.readback_has_first_mismatch) out << slot.readback_first_mismatch_offset;
        else out << "null";
        out << ", \"readback_expected_byte\": ";
        if (slot.readback_has_first_mismatch) out << static_cast<uint32_t>(slot.readback_expected_byte);
        else out << "null";
        out << ", \"readback_observed_byte\": ";
        if (slot.readback_has_first_mismatch) out << static_cast<uint32_t>(slot.readback_observed_byte);
        else out << "null";
        out
            << ", \"target_read_requests\": " << slot.target_read_requests
            << ", \"target_read_bytes\": " << slot.target_read_bytes
            << ", \"target_write_requests\": " << slot.target_write_requests
            << ", \"target_write_bytes\": " << slot.target_write_bytes
            << ", \"target_flush_requests\": " << slot.target_flush_requests
            << ", \"target_filename_requests\": " << slot.target_filename_requests
            << ", \"target_open_requests\": " << slot.target_open_requests << " }";
        out << (i + 1 == slots.size() ? "\n" : ",\n");
    }
    out << "  ] },\n";
    out << "  \"data_load\": { \"done_seen\": " << (boot_trace.data_all_complete_cycle ? "true" : "false")
        << ", \"done_cycle\": " << boot_trace.data_all_complete_cycle
        << ", \"total_loaded_bytes\": " << loaded_bytes_total
        << ", \"slots\": [\n";
    for (size_t i = 0; i < slots.size(); ++i) {
        const auto& slot = slots[i];
        out << "    { \"id\": " << slot.id
            << ", \"name\": \"" << json_escape(slot.name)
            << "\", \"path\": \"" << json_escape(slot.file.string())
            << "\", \"address\": \"" << hex32(slot.address)
            << "\", \"loaded_bytes\": " << slot.loaded_size
            << ", \"loaded_words\": " << slot.loaded_words
            << ", \"crc\": \"" << hex32(slot.loaded_crc32)
            << "\", \"checksum_fnv1a64\": \"" << hex64(slot.loaded_checksum)
            << "\", \"required\": " << (slot.required ? "true" : "false")
            << ", \"nonvolatile\": " << (slot.nonvolatile ? "true" : "false")
            << ", \"deferload\": " << (slot.deferload ? "true" : "false")
            << ", \"verify_readback\": " << (slot.verify_readback ? "true" : "false")
            << ", \"readback_attempted\": " << (slot.readback_attempted ? "true" : "false")
            << ", \"readback_matches\": ";
        if (slot.readback_attempted) out << (slot.readback_matches ? "true" : "false");
        else out << "null";
        out << ", \"readback_bytes\": " << slot.readback_bytes
            << ", \"readback_crc\": \"" << hex32(slot.readback_crc32)
            << "\", \"readback_checksum_fnv1a64\": \"" << hex64(slot.readback_checksum)
            << "\", \"readback_mismatch_count\": " << slot.readback_mismatch_count
            << ", \"readback_first_mismatch_offset\": ";
        if (slot.readback_has_first_mismatch) out << slot.readback_first_mismatch_offset;
        else out << "null";
        out << ", \"readback_expected_byte\": ";
        if (slot.readback_has_first_mismatch) out << static_cast<uint32_t>(slot.readback_expected_byte);
        else out << "null";
        out << ", \"readback_observed_byte\": ";
        if (slot.readback_has_first_mismatch) out << static_cast<uint32_t>(slot.readback_observed_byte);
        else out << "null";
        out
            << ", \"observed_write_words\": " << slot.observed_write_words
            << ", \"observed_write_address_errors\": " << slot.observed_write_address_errors
            << ", \"done_seen\": " << ((slot.deferload || slot.file.empty() || slot.loaded_size > 0) ? "true" : "false") << " }";
        out << (i + 1 == slots.size() ? "\n" : ",\n");
    }
    out << "  ] },\n";
    const auto& bstats = bridge.stats();
    out << "  \"bridge\": { \"endian\": \"" << (bstats.endian_little ? "little" : "big")
        << "\", \"read_latency_cycles\": " << bstats.read_latency_cycles
        << ", \"write_idle_cycles\": " << bstats.write_idle_cycles
        << ", \"write_strobe_cycles\": " << bstats.write_strobe_cycles
        << ", \"reads\": " << bstats.reads
        << ", \"writes\": " << bstats.writes
        << ", \"framework_reads\": " << bstats.framework_reads
        << ", \"framework_writes\": " << bstats.framework_writes
        << ", \"host_commands\": " << bstats.host_commands
        << ", \"target_commands\": " << bstats.target_commands
        << ", \"host_timeouts\": " << bstats.host_timeouts
        << ", \"host_command_writes\": " << bstats.host_command_writes
        << ", \"target_command_reads\": " << bstats.target_command_reads
        << ", \"target_command_writes\": " << bstats.target_command_writes
        << ", \"target_debug_events\": " << bstats.target_debug_events
        << ", \"target_dataslot_reads\": " << bstats.target_dataslot_reads
        << ", \"target_dataslot_read_bytes\": " << bstats.target_dataslot_read_bytes
        << ", \"target_dataslot_writes\": " << bstats.target_dataslot_writes
        << ", \"target_dataslot_write_bytes\": " << bstats.target_dataslot_write_bytes
        << ", \"target_dataslot_flushes\": " << bstats.target_dataslot_flushes
        << ", \"target_filename_requests\": " << bstats.target_filename_requests
        << ", \"target_open_file_requests\": " << bstats.target_open_file_requests
        << ", \"runtime_dataslot_updates\": " << bstats.runtime_dataslot_updates
        << ", \"savestate_save_requests\": " << bstats.savestate_save_requests
        << ", \"savestate_save_bytes\": " << bstats.savestate_save_bytes
        << ", \"target_unsupported_commands\": " << bstats.target_unsupported_commands
        << ", \"target_slot_errors\": " << bstats.target_slot_errors
        << ", \"target_range_errors\": " << bstats.target_range_errors
        << ", \"slot_table_writes\": " << bstats.slot_table_writes
        << ", \"data_payload_writes\": " << bstats.data_payload_writes
        << ", \"save_payload_reads\": " << bstats.save_payload_reads
        << ", \"custom_reads\": " << bstats.custom_reads
        << ", \"custom_writes\": " << bstats.custom_writes
        << ", \"first_cycle\": " << bstats.first_cycle
        << ", \"last_cycle\": " << bstats.last_cycle
        << ", \"last_read_addr\": \"" << hex32(bstats.last_read_addr)
        << "\", \"last_read_data\": \"" << hex32(bstats.last_read_data)
        << "\", \"last_write_addr\": \"" << hex32(bstats.last_write_addr)
        << "\", \"last_write_data\": \"" << hex32(bstats.last_write_data)
        << "\", \"slot_table_ok\": " << (bridge.slot_table_matches(slots) ? "true" : "false")
        << " },\n";
    out << "  \"video\": { \"frames_requested\": " << scenario.frames
        << ", \"frames_completed\": " << video.frames_completed()
        << ", \"frames_started\": " << video.frames_started()
        << ", \"validated_frames\": " << video_agg.frames
        << ", \"frames_considered\": " << video_agg.frames
        << ", \"active_width\": " << meta.active_width
        << ", \"active_width_frame_min\": " << video_agg.active_width_min
        << ", \"active_width_frame_max\": " << video_agg.active_width_max
        << ", \"active_width_min\": " << meta.active_width_min
        << ", \"active_height\": " << meta.active_height
        << ", \"active_height_frame_min\": " << video_agg.active_height_min
        << ", \"active_height_frame_max\": " << video_agg.active_height_max
        << ", \"total_pixel_clocks\": " << meta.total_pixel_clocks
        << ", \"refresh_hz\": "
        << ((scenario.video_expect.pixel_clock_hz > 0.0 && meta.total_pixel_clocks > 0)
                ? scenario.video_expect.pixel_clock_hz / static_cast<double>(meta.total_pixel_clocks)
                : 0.0)
        << ", \"pixels_per_line_min\": " << meta.pixels_per_line_min
        << ", \"pixels_per_line_max\": " << meta.pixels_per_line_max
        << ", \"hs_pulses\": " << meta.hs_pulses
        << ", \"vs_pulses\": " << meta.vs_pulses
        << ", \"hs_after_vs_gap_min\": " << meta.hs_after_vs_gap_min
        << ", \"hs_to_de_gap_min\": " << meta.hs_to_de_gap_min
        << ", \"de_to_hs_gap_min\": " << meta.de_to_hs_gap_min
        << ", \"de_errors\": " << meta.de_errors
        << ", \"rgb_when_de_low_errors\": " << meta.rgb_when_de_low_errors
        << ", \"pulse_width_errors\": " << meta.pulse_width_errors
        << ", \"skip_errors\": " << meta.skip_errors
        << ", \"unique_colors\": " << meta.unique_colors
        << ", \"nonzero_pixels\": " << meta.nonzero_pixels
        << ", \"changed_pixels_from_previous\": " << meta.changed_pixels_from_previous
        << ", \"changed_frames\": " << video.changed_frames()
        << ", \"max_changed_pixels_from_previous\": " << video.max_changed_pixels_from_previous()
        << ", \"frame_hash\": \"" << hex64(meta.frame_hash) << "\""
        << ", \"unstable_dimension_frames\": " << video_agg.unstable_dimension_frames
        << ", \"hs_under_active_height_frames\": " << video_agg.hs_under_active_height_frames
        << ", \"errors\": " << validated_video_errors
        << ", \"raw_errors\": " << video.errors()
        << ", \"ignored_startup_frames\": " << scenario.video_expect.ignore_startup_frames
        << ", \"startup_frames_ignored\": " << scenario.video_expect.ignore_startup_frames << " },\n";
    out << "  \"video_shape\": ";
    write_video_shape_object(out, scenario, video, 2);
    out << ",\n";
    const uint64_t video_trace_start = video.first_error_cycle() > 2048 ? video.first_error_cycle() - 2048 : 0;
    const uint64_t video_trace_end = video.first_error_cycle() ? video.first_error_cycle() + 2048 : 0;
    out << "  \"video_protocol\": { \"valid\": " << (video_agg.total_errors == 0 ? "true" : "false")
        << ", \"first_error_cycle\": " << video.first_error_cycle()
        << ", \"first_error_frame\": " << video.first_error_frame()
        << ", \"first_error_pixel\": " << video.first_error_pixel()
        << ", \"first_error_code\": \"" << json_escape(video.first_error_code())
        << "\", \"trace_window\": { \"start_cycle\": " << video_trace_start
        << ", \"end_cycle\": " << video_trace_end << " }"
        << ", \"source_signals\": [\"video_rgb\", \"video_de\", \"video_hs\", \"video_vs\", \"video_skip\"] },\n";
    out << "  \"audio\": { \"sample_rate\": " << astats.sample_rate
        << ", \"samples\": " << astats.samples
        << ", \"min_l\": " << astats.min_l
        << ", \"max_l\": " << astats.max_l
        << ", \"min_r\": " << astats.min_r
        << ", \"max_r\": " << astats.max_r
        << ", \"peak_to_peak_l\": " << astats.peak_to_peak_l
        << ", \"peak_to_peak_r\": " << astats.peak_to_peak_r
        << ", \"peak\": " << astats.peak
        << ", \"nonzero_samples\": " << astats.nonzero_samples
        << ", \"activity\": \"" << json_escape(astats.activity) << "\""
        << ", \"dc_offset_l\": " << astats.dc_offset_l
        << ", \"dc_offset_r\": " << astats.dc_offset_r
        << ", \"clipped_samples\": " << astats.clipped_samples
        << ", \"mclk_edges\": " << astats.mclk_edges
        << ", \"lrck_edges\": " << astats.lrck_edges
        << ", \"mclk_seen\": " << (astats.mclk_seen ? "true" : "false")
        << ", \"lrclk_seen\": " << (astats.lrclk_seen ? "true" : "false")
        << ", \"stuck_sample\": " << (astats.stuck_sample ? "true" : "false")
        << ", \"lrck_half_period_mclk_min\": " << astats.lrck_half_period_mclk_min
        << ", \"lrck_half_period_mclk_max\": " << astats.lrck_half_period_mclk_max
        << ", \"avg_mclk_per_lrck_half_period\": " << astats.avg_mclk_per_lrck_half_period
        << ", \"estimated_mclk_lrck_ratio\": " << astats.estimated_mclk_lrck_ratio << " },\n";
    const bool interact_verified = interact_verify_readback && interact_writes > 0 && interact_ok;
    const bool reset_action_seen = boot_trace.reset_enter_cycle != 0 && boot_trace.reset_exit_cycle != 0;
    out << "  \"interact\": { \"persistent_writes\": " << interact_writes
        << ", \"readback_enabled\": " << (interact_verify_readback ? "true" : "false")
        << ", \"readback_verified\": " << (interact_verified ? "true" : "false") << " },\n";
    out << "  \"interact_readback\": { \"enabled\": " << (interact_verify_readback ? "true" : "false")
        << ", \"verified\": " << (interact_verified ? "true" : "false")
        << ", \"persistent_writes\": " << interact_writes << " },\n";
    out << "  \"reset_action_seen\": " << (reset_action_seen ? "true" : "false") << ",\n";
    out << "  \"control_plane\": { \"interact_readback\": { \"enabled\": " << (interact_verify_readback ? "true" : "false")
        << ", \"verified\": " << (interact_verified ? "true" : "false")
        << ", \"persistent_writes\": " << interact_writes << " }, \"reset_action_seen\": "
        << (reset_action_seen ? "true" : "false") << " },\n";
    out << "  \"input\": { \"scripted_events\": " << scenario.inputs.size()
        << ", \"delivered_events\": " << inputs.delivered_event_count()
        << ", \"input_effect_seen\": " << ((inputs.ever_active() && inputs.delivered_event_count() > 0) ? "true" : "false")
        << ", \"ever_active\": " << (inputs.ever_active() ? "true" : "false")
        << ", \"key_state\": { \"cont1_key\": \"" << hex32(inputs.key_state(1))
        << "\", \"cont2_key\": \"" << hex32(inputs.key_state(2))
        << "\", \"cont3_key\": \"" << hex32(inputs.key_state(3))
        << "\", \"cont4_key\": \"" << hex32(inputs.key_state(4)) << "\" }, \"input_trace\": [\n";
    for (size_t i = 0; i < inputs.events().size(); ++i) {
        const auto& event = inputs.events()[i];
        out << "    { \"frame\": " << event.frame
            << ", \"player\": " << event.player
            << ", \"button\": \"" << button_name(event.button)
            << "\", \"hold_frames\": " << event.hold_frames
            << ", \"delivered\": " << (inputs.event_delivered(i) ? "true" : "false") << " }";
        out << (i + 1 == inputs.events().size() ? "\n" : ",\n");
    }
    out << "  ] },\n";
    out << "  \"input_trace\": [\n";
    for (size_t i = 0; i < inputs.events().size(); ++i) {
        const auto& event = inputs.events()[i];
        out << "    { \"frame\": " << event.frame
            << ", \"player\": " << event.player
            << ", \"button\": \"" << button_name(event.button)
            << "\", \"hold_frames\": " << event.hold_frames
            << ", \"delivered\": " << (inputs.event_delivered(i) ? "true" : "false") << " }";
        out << (i + 1 == inputs.events().size() ? "\n" : ",\n");
    }
    out << "  ],\n";
    out << "  \"input_effect_seen\": " << ((inputs.ever_active() && inputs.delivered_event_count() > 0) ? "true" : "false") << ",\n";
    out << "  \"save\": { \"reports\": [\n";
    for (size_t i = 0; i < save_reports.size(); ++i) {
        const auto& report = save_reports[i];
        out << "    { \"id\": " << report.id
            << ", \"bytes\": " << report.bytes
            << ", \"path\": \"" << json_escape(report.path.string())
            << "\", \"checksum\": \"" << hex64(report.checksum)
            << "\", \"input_checksum\": \"" << hex64(report.input_checksum)
            << "\", \"matches_input\": " << (report.matches_input ? "true" : "false") << " }";
        out << (i + 1 == save_reports.size() ? "\n" : ",\n");
    }
    out << "  ] },\n";
    out << "  \"savestate\": { \"reports\": [\n";
    for (size_t i = 0; i < savestate_reports.size(); ++i) {
        const auto& report = savestate_reports[i];
        out << "    { \"name\": \"" << json_escape(report.name)
            << "\", \"attempted\": " << (report.attempted ? "true" : "false")
            << ", \"supported\": " << (report.supported ? "true" : "false")
            << ", \"ready\": " << (report.ready ? "true" : "false")
            << ", \"query_result\": \"" << hex32(report.query_result)
            << "\", \"start_result\": \"" << hex32(report.start_result)
            << "\", \"final_result\": \"" << hex32(report.final_result)
            << "\", \"address\": \"" << hex32(report.address)
            << "\", \"size\": " << report.size
            << ", \"bytes\": " << report.bytes
            << ", \"polls\": " << report.polls
            << ", \"checksum\": \"" << hex64(report.checksum)
            << "\", \"path\": \"" << json_escape(report.path.string()) << "\" }";
        out << (i + 1 == savestate_reports.size() ? "\n" : ",\n");
    }
    out << "  ] },\n";
    out << "  \"memory_activity\": ";
    write_memory_activity_object(out, memory_activity, 2);
    out << ",\n";
    out << "  \"host_commands\": [\n";
    for (size_t i = 0; i < scenario.host_commands.size(); ++i) {
        const auto& event = scenario.host_commands[i];
        out << "    { \"name\": \"" << json_escape(event.name)
            << "\", \"command_name\": \"" << json_escape(event.command_name)
            << "\", \"command\": \"" << hex32(event.command)
            << "\", \"frame\": " << event.frame
            << ", \"cycle\": " << event.cycle
            << ", \"executed\": " << (event.executed ? "true" : "false")
            << ", \"executed_cycle\": " << event.executed_cycle
            << ", \"result\": \"" << hex32(event.result)
            << "\", \"p0\": \"" << hex32(event.params[0])
            << "\", \"p1\": \"" << hex32(event.params[1])
            << "\", \"p2\": \"" << hex32(event.params[2])
            << "\", \"p3\": \"" << hex32(event.params[3])
            << "\", \"response0\": \"" << hex32(event.responses[0])
            << "\", \"response1\": \"" << hex32(event.responses[1])
            << "\", \"response2\": \"" << hex32(event.responses[2])
            << "\", \"response3\": \"" << hex32(event.responses[3])
            << "\", \"slot_id\": " << event.slot_id
            << ", \"bytes\": " << event.bytes
            << ", \"output_path\": \"" << json_escape(event.output_path.string()) << "\" }";
        out << (i + 1 == scenario.host_commands.size() ? "\n" : ",\n");
    }
    out << "  ],\n";
    out << "  \"readbacks\": [\n";
    for (size_t i = 0; i < readbacks.size(); ++i) {
        const auto& readback = readbacks[i];
        out << "    { \"name\": \"" << json_escape(readback.expect.name)
            << "\", \"address\": \"" << hex32(readback.expect.address)
            << "\", \"expected\": \"" << hex32(readback.expect.value)
            << "\", \"mask\": \"" << hex32(readback.expect.mask)
            << "\", \"observed\": \"" << hex32(readback.observed)
            << "\", \"ok\": " << (readback.ok ? "true" : "false") << " }";
        out << (i + 1 == readbacks.size() ? "\n" : ",\n");
    }
    out << "  ],\n";
    out << "  \"failures\": [\n";
    for (size_t i = 0; i < failures.size(); ++i) {
        out << "    \"" << json_escape(failures[i]) << "\"";
        out << (i + 1 == failures.size() ? "\n" : ",\n");
    }
    out << "  ]\n";
    out << "}\n";
}

template <typename Bridge>
static void write_bridge_summary_json(
    const fs::path& path,
    const Bridge& bridge,
    const std::vector<DataSlot>& slots) {
    if (path.empty()) return;
    if (!path.parent_path().empty()) fs::create_directories(path.parent_path());
    std::ofstream out(path);
    if (!out) return;
    const auto& stats = bridge.stats();
    const auto& commands = bridge.command_trace();
    out << "{\n";
    out << "  \"endian\": \"" << (stats.endian_little ? "little" : "big") << "\",\n";
    out << "  \"read_latency_cycles\": " << stats.read_latency_cycles << ",\n";
    out << "  \"write_idle_cycles\": " << stats.write_idle_cycles << ",\n";
    out << "  \"write_strobe_cycles\": " << stats.write_strobe_cycles << ",\n";
    out << "  \"reads\": " << stats.reads << ",\n";
    out << "  \"writes\": " << stats.writes << ",\n";
    out << "  \"framework_reads\": " << stats.framework_reads << ",\n";
    out << "  \"framework_writes\": " << stats.framework_writes << ",\n";
    out << "  \"host_commands\": " << stats.host_commands << ",\n";
    out << "  \"target_commands\": " << stats.target_commands << ",\n";
    out << "  \"host_timeouts\": " << stats.host_timeouts << ",\n";
    out << "  \"host_command_writes\": " << stats.host_command_writes << ",\n";
    out << "  \"target_command_reads\": " << stats.target_command_reads << ",\n";
    out << "  \"target_command_writes\": " << stats.target_command_writes << ",\n";
    out << "  \"target_debug_events\": " << stats.target_debug_events << ",\n";
    out << "  \"target_dataslot_reads\": " << stats.target_dataslot_reads << ",\n";
    out << "  \"target_dataslot_read_bytes\": " << stats.target_dataslot_read_bytes << ",\n";
    out << "  \"target_dataslot_writes\": " << stats.target_dataslot_writes << ",\n";
    out << "  \"target_dataslot_write_bytes\": " << stats.target_dataslot_write_bytes << ",\n";
    out << "  \"target_dataslot_flushes\": " << stats.target_dataslot_flushes << ",\n";
    out << "  \"target_filename_requests\": " << stats.target_filename_requests << ",\n";
    out << "  \"target_open_file_requests\": " << stats.target_open_file_requests << ",\n";
    out << "  \"runtime_dataslot_updates\": " << stats.runtime_dataslot_updates << ",\n";
    out << "  \"savestate_save_requests\": " << stats.savestate_save_requests << ",\n";
    out << "  \"savestate_save_bytes\": " << stats.savestate_save_bytes << ",\n";
    out << "  \"target_unsupported_commands\": " << stats.target_unsupported_commands << ",\n";
    out << "  \"target_slot_errors\": " << stats.target_slot_errors << ",\n";
    out << "  \"target_range_errors\": " << stats.target_range_errors << ",\n";
    out << "  \"slot_table_writes\": " << stats.slot_table_writes << ",\n";
    out << "  \"data_payload_writes\": " << stats.data_payload_writes << ",\n";
    out << "  \"save_payload_reads\": " << stats.save_payload_reads << ",\n";
    out << "  \"custom_reads\": " << stats.custom_reads << ",\n";
    out << "  \"custom_writes\": " << stats.custom_writes << ",\n";
    out << "  \"first_cycle\": " << stats.first_cycle << ",\n";
    out << "  \"last_cycle\": " << stats.last_cycle << ",\n";
    out << "  \"last_read_addr\": \"" << hex32(stats.last_read_addr) << "\",\n";
    out << "  \"last_read_data\": \"" << hex32(stats.last_read_data) << "\",\n";
    out << "  \"last_write_addr\": \"" << hex32(stats.last_write_addr) << "\",\n";
    out << "  \"last_write_data\": \"" << hex32(stats.last_write_data) << "\",\n";
    out << "  \"slot_table_ok\": " << (bridge.slot_table_matches(slots) ? "true" : "false") << ",\n";
    out << "  \"commands\": [\n";
    for (size_t i = 0; i < commands.size(); ++i) {
        const auto& cmd = commands[i];
        out << "    { \"direction\": \"" << json_escape(cmd.direction)
            << "\", \"cycle\": " << cmd.cycle
            << ", \"command\": \"" << hex32(cmd.command)
            << "\", \"result\": \"" << hex32(cmd.result)
            << "\", \"word\": \"" << hex32(cmd.word)
            << "\", \"p0\": \"" << hex32(cmd.p0)
            << "\", \"p1\": \"" << hex32(cmd.p1)
            << "\", \"p2\": \"" << hex32(cmd.p2)
            << "\", \"p3\": \"" << hex32(cmd.p3) << "\" }";
        out << (i + 1 == commands.size() ? "\n" : ",\n");
    }
    out << "  ]\n";
    out << "}\n";
}

class SimHarness {
public:
    SimHarness(VerilatedContext* context, Vcore_top* top, VideoCapture* video, AudioCapture* audio, InputDriver* inputs)
        : context_(context), top_(top), video_(video), audio_(audio), inputs_(inputs) {}

#if VM_TRACE
    void set_trace(VerilatedFstC* trace) { trace_ = trace; }
#endif

    void eval_half() {
        clk_ = !clk_;
        top_->clk_74a = clk_;
        top_->clk_74b = clk_;
        inputs_->drive(top_);
        top_->eval();
        video_->sample(top_, time_.cycles_74a);
        audio_->sample(top_);
#if VM_TRACE
        if (trace_) trace_->dump(context_->time());
#endif
        context_->timeInc(time_.half_period_ps);
        time_.advance_half();
    }

    void cycle() {
        eval_half();
        eval_half();
        ++time_.cycles_74a;
    }

    void cycles(uint64_t n) {
        for (uint64_t i = 0; i < n && !context_->gotFinish(); ++i) cycle();
    }

    uint64_t cycles_74a() const { return time_.cycles_74a; }
    bool got_finish() const { return context_->gotFinish(); }

private:
    VerilatedContext* context_ = nullptr;
    Vcore_top* top_ = nullptr;
    VideoCapture* video_ = nullptr;
    AudioCapture* audio_ = nullptr;
    InputDriver* inputs_ = nullptr;
    SimTime time_;
    bool clk_ = false;
#if VM_TRACE
    VerilatedFstC* trace_ = nullptr;
#endif
};

#if APFSIM_ENABLE_SDL
static bool map_sdl_key(SDL_Keycode key, int& player, Button& button) {
    player = 1;
    switch (key) {
        case SDLK_UP: button = Button::Up; return true;
        case SDLK_DOWN: button = Button::Down; return true;
        case SDLK_LEFT: button = Button::Left; return true;
        case SDLK_RIGHT: button = Button::Right; return true;
        case SDLK_z:
        case SDLK_a:
        case SDLK_SPACE: button = Button::A; return true;
        case SDLK_x:
        case SDLK_s: button = Button::B; return true;
        case SDLK_RETURN:
        case SDLK_KP_ENTER: button = Button::Start; return true;
        case SDLK_5:
        case SDLK_c: button = Button::Select; return true;
        case SDLK_p: button = Button::L1; return true;
        default: break;
    }
    return false;
}

template <typename Bridge>
static int run_interactive_loop(
    SimHarness& sim,
    VideoCapture& video,
    InputDriver& inputs,
    Bridge& bridge,
    Scenario& scenario,
    std::vector<SavestateReport>& savestate_reports,
    const CliOptions& opt) {
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS) != 0) {
        throw std::runtime_error(std::string("SDL_Init failed: ") + SDL_GetError());
    }

    std::cout << "PLAY controls: arrows=move, Z/A/Space=jump, Enter=start, 5/C=coin, P=pause, Q/Esc=quit\n";

    const int scale = std::max(1, opt.play_scale);
    SDL_Window* window = nullptr;
    SDL_Renderer* renderer = nullptr;
    SDL_Texture* texture = nullptr;
    int texture_w = 0;
    int texture_h = 0;
    std::vector<uint32_t> argb;

    auto cleanup = [&]() {
        if (texture) SDL_DestroyTexture(texture);
        if (renderer) SDL_DestroyRenderer(renderer);
        if (window) SDL_DestroyWindow(window);
        SDL_Quit();
    };

    bool quit = false;
    uint64_t last_frame_start = video.frames_started();
    uint64_t last_rendered_frame = video.frames_completed();
    uint64_t next_target_service_cycle = opt.target_service_interval_cycles ? sim.cycles_74a() + opt.target_service_interval_cycles : 0;
    auto last_present = std::chrono::steady_clock::now();

    while (!quit && !sim.got_finish()) {
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT) {
                quit = true;
            } else if (event.type == SDL_KEYDOWN || event.type == SDL_KEYUP) {
                if (event.key.repeat) continue;
                const bool down = event.type == SDL_KEYDOWN;
                if (event.key.keysym.sym == SDLK_ESCAPE || event.key.keysym.sym == SDLK_q) {
                    if (down) quit = true;
                    continue;
                }
                int player = 1;
                Button button = Button::A;
                if (map_sdl_key(event.key.keysym.sym, player, button)) inputs.set_button(player, button, down);
            }
        }

        const uint64_t frame_before = video.frames_completed();
        for (int i = 0; i < 2000 && !quit && !sim.got_finish() && video.frames_completed() == frame_before; ++i) {
            sim.cycle();
            if (opt.target_service_interval_cycles && sim.cycles_74a() >= next_target_service_cycle) {
                bridge.service_target_commands(scenario.slots, 4);
                next_target_service_cycle = sim.cycles_74a() + opt.target_service_interval_cycles;
            }
            if (video.frames_started() != last_frame_start) {
                last_frame_start = video.frames_started();
                inputs.on_frame(last_frame_start);
                execute_due_host_commands(bridge, scenario, savestate_reports, opt.dump_savestates, last_frame_start, sim.cycles_74a());
            }
        }

        if (video.frames_completed() != last_rendered_frame && !video.last_frame_pixels().empty()) {
            last_rendered_frame = video.frames_completed();
            const int w = static_cast<int>(video.last_frame_width());
            const int h = static_cast<int>(video.last_frame_height());
            if (w <= 0 || h <= 0) continue;

            if (!window) {
                window = SDL_CreateWindow("apfsim play", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                          w * scale, h * scale, SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE);
                if (!window) throw std::runtime_error(std::string("SDL_CreateWindow failed: ") + SDL_GetError());
                renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
                if (!renderer) throw std::runtime_error(std::string("SDL_CreateRenderer failed: ") + SDL_GetError());
                SDL_RenderSetLogicalSize(renderer, w, h);
            }
            if (!texture || texture_w != w || texture_h != h) {
                if (texture) SDL_DestroyTexture(texture);
                texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, w, h);
                if (!texture) throw std::runtime_error(std::string("SDL_CreateTexture failed: ") + SDL_GetError());
                texture_w = w;
                texture_h = h;
            }

            const auto& rgb = video.last_frame_pixels();
            argb.resize(rgb.size());
            for (size_t i = 0; i < rgb.size(); ++i) argb[i] = 0xFF000000u | (rgb[i] & 0x00FFFFFFu);
            SDL_UpdateTexture(texture, nullptr, argb.data(), w * static_cast<int>(sizeof(uint32_t)));
            SDL_RenderClear(renderer);
            SDL_RenderCopy(renderer, texture, nullptr, nullptr);
            SDL_RenderPresent(renderer);

            if (opt.play_speed_percent > 0) {
                const auto frame_ms = std::chrono::duration<double, std::milli>(1000.0 / 60.0 * 100.0 / opt.play_speed_percent);
                const auto target = last_present + std::chrono::duration_cast<std::chrono::steady_clock::duration>(frame_ms);
                const auto now = std::chrono::steady_clock::now();
                if (now < target) std::this_thread::sleep_until(target);
                last_present = std::chrono::steady_clock::now();
            }
        }
    }

    cleanup();
    return 0;
}
#else
template <typename Bridge>
static int run_interactive_loop(SimHarness&, VideoCapture&, InputDriver&, Bridge&, Scenario&, std::vector<SavestateReport>&, const CliOptions&) {
    throw std::runtime_error("interactive play requires an SDL-enabled build");
}
#endif

static void merge_slots(std::vector<DataSlot>& base, const std::vector<DataSlot>& extra) {
    for (const auto& slot : extra) {
        if (auto* existing = find_slot(base, slot.id)) {
            const auto override = *existing;
            *existing = slot;
            if (!override.name.empty()) existing->name = override.name;
            if (!override.file.empty()) existing->file = override.file;
            if (override.address != 0) existing->address = override.address;
            existing->required = existing->required || override.required;
            existing->nonvolatile = existing->nonvolatile || override.nonvolatile;
            existing->deferload = existing->deferload || override.deferload;
            existing->verify_readback = existing->verify_readback || override.verify_readback;
            if (override.size_exact) existing->size_exact = override.size_exact;
            if (override.size_maximum) existing->size_maximum = override.size_maximum;
            if (override.has_expected_checksum) {
                existing->expected_checksum = override.expected_checksum;
                existing->has_expected_checksum = true;
            }
        } else {
            base.push_back(slot);
        }
    }
}

static void apply_data_expect_to_slots(Scenario& scenario) {
    if (!(scenario.data_expect.verify_readback || scenario.data_expect.require_readback_match)) return;
    for (auto& slot : scenario.slots) {
        if (!slot.file.empty() && !slot.deferload) slot.verify_readback = true;
    }
}

static void validate_video(Assertions& asserts, const Scenario& scenario, const VideoCapture& video) {
    const auto& expect = scenario.video_expect;
    const auto& meta = video.last_metadata();
    const auto agg = video.aggregate_after_startup_frames(expect.ignore_startup_frames);
    const uint64_t required_frames = std::max<uint64_t>(scenario.frames, expect.min_frames);
    if (video.frames_completed() < required_frames) asserts.fail("video: did not produce required frame count");
    if (expect.active_width && (agg.active_width_min != expect.active_width || agg.active_width_max != expect.active_width)) asserts.fail("video: active width mismatch");
    if (expect.active_height && (agg.active_height_min != expect.active_height || agg.active_height_max != expect.active_height)) asserts.fail("video: active height mismatch");
    if (video.errors_after_startup_frames(expect.ignore_startup_frames) > expect.max_errors) asserts.fail("video: protocol error count exceeded");
    if (expect.require_rgb_zero_when_de_low && agg.rgb_when_de_low_errors != 0) asserts.fail("video: RGB was nonzero while DE was low");
    if (expect.require_single_cycle_sync && agg.pulse_width_errors != 0) asserts.fail("video: HS/VS pulse width was not one pixel clock");
    if (expect.require_skip_only_during_de && agg.skip_errors != 0) asserts.fail("video: SKIP asserted while DE was low");
    if (expect.require_stable_dimensions && agg.unstable_dimension_frames != 0) asserts.fail("video: active dimensions were not stable");
    if (expect.require_hs_per_active_line && agg.hs_under_active_height_frames != 0) asserts.fail("video: fewer HS pulses than active lines");
    if (expect.min_hs_after_vs_cycles && agg.hs_after_vs_gap_min < expect.min_hs_after_vs_cycles) asserts.fail("video: HS occurred too soon after VS");
    if (expect.min_hs_to_de_gap_cycles && agg.hs_to_de_gap_min < expect.min_hs_to_de_gap_cycles) asserts.fail("video: DE asserted too soon after HS");
    if (expect.min_de_to_hs_gap_cycles && agg.de_to_hs_gap_min < expect.min_de_to_hs_gap_cycles) asserts.fail("video: HS occurred too soon after DE fell");
    if (expect.min_unique_colors && meta.unique_colors < expect.min_unique_colors) asserts.fail("video: unique color count below expectation");
    if (expect.min_nonzero_pixels && meta.nonzero_pixels < expect.min_nonzero_pixels) asserts.fail("video: nonzero pixel count below expectation");
    if (expect.min_changed_pixels && video.max_changed_pixels_from_previous() < expect.min_changed_pixels) asserts.fail("video: changed pixel count below expectation");
    if (expect.min_changed_frames && video.changed_frames() < expect.min_changed_frames) asserts.fail("video: changed frame count below expectation");
    if ((expect.min_refresh_hz || expect.max_refresh_hz) && expect.pixel_clock_hz > 0.0 && meta.total_pixel_clocks > 0) {
        const double refresh = expect.pixel_clock_hz / static_cast<double>(meta.total_pixel_clocks);
        if (expect.min_refresh_hz && refresh < expect.min_refresh_hz) asserts.fail("video: refresh below expected range");
        if (expect.max_refresh_hz && refresh > expect.max_refresh_hz) asserts.fail("video: refresh above expected range");
    }
}

static void validate_audio(Assertions& asserts, const Scenario& scenario, const AudioCapture& audio) {
    const auto& expect = scenario.audio_expect;
    const auto& stats = audio.stats();
    if (stats.samples < expect.min_samples) asserts.fail("audio: decoded sample count below expectation");
    if (expect.require_changing &&
        (stats.peak_to_peak_l < expect.min_peak_to_peak && stats.peak_to_peak_r < expect.min_peak_to_peak)) {
        asserts.fail("audio: samples did not change enough");
    }
    if (stats.clipped_samples > expect.max_clipped_samples) asserts.fail("audio: clipped sample count exceeded");
    if (expect.max_abs_dc_offset > 0.0 &&
        (std::fabs(stats.dc_offset_l) > expect.max_abs_dc_offset || std::fabs(stats.dc_offset_r) > expect.max_abs_dc_offset)) {
        asserts.fail("audio: DC offset exceeded");
    }
    if (expect.expected_mclk_lrck_ratio > 0.0 && stats.estimated_mclk_lrck_ratio > 0.0) {
        const double max_error = expect.max_mclk_lrck_ratio_error > 0.0 ? expect.max_mclk_lrck_ratio_error : 1.0;
        if (std::fabs(stats.estimated_mclk_lrck_ratio - expect.expected_mclk_lrck_ratio) > max_error) {
            asserts.fail("audio: MCLK/LRCK ratio outside expectation");
        }
    }
    if (expect.max_lrck_half_period_jitter > 0 && stats.lrck_half_period_mclk_max >= stats.lrck_half_period_mclk_min) {
        const auto jitter = stats.lrck_half_period_mclk_max - stats.lrck_half_period_mclk_min;
        if (jitter > expect.max_lrck_half_period_jitter) asserts.fail("audio: LRCK half-period jitter exceeded");
    }
}

static void validate_data(Assertions& asserts, const Scenario& scenario) {
    const auto& expect = scenario.data_expect;
    for (const auto& slot : scenario.slots) {
        if (expect.require_required_slots && slot.required && !slot.deferload && slot.loaded_size == 0) {
            asserts.fail("data: required slot " + std::to_string(slot.id) + " was not loaded");
        }
        const bool slot_file_available = !slot.file.empty() && std::filesystem::exists(slot.file);
        if (expect.require_all_file_slots_loaded && !slot.deferload && slot_file_available && slot.loaded_size == 0) {
            asserts.fail("data: slot " + std::to_string(slot.id) + " has a file but loaded zero bytes");
        }
        if (slot.has_expected_checksum && slot.loaded_size != 0 && slot.loaded_checksum != slot.expected_checksum) {
            asserts.fail("data: slot " + std::to_string(slot.id) + " checksum mismatch");
        }
        const bool validate_host_boot_load = slot.loaded_size != 0 && !slot.file.empty() && !slot.deferload;
        if (expect.require_readback_match && validate_host_boot_load && !slot.readback_attempted) {
            asserts.fail("data: slot " + std::to_string(slot.id) + " readback was not attempted");
        }
        if (slot.readback_attempted && !slot.readback_matches) {
            asserts.fail("data: slot " + std::to_string(slot.id) + " readback mismatch");
        }
        if (validate_host_boot_load && slot.observed_write_words != slot.loaded_words) {
            asserts.fail("data: slot " + std::to_string(slot.id) + " bridge write count mismatch");
        }
        if (validate_host_boot_load && slot.observed_first_write_address != slot.address) {
            asserts.fail("data: slot " + std::to_string(slot.id) + " first bridge write address mismatch");
        }
        if (validate_host_boot_load && slot.observed_last_write_address != slot.loaded_last_address) {
            asserts.fail("data: slot " + std::to_string(slot.id) + " last bridge write address mismatch");
        }
        if (validate_host_boot_load && slot.observed_write_address_errors != 0) {
            asserts.fail("data: slot " + std::to_string(slot.id) + " bridge write address stride mismatch");
        }
    }
    if (expect.expected_total_loaded_bytes && host_loaded_bytes(scenario.slots) != expect.expected_total_loaded_bytes) {
        asserts.fail("data: total loaded byte count mismatch");
    }
}

template <typename Bridge>
static void validate_bridge(Assertions& asserts, const Scenario& scenario, const Bridge& bridge) {
    const auto& expect = scenario.bridge_expect;
    const auto& stats = bridge.stats();
    if (expect.require_little_endian && !bridge.endian_little()) asserts.fail("bridge: endian mode was not little-endian");
    if (expect.require_slot_table && !bridge.slot_table_matches(scenario.slots)) asserts.fail("bridge: data-slot table shadow mismatch");
    if (expect.min_reads && stats.reads < expect.min_reads) asserts.fail("bridge: read count below expectation");
    if (expect.min_writes && stats.writes < expect.min_writes) asserts.fail("bridge: write count below expectation");
    if (expect.min_host_commands && stats.host_commands < expect.min_host_commands) asserts.fail("bridge: host command count below expectation");
    if (expect.min_target_commands && stats.target_commands < expect.min_target_commands) asserts.fail("bridge: target command count below expectation");
    if (stats.host_timeouts != 0) asserts.fail("bridge: host command timeout observed");
}

static void validate_host_commands(Assertions& asserts, const Scenario& scenario) {
    for (const auto& event : scenario.host_commands) {
        const auto label = event.name.empty() ? event.command_name : event.name;
        if (!event.executed) asserts.fail("host-command: event was not executed: " + label);
        if (is_savestate_save_event(event) && event.bytes == 0) asserts.fail("host-command: savestate save produced no blob: " + label);
    }
}

static void validate_reset(Assertions& asserts, const Scenario& scenario, const BootTrace& trace) {
    const auto& expect = scenario.reset_expect;
    if (expect.require_reset_enter && trace.reset_enter_cycle == 0) asserts.fail("reset: Reset Enter was not observed");
    if (expect.require_reset_exit && trace.reset_exit_cycle == 0) asserts.fail("reset: Reset Exit was not observed");
    if (expect.require_ready_to_run && trace.target_ready_cycle == 0) asserts.fail("reset: target Ready to Run was not observed");
    if (trace.reset_enter_cycle && trace.data_all_complete_cycle && trace.reset_enter_cycle > trace.data_all_complete_cycle) asserts.fail("reset: data completed before Reset Enter");
    if (trace.data_all_complete_cycle && trace.target_ready_cycle && trace.data_all_complete_cycle > trace.target_ready_cycle) asserts.fail("reset: Ready to Run occurred before data all-complete");
    if (trace.target_ready_cycle && trace.reset_exit_cycle && trace.target_ready_cycle > trace.reset_exit_cycle) asserts.fail("reset: Reset Exit occurred before Ready to Run");
    if (trace.reset_exit_cycle && trace.running_cycle && trace.reset_exit_cycle > trace.running_cycle) asserts.fail("reset: running status occurred before Reset Exit");
    if (expect.max_setup_cycles && trace.setup_cycle && trace.setup_cycle - trace.start_cycle > expect.max_setup_cycles) asserts.fail("reset: setup took too many cycles");
    if (expect.max_boot_cycles && trace.running_cycle && trace.running_cycle - trace.start_cycle > expect.max_boot_cycles) asserts.fail("reset: boot took too many cycles");
    if (trace.reset_enter_cycle && trace.reset_exit_cycle && trace.reset_exit_cycle >= trace.reset_enter_cycle) {
        const auto reset_hold_cycles = trace.reset_exit_cycle - trace.reset_enter_cycle;
        if (expect.min_reset_hold_cycles && reset_hold_cycles < expect.min_reset_hold_cycles) asserts.fail("reset: reset hold time below expectation");
        if (expect.max_reset_hold_cycles && reset_hold_cycles > expect.max_reset_hold_cycles) asserts.fail("reset: reset hold time exceeded expectation");
    }
    if (expect.max_reset_exit_to_running_cycles && trace.running_cycle && trace.reset_exit_cycle &&
        trace.running_cycle - trace.reset_exit_cycle > expect.max_reset_exit_to_running_cycles) {
        asserts.fail("reset: Reset Exit to running took too many cycles");
    }
}

static void validate_save(Assertions& asserts, const Scenario& scenario, const std::vector<SaveReport>& reports) {
    if (scenario.save_expect.require_nonvolatile_unload) {
        bool any = false;
        for (const auto& report : reports) {
            if (report.bytes > 0) any = true;
        }
        if (!any) asserts.fail("save: no nonvolatile save data was unloaded");
    }
    if (scenario.save_expect.require_roundtrip_match) {
        for (const auto& report : reports) {
            if (!report.matches_input) asserts.fail("save: unloaded slot " + std::to_string(report.id) + " did not match input");
        }
    }
}

static void validate_interact(Assertions& asserts, const Scenario& scenario, size_t interact_writes) {
    if (interact_writes < scenario.interact_expect.min_persistent_writes) asserts.fail("interact: persistent write count below expectation");
}

static void validate_input(Assertions& asserts, const Scenario& scenario, const InputDriver& inputs) {
    if (!scenario.inputs.empty() && scenario.input_expect.require_scripted_activity && !inputs.ever_active()) {
        asserts.fail("input: scripted input was never driven");
    }
    if (!scenario.inputs.empty() && scenario.input_expect.require_scripted_activity && !inputs.all_scripted_events_delivered()) {
        asserts.fail("input: not all scripted input pulses were delivered");
    }
}

template <typename Bridge>
static std::vector<ReadbackObservation> run_readbacks(Bridge& bridge, const Scenario& scenario, Assertions& asserts) {
    std::vector<ReadbackObservation> observations;
    for (const auto& expect : scenario.readbacks) {
        ReadbackObservation observation;
        observation.expect = expect;
        observation.observed = bridge.read32(expect.address);
        observation.ok = (observation.observed & expect.mask) == (expect.value & expect.mask);
        if (!observation.ok) {
            const auto name = expect.name.empty() ? hex32(expect.address) : expect.name;
            asserts.fail("bridge: readback mismatch for " + name);
        }
        observations.push_back(observation);
    }
    return observations;
}

int main(int argc, char** argv) {
    CliOptions opt;
    std::string phase = "startup";
    try {
        opt = parse_args(argc, argv);
        phase = "scenario";
        auto scenario = parse_scenario(opt.scenario_path);
        if (!opt.data_json.empty()) merge_slots(scenario.slots, parse_data_json(opt.data_json));
        if (!opt.interact_json.empty()) {
            auto scenario_interact = scenario.interact;
            scenario.interact = InteractModel{};
            scenario.interact.load_json(opt.interact_json);
            scenario.interact.append(scenario_interact);
        }
        for (const auto& [id, file] : opt.slot_overrides) apply_slot_file_override(scenario.slots, id, file);
        apply_data_expect_to_slots(scenario);
        if (opt.frames_override) scenario.frames = opt.frames_override;
        if (opt.timeout_cycles_override) scenario.timeout_cycles = opt.timeout_cycles_override;
        if (!opt.video_json.empty()) {
            const auto [w, h] = parse_video_json_dimensions(opt.video_json);
            if (w) scenario.expected_width = w;
            if (h) scenario.expected_height = h;
        }
        if (scenario.video_expect.active_width == 0) scenario.video_expect.active_width = scenario.expected_width;
        if (scenario.video_expect.active_height == 0) scenario.video_expect.active_height = scenario.expected_height;

        auto context = std::make_unique<VerilatedContext>();
        context->commandArgs(argc, argv);
        auto top = std::make_unique<Vcore_top>(context.get());

        VideoCapture video;
        AudioCapture audio;
        InputDriver inputs;
        for (const auto& ev : scenario.inputs) inputs.add_event(ev);
        video.set_expected(scenario.expected_width, scenario.expected_height);
        if (!opt.dump_frames.empty()) video.set_dump_dir(opt.dump_frames);
        if (!opt.dump_audio.empty()) audio.set_wav_path(opt.dump_audio);
        if (!opt.audio_stats.empty()) audio.set_stats_path(opt.audio_stats);

        SimHarness sim(context.get(), top.get(), &video, &audio, &inputs);

#if VM_TRACE
        std::unique_ptr<VerilatedFstC> trace;
        if (std::getenv("APFSIM_WAVES")) {
            context->traceEverOn(true);
            trace = std::make_unique<VerilatedFstC>();
            top->trace(trace.get(), 99);
            trace->open(std::getenv("APFSIM_WAVE_PATH") ? std::getenv("APFSIM_WAVE_PATH") : "dump.fst");
            sim.set_trace(trace.get());
        }
#endif

        top->clk_74a = 0;
        top->clk_74b = 0;
        inputs.drive(top.get());
        BridgeHost<Vcore_top> bridge(top.get(), [&](uint64_t n) { sim.cycles(n); }, [&]() { return sim.cycles_74a(); });
        bridge.set_verbose(opt.verbose_bridge);
        if (opt.bridge_endian != "little" && opt.bridge_endian != "big") throw std::runtime_error("bridge endian must be little or big");
        bridge.set_endian_little(opt.bridge_endian != "big");
        if (opt.bridge_read_latency_cycles != UINT64_MAX) bridge.set_read_latency_cycles(opt.bridge_read_latency_cycles);
        if (opt.write_idle_cycles) bridge.set_write_idle_cycles(opt.write_idle_cycles);
        if (opt.bridge_write_strobe_cycles) bridge.set_write_strobe_cycles(opt.bridge_write_strobe_cycles);
        if (!opt.bridge_log.empty()) bridge.set_log_path(opt.bridge_log);
        if (!opt.bridge_trace.empty()) bridge.set_trace_path(opt.bridge_trace);
        bridge.reset_lines();

        size_t interact_writes = 0;
        std::vector<SavestateReport> savestate_reports;
        BootTrace boot_trace;
        if (!opt.no_boot) {
            phase = "boot";
            ApfHost<Vcore_top> host(bridge, [&]() { return sim.cycles_74a(); });
            host.boot(scenario.slots, [&]() {
                interact_writes = scenario.interact.write_persistent_defaults(bridge, opt.interact_verify_readback);
            });
            boot_trace = host.trace();
            if (interact_writes) {
                std::cout << "PASS interact: " << interact_writes
                          << " persistent writes "
                          << (opt.interact_verify_readback ? "verified" : "applied")
                          << "\n";
            }
            video.reset_capture();
            audio.reset_capture();
        }

        if (!opt.dump_savestates.empty()) fs::create_directories(opt.dump_savestates);
        phase = "host_commands";
        execute_due_host_commands(bridge, scenario, savestate_reports, opt.dump_savestates, 0, sim.cycles_74a());

        if (opt.interactive) {
            phase = "play";
            const int rc = run_interactive_loop(sim, video, inputs, bridge, scenario, savestate_reports, opt);

            const MemoryActivitySnapshot memory_activity = capture_memory_activity(top.get());
            top->final();
            phase = "audio";
            audio.finish();
#if VM_TRACE
            if (trace) trace->close();
#endif
            phase = "save";
            std::vector<SaveReport> save_reports;
            if (!opt.dump_saves.empty()) save_reports = bridge.unload_nonvolatile(scenario.slots, opt.dump_saves);
            write_bridge_summary_json(opt.bridge_summary, bridge, scenario.slots);
            std::vector<ReadbackObservation> readback_observations;
            std::vector<std::string> failures;
            write_result_json(opt.result_json, rc == 0, rc == 0 ? "" : "play", "", scenario, scenario.slots, video, audio, inputs, bridge, boot_trace, save_reports, savestate_reports, readback_observations, memory_activity, failures, interact_writes, opt.interact_verify_readback, sim.cycles_74a());
            write_video_shape_json(opt.video_shape_json, opt.result_json, rc == 0, scenario, video);
            std::cout << "PASS play: frames=" << video.frames_completed() << " cycles_74a=" << sim.cycles_74a() << "\n";
            return rc;
        }

        uint64_t last_frame_start = video.frames_started();
        inputs.on_frame(last_frame_start);
        uint64_t next_target_service_cycle = opt.target_service_interval_cycles ? sim.cycles_74a() + opt.target_service_interval_cycles : 0;
        phase = "run";
        while (!context->gotFinish() && video.frames_completed() < scenario.frames && sim.cycles_74a() < scenario.timeout_cycles) {
            sim.cycle();
            if (opt.target_service_interval_cycles && sim.cycles_74a() >= next_target_service_cycle) {
                bridge.service_target_commands(scenario.slots, 4);
                next_target_service_cycle = sim.cycles_74a() + opt.target_service_interval_cycles;
            }
            execute_due_host_commands(bridge, scenario, savestate_reports, opt.dump_savestates, last_frame_start, sim.cycles_74a());
            if (video.frames_started() != last_frame_start) {
                last_frame_start = video.frames_started();
                inputs.on_frame(last_frame_start);
                execute_due_host_commands(bridge, scenario, savestate_reports, opt.dump_savestates, last_frame_start, sim.cycles_74a());
            }
        }

        const MemoryActivitySnapshot memory_activity = capture_memory_activity(top.get());
        top->final();
        phase = "audio";
        audio.finish();
#if VM_TRACE
        if (trace) trace->close();
#endif

        phase = "assert";
        Assertions asserts;
        std::vector<ReadbackObservation> readback_observations = run_readbacks(bridge, scenario, asserts);

        phase = "save";
        std::vector<SaveReport> save_reports;
        if (!opt.dump_saves.empty()) save_reports = bridge.unload_nonvolatile(scenario.slots, opt.dump_saves);
        write_bridge_summary_json(opt.bridge_summary, bridge, scenario.slots);

        validate_video(asserts, scenario, video);
        validate_audio(asserts, scenario, audio);
        validate_data(asserts, scenario);
        validate_bridge(asserts, scenario, bridge);
        if (!opt.no_boot) validate_reset(asserts, scenario, boot_trace);
        validate_save(asserts, scenario, save_reports);
        validate_interact(asserts, scenario, interact_writes);
        validate_input(asserts, scenario, inputs);
        validate_host_commands(asserts, scenario);

        if (!asserts.ok()) {
            asserts.print();
            print_failure_diagnostics("assert", opt.result_json, video, audio, bridge, sim.cycles_74a());
            write_result_json(opt.result_json, false, "assert", format_failure_summary(asserts), scenario, scenario.slots, video, audio, inputs, bridge, boot_trace, save_reports, savestate_reports, readback_observations, memory_activity, asserts.failures(), interact_writes, opt.interact_verify_readback, sim.cycles_74a());
            write_video_shape_json(opt.video_shape_json, opt.result_json, false, scenario, video);
            return 1;
        }

        write_result_json(opt.result_json, true, "", "", scenario, scenario.slots, video, audio, inputs, bridge, boot_trace, save_reports, savestate_reports, readback_observations, memory_activity, asserts.failures(), interact_writes, opt.interact_verify_readback, sim.cycles_74a());
        write_video_shape_json(opt.video_shape_json, opt.result_json, true, scenario, video);
        const auto& meta = video.last_metadata();
        const auto& astats = audio.stats();
        std::cout << "PASS video: " << video.frames_completed() << " frames, " << meta.active_width << "x" << meta.active_height << " active\n";
        std::cout << "PASS audio: " << astats.samples << " stereo samples\n";
        if (!scenario.inputs.empty()) std::cout << "PASS input: scripted pulses delivered\n";
        std::cout << "STATUS running\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "apfsim error: " << e.what() << "\n";
        write_failure_result(opt.result_json, phase, e.what());
        return 2;
    }
}
