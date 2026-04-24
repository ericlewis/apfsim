#pragma once

#include <iostream>
#include <string>
#include <vector>

namespace apfsim {

class Assertions {
public:
    void fail(std::string msg) { failures_.push_back(std::move(msg)); }
    bool ok() const { return failures_.empty(); }
    size_t count() const { return failures_.size(); }
    const std::vector<std::string>& failures() const { return failures_; }

    void print() const {
        for (const auto& failure : failures_) std::cerr << "FAIL assert: " << failure << "\n";
    }

private:
    std::vector<std::string> failures_;
};

} // namespace apfsim
