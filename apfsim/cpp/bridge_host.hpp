#pragma once

#include "apf_commands.hpp"
#include "data_slots.hpp"
#include "sim_time.hpp"

#include <cstdint>
#include <filesystem>
#include <functional>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace apfsim {

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
        write32(apf::kCommandBase + apf::kHostParam0Offset, p0);
        write32(apf::kCommandBase + apf::kHostParam1Offset, p1);
        write32(apf::kCommandBase + apf::kHostParam2Offset, p2);
        write32(apf::kCommandBase + apf::kHostParam3Offset, p3);
        write32(apf::kCommandBase + apf::kHostStatusOffset, apf::magic_cmd(cmd));
        for (int i = 0; i < timeout_polls; ++i) {
            const uint32_t status = read32(apf::kCommandBase + apf::kHostStatusOffset);
            if (apf::is_ok(status)) {
                const uint16_t result = apf::low16(status);
                if (verbose_) std::cout << "APF host command " << apf::command_name(cmd) << " -> " << result << "\n";
                return result;
            }
            idle_cycles(1);
        }
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
            if ((apf::is_target_cmd(word) || apf::is_cmd(word)) && apf::low16(word) == apf::kTargetReadyToRun) {
                write32(apf::kTargetBase, apf::target_magic_ok(0));
                return;
            }
            idle_cycles(8);
        }
        throw std::runtime_error("target Ready to Run command not observed");
    }

    void populate_slot_table(const std::vector<DataSlot>& slots) {
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
        host_command(apf::kDataSlotRequestWrite, slot.id, static_cast<uint32_t>(bytes.size()), slot.address, 0);
        burst_write(slot.address, bytes);
        std::cout << "PASS data: slot " << slot.id << " loaded " << bytes.size() << " bytes at " << hex32(slot.address) << "\n";
    }

    void unload_nonvolatile(const std::vector<DataSlot>& slots, const std::filesystem::path& dir) {
        if (dir.empty()) return;
        std::filesystem::create_directories(dir);
        for (const auto& slot : slots) {
            if (!slot.nonvolatile || slot.loaded_size == 0) continue;
            const auto bytes = burst_read(slot.address, slot.loaded_size);
            const auto path = dir / ("slot_" + std::to_string(slot.id) + ".bin");
            write_binary_file(path, bytes);
            std::cout << "PASS save: slot " << slot.id << " unloaded " << bytes.size() << " bytes\n";
        }
    }

    void set_read_latency_cycles(uint64_t cycles) { read_latency_cycles_ = cycles; }

private:
    Top* top_ = nullptr;
    CycleFn cycle_fn_;
    uint64_t read_latency_cycles_ = 2;
    uint64_t write_idle_cycles_ = 1;
    bool verbose_ = false;
};

template <typename Top>
class ApfHost {
public:
    explicit ApfHost(BridgeHost<Top>& bridge) : bridge_(bridge) {}

    void boot(std::vector<DataSlot>& slots, const std::function<void()>& before_reset_exit = {}) {
        bridge_.idle_cycles(1024);
        bridge_.poll_status_until(apf::kStatusSetup);
        bridge_.host_command(apf::kResetEnter);
        for (auto& slot : slots) {
            if (!slot.file.empty() && !slot.deferload) {
                slot.loaded_size = std::filesystem::file_size(slot.file);
            }
        }
        bridge_.populate_slot_table(slots);
        for (auto& slot : slots) bridge_.load_slot(slot);
        bridge_.host_command(apf::kDataSlotAllComplete);
        bridge_.host_command(apf::kRtcData, 0, 0, 0, 0);
        bridge_.wait_target_ready_to_run();
        if (before_reset_exit) before_reset_exit();
        bridge_.host_command(apf::kResetExit);
        poll_running_or_idle_after_reset_exit();
        std::cout << "PASS boot: reached running\n";
    }

private:
    void poll_running_or_idle_after_reset_exit() {
        for (int i = 0; i < 5000; ++i) {
            const auto status = bridge_.request_status();
            if (status == apf::kStatusRunning || status == apf::kStatusIdle) return;
            bridge_.idle_cycles(8);
        }
        throw std::runtime_error("status did not reach running/idle after Reset Exit");
    }

    BridgeHost<Top>& bridge_;
};

} // namespace apfsim
