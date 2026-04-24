#pragma once

#include "data_slots.hpp"
#include "sim_time.hpp"

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace apfsim {

struct InteractWrite {
    std::string id;
    uint32_t address = 0;
    uint32_t value = 0;
    uint32_t mask = 0xFFFFFFFFu;
    bool has_mask = false;
    bool persistent = false;
};

class InteractModel {
public:
    void load_json(const std::filesystem::path& path) {
        if (path.empty()) return;
        const auto text = read_text_file(path);
        auto objects = json_array_objects(text, "variables");
        if (objects.empty()) objects = json_object_fragments(text);
        for (const auto& obj : objects) {
            const auto address = json_int_field(obj, "address", json_int_field(obj, "addr", 0));
            if (address == 0) continue;
            InteractWrite write;
            write.id = json_string_field(obj, "id");
            if (write.id.empty()) write.id = json_string_field(obj, "name");
            write.address = static_cast<uint32_t>(address);
            const uint32_t default_value = static_cast<uint32_t>(json_int_field(obj, "default", json_int_field(obj, "defaultval", json_int_field(obj, "value", 0))));
            const auto type = json_string_field(obj, "type");
            const bool nested_options = type == "list" || type == "radio" || type == "radioselect";
            const bool has_value = !nested_options && json_has_int_field(obj, "value");
            const bool has_value_off = !nested_options && json_has_int_field(obj, "value_off");
            const uint32_t value_on = static_cast<uint32_t>(json_int_field(obj, "value", default_value));
            const uint32_t value_off = static_cast<uint32_t>(json_int_field(obj, "value_off", 0));
            if (nested_options) {
                write.value = option_value_for_default(obj, default_value, default_value);
            } else if (has_value || has_value_off) {
                if (default_value == value_on || default_value == value_off) {
                    write.value = default_value;
                } else {
                    write.value = default_value ? value_on : value_off;
                }
            } else {
                write.value = default_value;
            }
            if (json_has_int_field(obj, "mask")) {
                write.mask = static_cast<uint32_t>(json_int_field(obj, "mask", 0xFFFFFFFFu));
                write.has_mask = true;
            }
            write.persistent = json_bool_field(obj, "persist", json_bool_field(obj, "persistent", false));
            writes_.push_back(write);
        }
    }

    void add_write(uint32_t address, uint32_t value, bool persistent = true) {
        writes_.push_back({{}, address, value, 0xFFFFFFFFu, false, persistent});
    }

    void append(const InteractModel& other) {
        writes_.insert(writes_.end(), other.writes_.begin(), other.writes_.end());
    }

    template <typename Bridge>
    size_t write_persistent_defaults(Bridge& bridge, bool verify = true) const {
        struct PendingWrite {
            uint32_t address = 0;
            uint32_t value = 0;
        };
        std::vector<PendingWrite> pending;
        size_t count = 0;
        for (const auto& write : writes_) {
            if (!write.persistent) continue;
            auto it = std::find_if(pending.begin(), pending.end(), [&](const PendingWrite& item) {
                return item.address == write.address;
            });
            if (it == pending.end()) {
                PendingWrite item;
                item.address = write.address;
                item.value = write.has_mask ? bridge.read32(write.address) : 0;
                pending.push_back(item);
                it = pending.end() - 1;
            }
            it->value = write.has_mask ? ((it->value & write.mask) | write.value) : write.value;
            ++count;
        }
        for (const auto& write : pending) {
            bridge.write32(write.address, write.value);
            if (verify) {
                const uint32_t readback = bridge.read32(write.address);
                if (readback != write.value) {
                    throw std::runtime_error("interact write readback mismatch at " + hex32(write.address));
                }
            }
        }
        return count;
    }

    bool empty() const { return writes_.empty(); }

private:
    static uint32_t option_value_for_default(const std::string& obj, uint32_t default_index, uint32_t fallback) {
        const auto options = json_array_objects(obj, "options");
        if (default_index >= options.size()) return fallback;
        if (!json_has_int_field(options[default_index], "value")) return fallback;
        return static_cast<uint32_t>(json_int_field(options[default_index], "value", fallback));
    }

    static std::vector<std::string> json_array_objects(const std::string& text, const std::string& key) {
        const std::string needle = "\"" + key + "\"";
        const auto key_pos = text.find(needle);
        if (key_pos == std::string::npos) return {};
        const auto array_pos = text.find('[', key_pos + needle.size());
        if (array_pos == std::string::npos) return {};

        std::vector<std::string> out;
        bool in_string = false;
        bool escape = false;
        int array_depth = 0;
        int object_depth = 0;
        size_t object_start = std::string::npos;
        for (size_t i = array_pos; i < text.size(); ++i) {
            const char c = text[i];
            if (in_string) {
                if (escape) escape = false;
                else if (c == '\\') escape = true;
                else if (c == '"') in_string = false;
                continue;
            }
            if (c == '"') {
                in_string = true;
                continue;
            }
            if (c == '[') {
                ++array_depth;
                continue;
            }
            if (c == ']') {
                --array_depth;
                if (array_depth == 0) break;
                continue;
            }
            if (array_depth != 1 && object_depth == 0) continue;
            if (c == '{') {
                if (object_depth == 0) object_start = i;
                ++object_depth;
            } else if (c == '}' && object_depth > 0) {
                --object_depth;
                if (object_depth == 0 && object_start != std::string::npos) {
                    out.emplace_back(text.substr(object_start, i - object_start + 1));
                    object_start = std::string::npos;
                }
            }
        }
        return out;
    }

    std::vector<InteractWrite> writes_;
};

} // namespace apfsim
