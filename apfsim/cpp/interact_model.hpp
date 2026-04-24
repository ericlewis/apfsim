#pragma once

#include "data_slots.hpp"
#include "sim_time.hpp"

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace apfsim {

struct InteractWrite {
    std::string id;
    uint32_t address = 0;
    uint32_t value = 0;
    bool persistent = false;
};

class InteractModel {
public:
    void load_json(const std::filesystem::path& path) {
        if (path.empty()) return;
        const auto text = read_text_file(path);
        for (const auto& obj : json_object_fragments(text)) {
            const auto address = json_int_field(obj, "address", json_int_field(obj, "addr", 0));
            if (address == 0) continue;
            InteractWrite write;
            write.id = json_string_field(obj, "id");
            if (write.id.empty()) write.id = json_string_field(obj, "name");
            write.address = static_cast<uint32_t>(address);
            write.value = static_cast<uint32_t>(json_int_field(obj, "default", json_int_field(obj, "defaultval", json_int_field(obj, "value", 0))));
            write.persistent = json_bool_field(obj, "persist", json_bool_field(obj, "persistent", false));
            writes_.push_back(write);
        }
    }

    void add_write(uint32_t address, uint32_t value, bool persistent = true) {
        writes_.push_back({{}, address, value, persistent});
    }

    template <typename Bridge>
    size_t write_persistent_defaults(Bridge& bridge, bool verify = true) const {
        size_t count = 0;
        for (const auto& write : writes_) {
            if (!write.persistent) continue;
            bridge.write32(write.address, write.value);
            if (verify) {
                const uint32_t readback = bridge.read32(write.address);
                if (readback != write.value) {
                    throw std::runtime_error("interact write readback mismatch at " + hex32(write.address));
                }
            }
            ++count;
        }
        return count;
    }

    bool empty() const { return writes_.empty(); }

private:
    std::vector<InteractWrite> writes_;
};

} // namespace apfsim
