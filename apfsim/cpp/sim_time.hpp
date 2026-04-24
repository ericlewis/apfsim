#pragma once

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace apfsim {

inline std::string trim(std::string s) {
    auto not_space = [](unsigned char c) { return !std::isspace(c); };
    s.erase(s.begin(), std::find_if(s.begin(), s.end(), not_space));
    s.erase(std::find_if(s.rbegin(), s.rend(), not_space).base(), s.end());
    return s;
}

inline std::string strip_comment(const std::string& s) {
    bool in_quote = false;
    for (size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '"' || s[i] == '\'') in_quote = !in_quote;
        if (!in_quote && s[i] == '#') return s.substr(0, i);
    }
    return s;
}

inline std::string unquote(std::string s) {
    s = trim(s);
    if (s.size() >= 2 && ((s.front() == '"' && s.back() == '"') || (s.front() == '\'' && s.back() == '\''))) {
        return s.substr(1, s.size() - 2);
    }
    return s;
}

inline uint64_t parse_u64(std::string s) {
    s = unquote(trim(s));
    if (s.empty()) return 0;
    size_t idx = 0;
    int base = 10;
    if (s.size() > 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) base = 16;
    uint64_t value = std::stoull(s, &idx, base);
    return value;
}

inline double parse_double(std::string s) {
    s = unquote(trim(s));
    if (s.empty()) return 0.0;
    return std::stod(s);
}

inline bool parse_bool(std::string s) {
    s = unquote(trim(s));
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s == "true" || s == "yes" || s == "1" || s == "on";
}

inline std::optional<std::pair<std::string, std::string>> parse_key_value(const std::string& raw) {
    std::string s = trim(strip_comment(raw));
    if (s.empty()) return std::nullopt;
    if (s.rfind("- ", 0) == 0) s = trim(s.substr(2));
    auto pos = s.find(':');
    if (pos == std::string::npos) return std::nullopt;
    auto key = trim(s.substr(0, pos));
    auto value = trim(s.substr(pos + 1));
    if (key.empty()) return std::nullopt;
    return std::make_pair(key, value);
}

inline std::string read_text_file(const std::filesystem::path& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("failed to open " + path.string());
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

inline std::vector<uint8_t> read_binary_file(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("failed to open " + path.string());
    return std::vector<uint8_t>(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
}

inline void write_binary_file(const std::filesystem::path& path, const std::vector<uint8_t>& bytes) {
    if (!path.parent_path().empty()) std::filesystem::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error("failed to write " + path.string());
    out.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
}

inline std::string hex32(uint32_t value) {
    std::ostringstream ss;
    ss << "0x" << std::hex << std::uppercase << std::setw(8) << std::setfill('0') << value;
    return ss.str();
}

inline std::string frame_name(uint64_t index, const char* ext) {
    std::ostringstream ss;
    ss << "frame_" << std::setw(6) << std::setfill('0') << index << "." << ext;
    return ss.str();
}

struct SimTime {
    uint64_t now_ps = 0;
    uint64_t cycles_74a = 0;
    uint64_t half_period_ps = 6734; // 74.25 MHz nominal, rounded to picoseconds.

    void advance_half() { now_ps += half_period_ps; }
};

} // namespace apfsim
