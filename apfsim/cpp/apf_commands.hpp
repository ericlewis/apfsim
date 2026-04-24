#pragma once

#include <cstdint>
#include <string>

namespace apfsim::apf {

constexpr uint32_t kCommandBase = 0xF8000000u;
constexpr uint32_t kTargetBase = 0xF8001000u;
constexpr uint32_t kDataSlotTableBase = 0xF8002000u;

constexpr uint32_t kHostStatusOffset = 0x0000u;
constexpr uint32_t kHostParamPointerOffset = 0x0004u;
constexpr uint32_t kHostResponsePointerOffset = 0x0008u;
constexpr uint32_t kHostParam0Offset = 0x0020u;
constexpr uint32_t kHostParam1Offset = 0x0024u;
constexpr uint32_t kHostParam2Offset = 0x0028u;
constexpr uint32_t kHostParam3Offset = 0x002Cu;

constexpr uint32_t magic_cmd(uint16_t cmd) { return 0x434D0000u | cmd; } // "CM"
constexpr uint32_t magic_busy(uint16_t cmd) { return 0x42550000u | cmd; } // "BU"
constexpr uint32_t magic_ok(uint16_t result) { return 0x4F4B0000u | result; } // "OK"
constexpr uint32_t target_magic_cmd(uint16_t cmd) { return 0x636D0000u | cmd; } // "cm"
constexpr uint32_t target_magic_ok(uint16_t result) { return 0x6F6B0000u | result; } // "ok"
constexpr bool is_cmd(uint32_t word) { return (word & 0xFFFF0000u) == 0x434D0000u; }
constexpr bool is_busy(uint32_t word) { return (word & 0xFFFF0000u) == 0x42550000u; }
constexpr bool is_ok(uint32_t word) { return (word & 0xFFFF0000u) == 0x4F4B0000u; }
constexpr bool is_target_cmd(uint32_t word) { return (word & 0xFFFF0000u) == 0x636D0000u; }
constexpr bool is_target_ok(uint32_t word) { return (word & 0xFFFF0000u) == 0x6F6B0000u; }
constexpr uint16_t low16(uint32_t word) { return static_cast<uint16_t>(word & 0xFFFFu); }

constexpr uint16_t kRequestStatus = 0x0000u;
constexpr uint16_t kResetEnter = 0x0010u;
constexpr uint16_t kResetExit = 0x0011u;
constexpr uint16_t kDataSlotRequestRead = 0x0080u;
constexpr uint16_t kDataSlotRequestWrite = 0x0082u;
constexpr uint16_t kDataSlotUpdate = 0x008Au;
constexpr uint16_t kDataSlotAllComplete = 0x008Fu;
constexpr uint16_t kRtcData = 0x0090u;
constexpr uint16_t kOsNotifyCartridgeAdapter = 0x00B1u;
constexpr uint16_t kOsNotifyDisplayMode = 0x00B8u;

constexpr uint16_t kTargetReadyToRun = 0x0140u;

constexpr uint16_t kStatusBooting = 0x01u;
constexpr uint16_t kStatusSetup = 0x02u;
constexpr uint16_t kStatusIdle = 0x03u;
constexpr uint16_t kStatusRunning = 0x04u;

inline const char* status_name(uint16_t status) {
    switch (status) {
        case kStatusBooting: return "booting";
        case kStatusSetup: return "setup";
        case kStatusIdle: return "idle";
        case kStatusRunning: return "running";
        default: return "unknown";
    }
}

inline const char* command_name(uint16_t cmd) {
    switch (cmd) {
        case kRequestStatus: return "Request Status";
        case kResetEnter: return "Reset Enter";
        case kResetExit: return "Reset Exit";
        case kDataSlotRequestRead: return "Data slot request read";
        case kDataSlotRequestWrite: return "Data slot request write";
        case kDataSlotUpdate: return "Data slot update";
        case kDataSlotAllComplete: return "Data slot access all complete";
        case kRtcData: return "Real-time clock data";
        case kTargetReadyToRun: return "Ready to Run";
        default: return "unknown";
    }
}

} // namespace apfsim::apf
