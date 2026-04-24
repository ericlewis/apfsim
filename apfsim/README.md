# apfsim

`apfsim` is a Verilator-based Analogue Pocket APF host emulator. It is built around the generated `core_top` interface instead of a generic HDL testbench: the C++ harness drives Pocket-facing clocks, APF bridge transactions, host/target commands, data-slot loading, controller inputs, video capture, audio capture, persistent interact writes, and nonvolatile save unloads.

The repository includes a deterministic mock APF `core_top` under `examples/mock` so the simulator can be built and tested before attaching a real core.

## What Is Implemented

- Verilated `core_top` executable with C++ `eval()` loop.
- `clk_74a` and `clk_74b` deterministic host clocks at the nominal 74.25 MHz cadence.
- APF bridge host with configurable delayed reads.
- Minimal host command engine for Request Status, Reset Enter, Reset Exit, Data Slot Request Write, Data Slot All Complete, and RTC.
- Minimal target command polling for `0x0140 Ready to Run`.
- Data-slot table population at `0xF8002000` and file burst writes to slot bridge addresses.
- Nonvolatile save unload by bridge burst reads.
- Persistent `interact.json` default writes for address/value-style entries.
- Controller key/joy/trig driving from YAML scenarios.
- APF video capture on `video_rgb_clock`, protocol checks, PPM frame dumps, and per-frame JSON metadata.
- I2S pin capture from `audio_mclk`, `audio_lrck`, and `audio_dac`, with WAV output.
- Profile-driven CLI for repeatable builds/runs across mock and local real-core checkouts.
- Structured run artifacts: `result.json`, `bridge.log`, frame metadata/PPM, WAV, audio stats, and save dumps.
- Simulation replacements for common FPGA IP: `mf_pllbase`, `altsyncram`, selected `lpm_*` modules.
- Make, CMake, and pytest wrapper scaffolding.

## Quick Start

From the repository root:

```sh
make lint
make profile-run PROFILE=mock FRAMES=2
```

The mock run produces:

```text
PASS data: slot 1 loaded 1024 bytes at 0x10000000
PASS boot: reached running
PASS interact: 1 persistent writes verified
PASS video: 5 frames, 256x224 active
PASS audio: ... stereo samples
PASS input: scripted pulses delivered
STATUS running
```

Profile artifacts are written under `apfsim/build/profiles/<profile>/run` by default:

- `result.json`
- `bridge.log`
- `video/frame_000001.ppm`
- `video/frame_000001.json`
- `audio/out.wav`
- `audio/stats.json`
- `saves/slot_<id>.bin` for nonvolatile slots

The older direct Make targets, such as `make run-mock`, are still available and now also emit `result.json`, `bridge.log`, and `audio/stats.json` under their legacy dump roots.

## Profile CLI

The production-gate entrypoint is `bin/apfsim` from this directory:

```sh
cd apfsim
bin/apfsim doctor
bin/apfsim build --profile mock
bin/apfsim run --profile mock --frames 2
bin/apfsim test --matrix local-fast
```

Available profile manifests live in `profiles/*.json`:

| Profile | Purpose |
| --- | --- |
| `mock` | Built-in deterministic APF `core_top`. |
| `mock_port_gate` | Strict built-in correctness gate for APF-facing timing, data, reset, audio, input, interact, and readback checks. |
| `core_template` | Local agg23 APF core template checkout, skipped if absent. |
| `basicassets` | Local official BasicAssets checkout with generated sim wrapper and SDRAM model. |
| `pacman` | Local Pac-Man APF shell check using VHDL entity stubs. |
| `mrjong` | Local Mr. Jong real Verilog gameplay path with non-placeholder frame capture. |

External checkout roots can be overridden with environment variables:

```sh
TEMPLATE_ROOT=/path/to/template bin/apfsim run --profile core_template
BASICASSETS_ROOT=/path/to/core-example-basicassets bin/apfsim run --profile basicassets
PACMAN_ROOT=/path/to/openFPGA-PacMan bin/apfsim run --profile pacman
MRJONG_ROOT=/path/to/openFPGA-MrJong bin/apfsim run --profile mrjong
```

Matrix modes:

| Matrix | Profiles |
| --- | --- |
| `ci` | `mock_port_gate` only. |
| `local-fast` | `mock_port_gate` plus available core template. |
| `local-real` | `mock_port_gate`, core template, BasicAssets, Pac-Man, and Mr. Jong when their checkouts exist. |

## Pocket Log Analysis

Use Pocket debug logs to compare real hardware lifecycle behavior against simulator output:

```sh
bin/apfsim analyze-log /Volumes/Untitled/System/Logs/ericlewis.TimePilot_20260423_143713.txt \
  --json build/logs/timepilot_lifecycle.json \
  --strict-lifecycle \
  --verbose
```

The analyzer extracts APF lifecycle phases from Pocket logs or `apfsim` `bridge.log` files: setup status, Reset Enter, data-slot request write, all-complete, RTC, target Ready-to-Run, Reset Exit, and running status. It also reports observed data-slot IDs, sizes, load addresses, target commands, and missing or out-of-order phases.

## Correctness Checks

Scenarios can make port-validation strict under `expect:`. The built-in [port gate](scenarios/port_gate.yml) demonstrates the supported checks:

```yaml
expect:
  video:
    active_width: 256
    active_height: 224
    max_errors: 0
    min_hs_after_vs_cycles: 3
    min_hs_to_de_gap_cycles: 1
    min_de_to_hs_gap_cycles: 1
    min_unique_colors: 2
    min_nonzero_pixels: 1
  audio:
    min_samples: 64
    require_changing: true
    min_peak_to_peak: 32
    max_clipped_samples: 0
  data:
    require_required_slots: true
    expected_total_loaded_bytes: 1024
  reset:
    require_reset_enter: true
    require_reset_exit: true
    require_ready_to_run: true
    max_boot_cycles: 200000
    min_reset_hold_cycles: 500
    max_reset_exit_to_running_cycles: 2000
  save:
    require_nonvolatile_unload: true
    require_roundtrip_match: true
  bridge:
    readbacks:
      - name: rom_write_count
        address: 0x50000020
        value: 1024
        mask: 0xffffffff
```

Each run writes the measured values to `result.json`. The boot block includes the APF lifecycle timeline, reset hold time, Reset Exit to running latency, and ordered lifecycle events. Video frame JSON also includes content metrics: `unique_colors`, `nonzero_pixels`, `changed_pixels_from_previous`, and `frame_hash`. Failed gates return nonzero and include `failed_phase`, `message`, and a `failures` array, so profile runs can be used directly as CI checks.

## Build Targets

Run targets from `apfsim/` or through the root `Makefile`.

```sh
make -C apfsim lint
make -C apfsim build
make -C apfsim build-waves
make -C apfsim run-mock
make -C apfsim run-mock-waves
make -C apfsim doctor
make -C apfsim profile-build PROFILE=mock
make -C apfsim profile-run PROFILE=mock FRAMES=2
make -C apfsim test-matrix MATRIX=local-fast
make -C apfsim test
make -C apfsim clean
```

`make test` expects `pytest` to be installed. Install local test deps with `python3 -m pip install -r apfsim/requirements-dev.txt` in the active Python environment. The tests skip only if Verilator is unavailable.

## Running A Real Core

Provide a Verilator filelist that includes your real APF framework files, real core RTL, and the sim shims before vendor IP that needs replacement.

```sh
make -C apfsim build \
  TOP=core_top \
  FILELIST=/absolute/or/relative/path/to/build/verilator_filelist.f

apfsim/build/obj/Vcore_top \
  --scenario /path/to/scenarios/boot_coin_start.yml \
  --data /path/to/data.json \
  --video /path/to/video.json \
  --interact /path/to/interact.json \
  --slot 1=/path/to/game.rom \
  --slot 4=/path/to/game.hi \
  --frames 300 \
  --dump-frames /tmp/apfsim-frames \
  --dump-audio /tmp/apfsim-audio/out.wav \
  --audio-stats /tmp/apfsim-audio/stats.json \
  --result-json /tmp/apfsim-result.json \
  --bridge-log /tmp/apfsim-bridge.log \
  --dump-saves /tmp/apfsim-saves
```

You can generate a first-pass filelist with:

```sh
cd apfsim
scripts/generate_filelist.py rtl core/rtl apf/framework -o build/verilator_filelist.f
```

Review the generated filelist manually. A transactional memory model is safer than a silent stub for DDR/CRAM/SDRAM controllers.

## Required `core_top` Port Contract

The harness currently expects these APF-facing ports to exist on `core_top`:

```systemverilog
input  clk_74a, clk_74b;
input  bridge_wr, bridge_rd, bridge_endian_little;
input  [31:0] bridge_addr, bridge_wr_data;
output [31:0] bridge_rd_data;
input  [31:0] cont1_key, cont2_key, cont3_key, cont4_key;
input  [31:0] cont1_joy, cont2_joy, cont3_joy, cont4_joy;
input  [31:0] cont1_trig, cont2_trig, cont3_trig, cont4_trig;
output video_rgb_clock, video_rgb_clock_90, video_de, video_skip, video_vs, video_hs;
output [23:0] video_rgb;
output audio_mclk, audio_lrck, audio_dac;
```

If a core uses different names or widths, add a thin simulation wrapper and set `TOP` to that wrapper.

## Bridge And Command Assumptions

The simulator reserves the APF command window at `0xF8000000` and target command window at `0xF8001000`.

Default host command layout:

| Address | Meaning |
| --- | --- |
| `0xF8000000` | command/status word |
| `0xF8000004` | parameter 0 |
| `0xF8000008` | parameter 1 |
| `0xF800000C` | parameter 2 |
| `0xF8000010` | parameter 3 |
| `0xF8002000` | 32-entry data-slot ID/size table |

Command/status words use the common staged-magic form:

- `0x434Dxxxx`: host or target command (`CM`)
- `0x4255xxxx`: busy (`BU`)
- `0x4F4Bxxxx`: accepted/result (`OK`)

Some generated cores use a different `core_bridge_cmd` register layout. In that case, keep the C++ harness and adapt only `cpp/apf_commands.hpp` plus `BridgeHost::host_command()`.

## Scenario Format

The YAML parser intentionally supports a small deterministic subset:

```yaml
name: timepilot_boot_smoke
data_slots:
  - id: 1
    name: ROM
    file: assets/timepilot.rom
    address: 0x10000000
    required: true
  - id: 4
    name: HISCORE
    file: saves/timepilot.hi
    address: 0x20000000
    nonvolatile: true
interact:
  writes:
    - frame: boot
      address: 0x50000010
      value: 1
inputs:
  - frame: 60
    player: 1
    button: Select
    hold_frames: 4
run:
  until_frames: 300
  timeout_cycles: 50000000
expect:
  status: running
  video:
    active_width: 256
    active_height: 224
```

Command-line `--slot id=file`, `--frames`, and `--timeout-cycles` override scenario values.

## Waveforms

Build with trace support:

```sh
make -C apfsim build-waves
```

Run with FST output:

```sh
APFSIM_WAVES=1 APFSIM_WAVE_PATH=/tmp/apfsim.fst \
  apfsim/build/obj/Vcore_top --scenario apfsim/scenarios/boot_rom.yml --frames 5
```

## Current Limitations

- The command register layout is intentionally isolated but may need adjustment for a specific generated `core_bridge_cmd` implementation.
- `data.json`, `interact.json`, and scenario parsing are dependency-free subsets, not full JSON/YAML schema validators.
- PNG frame export is not included yet; PPM and JSON metadata are always generated.
- DDR/CRAM/SDRAM controller models are placeholders for future core-specific transactional models.
- Audio sample-rate validation is statistical today; the decoder captures I2S words and emits WAV, but does not yet fail on measured LRCK drift.

## Pac-Man Checkout Smoke Test

This repo includes a convenience filelist and scenario for:

```text
/Users/ericlewis/Developer/openfpga-arcade-cores/our-pocket-cores/openFPGA-PacMan
```

Run it with:

```sh
make -C apfsim run-pacman FRAMES=2
```

Expected result:

```text
PASS data: slot 1 loaded 54048 bytes at 0x10000000
PASS boot: reached running
PASS video: 2 frames, 288x224 active
PASS audio: ... stereo samples
PASS input: scripted pulses delivered
STATUS running
```

Important limitation: Pac-Man's real game logic is VHDL and `core_top.sv` directly instantiates the VHDL `pacman` entity. The Verilator path therefore uses [pacman_mixed_language_stubs.sv](rtl_shims/pacman_mixed_language_stubs.sv) for the VHDL game and savestate entities. This validates the APF-facing shell, bridge command flow, data-slot writes, interact writes, video/audio contracts, and controller delivery through the integration wrapper; it does not yet simulate the real Z80/VHDL gameplay.

## Core Template Smoke Test

The APF core template at:

```text
/Users/ericlewis/Developer/openfpga-arcade-cores/ref-pocket-cores/agg23/template
```

can be simulated with:

```sh
make -C apfsim run-template FRAMES=3
```

## Mr. Jong Real-Frame Smoke Test

The Mr. Jong port at:

```text
/Users/ericlewis/Developer/openfpga-arcade-cores/our-pocket-cores/openFPGA-MrJong
```

can be simulated with:

```sh
bin/apfsim run --profile mrjong
```

Expected result:

```text
PASS data: slot 1 loaded 41248 bytes at 0x10000000
PASS boot: reached running
PASS video: 12 frames, 240x224 active
PASS audio: ... stereo samples
PASS input: scripted pulses delivered
STATUS running
```

This is the first local pure-Verilog arcade profile in this repo that produces non-placeholder frame pixels from a real gameplay path. The current smoke expects valid APF timing and non-black frame output; it does not yet require audio activity because the captured I2S stream is silent in this early bringup.

## BasicAssets Smoke Test

The official BasicAssets example at:

```text
/Users/ericlewis/Developer/core-example-basicassets
```

can be simulated with:

```sh
make -C apfsim run-basicassets FRAMES=2
```

This target uses a small wrapper around the example `core_top.v` and a behavioral SDRAM model so data-slot writes are visible to the image and audio readers.
