#pragma once

#include <cstdint>
#include <string>

namespace apfsim::apf {

constexpr uint32_t kCommandBase = 0xF8000000u;
constexpr uint32_t kTargetBase = 0xF8001000u;
constexpr uint32_t kTargetStatusOffset = 0x1000u;
constexpr uint32_t kTargetParamPointerOffset = 0x1004u;
constexpr uint32_t kTargetResponsePointerOffset = 0x1008u;
constexpr uint32_t kDataSlotTableBase = 0xF8002000u;

constexpr uint32_t kHostStatusOffset = 0x0000u;
constexpr uint32_t kHostParamPointerOffset = 0x0004u;
constexpr uint32_t kHostResponsePointerOffset = 0x0008u;
constexpr uint32_t kHostParam0Offset = 0x0020u;
constexpr uint32_t kHostParam1Offset = 0x0024u;
constexpr uint32_t kHostParam2Offset = 0x0028u;
constexpr uint32_t kHostParam3Offset = 0x002Cu;
constexpr uint32_t kTargetParam0Offset = 0x1020u;
constexpr uint32_t kTargetParam1Offset = 0x1024u;
constexpr uint32_t kTargetParam2Offset = 0x1028u;
constexpr uint32_t kTargetParam3Offset = 0x102Cu;

constexpr uint32_t magic_cmd(uint16_t cmd) { return 0x434D0000u | cmd; } // "CM"
constexpr uint32_t magic_busy(uint16_t cmd) { return 0x42550000u | cmd; } // "BU"
constexpr uint32_t magic_ok(uint16_t result) { return 0x4F4B0000u | result; } // "OK"
constexpr uint32_t target_magic_cmd(uint16_t cmd) { return 0x636D0000u | cmd; } // "cm"
constexpr uint32_t target_magic_busy(uint16_t status) { return 0x62750000u | status; } // "bu"
constexpr uint32_t target_magic_ok(uint16_t result) { return 0x6F6B0000u | result; } // "ok"
constexpr bool is_cmd(uint32_t word) { return (word & 0xFFFF0000u) == 0x434D0000u; }
constexpr bool is_busy(uint32_t word) { return (word & 0xFFFF0000u) == 0x42550000u; }
constexpr bool is_ok(uint32_t word) { return (word & 0xFFFF0000u) == 0x4F4B0000u; }
constexpr bool is_target_cmd(uint32_t word) { return (word & 0xFFFF0000u) == 0x636D0000u; }
constexpr bool is_target_busy(uint32_t word) { return (word & 0xFFFF0000u) == 0x62750000u; }
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
constexpr uint16_t kSavestateStartQuery = 0x00A0u;
constexpr uint16_t kSavestateLoadQuery = 0x00A4u;
constexpr uint16_t kOsNotifyMenuState = 0x00B0u;
constexpr uint16_t kOsNotifyCartridgeAdapter = 0x00B1u;
constexpr uint16_t kOsNotifyDockedState = 0x00B2u;
constexpr uint16_t kOsNotifyDisplayMode = 0x00B8u;

constexpr uint16_t kTargetReadyToRun = 0x0140u;
constexpr uint16_t kTargetDebugEventLog = 0x0152u;
constexpr uint16_t kTargetDataSlotRead = 0x0180u;
constexpr uint16_t kTargetDataSlotRead48 = 0x0181u;
constexpr uint16_t kTargetDataSlotWrite = 0x0184u;
constexpr uint16_t kTargetDataSlotWrite48 = 0x0185u;
constexpr uint16_t kTargetDataSlotFlush = 0x0188u;
constexpr uint16_t kTargetGetDataSlotFilename = 0x0190u;
constexpr uint16_t kTargetOpenNewFileIntoDataSlot = 0x0192u;

constexpr uint16_t kStatusBooting = 0x01u;
constexpr uint16_t kStatusSetup = 0x02u;
constexpr uint16_t kStatusIdle = 0x03u;
constexpr uint16_t kStatusRunning = 0x04u;

constexpr uint16_t kHostDataSlotReady = 0x00u;
constexpr uint16_t kHostDataSlotNotAllowed = 0x01u;
constexpr uint16_t kHostDataSlotCheckLater = 0x02u;

constexpr uint16_t kTargetOk = 0x00u;
constexpr uint16_t kTargetSlotNotDefined = 0x01u;
constexpr uint16_t kTargetRangeError = 0x02u;
constexpr uint16_t kTargetFileNotFound = 0x03u;
constexpr uint16_t kTargetMalformedPath = 0x04u;
constexpr uint16_t kTargetGeneralError = 0x05u;

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
        case kSavestateStartQuery: return "Savestate Start/Query";
        case kSavestateLoadQuery: return "Savestate Load/Query";
        case kOsNotifyMenuState: return "OS notify menu state";
        case kOsNotifyCartridgeAdapter: return "OS notify cartridge adapter";
        case kOsNotifyDockedState: return "OS notify docked state";
        case kOsNotifyDisplayMode: return "OS notify display mode";
        case kTargetReadyToRun: return "Ready to Run";
        case kTargetDebugEventLog: return "Debug Event Log";
        case kTargetDataSlotRead: return "Data slot read";
        case kTargetDataSlotRead48: return "Data slot read 48-bit";
        case kTargetDataSlotWrite: return "Data slot write";
        case kTargetDataSlotWrite48: return "Data slot write 48-bit";
        case kTargetDataSlotFlush: return "Data slot flush";
        case kTargetGetDataSlotFilename: return "Get filename of data slot";
        case kTargetOpenNewFileIntoDataSlot: return "Open new file into data slot";
        default: return "unknown";
    }
}

} // namespace apfsim::apf
