#pragma once

#include "sim_time.hpp"

#include <cstdint>
#include <filesystem>
#include <regex>
#include <string>
#include <unordered_map>
#include <vector>

namespace apfsim {

struct DataSlot {
    uint16_t id = 0;
    std::string name;
    uint32_t address = 0;
    bool has_address = false;
    std::filesystem::path file;
    bool required = false;
    bool nonvolatile = false;
    bool deferload = false;
    size_t size_exact = 0;
    size_t size_maximum = 0;
    size_t loaded_size = 0;
    size_t loaded_words = 0;
    uint32_t loaded_last_address = 0;
    size_t observed_write_words = 0;
    uint32_t observed_first_write_address = 0;
    uint32_t observed_last_write_address = 0;
    uint64_t observed_write_address_errors = 0;
    std::string load_status;
    std::string load_error;
    uint64_t loaded_checksum = 0;
    uint32_t loaded_crc32 = 0;
    uint64_t expected_checksum = 0;
    bool has_expected_checksum = false;
    bool verify_readback = false;
    bool readback_attempted = false;
    bool readback_matches = false;
    size_t readback_bytes = 0;
    uint32_t readback_crc32 = 0;
    uint64_t readback_checksum = 0;
    uint64_t readback_mismatch_count = 0;
    size_t readback_first_mismatch_offset = 0;
    bool readback_has_first_mismatch = false;
    uint8_t readback_expected_byte = 0;
    uint8_t readback_observed_byte = 0;
    std::vector<uint8_t> image;
    uint64_t target_read_requests = 0;
    uint64_t target_read_bytes = 0;
    uint64_t target_write_requests = 0;
    uint64_t target_write_bytes = 0;
    uint64_t target_flush_requests = 0;
    uint64_t target_filename_requests = 0;
    uint64_t target_open_requests = 0;
};

inline constexpr uint64_t kFnv1a64OffsetBasis = 14695981039346656037ull;
inline constexpr uint64_t kFnv1a64Prime = 1099511628211ull;

inline uint64_t fnv1a64(const std::vector<uint8_t>& bytes) {
    uint64_t hash = kFnv1a64OffsetBasis;
    for (const auto byte : bytes) {
        hash ^= byte;
        hash *= kFnv1a64Prime;
    }
    return hash;
}

inline uint32_t crc32(const std::vector<uint8_t>& bytes) {
    uint32_t crc = 0xFFFFFFFFu;
    for (const auto byte : bytes) {
        crc ^= static_cast<uint32_t>(byte);
        for (int i = 0; i < 8; ++i) {
            crc = (crc >> 1) ^ (0xEDB88320u & static_cast<uint32_t>(-static_cast<int32_t>(crc & 1u)));
        }
    }
    return ~crc;
}

inline uint64_t host_loaded_bytes(const std::vector<DataSlot>& slots) {
    uint64_t total = 0;
    for (const auto& slot : slots) {
        if (slot.has_address && !slot.deferload && !slot.nonvolatile) total += slot.loaded_size;
    }
    return total;
}

inline std::string json_string_field(const std::string& object, const std::string& key) {
    std::regex re("\\\"" + key + "\\\"\\s*:\\s*\\\"([^\\\"]*)\\\"");
    std::smatch m;
    if (std::regex_search(object, m, re)) return m[1].str();
    return {};
}

inline uint64_t json_int_field(const std::string& object, const std::string& key, uint64_t fallback = 0) {
    std::regex re("\\\"" + key + "\\\"\\s*:\\s*\\\"?(0x[0-9A-Fa-f]+|[0-9]+)\\\"?");
    std::smatch m;
    if (std::regex_search(object, m, re)) return parse_u64(m[1].str());
    return fallback;
}

inline bool json_has_int_field(const std::string& object, const std::string& key) {
    std::regex re("\\\"" + key + "\\\"\\s*:\\s*\\\"?(0x[0-9A-Fa-f]+|[0-9]+)\\\"?");
    return std::regex_search(object, re);
}

inline bool json_bool_field(const std::string& object, const std::string& key, bool fallback = false) {
    std::regex re("\\\"" + key + "\\\"\\s*:\\s*(true|false|1|0)", std::regex::icase);
    std::smatch m;
    if (std::regex_search(object, m, re)) return parse_bool(m[1].str());
    return fallback;
}

inline std::vector<std::string> json_object_fragments(const std::string& text) {
    std::vector<std::string> out;
    std::vector<size_t> starts;
    bool in_string = false;
    bool escape = false;
    for (size_t i = 0; i < text.size(); ++i) {
        char c = text[i];
        if (in_string) {
            if (escape) {
                escape = false;
            } else if (c == '\\') {
                escape = true;
            } else if (c == '"') {
                in_string = false;
            }
            continue;
        }
        if (c == '"') {
            in_string = true;
            continue;
        }
        if (c == '{') {
            starts.push_back(i);
        } else if (c == '}' && !starts.empty()) {
            const size_t start = starts.back();
            starts.pop_back();
            auto object = text.substr(start, i - start + 1);
            if (object.find('{', 1) == std::string::npos) out.emplace_back(std::move(object));
        }
    }
    return out;
}

inline std::vector<DataSlot> parse_data_json(const std::filesystem::path& path) {
    std::vector<DataSlot> slots;
    if (path.empty()) return slots;
    const auto text = read_text_file(path);
    for (const auto& obj : json_object_fragments(text)) {
        const auto id = json_int_field(obj, "id", UINT64_MAX);
        const bool has_address = json_has_int_field(obj, "address") ||
                                 json_has_int_field(obj, "load_address") ||
                                 json_has_int_field(obj, "bridge_address");
        const auto address = json_int_field(obj, "address", json_int_field(obj, "load_address", json_int_field(obj, "bridge_address", 0)));
        if (id == UINT64_MAX) continue;
        DataSlot slot;
        slot.id = static_cast<uint16_t>(id);
        slot.name = json_string_field(obj, "name");
        if (slot.name.empty()) slot.name = json_string_field(obj, "description");
        slot.file = json_string_field(obj, "file");
        if (slot.file.empty()) slot.file = json_string_field(obj, "filename");
        slot.address = static_cast<uint32_t>(address);
        slot.has_address = has_address;
        slot.required = json_bool_field(obj, "required", false);
        slot.nonvolatile = json_bool_field(obj, "nonvolatile", json_bool_field(obj, "persistent", false));
        slot.deferload = json_bool_field(obj, "deferload", json_bool_field(obj, "deferred", false));
        slot.verify_readback = json_bool_field(obj, "verify_readback", json_bool_field(obj, "readback_verify", false));
        slot.size_exact = static_cast<size_t>(json_int_field(obj, "size_exact", json_int_field(obj, "size", 0)));
        slot.size_maximum = static_cast<size_t>(json_int_field(obj, "size_maximum", json_int_field(obj, "maximum_size", 0)));
        if (json_has_int_field(obj, "expected_checksum") || json_has_int_field(obj, "checksum") || json_has_int_field(obj, "fnv1a64")) {
            slot.expected_checksum = json_int_field(obj, "expected_checksum", json_int_field(obj, "checksum", json_int_field(obj, "fnv1a64", 0)));
            slot.has_expected_checksum = true;
        }
        slots.push_back(slot);
    }
    return slots;
}

inline DataSlot* find_slot(std::vector<DataSlot>& slots, uint16_t id) {
    for (auto& slot : slots) {
        if (slot.id == id) return &slot;
    }
    return nullptr;
}

inline const DataSlot* find_slot(const std::vector<DataSlot>& slots, uint16_t id) {
    for (const auto& slot : slots) {
        if (slot.id == id) return &slot;
    }
    return nullptr;
}

inline void apply_slot_file_override(std::vector<DataSlot>& slots, uint16_t id, const std::filesystem::path& file) {
    if (auto* slot = find_slot(slots, id)) {
        slot->file = file;
        return;
    }
    DataSlot slot;
    slot.id = id;
    slot.name = "slot" + std::to_string(id);
    slot.file = file;
    slot.address = id == 4 ? 0x20000000u : 0x10000000u + (static_cast<uint32_t>(id) - 1u) * 0x01000000u;
    slot.has_address = true;
    slot.nonvolatile = id >= 4;
    slots.push_back(slot);
}

} // namespace apfsim
