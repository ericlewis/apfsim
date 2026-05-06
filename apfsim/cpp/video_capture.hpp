#pragma once

#include "sim_time.hpp"
#include "data_slots.hpp"

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <unordered_set>
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
    uint64_t vs_to_first_de_lines = UINT64_MAX;
    uint64_t de_errors = 0;
    uint64_t rgb_when_de_low_errors = 0;
    uint64_t pulse_width_errors = 0;
    uint64_t skip_errors = 0;
    uint64_t unique_colors = 0;
    uint64_t nonzero_pixels = 0;
    uint64_t changed_pixels_from_previous = 0;
    uint64_t frame_hash = 0;
};

struct VideoAggregate {
    uint64_t frames = 0;
    size_t active_width_min = 0;
    size_t active_width_max = 0;
    size_t active_height_min = 0;
    size_t active_height_max = 0;
    uint64_t hs_pulses_min = 0;
    uint64_t hs_pulses_max = 0;
    uint64_t hs_after_vs_gap_min = 0;
    uint64_t hs_to_de_gap_min = 0;
    uint64_t de_to_hs_gap_min = 0;
    uint64_t vs_to_first_de_lines_min = 0;
    uint64_t vs_to_first_de_lines_max = 0;
    uint64_t total_width_min = 0;
    uint64_t total_width_max = 0;
    uint64_t de_errors = 0;
    uint64_t rgb_when_de_low_errors = 0;
    uint64_t pulse_width_errors = 0;
    uint64_t skip_errors = 0;
    uint64_t total_errors = 0;
    uint64_t unstable_dimension_frames = 0;
    uint64_t hs_under_active_height_frames = 0;
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
    void sample(const Top* top, uint64_t sim_cycle = 0) {
        current_cycle_ = sim_cycle;
        const bool clk = top->video_rgb_clock != 0;
        if (clk && !prev_clk_) on_pixel_clock(top);
        prev_clk_ = clk;
    }

    uint64_t frames_started() const { return frames_started_; }
    uint64_t frames_completed() const { return frames_completed_; }
    uint64_t changed_frames() const { return changed_frames_; }
    uint64_t max_changed_pixels_from_previous() const { return max_changed_pixels_from_previous_; }
    uint64_t frames_in_range(uint64_t start_frame, uint64_t end_frame = 0) const {
        uint64_t count = 0;
        for (const auto& frame : frame_history_) {
            if (frame.frame < start_frame) continue;
            if (end_frame && frame.frame > end_frame) continue;
            ++count;
        }
        return count;
    }
    uint64_t changed_frames_in_range(uint64_t start_frame, uint64_t end_frame = 0, uint64_t min_changed_pixels = 1) const {
        uint64_t count = 0;
        for (const auto& frame : frame_history_) {
            if (frame.frame < start_frame) continue;
            if (end_frame && frame.frame > end_frame) continue;
            if (frame.changed_pixels_from_previous >= min_changed_pixels) ++count;
        }
        return count;
    }
    uint64_t max_changed_pixels_in_range(uint64_t start_frame, uint64_t end_frame = 0) const {
        uint64_t max_changed = 0;
        for (const auto& frame : frame_history_) {
            if (frame.frame < start_frame) continue;
            if (end_frame && frame.frame > end_frame) continue;
            max_changed = std::max(max_changed, frame.changed_pixels_from_previous);
        }
        return max_changed;
    }
    uint64_t first_changed_frame_in_range(uint64_t start_frame, uint64_t end_frame = 0, uint64_t min_changed_pixels = 1) const {
        for (const auto& frame : frame_history_) {
            if (frame.frame < start_frame) continue;
            if (end_frame && frame.frame > end_frame) continue;
            if (frame.changed_pixels_from_previous >= min_changed_pixels) return frame.frame;
        }
        return 0;
    }
    const FrameMetadata& last_metadata() const { return last_metadata_; }
    const std::vector<FrameMetadata>& frame_history() const { return frame_history_; }
    const std::vector<uint32_t>& last_frame_pixels() const { return last_frame_pixels_; }
    size_t last_frame_width() const { return last_metadata_.active_width; }
    size_t last_frame_height() const { return last_metadata_.active_height; }
    uint64_t errors() const { return total_errors_; }
    bool has_first_error() const { return first_error_seen_; }
    uint64_t first_error_cycle() const { return first_error_cycle_; }
    uint64_t first_error_frame() const { return first_error_frame_; }
    uint64_t first_error_pixel() const { return first_error_pixel_; }
    const std::string& first_error_code() const { return first_error_code_; }
    uint64_t errors_after_startup_frames(uint64_t ignored_frames) const {
        uint64_t errors = 0;
        for (const auto& frame : frame_history_) {
            if (frame.frame <= ignored_frames) continue;
            errors += frame_error_count(frame);
        }
        return errors;
    }
    VideoAggregate aggregate_after_startup_frames(uint64_t ignored_frames) const {
        VideoAggregate agg;
        size_t previous_width = 0;
        size_t previous_height = 0;
        for (const auto& frame : frame_history_) {
            if (frame.frame <= ignored_frames) continue;
            ++agg.frames;
            agg.active_width_min = agg.active_width_min == 0 ? frame.active_width : std::min(agg.active_width_min, frame.active_width);
            agg.active_width_max = std::max(agg.active_width_max, frame.active_width);
            agg.active_height_min = agg.active_height_min == 0 ? frame.active_height : std::min(agg.active_height_min, frame.active_height);
            agg.active_height_max = std::max(agg.active_height_max, frame.active_height);
            agg.hs_pulses_min = agg.hs_pulses_min == 0 ? frame.hs_pulses : std::min(agg.hs_pulses_min, frame.hs_pulses);
            agg.hs_pulses_max = std::max(agg.hs_pulses_max, frame.hs_pulses);
            agg.hs_after_vs_gap_min = agg.hs_after_vs_gap_min == 0 ? frame.hs_after_vs_gap_min : std::min(agg.hs_after_vs_gap_min, frame.hs_after_vs_gap_min);
            agg.hs_to_de_gap_min = agg.hs_to_de_gap_min == 0 ? frame.hs_to_de_gap_min : std::min(agg.hs_to_de_gap_min, frame.hs_to_de_gap_min);
            agg.de_to_hs_gap_min = agg.de_to_hs_gap_min == 0 ? frame.de_to_hs_gap_min : std::min(agg.de_to_hs_gap_min, frame.de_to_hs_gap_min);
            agg.vs_to_first_de_lines_min = agg.vs_to_first_de_lines_min == 0 ? frame.vs_to_first_de_lines : std::min(agg.vs_to_first_de_lines_min, frame.vs_to_first_de_lines);
            agg.vs_to_first_de_lines_max = std::max(agg.vs_to_first_de_lines_max, frame.vs_to_first_de_lines);
            agg.total_width_min = agg.total_width_min == 0 ? frame.pixels_per_line_min : std::min(agg.total_width_min, frame.pixels_per_line_min);
            agg.total_width_max = std::max(agg.total_width_max, frame.pixels_per_line_max);
            agg.de_errors += frame.de_errors;
            agg.rgb_when_de_low_errors += frame.rgb_when_de_low_errors;
            agg.pulse_width_errors += frame.pulse_width_errors;
            agg.skip_errors += frame.skip_errors;
            agg.total_errors += frame_error_count(frame);
            if (previous_width != 0 && (frame.active_width != previous_width || frame.active_height != previous_height)) {
                ++agg.unstable_dimension_frames;
            }
            previous_width = frame.active_width;
            previous_height = frame.active_height;
            if (frame.active_height > 0 && frame.hs_pulses < frame.active_height) ++agg.hs_under_active_height_frames;
        }
        return agg;
    }

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
        first_de_seen_ = false;
        line_index_since_vs_ = 0;
        last_vs_rise_pixel_ = 0;
        last_hs_rise_pixel_ = 0;
        last_de_fall_pixel_ = 0;
        have_de_fall_ = false;
        total_errors_ = 0;
        current_cycle_ = 0;
        first_error_seen_ = false;
        first_error_cycle_ = 0;
        first_error_frame_ = 0;
        first_error_pixel_ = 0;
        first_error_code_.clear();
        changed_frames_ = 0;
        max_changed_pixels_from_previous_ = 0;
        current_ = {};
        last_metadata_ = {};
        frame_history_.clear();
        previous_frame_pixels_.clear();
        last_frame_pixels_.clear();
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

        if (vs && !prev_vs_) {
            if (in_frame_) finalize_frame();
            start_frame();
            last_vs_rise_pixel_ = pixel_in_frame_;
            seen_hs_after_vs_ = false;
        }

        if (!in_frame_) {
            prev_hs_ = hs;
            prev_vs_ = vs;
            prev_de_ = de;
            return;
        }

        if (vs) ++vs_width_;
        if (hs) ++hs_width_;

        if (hs && !prev_hs_) {
            record_line_length_if_needed();
            ++current_.hs_pulses;
            close_line_if_needed();
            if (!seen_hs_after_vs_) {
                const uint64_t gap = pixel_in_frame_ >= last_vs_rise_pixel_ ? pixel_in_frame_ - last_vs_rise_pixel_ : 0;
                current_.hs_after_vs_gap_min = std::min(current_.hs_after_vs_gap_min, gap);
                seen_hs_after_vs_ = true;
                line_index_since_vs_ = 0;
            } else {
                ++line_index_since_vs_;
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
                record_error("vs_pulse_width", current_.pulse_width_errors);
            }
            vs_width_ = 0;
        }
        if (!hs && prev_hs_) {
            if (hs_width_ != 1) {
                record_error("hs_pulse_width", current_.pulse_width_errors);
            }
            hs_width_ = 0;
        }

        if (de && !prev_de_) {
            if (!first_de_seen_) {
                current_.vs_to_first_de_lines = line_index_since_vs_;
                first_de_seen_ = true;
            }
            if (!have_hs_seen_) {
                record_error("de_before_hs", current_.de_errors);
            } else {
                const uint64_t gap = pixel_in_frame_ >= last_hs_rise_pixel_ ? pixel_in_frame_ - last_hs_rise_pixel_ : 0;
                current_.hs_to_de_gap_min = std::min(current_.hs_to_de_gap_min, gap);
            }
            if (de_seen_this_line_ || de_closed_this_line_) {
                record_error("de_multiple_per_line", current_.de_errors);
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
            record_error("skip_outside_de", current_.skip_errors);
        }
        if (de) {
            current_line_.push_back(rgb);
        } else if (rgb != 0) {
            record_error("rgb_when_de_low", current_.rgb_when_de_low_errors);
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
        current_.vs_to_first_de_lines = UINT64_MAX;
        current_lines_.clear();
        current_line_.clear();
        de_seen_this_line_ = false;
        de_closed_this_line_ = false;
        pixel_in_frame_ = 0;
        pixels_since_hs_ = 0;
        have_hs_seen_ = false;
        seen_hs_after_vs_ = false;
        first_de_seen_ = false;
        have_de_fall_ = false;
        line_index_since_vs_ = 0;
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
        close_line_if_needed();
        current_.active_height = current_lines_.size();
        if (current_.hs_after_vs_gap_min == UINT64_MAX) current_.hs_after_vs_gap_min = 0;
        if (current_.hs_to_de_gap_min == UINT64_MAX) current_.hs_to_de_gap_min = 0;
        if (current_.de_to_hs_gap_min == UINT64_MAX) current_.de_to_hs_gap_min = 0;
        if (current_.vs_to_first_de_lines == UINT64_MAX) current_.vs_to_first_de_lines = 0;
        if (expected_width_ && current_.active_width != expected_width_) {
            record_error("active_width_mismatch", current_.de_errors);
        }
        if (expected_height_ && current_.active_height != expected_height_) {
            record_error("active_height_mismatch", current_.de_errors);
        }
        compute_content_metrics();
        ++frames_completed_;
        last_metadata_ = current_;
        frame_history_.push_back(current_);
        if (!dump_dir_.empty()) dump_frame(current_, current_lines_);
    }

    static uint64_t frame_error_count(const FrameMetadata& meta) {
        return meta.de_errors + meta.rgb_when_de_low_errors + meta.pulse_width_errors + meta.skip_errors;
    }

    void record_error(const std::string& code, uint64_t& counter) {
        ++counter;
        ++total_errors_;
        if (!first_error_seen_) {
            first_error_seen_ = true;
            first_error_cycle_ = current_cycle_;
            first_error_frame_ = current_.frame;
            first_error_pixel_ = pixel_in_frame_;
            first_error_code_ = code;
        }
    }

    void compute_content_metrics() {
        std::vector<uint32_t> pixels;
        pixels.reserve(current_.active_width * current_.active_height);
        std::unordered_set<uint32_t> colors;
        uint64_t hash = kFnv1a64OffsetBasis;
        uint64_t nonzero = 0;
        for (const auto& line : current_lines_) {
            for (size_t x = 0; x < current_.active_width; ++x) {
                const uint32_t rgb = x < line.size() ? line[x] : 0;
                pixels.push_back(rgb);
                colors.insert(rgb);
                if (rgb != 0) ++nonzero;
                hash ^= rgb & 0xFFu;
                hash *= kFnv1a64Prime;
                hash ^= (rgb >> 8) & 0xFFu;
                hash *= kFnv1a64Prime;
                hash ^= (rgb >> 16) & 0xFFu;
                hash *= kFnv1a64Prime;
            }
        }
        uint64_t changed = 0;
        const bool had_previous = previous_frame_pixels_.size() == pixels.size();
        if (had_previous) {
            for (size_t i = 0; i < pixels.size(); ++i) {
                if (pixels[i] != previous_frame_pixels_[i]) ++changed;
            }
        }
        current_.unique_colors = colors.size();
        current_.nonzero_pixels = nonzero;
        current_.changed_pixels_from_previous = changed;
        if (had_previous && changed != 0) {
            ++changed_frames_;
            max_changed_pixels_from_previous_ = std::max(max_changed_pixels_from_previous_, changed);
        }
        current_.frame_hash = hash;
        last_frame_pixels_ = pixels;
        previous_frame_pixels_ = std::move(pixels);
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
            js << "  \"vs_to_first_de_lines\": " << meta.vs_to_first_de_lines << ",\n";
            js << "  \"de_errors\": " << meta.de_errors << ",\n";
            js << "  \"rgb_when_de_low_errors\": " << meta.rgb_when_de_low_errors << ",\n";
            js << "  \"pulse_width_errors\": " << meta.pulse_width_errors << ",\n";
            js << "  \"skip_errors\": " << meta.skip_errors << ",\n";
            js << "  \"errors\": " << frame_error_count(meta) << ",\n";
            js << "  \"unique_colors\": " << meta.unique_colors << ",\n";
            js << "  \"nonzero_pixels\": " << meta.nonzero_pixels << ",\n";
            js << "  \"changed_pixels_from_previous\": " << meta.changed_pixels_from_previous << ",\n";
            js << "  \"frame_hash\": \"" << hex64(meta.frame_hash) << "\"\n";
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
    uint64_t current_cycle_ = 0;
    bool first_error_seen_ = false;
    uint64_t first_error_cycle_ = 0;
    uint64_t first_error_frame_ = 0;
    uint64_t first_error_pixel_ = 0;
    std::string first_error_code_;
    uint64_t changed_frames_ = 0;
    uint64_t max_changed_pixels_from_previous_ = 0;
    bool have_hs_seen_ = false;
    bool seen_hs_after_vs_ = false;
    bool first_de_seen_ = false;
    bool have_de_fall_ = false;
    uint64_t line_index_since_vs_ = 0;
    FrameMetadata current_;
    FrameMetadata last_metadata_;
    std::vector<FrameMetadata> frame_history_;
    std::vector<uint32_t> current_line_;
    std::vector<std::vector<uint32_t>> current_lines_;
    std::vector<uint32_t> previous_frame_pixels_;
    std::vector<uint32_t> last_frame_pixels_;
};

inline std::pair<size_t, size_t> parse_video_json_dimensions(const std::filesystem::path& path) {
    if (path.empty()) return {0, 0};
    const auto text = read_text_file(path);
    const auto width = json_int_field(text, "expected_width", json_int_field(text, "width", 0));
    const auto height = json_int_field(text, "expected_height", json_int_field(text, "height", 0));
    return {static_cast<size_t>(width), static_cast<size_t>(height)};
}

} // namespace apfsim
