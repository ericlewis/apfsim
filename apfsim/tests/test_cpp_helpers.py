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

    data_json = tmp_path / "data.json"
    data_json.write_text(textwrap.dedent(
        """
        {
          "data": {
            "data_slots": [
              {
                "id": 0,
                "name": "Game JSON Setup",
                "required": true,
                "filename": "setup.json",
                "extensions": ["json"]
              },
              {
                "id": 4,
                "name": "Cartridge",
                "required": true,
                "address": "0x10000000",
                "filename": "cart.ngp"
              }
            ]
          }
        }
        """
    ))

    source = tmp_path / "check.cpp"
    binary = tmp_path / "check"
    source.write_text(textwrap.dedent(
        """
        #include "cpp/data_slots.hpp"

        #include <cstdint>
        #include <iostream>
        #include <vector>

        int main(int argc, char** argv) {
            if (argc != 2) return 2;
            std::vector<uint8_t> bytes = {'a', 'b', 'c'};
            std::vector<apfsim::DataSlot> slots(2);
            slots[0].loaded_size = 493;
            slots[0].deferload = true;
            slots[1].loaded_size = 393984;
            slots[1].has_address = true;
            slots.push_back({});
            slots[2].loaded_size = 43;
            slots[2].has_address = true;
            slots[2].nonvolatile = true;

            std::cout << apfsim::hex64(apfsim::fnv1a64(bytes)) << "\\n";
            std::cout << apfsim::host_loaded_bytes(slots) << "\\n";

            auto parsed = apfsim::parse_data_json(argv[1]);
            std::cout << parsed.size() << "\\n";
            std::cout << parsed[0].id << ":" << parsed[0].required << ":" << parsed[0].has_address << ":" << parsed[0].file.string() << "\\n";
            std::cout << parsed[1].id << ":" << parsed[1].required << ":" << parsed[1].has_address << ":" << apfsim::hex32(parsed[1].address) << "\\n";

            apfsim::apply_slot_file_override(parsed, 5, "override.bin");
            std::cout << parsed.back().id << ":" << parsed.back().has_address << ":" << apfsim::hex32(parsed.back().address) << "\\n";
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

    result = subprocess.run([str(binary), str(data_json)], text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [
        "0xE71FA2190541574B",
        "393984",
        "2",
        "0:1:0:setup.json",
        "4:1:1:0x10000000",
        "5:1:0x14000000",
    ]
