#pragma once

#include "sim_time.hpp"

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <vector>

namespace apfsim {

struct StereoSample {
    int16_t l = 0;
    int16_t r = 0;
};

struct AudioStats {
    uint32_t sample_rate = 48000;
    size_t samples = 0;
    int16_t min_l = 0;
    int16_t max_l = 0;
    int16_t min_r = 0;
    int16_t max_r = 0;
    int32_t peak_to_peak_l = 0;
    int32_t peak_to_peak_r = 0;
    double dc_offset_l = 0.0;
    double dc_offset_r = 0.0;
    size_t clipped_samples = 0;
    uint64_t mclk_edges = 0;
    uint64_t lrck_edges = 0;
    uint64_t lrck_half_period_mclk_min = 0;
    uint64_t lrck_half_period_mclk_max = 0;
    double avg_mclk_per_lrck_half_period = 0.0;
    double estimated_mclk_lrck_ratio = 0.0;
};

class AudioCapture {
public:
    void set_wav_path(std::filesystem::path path) { wav_path_ = std::move(path); }
    void set_stats_path(std::filesystem::path path) { stats_path_ = std::move(path); }
    void set_expected_sample_rate(uint32_t hz) { expected_sample_rate_ = hz; }

    template <typename Top>
    void sample(const Top* top) {
        const bool mclk = top->audio_mclk != 0;
        if (mclk && !prev_mclk_) on_mclk(top->audio_lrck != 0, top->audio_dac != 0);
        prev_mclk_ = mclk;
    }

    void finish() {
        stats_ = compute_stats();
        if (!wav_path_.empty()) write_wav(wav_path_);
        if (!stats_path_.empty()) write_stats_json(stats_path_);
    }

    const AudioStats& stats() const { return stats_; }
    size_t sample_count() const { return samples_.size(); }

    void reset_capture() {
        current_lrck_ = false;
        shift_ = 0;
        bit_count_ = 0;
        pending_left_ = 0;
        have_left_ = false;
        mclk_edges_ = 0;
        lrck_edges_ = 0;
        mclk_since_lrck_edge_ = 0;
        lrck_half_period_mclk_min_ = 0;
        lrck_half_period_mclk_max_ = 0;
        lrck_half_period_total_ = 0;
        lrck_half_periods_seen_ = 0;
        lrck_half_periods_recorded_ = 0;
        have_lrck_period_ = false;
        samples_.clear();
        stats_ = {};
        stats_.sample_rate = expected_sample_rate_;
    }

private:
    void on_mclk(bool lrck, bool bit) {
        ++mclk_edges_;
        ++mclk_since_lrck_edge_;
        if (lrck != current_lrck_) {
            ++lrck_edges_;
            if (have_lrck_period_) {
                ++lrck_half_periods_seen_;
                if (lrck_half_periods_seen_ > kIgnoredStartupLrckHalfPeriods) {
                    lrck_half_period_mclk_min_ = lrck_half_period_mclk_min_ == 0 ? mclk_since_lrck_edge_ : std::min(lrck_half_period_mclk_min_, mclk_since_lrck_edge_);
                    lrck_half_period_mclk_max_ = std::max(lrck_half_period_mclk_max_, mclk_since_lrck_edge_);
                    lrck_half_period_total_ += mclk_since_lrck_edge_;
                    ++lrck_half_periods_recorded_;
                }
            } else {
                have_lrck_period_ = true;
            }
            mclk_since_lrck_edge_ = 0;
            bit_count_ = 0;
            shift_ = 0;
            current_lrck_ = lrck;
        }
        if (bit_count_ < 16) {
            shift_ = static_cast<uint32_t>((shift_ << 1) | (bit ? 1 : 0));
            ++bit_count_;
            if (bit_count_ == 16) {
                int16_t value = static_cast<int16_t>(shift_ & 0xFFFFu);
                if (!current_lrck_) {
                    pending_left_ = value;
                    have_left_ = true;
                } else if (have_left_) {
                    samples_.push_back({pending_left_, value});
                    have_left_ = false;
                }
            }
        }
    }

    AudioStats compute_stats() const {
        AudioStats s;
        s.sample_rate = expected_sample_rate_;
        s.samples = samples_.size();
        s.mclk_edges = mclk_edges_;
        s.lrck_edges = lrck_edges_;
        s.lrck_half_period_mclk_min = lrck_half_period_mclk_min_;
        s.lrck_half_period_mclk_max = lrck_half_period_mclk_max_;
        if (lrck_half_periods_recorded_ > 0) {
            s.avg_mclk_per_lrck_half_period = static_cast<double>(lrck_half_period_total_) / static_cast<double>(lrck_half_periods_recorded_);
            s.estimated_mclk_lrck_ratio = s.avg_mclk_per_lrck_half_period * 2.0;
        }
        if (samples_.empty()) return s;
        int64_t sum_l = 0;
        int64_t sum_r = 0;
        s.min_l = s.min_r = std::numeric_limits<int16_t>::max();
        s.max_l = s.max_r = std::numeric_limits<int16_t>::min();
        for (const auto& sample : samples_) {
            s.min_l = std::min(s.min_l, sample.l);
            s.max_l = std::max(s.max_l, sample.l);
            s.min_r = std::min(s.min_r, sample.r);
            s.max_r = std::max(s.max_r, sample.r);
            sum_l += sample.l;
            sum_r += sample.r;
            if (sample.l == std::numeric_limits<int16_t>::min() || sample.l == std::numeric_limits<int16_t>::max() ||
                sample.r == std::numeric_limits<int16_t>::min() || sample.r == std::numeric_limits<int16_t>::max()) {
                ++s.clipped_samples;
            }
        }
        s.dc_offset_l = static_cast<double>(sum_l) / static_cast<double>(samples_.size());
        s.dc_offset_r = static_cast<double>(sum_r) / static_cast<double>(samples_.size());
        s.peak_to_peak_l = static_cast<int32_t>(s.max_l) - static_cast<int32_t>(s.min_l);
        s.peak_to_peak_r = static_cast<int32_t>(s.max_r) - static_cast<int32_t>(s.min_r);
        return s;
    }

    static void write_u16(std::ofstream& out, uint16_t v) {
        out.put(static_cast<char>(v & 0xFF));
        out.put(static_cast<char>((v >> 8) & 0xFF));
    }

    static void write_u32(std::ofstream& out, uint32_t v) {
        write_u16(out, static_cast<uint16_t>(v & 0xFFFF));
        write_u16(out, static_cast<uint16_t>((v >> 16) & 0xFFFF));
    }

    void write_wav(const std::filesystem::path& path) const {
        if (!path.parent_path().empty()) std::filesystem::create_directories(path.parent_path());
        std::ofstream out(path, std::ios::binary);
        if (!out) return;
        const uint32_t data_bytes = static_cast<uint32_t>(samples_.size() * 4);
        out.write("RIFF", 4);
        write_u32(out, 36 + data_bytes);
        out.write("WAVE", 4);
        out.write("fmt ", 4);
        write_u32(out, 16);
        write_u16(out, 1);
        write_u16(out, 2);
        write_u32(out, expected_sample_rate_);
        write_u32(out, expected_sample_rate_ * 4);
        write_u16(out, 4);
        write_u16(out, 16);
        out.write("data", 4);
        write_u32(out, data_bytes);
        for (const auto& sample : samples_) {
            write_u16(out, static_cast<uint16_t>(sample.l));
            write_u16(out, static_cast<uint16_t>(sample.r));
        }
    }

    void write_stats_json(const std::filesystem::path& path) const {
        if (!path.parent_path().empty()) std::filesystem::create_directories(path.parent_path());
        std::ofstream out(path);
        if (!out) return;
        out << "{\n";
        out << "  \"sample_rate\": " << stats_.sample_rate << ",\n";
        out << "  \"channels\": 2,\n";
        out << "  \"samples\": " << stats_.samples << ",\n";
        out << "  \"min_l\": " << stats_.min_l << ",\n";
        out << "  \"max_l\": " << stats_.max_l << ",\n";
        out << "  \"min_r\": " << stats_.min_r << ",\n";
        out << "  \"max_r\": " << stats_.max_r << ",\n";
        out << "  \"peak_to_peak_l\": " << stats_.peak_to_peak_l << ",\n";
        out << "  \"peak_to_peak_r\": " << stats_.peak_to_peak_r << ",\n";
        out << "  \"dc_offset_l\": " << stats_.dc_offset_l << ",\n";
        out << "  \"dc_offset_r\": " << stats_.dc_offset_r << ",\n";
        out << "  \"clipped_samples\": " << stats_.clipped_samples << ",\n";
        out << "  \"mclk_edges\": " << stats_.mclk_edges << ",\n";
        out << "  \"lrck_edges\": " << stats_.lrck_edges << ",\n";
        out << "  \"lrck_half_period_mclk_min\": " << stats_.lrck_half_period_mclk_min << ",\n";
        out << "  \"lrck_half_period_mclk_max\": " << stats_.lrck_half_period_mclk_max << ",\n";
        out << "  \"avg_mclk_per_lrck_half_period\": " << stats_.avg_mclk_per_lrck_half_period << ",\n";
        out << "  \"estimated_mclk_lrck_ratio\": " << stats_.estimated_mclk_lrck_ratio << "\n";
        out << "}\n";
    }

    std::filesystem::path wav_path_;
    std::filesystem::path stats_path_;
    uint32_t expected_sample_rate_ = 48000;
    bool prev_mclk_ = false;
    bool current_lrck_ = false;
    uint32_t shift_ = 0;
    int bit_count_ = 0;
    int16_t pending_left_ = 0;
    bool have_left_ = false;
    uint64_t mclk_edges_ = 0;
    uint64_t lrck_edges_ = 0;
    uint64_t mclk_since_lrck_edge_ = 0;
    uint64_t lrck_half_period_mclk_min_ = 0;
    uint64_t lrck_half_period_mclk_max_ = 0;
    uint64_t lrck_half_period_total_ = 0;
    uint64_t lrck_half_periods_seen_ = 0;
    uint64_t lrck_half_periods_recorded_ = 0;
    bool have_lrck_period_ = false;
    static constexpr uint64_t kIgnoredStartupLrckHalfPeriods = 4;
    std::vector<StereoSample> samples_;
    AudioStats stats_;
};

} // namespace apfsim
