import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_cpp_data_slot_helpers_match_profile_generation(tmp_path):
    cxx = shutil.which("c++")
    if cxx is None:
        pytest.skip("c++ compiler is not installed")

    source = tmp_path / "check.cpp"
    binary = tmp_path / "check"
    source.write_text(textwrap.dedent(
        """
        #include "cpp/data_slots.hpp"

        #include <cstdint>
        #include <iostream>
        #include <vector>

        int main() {
            std::vector<uint8_t> bytes = {'a', 'b', 'c'};
            std::vector<apfsim::DataSlot> slots(2);
            slots[0].loaded_size = 493;
            slots[0].deferload = true;
            slots[1].loaded_size = 393984;
            slots.push_back({});
            slots[2].loaded_size = 43;
            slots[2].nonvolatile = true;

            std::cout << apfsim::hex64(apfsim::fnv1a64(bytes)) << "\\n";
            std::cout << apfsim::host_loaded_bytes(slots) << "\\n";
            return 0;
        }
        """
    ))

    result = subprocess.run(
        [cxx, "-std=c++20", "-I", str(ROOT), str(source), "-o", str(binary)],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [
        "0xE71FA2190541574B",
        "393984",
    ]
