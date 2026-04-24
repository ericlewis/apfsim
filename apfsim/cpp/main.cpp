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

#include <cstdlib>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
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
    fs::path result_json;
    fs::path bridge_log;
    std::vector<std::pair<uint16_t, fs::path>> slot_overrides;
    uint64_t frames_override = 0;
    uint64_t timeout_cycles_override = 0;
    uint64_t write_idle_cycles = 0;
    bool verbose_bridge = false;
    bool no_boot = false;
};

static void usage(const char* argv0) {
    std::cerr << "usage: " << argv0 << " [--scenario file.yml] [--frames n] [--slot id=file] "
              << "[--data data.json] [--video video.json] [--interact interact.json] "
              << "[--dump-frames dir] [--dump-audio out.wav] [--audio-stats stats.json] "
              << "[--dump-saves dir] [--result-json result.json] [--bridge-log bridge.log]\n";
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
        else if (arg == "--result-json") opt.result_json = need_value("--result-json");
        else if (arg == "--bridge-log") opt.bridge_log = need_value("--bridge-log");
        else if (arg == "--frames") opt.frames_override = parse_u64(need_value("--frames"));
        else if (arg == "--timeout-cycles") opt.timeout_cycles_override = parse_u64(need_value("--timeout-cycles"));
        else if (arg == "--write-idle-cycles") opt.write_idle_cycles = parse_u64(need_value("--write-idle-cycles"));
        else if (arg == "--slot") {
            const auto spec = need_value("--slot");
            const auto eq = spec.find('=');
            if (eq == std::string::npos) throw std::runtime_error("slot override must be id=file");
            opt.slot_overrides.emplace_back(static_cast<uint16_t>(parse_u64(spec.substr(0, eq))), spec.substr(eq + 1));
        } else if (arg == "--verbose-bridge") opt.verbose_bridge = true;
        else if (arg == "--no-boot") opt.no_boot = true;
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
    out << "  \"failed_phase\": \"" << json_escape(phase) << "\",\n";
    out << "  \"message\": \"" << json_escape(message) << "\"\n";
    out << "}\n";
}

struct ReadbackObservation {
    BridgeReadbackExpect expect;
    uint32_t observed = 0;
    bool ok = false;
};

static std::string format_failure_summary(const Assertions& asserts) {
    std::ostringstream ss;
    const auto& failures = asserts.failures();
    for (size_t i = 0; i < failures.size(); ++i) {
        if (i) ss << "; ";
        ss << failures[i];
    }
    return ss.str();
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
    const std::vector<ReadbackObservation>& readbacks,
    const std::vector<std::string>& failures,
    size_t interact_writes,
    uint64_t cycles_74a) {
    if (path.empty()) return;
    if (!path.parent_path().empty()) fs::create_directories(path.parent_path());
    std::ofstream out(path);
    if (!out) return;
    const auto& meta = video.last_metadata();
    const auto& astats = audio.stats();
    const bool boot_ok = boot_trace.running_cycle != 0;
    out << "{\n";
    out << "  \"ok\": " << (ok ? "true" : "false") << ",\n";
    out << "  \"scenario\": \"" << json_escape(scenario.name) << "\",\n";
    out << "  \"failed_phase\": \"" << json_escape(failed_phase) << "\",\n";
    out << "  \"message\": \"" << json_escape(message) << "\",\n";
    out << "  \"status\": \"" << (ok ? "running" : "failed") << "\",\n";
    out << "  \"cycles_74a\": " << cycles_74a << ",\n";
    out << "  \"boot\": { \"ok\": " << (boot_ok ? "true" : "false")
        << ", \"last_host_command\": \"" << hex32(bridge.last_host_command())
        << "\", \"last_host_result\": \"" << hex32(bridge.last_host_result())
        << "\", \"last_host_status_word\": \"" << hex32(bridge.last_host_status_word())
        << "\", \"last_target_word\": \"" << hex32(bridge.last_target_word())
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
            << "\", \"file\": \"" << json_escape(slot.file.string())
            << "\", \"loaded_size\": " << slot.loaded_size
            << ", \"loaded_checksum\": \"" << hex32(static_cast<uint32_t>(slot.loaded_checksum & 0xFFFFFFFFu)) << "\""
            << ", \"nonvolatile\": " << (slot.nonvolatile ? "true" : "false")
            << ", \"deferload\": " << (slot.deferload ? "true" : "false") << " }";
        out << (i + 1 == slots.size() ? "\n" : ",\n");
    }
    out << "  ] },\n";
    out << "  \"video\": { \"frames_requested\": " << scenario.frames
        << ", \"frames_completed\": " << video.frames_completed()
        << ", \"frames_started\": " << video.frames_started()
        << ", \"active_width\": " << meta.active_width
        << ", \"active_width_min\": " << meta.active_width_min
        << ", \"active_height\": " << meta.active_height
        << ", \"total_pixel_clocks\": " << meta.total_pixel_clocks
        << ", \"pixels_per_line_min\": " << meta.pixels_per_line_min
        << ", \"pixels_per_line_max\": " << meta.pixels_per_line_max
        << ", \"hs_pulses\": " << meta.hs_pulses
        << ", \"vs_pulses\": " << meta.vs_pulses
        << ", \"hs_after_vs_gap_min\": " << meta.hs_after_vs_gap_min
        << ", \"hs_to_de_gap_min\": " << meta.hs_to_de_gap_min
        << ", \"de_to_hs_gap_min\": " << meta.de_to_hs_gap_min
        << ", \"rgb_when_de_low_errors\": " << meta.rgb_when_de_low_errors
        << ", \"pulse_width_errors\": " << meta.pulse_width_errors
        << ", \"skip_errors\": " << meta.skip_errors
        << ", \"unique_colors\": " << meta.unique_colors
        << ", \"nonzero_pixels\": " << meta.nonzero_pixels
        << ", \"changed_pixels_from_previous\": " << meta.changed_pixels_from_previous
        << ", \"frame_hash\": \"" << hex32(static_cast<uint32_t>(meta.frame_hash >> 32))
        << hex32(static_cast<uint32_t>(meta.frame_hash)).substr(2) << "\""
        << ", \"errors\": " << video.errors() << " },\n";
    out << "  \"audio\": { \"sample_rate\": " << astats.sample_rate
        << ", \"samples\": " << astats.samples
        << ", \"min_l\": " << astats.min_l
        << ", \"max_l\": " << astats.max_l
        << ", \"min_r\": " << astats.min_r
        << ", \"max_r\": " << astats.max_r
        << ", \"peak_to_peak_l\": " << astats.peak_to_peak_l
        << ", \"peak_to_peak_r\": " << astats.peak_to_peak_r
        << ", \"dc_offset_l\": " << astats.dc_offset_l
        << ", \"dc_offset_r\": " << astats.dc_offset_r
        << ", \"clipped_samples\": " << astats.clipped_samples << " },\n";
    out << "  \"interact\": { \"persistent_writes\": " << interact_writes << " },\n";
    out << "  \"input\": { \"scripted_events\": " << scenario.inputs.size()
        << ", \"ever_active\": " << (inputs.ever_active() ? "true" : "false") << " },\n";
    out << "  \"save\": { \"reports\": [\n";
    for (size_t i = 0; i < save_reports.size(); ++i) {
        const auto& report = save_reports[i];
        out << "    { \"id\": " << report.id
            << ", \"bytes\": " << report.bytes
            << ", \"path\": \"" << json_escape(report.path.string())
            << "\", \"matches_input\": " << (report.matches_input ? "true" : "false") << " }";
        out << (i + 1 == save_reports.size() ? "\n" : ",\n");
    }
    out << "  ] },\n";
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
        video_->sample(top_);
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

static void merge_slots(std::vector<DataSlot>& base, const std::vector<DataSlot>& extra) {
    for (const auto& slot : extra) {
        if (auto* existing = find_slot(base, slot.id)) {
            const auto existing_file = existing->file;
            *existing = slot;
            if (existing->file.empty()) existing->file = existing_file;
        } else {
            base.push_back(slot);
        }
    }
}

static uint64_t total_loaded_bytes(const std::vector<DataSlot>& slots) {
    uint64_t total = 0;
    for (const auto& slot : slots) total += slot.loaded_size;
    return total;
}

static void validate_video(Assertions& asserts, const Scenario& scenario, const VideoCapture& video) {
    const auto& expect = scenario.video_expect;
    const auto& meta = video.last_metadata();
    const uint64_t required_frames = std::max<uint64_t>(scenario.frames, expect.min_frames);
    if (video.frames_completed() < required_frames) asserts.fail("video: did not produce required frame count");
    if (expect.active_width && meta.active_width != expect.active_width) asserts.fail("video: active width mismatch");
    if (expect.active_height && meta.active_height != expect.active_height) asserts.fail("video: active height mismatch");
    if (video.errors() > expect.max_errors) asserts.fail("video: protocol error count exceeded");
    if (expect.require_rgb_zero_when_de_low && meta.rgb_when_de_low_errors != 0) asserts.fail("video: RGB was nonzero while DE was low");
    if (expect.require_single_cycle_sync && meta.pulse_width_errors != 0) asserts.fail("video: HS/VS pulse width was not one pixel clock");
    if (expect.require_skip_only_during_de && meta.skip_errors != 0) asserts.fail("video: SKIP asserted while DE was low");
    if (expect.min_hs_after_vs_cycles && meta.hs_after_vs_gap_min < expect.min_hs_after_vs_cycles) asserts.fail("video: HS occurred too soon after VS");
    if (expect.min_hs_to_de_gap_cycles && meta.hs_to_de_gap_min < expect.min_hs_to_de_gap_cycles) asserts.fail("video: DE asserted too soon after HS");
    if (expect.min_de_to_hs_gap_cycles && meta.de_to_hs_gap_min < expect.min_de_to_hs_gap_cycles) asserts.fail("video: HS occurred too soon after DE fell");
    if (expect.min_unique_colors && meta.unique_colors < expect.min_unique_colors) asserts.fail("video: unique color count below expectation");
    if (expect.min_nonzero_pixels && meta.nonzero_pixels < expect.min_nonzero_pixels) asserts.fail("video: nonzero pixel count below expectation");
    if (expect.min_changed_pixels && meta.changed_pixels_from_previous < expect.min_changed_pixels) asserts.fail("video: changed pixel count below expectation");
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
}

static void validate_data(Assertions& asserts, const Scenario& scenario) {
    const auto& expect = scenario.data_expect;
    for (const auto& slot : scenario.slots) {
        if (expect.require_required_slots && slot.required && !slot.deferload && slot.loaded_size == 0) {
            asserts.fail("data: required slot " + std::to_string(slot.id) + " was not loaded");
        }
        if (expect.require_all_file_slots_loaded && !slot.deferload && !slot.file.empty() && slot.loaded_size == 0) {
            asserts.fail("data: slot " + std::to_string(slot.id) + " has a file but loaded zero bytes");
        }
    }
    if (expect.expected_total_loaded_bytes && total_loaded_bytes(scenario.slots) != expect.expected_total_loaded_bytes) {
        asserts.fail("data: total loaded byte count mismatch");
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
        if (!opt.interact_json.empty()) scenario.interact.load_json(opt.interact_json);
        for (const auto& [id, file] : opt.slot_overrides) apply_slot_file_override(scenario.slots, id, file);
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
        BridgeHost<Vcore_top> bridge(top.get(), [&](uint64_t n) { sim.cycles(n); });
        bridge.set_verbose(opt.verbose_bridge);
        if (opt.write_idle_cycles) bridge.set_write_idle_cycles(opt.write_idle_cycles);
        if (!opt.bridge_log.empty()) bridge.set_log_path(opt.bridge_log);
        bridge.reset_lines();

        size_t interact_writes = 0;
        BootTrace boot_trace;
        if (!opt.no_boot) {
            phase = "boot";
            ApfHost<Vcore_top> host(bridge, [&]() { return sim.cycles_74a(); });
            host.boot(scenario.slots, [&]() {
                interact_writes = scenario.interact.write_persistent_defaults(bridge);
            });
            boot_trace = host.trace();
            if (interact_writes) std::cout << "PASS interact: " << interact_writes << " persistent writes verified\n";
            video.reset_capture();
            audio.reset_capture();
        }

        uint64_t last_frame_start = video.frames_started();
        inputs.on_frame(last_frame_start);
        phase = "run";
        while (!context->gotFinish() && video.frames_completed() < scenario.frames && sim.cycles_74a() < scenario.timeout_cycles) {
            sim.cycle();
            if (video.frames_started() != last_frame_start) {
                last_frame_start = video.frames_started();
                inputs.on_frame(last_frame_start);
            }
        }

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

        validate_video(asserts, scenario, video);
        validate_audio(asserts, scenario, audio);
        validate_data(asserts, scenario);
        if (!opt.no_boot) validate_reset(asserts, scenario, boot_trace);
        validate_save(asserts, scenario, save_reports);
        validate_interact(asserts, scenario, interact_writes);
        validate_input(asserts, scenario, inputs);

        if (!asserts.ok()) {
            asserts.print();
            write_result_json(opt.result_json, false, "assert", format_failure_summary(asserts), scenario, scenario.slots, video, audio, inputs, bridge, boot_trace, save_reports, readback_observations, asserts.failures(), interact_writes, sim.cycles_74a());
            return 1;
        }

        write_result_json(opt.result_json, true, "", "", scenario, scenario.slots, video, audio, inputs, bridge, boot_trace, save_reports, readback_observations, asserts.failures(), interact_writes, sim.cycles_74a());
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
