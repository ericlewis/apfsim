#pragma once

#include "apf_commands.hpp"
#include "data_slots.hpp"
#include "sim_time.hpp"

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace apfsim {

struct SaveReport {
    uint16_t id = 0;
    size_t bytes = 0;
    std::filesystem::path path;
    bool matches_input = false;
};

struct BootTrace {
    uint64_t start_cycle = 0;
    uint64_t setup_cycle = 0;
    uint64_t reset_enter_cycle = 0;
    uint64_t slot_table_cycle = 0;
    uint64_t data_load_complete_cycle = 0;
    uint64_t data_all_complete_cycle = 0;
    uint64_t rtc_cycle = 0;
    uint64_t target_ready_cycle = 0;
    uint64_t before_reset_exit_cycle = 0;
    uint64_t reset_exit_cycle = 0;
    uint64_t running_cycle = 0;
    std::vector<std::string> events;
};

template <typename Top>
class BridgeHost {
public:
    using CycleFn = std::function<void(uint64_t)>;

    BridgeHost(Top* top, CycleFn cycle_fn) : top_(top), cycle_fn_(std::move(cycle_fn)) {}

    void reset_lines() {
        top_->bridge_addr = 0;
        top_->bridge_rd = 0;
        top_->bridge_wr = 0;
        top_->bridge_wr_data = 0;
        top_->bridge_endian_little = 1;
    }

    void set_verbose(bool verbose) { verbose_ = verbose; }
    void set_write_idle_cycles(uint64_t cycles) { write_idle_cycles_ = cycles; }
    void set_log_path(const std::filesystem::path& path) {
        if (path.empty()) return;
        if (!path.parent_path().empty()) std::filesystem::create_directories(path.parent_path());
        log_.open(path);
        if (log_) log_ << "apfsim bridge log\n";
    }

    uint16_t last_host_command() const { return last_host_command_; }
    uint16_t last_host_result() const { return last_host_result_; }
    uint32_t last_host_status_word() const { return last_host_status_word_; }
    uint32_t last_target_word() const { return last_target_word_; }

    void idle_cycles(uint64_t n) {
        top_->bridge_rd = 0;
        top_->bridge_wr = 0;
        cycle_fn_(n);
    }

    void write32(uint32_t addr, uint32_t data) {
        if (verbose_) std::cout << "BRIDGE W " << hex32(addr) << " " << hex32(data) << "\n";
        top_->bridge_addr = addr;
        top_->bridge_wr_data = data;
        top_->bridge_wr = 1;
        top_->bridge_rd = 0;
        cycle_fn_(1);
        top_->bridge_wr = 0;
        top_->bridge_wr_data = 0;
        idle_cycles(write_idle_cycles_);
    }

    uint32_t read32(uint32_t addr) {
        top_->bridge_addr = addr;
        top_->bridge_rd = 1;
        top_->bridge_wr = 0;
        cycle_fn_(1);
        top_->bridge_rd = 0;
        idle_cycles(read_latency_cycles_);
        const auto data = static_cast<uint32_t>(top_->bridge_rd_data);
        if (verbose_) std::cout << "BRIDGE R " << hex32(addr) << " -> " << hex32(data) << "\n";
        return data;
    }

    void burst_write(uint32_t base, const std::vector<uint8_t>& bytes) {
        for (size_t i = 0; i < bytes.size(); i += 4) {
            uint32_t word = 0;
            for (size_t b = 0; b < 4 && i + b < bytes.size(); ++b) {
                word |= static_cast<uint32_t>(bytes[i + b]) << (8 * b);
            }
            write32(base + static_cast<uint32_t>(i), word);
        }
    }

    std::vector<uint8_t> burst_read(uint32_t base, size_t size) {
        std::vector<uint8_t> out(size);
        for (size_t i = 0; i < size; i += 4) {
            const uint32_t word = read32(base + static_cast<uint32_t>(i));
            for (size_t b = 0; b < 4 && i + b < size; ++b) {
                out[i + b] = static_cast<uint8_t>((word >> (8 * b)) & 0xFFu);
            }
        }
        return out;
    }

    uint16_t host_command(uint16_t cmd, uint32_t p0 = 0, uint32_t p1 = 0, uint32_t p2 = 0, uint32_t p3 = 0, int timeout_polls = 1000) {
        last_host_command_ = cmd;
        log_event("HOST CM " + std::string(apf::command_name(cmd)) + " cmd=" + hex32(cmd) +
                  " p0=" + hex32(p0) + " p1=" + hex32(p1) + " p2=" + hex32(p2) + " p3=" + hex32(p3));
        write32(apf::kCommandBase + apf::kHostParam0Offset, p0);
        write32(apf::kCommandBase + apf::kHostParam1Offset, p1);
        write32(apf::kCommandBase + apf::kHostParam2Offset, p2);
        write32(apf::kCommandBase + apf::kHostParam3Offset, p3);
        write32(apf::kCommandBase + apf::kHostStatusOffset, apf::magic_cmd(cmd));
        for (int i = 0; i < timeout_polls; ++i) {
            const uint32_t status = read32(apf::kCommandBase + apf::kHostStatusOffset);
            last_host_status_word_ = status;
            if (apf::is_ok(status)) {
                const uint16_t result = apf::low16(status);
                last_host_result_ = result;
                if (verbose_) std::cout << "APF host command " << apf::command_name(cmd) << " -> " << result << "\n";
                log_event("HOST OK " + std::string(apf::command_name(cmd)) + " result=" + hex32(result));
                return result;
            }
            idle_cycles(1);
        }
        log_event("HOST TIMEOUT " + std::string(apf::command_name(cmd)));
        throw std::runtime_error("APF host command timed out: " + std::to_string(cmd));
    }

    uint16_t request_status() {
        return host_command(apf::kRequestStatus);
    }

    void poll_status_until(uint16_t expected, int timeout_polls = 5000) {
        for (int i = 0; i < timeout_polls; ++i) {
            const auto status = request_status();
            if (status == expected) return;
            if (expected == apf::kStatusSetup && (status == apf::kStatusIdle || status == apf::kStatusRunning)) return;
            idle_cycles(8);
        }
        throw std::runtime_error(std::string("status did not reach ") + apf::status_name(expected));
    }

    void wait_target_ready_to_run(int timeout_polls = 5000) {
        for (int i = 0; i < timeout_polls; ++i) {
            const uint32_t word = read32(apf::kTargetBase);
            last_target_word_ = word;
            if ((apf::is_target_cmd(word) || apf::is_cmd(word)) && apf::low16(word) == apf::kTargetReadyToRun) {
                log_event("TARGET CM Ready to Run word=" + hex32(word));
                write32(apf::kTargetBase, apf::target_magic_ok(0));
                log_event("TARGET OK Ready to Run");
                return;
            }
            idle_cycles(8);
        }
        throw std::runtime_error("target Ready to Run command not observed");
    }

    void populate_slot_table(const std::vector<DataSlot>& slots) {
        log_event("DATASLOT table populate entries=" + std::to_string(slots.size()));
        for (size_t i = 0; i < 32; ++i) {
            write32(apf::kDataSlotTableBase + static_cast<uint32_t>(i * 8), 0);
            write32(apf::kDataSlotTableBase + static_cast<uint32_t>(i * 8 + 4), 0);
        }
        for (size_t i = 0; i < slots.size() && i < 32; ++i) {
            write32(apf::kDataSlotTableBase + static_cast<uint32_t>(i * 8), slots[i].id);
            write32(apf::kDataSlotTableBase + static_cast<uint32_t>(i * 8 + 4), static_cast<uint32_t>(slots[i].loaded_size));
        }
    }

    void load_slot(DataSlot& slot) {
        if (slot.deferload || slot.file.empty()) return;
        const auto bytes = read_binary_file(slot.file);
        if (slot.size_exact && bytes.size() != slot.size_exact) {
            throw std::runtime_error("slot " + std::to_string(slot.id) + " size mismatch");
        }
        if (slot.size_maximum && bytes.size() > slot.size_maximum) {
            throw std::runtime_error("slot " + std::to_string(slot.id) + " exceeds maximum size");
        }
        slot.loaded_size = bytes.size();
        slot.loaded_checksum = fnv1a64(bytes);
        log_event("DATASLOT load begin id=" + std::to_string(slot.id) + " bytes=" + std::to_string(bytes.size()) +
                  " address=" + hex32(slot.address) + " file=" + slot.file.string());
        host_command(apf::kDataSlotRequestWrite, slot.id, static_cast<uint32_t>(bytes.size()), slot.address, 0);
        burst_write(slot.address, bytes);
        log_event("DATASLOT load done id=" + std::to_string(slot.id) + " writes32=" + std::to_string((bytes.size() + 3) / 4));
        std::cout << "PASS data: slot " << slot.id << " loaded " << bytes.size() << " bytes at " << hex32(slot.address) << "\n";
    }

    std::vector<SaveReport> unload_nonvolatile(const std::vector<DataSlot>& slots, const std::filesystem::path& dir) {
        std::vector<SaveReport> reports;
        if (dir.empty()) return reports;
        std::filesystem::create_directories(dir);
        for (const auto& slot : slots) {
            if (!slot.nonvolatile || slot.loaded_size == 0) continue;
            const auto bytes = burst_read(slot.address, slot.loaded_size);
            const auto path = dir / ("slot_" + std::to_string(slot.id) + ".bin");
            write_binary_file(path, bytes);
            SaveReport report;
            report.id = slot.id;
            report.bytes = bytes.size();
            report.path = path;
            if (!slot.file.empty()) {
                const auto input = read_binary_file(slot.file);
                report.matches_input = input == bytes;
            }
            reports.push_back(report);
            log_event("SAVE unload id=" + std::to_string(slot.id) + " bytes=" + std::to_string(bytes.size()) + " path=" + path.string());
            std::cout << "PASS save: slot " << slot.id << " unloaded " << bytes.size() << " bytes\n";
        }
        return reports;
    }

    void set_read_latency_cycles(uint64_t cycles) { read_latency_cycles_ = cycles; }

private:
    void log_event(const std::string& msg) {
        if (log_) log_ << msg << "\n";
    }

    Top* top_ = nullptr;
    CycleFn cycle_fn_;
    uint64_t read_latency_cycles_ = 2;
    uint64_t write_idle_cycles_ = 1;
    bool verbose_ = false;
    std::ofstream log_;
    uint16_t last_host_command_ = 0;
    uint16_t last_host_result_ = 0;
    uint32_t last_host_status_word_ = 0;
    uint32_t last_target_word_ = 0;
};

template <typename Top>
class ApfHost {
public:
    using NowFn = std::function<uint64_t()>;

    explicit ApfHost(BridgeHost<Top>& bridge, NowFn now_fn = {}) : bridge_(bridge), now_fn_(std::move(now_fn)) {}

    void boot(std::vector<DataSlot>& slots, const std::function<void()>& before_reset_exit = {}) {
        trace_ = {};
        trace_.start_cycle = now();
        trace_.events.push_back("boot_start");
        bridge_.idle_cycles(1024);
        bridge_.poll_status_until(apf::kStatusSetup);
        trace_.setup_cycle = now();
        trace_.events.push_back("status_setup");
        bridge_.host_command(apf::kResetEnter);
        trace_.reset_enter_cycle = now();
        trace_.events.push_back("reset_enter");
        for (auto& slot : slots) {
            if (!slot.file.empty() && !slot.deferload) {
                slot.loaded_size = std::filesystem::file_size(slot.file);
            }
        }
        bridge_.populate_slot_table(slots);
        trace_.slot_table_cycle = now();
        trace_.events.push_back("slot_table_populated");
        for (auto& slot : slots) bridge_.load_slot(slot);
        trace_.data_load_complete_cycle = now();
        trace_.events.push_back("data_load_complete");
        bridge_.host_command(apf::kDataSlotAllComplete);
        trace_.data_all_complete_cycle = now();
        trace_.events.push_back("data_slot_all_complete");
        bridge_.host_command(apf::kRtcData, 0, 0, 0, 0);
        trace_.rtc_cycle = now();
        trace_.events.push_back("rtc_sent");
        bridge_.wait_target_ready_to_run();
        trace_.target_ready_cycle = now();
        trace_.events.push_back("target_ready_to_run");
        if (before_reset_exit) before_reset_exit();
        trace_.before_reset_exit_cycle = now();
        trace_.events.push_back("before_reset_exit");
        bridge_.host_command(apf::kResetExit);
        trace_.reset_exit_cycle = now();
        trace_.events.push_back("reset_exit");
        poll_running_or_idle_after_reset_exit();
        trace_.running_cycle = now();
        trace_.events.push_back("status_running");
        std::cout << "PASS boot: reached running\n";
    }

    const BootTrace& trace() const { return trace_; }

private:
    uint64_t now() const { return now_fn_ ? now_fn_() : 0; }

    void poll_running_or_idle_after_reset_exit() {
        for (int i = 0; i < 5000; ++i) {
            const auto status = bridge_.request_status();
            if (status == apf::kStatusRunning || status == apf::kStatusIdle) return;
            bridge_.idle_cycles(8);
        }
        throw std::runtime_error("status did not reach running/idle after Reset Exit");
    }

    BridgeHost<Top>& bridge_;
    NowFn now_fn_;
    BootTrace trace_;
};

} // namespace apfsim
