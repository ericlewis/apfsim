#pragma once

#include "sim_time.hpp"
#include "data_slots.hpp"

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace apfsim {

struct FrameMetadata {
    uint64_t frame = 0;
    size_t active_width = 0;
    size_t active_width_min = 0;
    size_t active_height = 0;
    uint64_t hs_pulses = 0;
    uint64_t vs_pulses = 0;
    uint64_t total_pixel_clocks = 0;
    uint64_t pixels_per_line_min = 0;
    uint64_t pixels_per_line_max = 0;
    uint64_t hs_after_vs_gap_min = UINT64_MAX;
    uint64_t hs_to_de_gap_min = UINT64_MAX;
    uint64_t de_to_hs_gap_min = UINT64_MAX;
    uint64_t de_errors = 0;
    uint64_t rgb_when_de_low_errors = 0;
    uint64_t pulse_width_errors = 0;
    uint64_t skip_errors = 0;
};

class VideoCapture {
public:
    void set_dump_dir(std::filesystem::path dir) {
        dump_dir_ = std::move(dir);
        if (!dump_dir_.empty()) std::filesystem::create_directories(dump_dir_);
    }

    void set_expected(size_t width, size_t height) {
        expected_width_ = width;
        expected_height_ = height;
    }

    template <typename Top>
    void sample(const Top* top) {
        const bool clk = top->video_rgb_clock != 0;
        if (clk && !prev_clk_) on_pixel_clock(top);
        prev_clk_ = clk;
    }

    uint64_t frames_started() const { return frames_started_; }
    uint64_t frames_completed() const { return frames_completed_; }
    const FrameMetadata& last_metadata() const { return last_metadata_; }
    uint64_t errors() const { return total_errors_; }

    void reset_capture() {
        in_frame_ = false;
        de_seen_this_line_ = false;
        de_closed_this_line_ = false;
        frames_started_ = 0;
        frames_completed_ = 0;
        hs_width_ = 0;
        vs_width_ = 0;
        pixel_in_frame_ = 0;
        pixels_since_hs_ = 0;
        have_hs_seen_ = false;
        seen_hs_after_vs_ = false;
        last_vs_rise_pixel_ = 0;
        last_hs_rise_pixel_ = 0;
        last_de_fall_pixel_ = 0;
        have_de_fall_ = false;
        total_errors_ = 0;
        current_ = {};
        last_metadata_ = {};
        current_line_.clear();
        current_lines_.clear();
        if (!dump_dir_.empty()) {
            std::filesystem::remove_all(dump_dir_);
            std::filesystem::create_directories(dump_dir_);
        }
    }

private:
    template <typename Top>
    void on_pixel_clock(const Top* top) {
        const bool hs = top->video_hs != 0;
        const bool vs = top->video_vs != 0;
        const bool de = top->video_de != 0;
        const bool skip = top->video_skip != 0;
        const uint32_t rgb = static_cast<uint32_t>(top->video_rgb) & 0x00FFFFFFu;

        if (vs) ++vs_width_;
        if (hs) ++hs_width_;

        if (vs && !prev_vs_) {
            if (in_frame_) finalize_frame();
            start_frame();
            last_vs_rise_pixel_ = pixel_in_frame_;
            seen_hs_after_vs_ = false;
        }

        if (hs && !prev_hs_) {
            record_line_length_if_needed();
            ++current_.hs_pulses;
            close_line_if_needed();
            if (!seen_hs_after_vs_) {
                const uint64_t gap = pixel_in_frame_ >= last_vs_rise_pixel_ ? pixel_in_frame_ - last_vs_rise_pixel_ : 0;
                current_.hs_after_vs_gap_min = std::min(current_.hs_after_vs_gap_min, gap);
                seen_hs_after_vs_ = true;
            }
            if (have_de_fall_) {
                const uint64_t gap = pixel_in_frame_ >= last_de_fall_pixel_ ? pixel_in_frame_ - last_de_fall_pixel_ : 0;
                current_.de_to_hs_gap_min = std::min(current_.de_to_hs_gap_min, gap);
            }
            have_hs_seen_ = true;
            pixels_since_hs_ = 0;
            last_hs_rise_pixel_ = pixel_in_frame_;
            de_seen_this_line_ = false;
            de_closed_this_line_ = false;
        }

        if (!vs && prev_vs_) {
            if (vs_width_ != 1) {
                ++current_.pulse_width_errors;
                ++total_errors_;
            }
            vs_width_ = 0;
        }
        if (!hs && prev_hs_) {
            if (hs_width_ != 1) {
                ++current_.pulse_width_errors;
                ++total_errors_;
            }
            hs_width_ = 0;
        }

        if (de && !prev_de_) {
            if (!have_hs_seen_) {
                ++current_.de_errors;
                ++total_errors_;
            } else {
                const uint64_t gap = pixel_in_frame_ >= last_hs_rise_pixel_ ? pixel_in_frame_ - last_hs_rise_pixel_ : 0;
                current_.hs_to_de_gap_min = std::min(current_.hs_to_de_gap_min, gap);
            }
            if (de_seen_this_line_ || de_closed_this_line_) {
                ++current_.de_errors;
                ++total_errors_;
            }
            de_seen_this_line_ = true;
        }
        if (!de && prev_de_) {
            de_closed_this_line_ = true;
            have_de_fall_ = true;
            last_de_fall_pixel_ = pixel_in_frame_;
            close_line_if_needed();
        }

        if (skip && !de) {
            ++current_.skip_errors;
            ++total_errors_;
        }
        if (de) {
            current_line_.push_back(rgb);
        } else if (rgb != 0) {
            ++current_.rgb_when_de_low_errors;
            ++total_errors_;
        }

        prev_hs_ = hs;
        prev_vs_ = vs;
        prev_de_ = de;

        if (in_frame_) {
            ++current_.total_pixel_clocks;
            ++pixel_in_frame_;
            if (have_hs_seen_) ++pixels_since_hs_;
        }
    }

    void start_frame() {
        in_frame_ = true;
        ++frames_started_;
        current_ = {};
        current_.frame = frames_started_;
        current_.vs_pulses = 1;
        current_.hs_after_vs_gap_min = UINT64_MAX;
        current_.hs_to_de_gap_min = UINT64_MAX;
        current_.de_to_hs_gap_min = UINT64_MAX;
        current_lines_.clear();
        current_line_.clear();
        de_seen_this_line_ = false;
        de_closed_this_line_ = false;
        pixel_in_frame_ = 0;
        pixels_since_hs_ = 0;
        have_hs_seen_ = false;
        seen_hs_after_vs_ = false;
        have_de_fall_ = false;
    }

    void close_line_if_needed() {
        if (!current_line_.empty()) {
            current_.active_width = std::max(current_.active_width, current_line_.size());
            current_.active_width_min = current_.active_width_min == 0 ? current_line_.size() : std::min(current_.active_width_min, current_line_.size());
            current_lines_.push_back(std::move(current_line_));
            current_line_.clear();
        }
    }

    void record_line_length_if_needed() {
        if (!have_hs_seen_ || pixels_since_hs_ == 0) return;
        current_.pixels_per_line_min = current_.pixels_per_line_min == 0 ? pixels_since_hs_ : std::min(current_.pixels_per_line_min, pixels_since_hs_);
        current_.pixels_per_line_max = std::max(current_.pixels_per_line_max, pixels_since_hs_);
    }

    void finalize_frame() {
        record_line_length_if_needed();
        close_line_if_needed();
        current_.active_height = current_lines_.size();
        if (current_.hs_after_vs_gap_min == UINT64_MAX) current_.hs_after_vs_gap_min = 0;
        if (current_.hs_to_de_gap_min == UINT64_MAX) current_.hs_to_de_gap_min = 0;
        if (current_.de_to_hs_gap_min == UINT64_MAX) current_.de_to_hs_gap_min = 0;
        if (expected_width_ && current_.active_width != expected_width_) {
            ++current_.de_errors;
            ++total_errors_;
        }
        if (expected_height_ && current_.active_height != expected_height_) {
            ++current_.de_errors;
            ++total_errors_;
        }
        ++frames_completed_;
        last_metadata_ = current_;
        if (!dump_dir_.empty()) dump_frame(current_, current_lines_);
    }

    void dump_frame(const FrameMetadata& meta, const std::vector<std::vector<uint32_t>>& lines) const {
        const auto ppm = dump_dir_ / frame_name(meta.frame, "ppm");
        const auto json = dump_dir_ / frame_name(meta.frame, "json");
        std::ofstream out(ppm, std::ios::binary);
        if (out) {
            out << "P6\n" << meta.active_width << " " << meta.active_height << "\n255\n";
            for (const auto& line : lines) {
                for (size_t x = 0; x < meta.active_width; ++x) {
                    uint32_t rgb = x < line.size() ? line[x] : 0;
                    char px[3] = {
                        static_cast<char>((rgb >> 16) & 0xFF),
                        static_cast<char>((rgb >> 8) & 0xFF),
                        static_cast<char>(rgb & 0xFF),
                    };
                    out.write(px, 3);
                }
            }
        }
        std::ofstream js(json);
        if (js) {
            js << "{\n";
            js << "  \"frame\": " << meta.frame << ",\n";
            js << "  \"active_width\": " << meta.active_width << ",\n";
            js << "  \"active_width_min\": " << meta.active_width_min << ",\n";
            js << "  \"active_height\": " << meta.active_height << ",\n";
            js << "  \"total_pixel_clocks\": " << meta.total_pixel_clocks << ",\n";
            js << "  \"pixels_per_line_min\": " << meta.pixels_per_line_min << ",\n";
            js << "  \"pixels_per_line_max\": " << meta.pixels_per_line_max << ",\n";
            js << "  \"hs_pulses\": " << meta.hs_pulses << ",\n";
            js << "  \"vs_pulses\": " << meta.vs_pulses << ",\n";
            js << "  \"hs_after_vs_gap_min\": " << meta.hs_after_vs_gap_min << ",\n";
            js << "  \"hs_to_de_gap_min\": " << meta.hs_to_de_gap_min << ",\n";
            js << "  \"de_to_hs_gap_min\": " << meta.de_to_hs_gap_min << ",\n";
            js << "  \"de_errors\": " << meta.de_errors << ",\n";
            js << "  \"rgb_when_de_low_errors\": " << meta.rgb_when_de_low_errors << ",\n";
            js << "  \"pulse_width_errors\": " << meta.pulse_width_errors << ",\n";
            js << "  \"skip_errors\": " << meta.skip_errors << "\n";
            js << "}\n";
        }
    }

    std::filesystem::path dump_dir_;
    size_t expected_width_ = 0;
    size_t expected_height_ = 0;
    bool prev_clk_ = false;
    bool prev_hs_ = false;
    bool prev_vs_ = false;
    bool prev_de_ = false;
    bool in_frame_ = false;
    bool de_seen_this_line_ = false;
    bool de_closed_this_line_ = false;
    uint64_t frames_started_ = 0;
    uint64_t frames_completed_ = 0;
    uint64_t hs_width_ = 0;
    uint64_t vs_width_ = 0;
    uint64_t pixel_in_frame_ = 0;
    uint64_t pixels_since_hs_ = 0;
    uint64_t last_vs_rise_pixel_ = 0;
    uint64_t last_hs_rise_pixel_ = 0;
    uint64_t last_de_fall_pixel_ = 0;
    uint64_t total_errors_ = 0;
    bool have_hs_seen_ = false;
    bool seen_hs_after_vs_ = false;
    bool have_de_fall_ = false;
    FrameMetadata current_;
    FrameMetadata last_metadata_;
    std::vector<uint32_t> current_line_;
    std::vector<std::vector<uint32_t>> current_lines_;
};

inline std::pair<size_t, size_t> parse_video_json_dimensions(const std::filesystem::path& path) {
    if (path.empty()) return {0, 0};
    const auto text = read_text_file(path);
    const auto width = json_int_field(text, "expected_width", json_int_field(text, "width", 0));
    const auto height = json_int_field(text, "expected_height", json_int_field(text, "height", 0));
    return {static_cast<size_t>(width), static_cast<size_t>(height)};
}

} // namespace apfsim
