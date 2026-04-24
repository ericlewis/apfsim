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
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
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
    uint64_t cycles_74a) {
    if (path.empty()) return;
    if (!path.parent_path().empty()) fs::create_directories(path.parent_path());
    std::ofstream out(path);
    if (!out) return;
    const auto& meta = video.last_metadata();
    const auto& astats = audio.stats();
    out << "{\n";
    out << "  \"ok\": " << (ok ? "true" : "false") << ",\n";
    out << "  \"scenario\": \"" << json_escape(scenario.name) << "\",\n";
    out << "  \"failed_phase\": \"" << json_escape(failed_phase) << "\",\n";
    out << "  \"message\": \"" << json_escape(message) << "\",\n";
    out << "  \"status\": \"" << (ok ? "running" : "failed") << "\",\n";
    out << "  \"cycles_74a\": " << cycles_74a << ",\n";
    out << "  \"boot\": { \"ok\": " << (ok ? "true" : "false")
        << ", \"last_host_command\": \"" << hex32(bridge.last_host_command())
        << "\", \"last_host_result\": \"" << hex32(bridge.last_host_result())
        << "\", \"last_host_status_word\": \"" << hex32(bridge.last_host_status_word())
        << "\", \"last_target_word\": \"" << hex32(bridge.last_target_word()) << "\" },\n";
    out << "  \"data\": { \"slots\": [\n";
    for (size_t i = 0; i < slots.size(); ++i) {
        const auto& slot = slots[i];
        out << "    { \"id\": " << slot.id
            << ", \"name\": \"" << json_escape(slot.name)
            << "\", \"address\": \"" << hex32(slot.address)
            << "\", \"file\": \"" << json_escape(slot.file.string())
            << "\", \"loaded_size\": " << slot.loaded_size
            << ", \"nonvolatile\": " << (slot.nonvolatile ? "true" : "false")
            << ", \"deferload\": " << (slot.deferload ? "true" : "false") << " }";
        out << (i + 1 == slots.size() ? "\n" : ",\n");
    }
    out << "  ] },\n";
    out << "  \"video\": { \"frames_requested\": " << scenario.frames
        << ", \"frames_completed\": " << video.frames_completed()
        << ", \"frames_started\": " << video.frames_started()
        << ", \"active_width\": " << meta.active_width
        << ", \"active_height\": " << meta.active_height
        << ", \"hs_pulses\": " << meta.hs_pulses
        << ", \"vs_pulses\": " << meta.vs_pulses
        << ", \"errors\": " << video.errors() << " },\n";
    out << "  \"audio\": { \"sample_rate\": " << astats.sample_rate
        << ", \"samples\": " << astats.samples
        << ", \"min_l\": " << astats.min_l
        << ", \"max_l\": " << astats.max_l
        << ", \"min_r\": " << astats.min_r
        << ", \"max_r\": " << astats.max_r
        << ", \"dc_offset_l\": " << astats.dc_offset_l
        << ", \"dc_offset_r\": " << astats.dc_offset_r
        << ", \"clipped_samples\": " << astats.clipped_samples << " },\n";
    out << "  \"input\": { \"scripted_events\": " << scenario.inputs.size()
        << ", \"ever_active\": " << (inputs.ever_active() ? "true" : "false") << " }\n";
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
        if (!opt.no_boot) {
            phase = "boot";
            ApfHost<Vcore_top> host(bridge);
            host.boot(scenario.slots, [&]() {
                interact_writes = scenario.interact.write_persistent_defaults(bridge);
            });
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
        if (video.frames_completed() < scenario.frames) asserts.fail("video did not produce requested frame count before timeout");
        if (video.errors() != 0) asserts.fail("video protocol/dimension errors detected");
        if (scenario.inputs.size() && !inputs.ever_active()) asserts.fail("scripted input was never driven");
        if (audio.sample_count() == 0) asserts.fail("audio capture saw no decoded samples");

        phase = "save";
        if (!opt.dump_saves.empty()) bridge.unload_nonvolatile(scenario.slots, opt.dump_saves);

        if (!asserts.ok()) {
            asserts.print();
            write_result_json(opt.result_json, false, "assert", "simulation assertions failed", scenario, scenario.slots, video, audio, inputs, bridge, sim.cycles_74a());
            return 1;
        }

        write_result_json(opt.result_json, true, "", "", scenario, scenario.slots, video, audio, inputs, bridge, sim.cycles_74a());
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
