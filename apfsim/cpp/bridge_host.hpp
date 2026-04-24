#pragma once

#include "apf_commands.hpp"
#include "data_slots.hpp"
#include "sim_time.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

namespace apfsim {

struct SaveReport {
    uint16_t id = 0;
    size_t bytes = 0;
    std::filesystem::path path;
    uint64_t checksum = 0;
    uint64_t input_checksum = 0;
    bool matches_input = false;
};

struct SavestateReport {
    std::string name;
    bool attempted = false;
    bool supported = false;
    bool ready = false;
    uint16_t query_result = 0;
    uint16_t start_result = 0;
    uint16_t final_result = 0;
    uint32_t address = 0;
    uint32_t size = 0;
    size_t bytes = 0;
    uint64_t polls = 0;
    uint64_t checksum = 0;
    std::filesystem::path path;
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

struct BridgeStats {
    uint64_t reads = 0;
    uint64_t writes = 0;
    uint64_t framework_reads = 0;
    uint64_t framework_writes = 0;
    uint64_t host_command_writes = 0;
    uint64_t target_command_reads = 0;
    uint64_t target_command_writes = 0;
    uint64_t slot_table_writes = 0;
    uint64_t data_payload_writes = 0;
    uint64_t save_payload_reads = 0;
    uint64_t target_debug_events = 0;
    uint64_t target_dataslot_reads = 0;
    uint64_t target_dataslot_read_bytes = 0;
    uint64_t target_dataslot_writes = 0;
    uint64_t target_dataslot_write_bytes = 0;
    uint64_t target_dataslot_flushes = 0;
    uint64_t target_filename_requests = 0;
    uint64_t target_open_file_requests = 0;
    uint64_t runtime_dataslot_updates = 0;
    uint64_t savestate_save_requests = 0;
    uint64_t savestate_save_bytes = 0;
    uint64_t target_unsupported_commands = 0;
    uint64_t target_slot_errors = 0;
    uint64_t target_range_errors = 0;
    uint64_t custom_reads = 0;
    uint64_t custom_writes = 0;
    uint64_t host_commands = 0;
    uint64_t target_commands = 0;
    uint64_t host_timeouts = 0;
    uint64_t read_latency_cycles = 2;
    uint64_t write_idle_cycles = 1;
    uint64_t write_strobe_cycles = 1;
    uint64_t first_cycle = 0;
    uint64_t last_cycle = 0;
    uint32_t last_read_addr = 0;
    uint32_t last_read_data = 0;
    uint32_t last_write_addr = 0;
    uint32_t last_write_data = 0;
    bool endian_little = true;
};

struct BridgeCommandTrace {
    std::string direction;
    uint64_t cycle = 0;
    uint16_t command = 0;
    uint16_t result = 0;
    uint32_t word = 0;
    uint32_t p0 = 0;
    uint32_t p1 = 0;
    uint32_t p2 = 0;
    uint32_t p3 = 0;
};

enum class TargetServiceOutcome {
    None,
    Serviced,
    ReadyToRun,
};

template <typename Top>
class BridgeHost {
public:
    using CycleFn = std::function<void(uint64_t)>;
    using NowFn = std::function<uint64_t()>;

    BridgeHost(Top* top, CycleFn cycle_fn, NowFn now_fn = {}) : top_(top), cycle_fn_(std::move(cycle_fn)), now_fn_(std::move(now_fn)) {}

    void reset_lines() {
        top_->bridge_addr = 0;
        top_->bridge_rd = 0;
        top_->bridge_wr = 0;
        top_->bridge_wr_data = 0;
        top_->bridge_endian_little = endian_little_ ? 1 : 0;
        stats_.endian_little = endian_little_;
        stats_.read_latency_cycles = read_latency_cycles_;
        stats_.write_idle_cycles = write_idle_cycles_;
        stats_.write_strobe_cycles = write_strobe_cycles_;
    }

    void set_verbose(bool verbose) { verbose_ = verbose; }
    void set_write_idle_cycles(uint64_t cycles) { write_idle_cycles_ = cycles; }
    void set_write_strobe_cycles(uint64_t cycles) { write_strobe_cycles_ = cycles == 0 ? 1 : cycles; }
    void set_read_latency_cycles(uint64_t cycles) { read_latency_cycles_ = cycles; }
    void set_endian_little(bool little) { endian_little_ = little; }
    void set_log_path(const std::filesystem::path& path) {
        if (path.empty()) return;
        if (!path.parent_path().empty()) std::filesystem::create_directories(path.parent_path());
        log_.open(path);
        if (log_) log_ << "apfsim bridge log\n";
    }
    void set_trace_path(const std::filesystem::path& path) {
        if (path.empty()) return;
        if (!path.parent_path().empty()) std::filesystem::create_directories(path.parent_path());
        trace_.open(path);
    }

    uint16_t last_host_command() const { return last_host_command_; }
    uint16_t last_host_result() const { return last_host_result_; }
    uint32_t last_host_status_word() const { return last_host_status_word_; }
    uint32_t last_target_word() const { return last_target_word_; }
    uint16_t last_target_command() const { return last_target_command_; }
    uint16_t last_target_result() const { return last_target_result_; }
    const BridgeStats& stats() const { return stats_; }
    const std::vector<BridgeCommandTrace>& command_trace() const { return command_trace_; }
    bool endian_little() const { return endian_little_; }

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
        cycle_fn_(write_strobe_cycles_);
        top_->bridge_wr = 0;
        top_->bridge_wr_data = 0;
        record_write(addr, data);
        record_active_slot_write(addr);
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
        record_read(addr, data);
        if (verbose_) std::cout << "BRIDGE R " << hex32(addr) << " -> " << hex32(data) << "\n";
        return data;
    }

    void burst_write(uint32_t base, const std::vector<uint8_t>& bytes) {
        const bool little_endian = bridge_payload_little_endian();
        for (size_t i = 0; i < bytes.size(); i += 4) {
            uint32_t word = 0;
            for (size_t b = 0; b < 4 && i + b < bytes.size(); ++b) {
                const size_t shift_byte = little_endian ? b : (3 - b);
                word |= static_cast<uint32_t>(bytes[i + b]) << (8 * shift_byte);
            }
            write32(base + static_cast<uint32_t>(i), word);
        }
    }

    std::vector<uint8_t> burst_read(uint32_t base, size_t size) {
        const bool little_endian = bridge_payload_little_endian();
        std::vector<uint8_t> out(size);
        for (size_t i = 0; i < size; i += 4) {
            const uint32_t word = read32(base + static_cast<uint32_t>(i));
            for (size_t b = 0; b < 4 && i + b < size; ++b) {
                const size_t shift_byte = little_endian ? b : (3 - b);
                out[i + b] = static_cast<uint8_t>((word >> (8 * shift_byte)) & 0xFFu);
            }
        }
        return out;
    }

    uint16_t host_command(uint16_t cmd, uint32_t p0 = 0, uint32_t p1 = 0, uint32_t p2 = 0, uint32_t p3 = 0, int timeout_polls = 1000) {
        last_host_command_ = cmd;
        ++stats_.host_commands;
        command_trace_.push_back({"host", now(), cmd, 0, apf::magic_cmd(cmd), p0, p1, p2, p3});
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
                command_trace_.push_back({"host-ok", now(), cmd, result, status, p0, p1, p2, p3});
                if (verbose_) std::cout << "APF host command " << apf::command_name(cmd) << " -> " << result << "\n";
                log_event("HOST OK " + std::string(apf::command_name(cmd)) + " result=" + hex32(result));
                return result;
            }
            idle_cycles(1);
        }
        log_event("HOST TIMEOUT " + std::string(apf::command_name(cmd)));
        ++stats_.host_timeouts;
        throw std::runtime_error("APF host command timed out: " + std::to_string(cmd));
    }

    std::array<uint32_t, 4> read_host_responses(size_t count = 4) {
        std::array<uint32_t, 4> responses = {};
        uint32_t response_base = read32(apf::kCommandBase + apf::kHostResponsePointerOffset);
        if (response_base == 0 || response_base == 0xFFFFFFFFu) {
            response_base = apf::kCommandBase + 0x40u;
        }
        for (size_t i = 0; i < count && i < responses.size(); ++i) {
            responses[i] = read32(response_base + static_cast<uint32_t>(i * 4));
        }
        return responses;
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

    TargetServiceOutcome service_pending_target_command(std::vector<DataSlot>& slots) {
        const uint32_t word = read32(apf::kTargetBase);
        last_target_word_ = word;
        if (!(apf::is_target_cmd(word) || apf::is_cmd(word))) return TargetServiceOutcome::None;

        const uint16_t cmd = apf::low16(word);
        size_t param_count = 4;
        switch (cmd) {
            case apf::kTargetReadyToRun: param_count = 0; break;
            case apf::kTargetDebugEventLog:
            case apf::kTargetDataSlotFlush: param_count = 1; break;
            case apf::kTargetGetDataSlotFilename:
            case apf::kTargetOpenNewFileIntoDataSlot: param_count = 2; break;
            default: break;
        }
        const auto params = read_target_params(param_count);
        last_target_command_ = cmd;
        ++stats_.target_commands;
        command_trace_.push_back({"target", now(), cmd, 0, word, params[0], params[1], params[2], params[3]});
        log_event("TARGET CM " + std::string(apf::command_name(cmd)) + " word=" + hex32(word) +
                  " p0=" + hex32(params[0]) + " p1=" + hex32(params[1]) +
                  " p2=" + hex32(params[2]) + " p3=" + hex32(params[3]));

        write32(apf::kTargetBase, apf::target_magic_busy(0));
        const uint16_t result = handle_target_command(cmd, params, slots);
        last_target_result_ = result;
        const uint32_t ok_word = apf::target_magic_ok(result);
        write32(apf::kTargetBase, ok_word);
        command_trace_.push_back({"target-ok", now(), cmd, result, ok_word, params[0], params[1], params[2], params[3]});
        log_event("TARGET OK " + std::string(apf::command_name(cmd)) + " result=" + hex32(result));

        if (cmd == apf::kTargetReadyToRun) return TargetServiceOutcome::ReadyToRun;
        return TargetServiceOutcome::Serviced;
    }

    size_t service_target_commands(std::vector<DataSlot>& slots, size_t max_commands = 8) {
        size_t serviced = 0;
        for (; serviced < max_commands; ++serviced) {
            const auto outcome = service_pending_target_command(slots);
            if (outcome == TargetServiceOutcome::None) break;
        }
        return serviced;
    }

    void wait_target_ready_to_run(std::vector<DataSlot>& slots, int timeout_polls = 5000) {
        for (int i = 0; i < timeout_polls; ++i) {
            if (service_pending_target_command(slots) == TargetServiceOutcome::ReadyToRun) return;
            idle_cycles(8);
        }
        throw std::runtime_error("target Ready to Run command not observed");
    }

    void populate_slot_table(const std::vector<DataSlot>& slots) {
        log_event("DATASLOT table populate entries=" + std::to_string(slots.size()));
        for (size_t i = 0; i < 32; ++i) {
            slot_table_ids_[i] = 0;
            slot_table_sizes_[i] = 0;
            write32(apf::kDataSlotTableBase + static_cast<uint32_t>(i * 8), 0);
            write32(apf::kDataSlotTableBase + static_cast<uint32_t>(i * 8 + 4), 0);
        }
        for (size_t i = 0; i < slots.size() && i < 32; ++i) {
            slot_table_ids_[i] = slots[i].id;
            slot_table_sizes_[i] = static_cast<uint32_t>(slots[i].loaded_size);
            write32(apf::kDataSlotTableBase + static_cast<uint32_t>(i * 8), slots[i].id);
            write32(apf::kDataSlotTableBase + static_cast<uint32_t>(i * 8 + 4), static_cast<uint32_t>(slots[i].loaded_size));
        }
    }

    void write_slot_table_entry(const std::vector<DataSlot>& slots, uint16_t slot_id) {
        const auto it = std::find_if(slots.begin(), slots.end(), [&](const DataSlot& slot) { return slot.id == slot_id; });
        if (it == slots.end()) throw std::runtime_error("slot " + std::to_string(slot_id) + " not defined");
        const size_t index = static_cast<size_t>(std::distance(slots.begin(), it));
        if (index >= 32) throw std::runtime_error("slot " + std::to_string(slot_id) + " index exceeds APF slot table");
        slot_table_ids_[index] = it->id;
        slot_table_sizes_[index] = static_cast<uint32_t>(it->loaded_size);
        write32(apf::kDataSlotTableBase + static_cast<uint32_t>(index * 8), it->id);
        write32(apf::kDataSlotTableBase + static_cast<uint32_t>(index * 8 + 4), static_cast<uint32_t>(it->loaded_size));
    }

    void runtime_data_slot_update(std::vector<DataSlot>& slots, uint16_t slot_id, const std::filesystem::path& file, uint64_t explicit_size, bool has_explicit_size, bool update_slot_table) {
        auto* slot = find_slot(slots, slot_id);
        if (!slot) throw std::runtime_error("slot " + std::to_string(slot_id) + " not defined");
        if (!file.empty()) slot->file = file;
        if (!slot->file.empty() && std::filesystem::exists(slot->file)) {
            slot->image = read_binary_file(slot->file);
            slot->loaded_size = slot->image.size();
            slot->loaded_words = (slot->loaded_size + 3) / 4;
            slot->loaded_last_address = slot->loaded_words == 0 ? slot->address : slot->address + static_cast<uint32_t>((slot->loaded_words - 1) * 4);
            slot->loaded_checksum = fnv1a64(slot->image);
            slot->loaded_crc32 = crc32(slot->image);
        }
        if (has_explicit_size) {
            slot->loaded_size = static_cast<size_t>(explicit_size);
            slot->loaded_words = (slot->loaded_size + 3) / 4;
            slot->loaded_last_address = slot->loaded_words == 0 ? slot->address : slot->address + static_cast<uint32_t>((slot->loaded_words - 1) * 4);
            if (slot->image.size() < slot->loaded_size) slot->image.resize(slot->loaded_size, 0);
            if (!slot->image.empty()) {
                slot->loaded_checksum = fnv1a64(slot->image);
                slot->loaded_crc32 = crc32(slot->image);
            }
        }
        if (update_slot_table) write_slot_table_entry(slots, slot_id);
        ++stats_.runtime_dataslot_updates;
        log_event("DATASLOT runtime update id=" + std::to_string(slot_id) + " bytes=" + std::to_string(slot->loaded_size) +
                  " file=" + slot->file.string());
        host_command(apf::kDataSlotUpdate, slot_id, static_cast<uint32_t>(slot->loaded_size), 0, 0);
    }

    SavestateReport save_savestate(const std::filesystem::path& output_path, const std::string& name = {}, uint64_t poll_limit = 256) {
        SavestateReport report;
        report.name = name;
        report.attempted = true;
        ++stats_.savestate_save_requests;

        report.query_result = host_command(apf::kSavestateStartQuery, 0, 0, 0, 0);
        auto responses = read_host_responses(3);
        report.supported = (responses[0] & 1u) != 0;
        report.address = responses[1];
        report.size = responses[2];
        report.final_result = report.query_result;
        if (!report.supported) {
            log_event("SAVESTATE unsupported query_result=" + hex32(report.query_result));
            return report;
        }

        report.start_result = host_command(apf::kSavestateStartQuery, 1, 0, 0, 0);
        responses = read_host_responses(3);
        report.address = responses[1];
        report.size = responses[2];
        report.final_result = report.start_result;

        for (; report.polls < poll_limit; ++report.polls) {
            if (report.final_result == 2 || report.final_result == 3) break;
            report.final_result = host_command(apf::kSavestateStartQuery, 0, 0, 0, 0);
            responses = read_host_responses(3);
            report.address = responses[1];
            report.size = responses[2];
            if (report.final_result == 2 || report.final_result == 3) break;
        }

        report.ready = report.final_result == 2 && report.address != 0 && report.size != 0;
        if (!report.ready) {
            log_event("SAVESTATE not-ready result=" + hex32(report.final_result) + " address=" + hex32(report.address) +
                      " bytes=" + std::to_string(report.size));
            return report;
        }

        const auto bytes = burst_read(report.address, report.size);
        report.checksum = fnv1a64(bytes);
        report.bytes = bytes.size();
        report.path = output_path;
        if (!report.path.empty()) write_binary_file(report.path, bytes);
        stats_.savestate_save_bytes += bytes.size();
        log_event("SAVESTATE save bytes=" + std::to_string(bytes.size()) + " address=" + hex32(report.address) +
                  " path=" + report.path.string());
        return report;
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
        slot.loaded_words = (bytes.size() + 3) / 4;
        slot.loaded_last_address = slot.loaded_words == 0 ? slot.address : slot.address + static_cast<uint32_t>((slot.loaded_words - 1) * 4);
        slot.observed_write_words = 0;
        slot.observed_first_write_address = 0;
        slot.observed_last_write_address = 0;
        slot.observed_write_address_errors = 0;
        slot.readback_attempted = false;
        slot.readback_matches = false;
        slot.readback_bytes = 0;
        slot.readback_crc32 = 0;
        slot.readback_checksum = 0;
        slot.readback_mismatch_count = 0;
        slot.readback_first_mismatch_offset = 0;
        slot.readback_has_first_mismatch = false;
        slot.readback_expected_byte = 0;
        slot.readback_observed_byte = 0;
        slot.loaded_checksum = fnv1a64(bytes);
        slot.loaded_crc32 = crc32(bytes);
        slot.image = bytes;
        log_event("DATASLOT load begin id=" + std::to_string(slot.id) + " bytes=" + std::to_string(bytes.size()) +
                  " address=" + hex32(slot.address) + " file=" + slot.file.string());
        host_command(apf::kDataSlotRequestWrite, slot.id, static_cast<uint32_t>(bytes.size()), slot.address, 0);
        active_load_slot_ = &slot;
        burst_write(slot.address, bytes);
        active_load_slot_ = nullptr;
        if (slot.verify_readback) verify_loaded_slot_readback(slot, bytes);
        log_event("DATASLOT load done id=" + std::to_string(slot.id) + " writes32=" + std::to_string((bytes.size() + 3) / 4));
        std::cout << "PASS data: slot " << slot.id << " loaded " << bytes.size() << " bytes at " << hex32(slot.address) << "\n";
    }

    std::vector<SaveReport> unload_nonvolatile(const std::vector<DataSlot>& slots, const std::filesystem::path& dir) {
        std::vector<SaveReport> reports;
        if (dir.empty()) return reports;
        std::filesystem::create_directories(dir);
        for (const auto& slot : slots) {
            if (!slot.nonvolatile || slot.loaded_size == 0) continue;
            const auto bytes = slot.target_write_requests && !slot.image.empty()
                                   ? slot.image
                                   : burst_read(slot.address, slot.loaded_size);
            const auto path = dir / ("slot_" + std::to_string(slot.id) + ".bin");
            write_binary_file(path, bytes);
            SaveReport report;
            report.id = slot.id;
            report.bytes = bytes.size();
            report.path = path;
            report.checksum = fnv1a64(bytes);
            if (!slot.file.empty()) {
                const auto input = read_binary_file(slot.file);
            report.input_checksum = fnv1a64(input);
                report.matches_input = input == bytes;
            }
            reports.push_back(report);
            log_event("SAVE unload id=" + std::to_string(slot.id) + " bytes=" + std::to_string(bytes.size()) + " path=" + path.string());
            std::cout << "PASS save: slot " << slot.id << " unloaded " << bytes.size() << " bytes\n";
        }
        return reports;
    }

    bool slot_table_matches(const std::vector<DataSlot>& slots) const {
        for (size_t i = 0; i < 32; ++i) {
            const uint16_t expected_id = i < slots.size() ? slots[i].id : 0;
            const uint32_t expected_size = i < slots.size() ? static_cast<uint32_t>(slots[i].loaded_size) : 0;
            if (slot_table_ids_[i] != expected_id || slot_table_sizes_[i] != expected_size) return false;
        }
        return true;
    }

private:
    uint64_t now() const { return now_fn_ ? now_fn_() : 0; }

    static size_t target_param_count(uint16_t cmd) {
        switch (cmd) {
            case apf::kTargetReadyToRun: return 0;
            case apf::kTargetDebugEventLog: return 1;
            case apf::kTargetDataSlotFlush: return 1;
            case apf::kTargetGetDataSlotFilename:
            case apf::kTargetOpenNewFileIntoDataSlot:
                return 2;
            case apf::kTargetDataSlotRead:
            case apf::kTargetDataSlotRead48:
            case apf::kTargetDataSlotWrite:
            case apf::kTargetDataSlotWrite48:
                return 4;
            default:
                return 4;
        }
    }

    std::array<uint32_t, 4> read_target_params(size_t count) {
        std::array<uint32_t, 4> params = {};
        if (count == 0) return params;
        uint32_t param_base = read32(apf::kCommandBase + apf::kTargetParamPointerOffset);
        if (param_base == 0 || param_base == 0xFFFFFFFFu) {
            param_base = apf::kCommandBase + apf::kTargetParam0Offset;
        }
        for (size_t i = 0; i < count && i < params.size(); ++i) {
            params[i] = read32(param_base + static_cast<uint32_t>(i * 4));
        }
        return params;
    }

    uint16_t handle_target_command(uint16_t cmd, const std::array<uint32_t, 4>& params, std::vector<DataSlot>& slots) {
        switch (cmd) {
            case apf::kTargetReadyToRun:
                return apf::kTargetOk;
            case apf::kTargetDebugEventLog:
                ++stats_.target_debug_events;
                log_event("TARGET DEBUG event=" + hex32(params[0]));
                return apf::kTargetOk;
            case apf::kTargetDataSlotRead:
            case apf::kTargetDataSlotRead48:
                return handle_target_dataslot_read(cmd, params, slots);
            case apf::kTargetDataSlotWrite:
            case apf::kTargetDataSlotWrite48:
                return handle_target_dataslot_write(cmd, params, slots);
            case apf::kTargetDataSlotFlush:
                return handle_target_dataslot_flush(params, slots);
            case apf::kTargetGetDataSlotFilename:
                return handle_target_get_filename(params, slots);
            case apf::kTargetOpenNewFileIntoDataSlot:
                return handle_target_open_file(params, slots);
            default:
                ++stats_.target_unsupported_commands;
                log_event("TARGET unsupported command cmd=" + hex32(cmd));
                return apf::kTargetGeneralError;
        }
    }

    static uint16_t target_slot_id(uint16_t cmd, const std::array<uint32_t, 4>& params) {
        if (cmd == apf::kTargetDataSlotRead48 || cmd == apf::kTargetDataSlotWrite48) {
            return static_cast<uint16_t>(params[0] & 0xFFFFu);
        }
        return static_cast<uint16_t>(params[0] & 0xFFFFu);
    }

    static uint64_t target_slot_offset(uint16_t cmd, const std::array<uint32_t, 4>& params) {
        if (cmd == apf::kTargetDataSlotRead48 || cmd == apf::kTargetDataSlotWrite48) {
            return (static_cast<uint64_t>(params[0] >> 16) << 32) | params[1];
        }
        return params[1];
    }

    static uint32_t target_bridge_address(uint16_t cmd, const std::array<uint32_t, 4>& params) {
        return (cmd == apf::kTargetDataSlotRead48 || cmd == apf::kTargetDataSlotWrite48) ? params[2] : params[2];
    }

    static uint32_t target_transfer_length(uint16_t cmd, const std::array<uint32_t, 4>& params) {
        return (cmd == apf::kTargetDataSlotRead48 || cmd == apf::kTargetDataSlotWrite48) ? params[3] : params[3];
    }

    std::vector<uint8_t>& ensure_slot_image(DataSlot& slot) {
        if (slot.image.empty() && !slot.file.empty() && std::filesystem::exists(slot.file)) {
            slot.image = read_binary_file(slot.file);
            slot.loaded_size = slot.image.size();
            slot.loaded_words = (slot.loaded_size + 3) / 4;
            slot.loaded_last_address = slot.loaded_words == 0 ? slot.address : slot.address + static_cast<uint32_t>((slot.loaded_words - 1) * 4);
            slot.loaded_checksum = fnv1a64(slot.image);
            slot.loaded_crc32 = crc32(slot.image);
        }
        return slot.image;
    }

    uint16_t handle_target_dataslot_read(uint16_t cmd, const std::array<uint32_t, 4>& params, std::vector<DataSlot>& slots) {
        ++stats_.target_dataslot_reads;
        const uint16_t slot_id = target_slot_id(cmd, params);
        auto* slot = find_slot(slots, slot_id);
        if (!slot) {
            ++stats_.target_slot_errors;
            return apf::kTargetSlotNotDefined;
        }

        auto& image = ensure_slot_image(*slot);
        const uint64_t offset = target_slot_offset(cmd, params);
        const uint32_t bridge_addr = target_bridge_address(cmd, params);
        uint64_t length = target_transfer_length(cmd, params);
        if (length == 0xFFFFFFFFull) {
            if (offset > image.size()) {
                ++stats_.target_range_errors;
                return apf::kTargetRangeError;
            }
            length = image.size() - offset;
        }
        if (!target_range_ok(offset, length, image.size())) {
            ++stats_.target_range_errors;
            return apf::kTargetRangeError;
        }
        std::vector<uint8_t> bytes(image.begin() + static_cast<std::ptrdiff_t>(offset),
                                   image.begin() + static_cast<std::ptrdiff_t>(offset + length));
        burst_write(bridge_addr, bytes);
        ++slot->target_read_requests;
        slot->target_read_bytes += length;
        stats_.target_dataslot_read_bytes += length;
        log_event("TARGET DATASLOT read id=" + std::to_string(slot_id) + " offset=" + hex32(static_cast<uint32_t>(offset)) +
                  " address=" + hex32(bridge_addr) + " bytes=" + std::to_string(length));
        return apf::kTargetOk;
    }

    uint16_t handle_target_dataslot_write(uint16_t cmd, const std::array<uint32_t, 4>& params, std::vector<DataSlot>& slots) {
        ++stats_.target_dataslot_writes;
        const uint16_t slot_id = target_slot_id(cmd, params);
        auto* slot = find_slot(slots, slot_id);
        if (!slot) {
            ++stats_.target_slot_errors;
            return apf::kTargetSlotNotDefined;
        }

        auto& image = ensure_slot_image(*slot);
        const uint64_t offset = target_slot_offset(cmd, params);
        const uint32_t bridge_addr = target_bridge_address(cmd, params);
        uint64_t length = target_transfer_length(cmd, params);
        if (length == 0xFFFFFFFFull) {
            if (offset > image.size()) {
                ++stats_.target_range_errors;
                return apf::kTargetRangeError;
            }
            length = image.size() - offset;
        }
        constexpr uint64_t kMaxTargetTransferBytes = 64ull * 1024ull * 1024ull;
        if (length > kMaxTargetTransferBytes || offset > kMaxTargetTransferBytes || offset + length > kMaxTargetTransferBytes) {
            ++stats_.target_range_errors;
            return apf::kTargetRangeError;
        }
        if (slot->size_maximum && offset + length > slot->size_maximum) {
            ++stats_.target_range_errors;
            return apf::kTargetRangeError;
        }
        if (image.size() < offset + length) image.resize(static_cast<size_t>(offset + length), 0);
        const auto bytes = burst_read(bridge_addr, static_cast<size_t>(length));
        std::copy(bytes.begin(), bytes.end(), image.begin() + static_cast<std::ptrdiff_t>(offset));
        slot->loaded_size = image.size();
        slot->loaded_words = (slot->loaded_size + 3) / 4;
        slot->loaded_last_address = slot->loaded_words == 0 ? slot->address : slot->address + static_cast<uint32_t>((slot->loaded_words - 1) * 4);
        slot->loaded_checksum = fnv1a64(image);
        slot->loaded_crc32 = crc32(image);
        sync_slot_table_size(*slot);
        ++slot->target_write_requests;
        slot->target_write_bytes += length;
        stats_.target_dataslot_write_bytes += length;
        log_event("TARGET DATASLOT write id=" + std::to_string(slot_id) + " offset=" + hex32(static_cast<uint32_t>(offset)) +
                  " address=" + hex32(bridge_addr) + " bytes=" + std::to_string(length));
        return apf::kTargetOk;
    }

    uint16_t handle_target_dataslot_flush(const std::array<uint32_t, 4>& params, std::vector<DataSlot>& slots) {
        ++stats_.target_dataslot_flushes;
        const uint16_t slot_id = static_cast<uint16_t>(params[0] & 0xFFFFu);
        auto* slot = find_slot(slots, slot_id);
        if (!slot) {
            ++stats_.target_slot_errors;
            return apf::kTargetSlotNotDefined;
        }
        ++slot->target_flush_requests;
        sync_slot_table_size(*slot);
        log_event("TARGET DATASLOT flush id=" + std::to_string(slot_id));
        return apf::kTargetOk;
    }

    uint16_t handle_target_get_filename(const std::array<uint32_t, 4>& params, std::vector<DataSlot>& slots) {
        ++stats_.target_filename_requests;
        const uint16_t slot_id = static_cast<uint16_t>(params[0] & 0xFFFFu);
        const uint32_t struct_addr = params[1];
        auto* slot = find_slot(slots, slot_id);
        if (!slot) {
            ++stats_.target_slot_errors;
            return apf::kTargetSlotNotDefined;
        }
        ++slot->target_filename_requests;
        if (struct_addr != 0) {
            std::vector<uint8_t> bytes(256, 0);
            const auto filename = slot->file.string();
            const size_t n = std::min(filename.size(), bytes.size() - 1);
            std::copy_n(filename.begin(), n, bytes.begin());
            burst_write(struct_addr, bytes);
        }
        log_event("TARGET filename id=" + std::to_string(slot_id) + " struct=" + hex32(struct_addr) + " file=" + slot->file.string());
        return apf::kTargetOk;
    }

    uint16_t handle_target_open_file(const std::array<uint32_t, 4>& params, std::vector<DataSlot>& slots) {
        ++stats_.target_open_file_requests;
        const uint16_t slot_id = static_cast<uint16_t>(params[0] & 0xFFFFu);
        const uint32_t struct_addr = params[1];
        auto* slot = find_slot(slots, slot_id);
        if (!slot) {
            ++stats_.target_slot_errors;
            return 2;
        }
        ++slot->target_open_requests;
        std::string requested;
        if (struct_addr != 0) {
            requested = read_bridge_c_string(struct_addr, 256);
        }
        if (requested.empty()) {
            log_event("TARGET open-file empty path id=" + std::to_string(slot_id));
            return apf::kTargetFileNotFound;
        }
        std::filesystem::path path(requested);
        if (!std::filesystem::exists(path)) {
            log_event("TARGET open-file missing id=" + std::to_string(slot_id) + " file=" + requested);
            return apf::kTargetFileNotFound;
        }
        slot->file = path;
        slot->image = read_binary_file(path);
        slot->loaded_size = slot->image.size();
        slot->loaded_words = (slot->loaded_size + 3) / 4;
        slot->loaded_last_address = slot->loaded_words == 0 ? slot->address : slot->address + static_cast<uint32_t>((slot->loaded_words - 1) * 4);
        slot->loaded_checksum = fnv1a64(slot->image);
        slot->loaded_crc32 = crc32(slot->image);
        sync_slot_table_size(*slot);
        log_event("TARGET open-file id=" + std::to_string(slot_id) + " file=" + requested + " bytes=" + std::to_string(slot->loaded_size));
        return apf::kTargetOk;
    }

    void sync_slot_table_size(const DataSlot& slot) {
        for (size_t i = 0; i < slot_table_ids_.size(); ++i) {
            if (slot_table_ids_[i] == slot.id) {
                slot_table_sizes_[i] = static_cast<uint32_t>(slot.loaded_size);
                return;
            }
        }
    }

    static bool target_range_ok(uint64_t offset, uint64_t length, size_t size) {
        const uint64_t total = static_cast<uint64_t>(size);
        return offset <= total && length <= total - offset;
    }

    void verify_loaded_slot_readback(DataSlot& slot, const std::vector<uint8_t>& expected) {
        slot.readback_attempted = true;
        const auto observed = burst_read(slot.address, expected.size());
        slot.readback_bytes = observed.size();
        slot.readback_crc32 = crc32(observed);
        slot.readback_checksum = fnv1a64(observed);
        slot.readback_matches = observed == expected;

        const size_t compare_size = std::min(expected.size(), observed.size());
        for (size_t i = 0; i < compare_size; ++i) {
            if (expected[i] == observed[i]) continue;
            ++slot.readback_mismatch_count;
            if (!slot.readback_has_first_mismatch) {
                slot.readback_has_first_mismatch = true;
                slot.readback_first_mismatch_offset = i;
                slot.readback_expected_byte = expected[i];
                slot.readback_observed_byte = observed[i];
            }
        }
        if (observed.size() != expected.size()) {
            slot.readback_mismatch_count += observed.size() > expected.size()
                                                ? observed.size() - expected.size()
                                                : expected.size() - observed.size();
            if (!slot.readback_has_first_mismatch) {
                slot.readback_has_first_mismatch = true;
                slot.readback_first_mismatch_offset = compare_size;
                slot.readback_expected_byte = compare_size < expected.size() ? expected[compare_size] : 0;
                slot.readback_observed_byte = compare_size < observed.size() ? observed[compare_size] : 0;
            }
        }

        log_event("DATASLOT readback id=" + std::to_string(slot.id) +
                  " bytes=" + std::to_string(observed.size()) +
                  " crc=" + hex32(slot.readback_crc32) +
                  " checksum=" + hex64(slot.readback_checksum) +
                  " matches=" + std::string(slot.readback_matches ? "true" : "false") +
                  " mismatches=" + std::to_string(slot.readback_mismatch_count));
    }

    std::string read_bridge_c_string(uint32_t addr, size_t max_len) {
        const auto bytes = burst_read(addr, max_len);
        size_t n = 0;
        while (n < bytes.size() && bytes[n] != 0) ++n;
        return std::string(bytes.begin(), bytes.begin() + static_cast<std::ptrdiff_t>(n));
    }

    static std::string escape_json_string(const std::string& text) {
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

    void touch_cycle() {
        const uint64_t cycle = now();
        if (stats_.first_cycle == 0) stats_.first_cycle = cycle;
        stats_.last_cycle = cycle;
    }

    bool is_framework_addr(uint32_t addr) const { return (addr & 0xFF000000u) == 0xF8000000u; }
    bool is_target_addr(uint32_t addr) const { return addr >= apf::kTargetBase && addr < apf::kTargetBase + 0x1000u; }
    bool is_slot_table_addr(uint32_t addr) const { return addr >= apf::kDataSlotTableBase && addr < apf::kDataSlotTableBase + 32u * 8u; }
    bool is_data_payload_addr(uint32_t addr) const { return (addr & 0xFF000000u) == 0x10000000u; }
    bool is_save_payload_addr(uint32_t addr) const { return (addr & 0xFFFF0000u) == 0x20000000u; }

    void record_write(uint32_t addr, uint32_t data) {
        touch_cycle();
        ++stats_.writes;
        stats_.last_write_addr = addr;
        stats_.last_write_data = data;
        if (is_framework_addr(addr)) ++stats_.framework_writes;
        else ++stats_.custom_writes;
        if (addr == apf::kCommandBase + apf::kHostStatusOffset) ++stats_.host_command_writes;
        if (is_target_addr(addr)) ++stats_.target_command_writes;
        if (is_slot_table_addr(addr)) {
            ++stats_.slot_table_writes;
            const uint32_t offset = addr - apf::kDataSlotTableBase;
            const size_t index = offset / 8;
            if (index < 32) {
                if ((offset % 8) == 0) slot_table_ids_[index] = static_cast<uint16_t>(data & 0xFFFFu);
                else if ((offset % 8) == 4) slot_table_sizes_[index] = data;
            }
        }
        if (is_data_payload_addr(addr)) ++stats_.data_payload_writes;
        record_transaction("write", addr, data);
    }

    void record_read(uint32_t addr, uint32_t data) {
        touch_cycle();
        ++stats_.reads;
        stats_.last_read_addr = addr;
        stats_.last_read_data = data;
        if (is_framework_addr(addr)) ++stats_.framework_reads;
        else ++stats_.custom_reads;
        if (is_target_addr(addr)) ++stats_.target_command_reads;
        if (is_save_payload_addr(addr)) ++stats_.save_payload_reads;
        record_transaction("read", addr, data);
    }

    void record_transaction(const char* op, uint32_t addr, uint32_t data) {
        if (!trace_) return;
        trace_ << "{\"cycle\":" << now()
               << ",\"op\":\"" << op
               << "\",\"addr\":\"" << hex32(addr)
               << "\",\"data\":\"" << hex32(data)
               << "\",\"framework\":" << (is_framework_addr(addr) ? "true" : "false")
               << ",\"endian\":\"" << (endian_little_ ? "little" : "big") << "\"}\n";
    }

    void record_active_slot_write(uint32_t addr) {
        if (!active_load_slot_) return;
        auto& slot = *active_load_slot_;
        if (slot.observed_write_words == 0) slot.observed_first_write_address = addr;
        const uint32_t expected_addr = slot.address + static_cast<uint32_t>(slot.observed_write_words * 4);
        if (addr != expected_addr) ++slot.observed_write_address_errors;
        slot.observed_last_write_address = addr;
        ++slot.observed_write_words;
    }

    bool bridge_payload_little_endian() const {
        return top_->bridge_endian_little != 0;
    }

    void log_event(const std::string& msg) {
        if (log_) log_ << msg << "\n";
    }

    Top* top_ = nullptr;
    CycleFn cycle_fn_;
    NowFn now_fn_;
    uint64_t read_latency_cycles_ = 2;
    uint64_t write_idle_cycles_ = 1;
    uint64_t write_strobe_cycles_ = 1;
    bool endian_little_ = true;
    bool verbose_ = false;
    std::ofstream log_;
    std::ofstream trace_;
    BridgeStats stats_;
    std::array<uint16_t, 32> slot_table_ids_ = {};
    std::array<uint32_t, 32> slot_table_sizes_ = {};
    std::vector<BridgeCommandTrace> command_trace_;
    uint16_t last_host_command_ = 0;
    uint16_t last_host_result_ = 0;
    uint32_t last_host_status_word_ = 0;
    uint32_t last_target_word_ = 0;
    uint16_t last_target_command_ = 0;
    uint16_t last_target_result_ = 0;
    DataSlot* active_load_slot_ = nullptr;
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
        bridge_.wait_target_ready_to_run(slots);
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
