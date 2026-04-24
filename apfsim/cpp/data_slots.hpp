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
    std::filesystem::path file;
    bool required = false;
    bool nonvolatile = false;
    bool deferload = false;
    size_t size_exact = 0;
    size_t size_maximum = 0;
    size_t loaded_size = 0;
};

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
        if (id == UINT64_MAX || !has_address) continue;
        DataSlot slot;
        slot.id = static_cast<uint16_t>(id);
        slot.name = json_string_field(obj, "name");
        if (slot.name.empty()) slot.name = json_string_field(obj, "description");
        slot.file = json_string_field(obj, "file");
        if (slot.file.empty()) slot.file = json_string_field(obj, "filename");
        slot.address = static_cast<uint32_t>(address);
        slot.required = json_bool_field(obj, "required", false);
        slot.nonvolatile = json_bool_field(obj, "nonvolatile", json_bool_field(obj, "persistent", false));
        slot.deferload = json_bool_field(obj, "deferload", json_bool_field(obj, "deferred", false));
        slot.size_exact = static_cast<size_t>(json_int_field(obj, "size_exact", json_int_field(obj, "size", 0)));
        slot.size_maximum = static_cast<size_t>(json_int_field(obj, "size_maximum", json_int_field(obj, "maximum_size", 0)));
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
    slot.nonvolatile = id >= 4;
    slots.push_back(slot);
}

} // namespace apfsim
