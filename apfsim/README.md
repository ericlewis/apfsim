# apfsim

`apfsim` is a Verilator-based Analogue Pocket APF host emulator. It is built around the generated `core_top` interface instead of a generic HDL testbench: the C++ harness drives Pocket-facing clocks, APF bridge transactions, host/target commands, data-slot loading, controller inputs, video capture, audio capture, persistent interact writes, and nonvolatile save unloads.

The repository includes a deterministic mock APF `core_top` under `examples/mock` so the simulator can be built and tested before attaching a real core.

## What Is Implemented

- Verilated `core_top` executable with C++ `eval()` loop.
- `clk_74a` and `clk_74b` deterministic host clocks at the nominal 74.25 MHz cadence.
- APF bridge host with configurable delayed reads, write strobes, endian mode, transaction tracing, and target-command runtime polling when enabled by profile.
- Host command API and trace naming for the documented APF host command set; the default boot sequence drives Request Status, Reset Enter, Data Slot Request Write, Data Slot All Complete, RTC, and Reset Exit.
- Scenario-driven runtime host command injection for OS notify commands, `0x008A` data-slot update/reload, and `0x00A0` savestate save/query blob copy-out.
- Target command service for Ready-to-Run, Debug Event Log, Data Slot Read/Write including 48-bit variants, Data Slot Flush, Get Filename, and Open New File.
- Data-slot table population at `0xF8002000`, file burst writes to slot bridge addresses, and per-slot write-map verification.
- Nonvolatile save unload by bridge burst reads.
- Persistent `interact.json` default writes for address/value-style entries.
- Controller key/joy/trig driving from YAML scenarios.
- APF video capture on `video_rgb_clock`, protocol checks, PPM frame dumps, and per-frame JSON metadata.
- I2S pin capture from `audio_mclk`, `audio_lrck`, and `audio_dac`, with WAV output, sample stats, and MCLK/LRCK ratio checks.
- Profile-driven CLI for repeatable builds/runs across mock and local real-core checkouts.
- Structured run artifacts: phase-annotated `result.json`, `bridge.log`, frame metadata/PPM, WAV, audio stats, and save dumps.
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
- `video_shape.json`
- `lifecycle.json`
- `bridge.log`
- `bridge_summary.json`
- `bridge_transactions.jsonl` when `--bridge-trace` is enabled
- `video/frame_000001.ppm`
- `video/frame_000001.json`
- `audio/out.wav`
- `audio/stats.json`
- `saves/slot_<id>.bin` for nonvolatile slots
- `savestates/*.sta` for scenario-requested savestate save blobs

The older direct Make targets, such as `make run-mock`, are still available and now also emit `result.json`, `bridge.log`, and `audio/stats.json` under their legacy dump roots.

## Profile CLI

The production-gate entrypoint is `bin/apfsim` from this directory:

```sh
cd apfsim
bin/apfsim doctor
bin/apfsim build --profile mock
bin/apfsim run --profile mock --frames 2
bin/apfsim run --profile mock_port_gate --bridge-trace
bin/apfsim video-shape --profile mock_port_gate --frames 20 --json-out output/mock_shape.json
bin/apfsim compare-video-json --shape output/mock_shape.json --video-json examples/mock/video.json
bin/apfsim apply-video-shape --shape output/mock_shape.json --video-json examples/mock/video.json --out output/video.json
bin/apfsim validate-artifacts build/profiles/mock_port_gate/run
bin/apfsim shim-catalog --json
bin/apfsim play --profile mock_port_gate
bin/apfsim test --matrix local-fast
bin/apfsim discover --output output/core-inventory
bin/apfsim generate-profile --root /path/to/openFPGA-Core --output output/generated-profiles
```

`apfsim play` builds the selected profile with SDL2 enabled, performs the same APF boot/data-slot/interact/reset flow as `apfsim run`, then opens a live video window and maps keyboard state into the APF controller pins. Controls: arrows move, `Z`/`A`/Space are button A, Enter is Start, `5`/`C` insert coin, `P` is pause, and `Q`/Esc quits. On macOS with Homebrew, SDL2 is expected to provide `sdl2-config` on `PATH`.

Bridge timing is configurable from the CLI or profile manifest: `--bridge-read-latency-cycles`, `--bridge-write-strobe-cycles`, `--write-idle-cycles`, `--bridge-endian little|big`, `--target-service-interval-cycles`, and `--bridge-trace`. Profiles can set the same behavior with `bridge_read_latency_cycles`, `bridge_write_strobe_cycles`, `write_idle_cycles`, `bridge_endian`, `target_service_interval_cycles`, and `bridge_trace`. Runtime target polling is opt-in so large real-core profiles do not pay bridge-read overhead unless they need deferred load/save/file services after boot.

Available profile manifests live in `profiles/*.json`:

| Profile | Purpose |
| --- | --- |
| `mock` | Built-in deterministic APF `core_top`. |
| `mock_port_gate` | Strict built-in correctness gate for APF-facing timing, data, reset, audio, input, interact, and readback checks. |
| `mock_target_commands` | Built-in target-command service regression for runtime target data-slot read/write/read48/write48/flush, filename, open-file, and debug-event paths. |
| `mock_lifecycle` | Built-in host lifecycle injection regression for OS notify, runtime `0x008A` data-slot update, and `0x00A0` savestate save/query blob transfer. |
| `core_template` | Official `open-fpga/core-template` checkout, skipped if absent. |
| `interact` | Official `open-fpga/core-example-interact` checkout for persistent interact writes and runtime AV. |
| `kbmouse_targetdata` | Official `open-fpga/core-example-kbmouse-targetdata` checkout for controller and target data-command smoke coverage. |
| `basicassets` | Official `open-fpga/core-example-basicassets` checkout with behavioral SDRAM model. |
| `basicchip32` | Official `open-fpga/core-example-basicchip32` HDL smoke profile; Chip32 VM execution is not integrated yet. |

External checkout roots are configured with environment variables. The public profile set intentionally targets only official openFPGA example repositories.

```sh
CORE_TEMPLATE_ROOT=/path/to/core-template bin/apfsim run --profile core_template
CORE_EXAMPLE_INTERACT_ROOT=/path/to/core-example-interact bin/apfsim run --profile interact
CORE_EXAMPLE_KBMOUSE_TARGETDATA_ROOT=/path/to/core-example-kbmouse-targetdata bin/apfsim run --profile kbmouse_targetdata
CORE_EXAMPLE_BASICASSETS_ROOT=/path/to/core-example-basicassets bin/apfsim run --profile basicassets
CORE_EXAMPLE_BASICCHIP32_ROOT=/path/to/core-example-basicchip32 bin/apfsim run --profile basicchip32
```

Matrix modes:

| Matrix | Profiles |
| --- | --- |
| `ci` | `mock_port_gate`, `mock_target_commands`, and `mock_lifecycle`. |
| `local-fast` | `mock_port_gate`, `mock_target_commands`, `mock_lifecycle`, plus available core template. |
| `local-real` | Mock gate profiles plus all available official examples: core template, Interact, KB/Mouse TargetData, BasicAssets, and BasicChip32. |
| `official-examples` | Only available official example profiles, without mock profiles. |

## Core Inventory

Use discovery before hand-writing profiles for a batch of local cores:

```sh
bin/apfsim discover \
  --root /path/to/pocket-core-checkouts \
  --output output/core-inventory
```

The command writes:

- `output/core-inventory/cores.json`
- `output/core-inventory/cores.md`

Discovery classifies each checkout as `profiled`, `candidate`, `needs-ip-shims`, `needs-vhdl-shims`, `needs-memory-model`, `package-only`, or `no-core-top`. It also records git state (`clean`, `dirty`, `no-git`), dirty-file counts, core IDs, metadata presence, data-slot counts, nonvolatile slot counts, video modes, HDL language counts, APF top-port coverage, and likely simulator blockers. This is the input list for deciding which cores should get the next production-grade profile or which failing core is safe to edit.

Generate a reviewable candidate profile/filelist/scenario bundle from one discovered checkout:

```sh
bin/apfsim generate-profile \
  --root /path/to/openFPGA-Core \
  --output output/generated-profiles \
  --json
```

The generated bundle is intentionally not installed into `profiles/`. Review `NOTES.md`, `filelist.f`, and `scenario.yml`, then run:

```sh
bin/apfsim build --profile output/generated-profiles/core/core.json --preflight-only
bin/apfsim run --profile output/generated-profiles/core/core.json --artifacts output/core-generated
```

See [Generated Profile Candidates](docs/generated-profiles.md).

Candidate generation is QSF-aware when the core checkout contains a Quartus project. Verilog/SystemVerilog source order, recursively expanded QIP sources, `SEARCH_PATH` include directories, and Verilog macro defines are imported from the project metadata, while VHDL/non-RTL-QIP/vendor-IP references are reported for review and filtered or shimmed before Verilator.

## Shim And Substitution Catalog

Full-auto profile generation needs reusable knowledge for non-Verilator-friendly IP and source-specific substitutions. The catalog lives at `catalogs/shims.json` and contains named entries for copy/replace generation, selected external source candidates, required paths, and optional flags/artifacts. Profiles opt in with `shim_catalog`.

Example profile usage:

```json
{
  "shim_catalog": [
    "public_vendor_ram"
  ]
}
```

Inspect the catalog or a profile's expanded substitutions:

```sh
bin/apfsim shim-catalog --json
bin/apfsim shim-catalog --profile mock --json
```

This keeps hand-discovered substitutions and source-specific simulator wrappers in one reusable place instead of burying them in one-off profile manifests. The public catalog starts conservative and can be extended with reusable entries that do not depend on private checkout layout. Auto-generation uses discovery results to select likely catalog entries and emit candidate profiles/filelists for review.

See [Shim And Substitution Catalog](docs/shim-catalog.md).

## Pocket Log Analysis

Use Pocket debug logs to compare real hardware lifecycle behavior against simulator output:

```sh
bin/apfsim analyze-log /path/to/Pocket/System/Logs/core_log.txt \
  --json build/logs/timepilot_lifecycle.json \
  --strict-lifecycle \
  --verbose
```

The analyzer extracts APF lifecycle phases from Pocket logs or `apfsim` `bridge.log` files: setup status, Reset Enter, data-slot request write, all-complete, RTC, target Ready-to-Run, Reset Exit, and running status. It also recognizes the documented host/target command names, reports observed data-slot IDs, sizes, load addresses, target commands, and missing or out-of-order phases. Real Pocket logs remain useful because they show optional command order and parameter patterns used by firmware for specific cores.

Local Pocket debug logs were used to model these runtime flows:

- `0x008A Data slot update`: update the data-slot ID/size table first, then send host command `0x008A` with slot ID and size. MacPlus and PC Engine CD logs show this during user-initiated runtime reloads.
- `0x00A0 Savestate Start/Query`: query support with `p0=0`, request creation with `p0=1`, poll while result is busy, then copy the returned blob from response address/size. Pocket handheld and Arduboy-style logs show this flow.
- `0x00B0/0x00B1/0x00B2/0x00B8 OS notify`: menu state, cartridge adapter, docked state, and display mode are now scenario-injectable host commands.

Example scenario fragment:

```yaml
host_commands:
  - frame: 1
    command: os_notify_menu_state
    p0: 1
  - frame: 2
    command: os_notify_display_mode
    p0: 0x00001000
  - frame: 2
    command: data_slot_update
    slot: 1
    file: examples/assets/mock.rom
    size: 1024
  - frame: 3
    command: savestate_save
    output: mock_state.sta
```

See [Log-Derived APF Runtime Flows](docs/log-derived-flows.md) for the compact command-order notes used by the scenario driver.

## Video Shape Discovery

Every successful profile run writes a stable APF-facing shape contract in two places:

- `result.json` at top-level key `video_shape`
- `video_shape.json` as a dedicated artifact for external tools such as coreir

The shape is measured from `video_rgb`, `video_de`, `video_hs`, `video_vs`, and `video_skip` after ignoring scenario startup frames. It reports active dimensions, HS-to-HS line totals, HS/DE and VS/first-active-line gaps, protocol error counters, and whether dimensions were stable across measured frames.

Example:

```json
{
  "schema": "apfsim.video_shape.v1",
  "source_result": "run/result.json",
  "result_ok": true,
  "video_shape": {
    "active_width": 256,
    "active_height": 224,
    "total_width_min": 320,
    "total_width_max": 320,
    "hs_to_de_gap_min": 2,
    "de_to_hs_gap_min": 62,
    "vs_to_first_de_lines": 0,
    "de_errors": 0,
    "pulse_width_errors": 0,
    "skip_errors": 0,
    "stable_dimensions": true,
    "protocol_valid": true
  }
}
```

Run shape discovery directly:

```sh
bin/apfsim video-shape \
  --profile mock_port_gate \
  --frames 20 \
  --json-out output/mock_shape.json
```

Or extract from an existing run:

```sh
bin/apfsim video-shape build/profiles/mock_port_gate/run --pretty
```

For generated metadata checks, coreir should compare `video_shape.active_width` and `video_shape.active_height` against generated `video.json`, require `stable_dimensions: true`, and treat nonzero `de_errors`, `pulse_width_errors`, or `skip_errors` as APF video protocol failures.

The CLI can perform that comparison directly:

```sh
bin/apfsim compare-video-json \
  --shape build/profiles/mock_port_gate/run \
  --video-json examples/mock/video.json \
  --json-out output/mock_video_compare.json
```

The comparison report uses schema `apfsim.video_compare.v1` and fails nonzero when no scaler mode matches the simulated active dimensions, when dimensions are unstable, or when APF video protocol error counters are nonzero.

Apply the discovered shape back into generated metadata:

```sh
bin/apfsim apply-video-shape \
  --shape build/profiles/mock_port_gate/run \
  --video-json path/to/video.json \
  --out build/generated/video.json \
  --timing-hints
```

`apply-video-shape` patches `scaler_modes[*].width` and `scaler_modes[*].height` to the simulated active dimensions. With `--timing-hints`, it also writes an internal `_apfsim_video_shape` object containing measured line totals and porch-ish gaps for generators such as coreir. Use `--in-place --backup` only when intentionally updating a checkout's `video.json`.

See [Video Shape Workflow](docs/video-shape.md).

## Public Schemas And Lifecycle

Public artifact schemas live under `schemas/*.schema.json`:

- `result.schema.json`
- `video_shape.schema.json`
- `video_compare.schema.json`
- `video_apply.schema.json`
- `lifecycle.schema.json`
- `bridge_summary.schema.json`
- `generated_profile.schema.json`
- `profile.schema.json`
- `shim_catalog.schema.json`

The Python CLI validates and hydrates artifacts after successful runs. It adds derived `phases` and `lifecycle` objects to `result.json` and writes dedicated `lifecycle.json` with schema `apfsim.lifecycle.v1`. The lifecycle report records the APF boot sequence cycles for setup, Reset Enter, data-slot table population, data load completion, all-complete, RTC, Ready-to-Run, Reset Exit, and Running status, plus reset/data/load durations and AV counters.

Validate an existing run directory explicitly:

```sh
bin/apfsim validate-artifacts build/profiles/mock_port_gate/run
```

See [APF Contract Coverage](docs/apf-contract.md), [Runtime Artifacts](docs/artifacts.md), and [Public Readiness Notes](docs/public-readiness.md).

## Correctness Checks

Scenarios can make port-validation strict under `expect:`. The built-in [port gate](scenarios/port_gate.yml) demonstrates the supported checks:

```yaml
expect:
  video:
    active_width: 256
    active_height: 224
    max_errors: 0
    require_stable_dimensions: true
    require_hs_per_active_line: true
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
    expected_mclk_lrck_ratio: 64
    max_mclk_lrck_ratio_error: 1
    max_lrck_half_period_jitter: 0
  data:
    require_required_slots: true
    expected_total_loaded_bytes: 1024
    # Per-slot `expected_checksum` / `fnv1a64` can also be set under `data_slots:`.
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
    require_little_endian: true
    require_slot_table: true
    min_host_commands: 6
    min_target_commands: 1
```

The mock core uses a simplified I2S cadence, so its strict gate expects ratio `64`; a production APF I2S output with 12.288 MHz MCLK and 48 kHz LRCK should normally use ratio `256`.

Each run writes the measured values to `result.json`. The top-level `phases` object reports `boot`, `reset`, `data`, `video`, `audio`, `interact`, `input`, and `save` as machine-readable pass/fail statuses. The top-level `lifecycle` object and dedicated `lifecycle.json` report boot/setup/reset/data/RTC/Ready-to-Run/running cycle markers. The data block includes loaded byte counts, bridge write counts, first/last write addresses, stride errors, full 64-bit FNV-1a checksums, and target-side per-slot read/write/flush/filename counters. The bridge block includes endian mode, read latency, write idle/strobe timing, read/write counts by address class, host/target command counts, target data-slot/debug/filename/open-file counters, slot/range error counters, data-slot table status, data payload writes, save payload reads, and last observed read/write. `bridge_summary.json` mirrors those counters and adds ordered host/target command history. Use `--bridge-trace` or profile `"bridge_trace": true` to emit `bridge_transactions.jsonl` with every individual bridge read/write for low-level failures. The boot block includes the APF lifecycle timeline, reset hold time, Reset Exit to running latency, and ordered lifecycle events. Video frame JSON also includes content metrics: `unique_colors`, `nonzero_pixels`, `changed_pixels_from_previous`, and `frame_hash`. Run-level video JSON includes post-warmup dimension stability, HS-vs-active-line coverage, aggregate motion metrics, `changed_frames`, and `max_changed_pixels_from_previous`, so gates can catch ports that meet timing but stay visually static. `video_shape` is the stable schema for generated `video.json` comparisons. Audio JSON includes decoded sample counts, min/max/DC/clipping, MCLK/LRCK edge counts, steady-state LRCK half-period min/max, and estimated MCLK/LRCK ratio. Failed gates return nonzero and include `failed_phase`, `message`, `failures`, last APF host/target status in `boot`, and a stderr diagnostics line with frame/audio counters and artifact directory.

After a successful profile run, the Python CLI validates the artifact directory too: `result.json` must carry all phase statuses, frame JSON dimensions must match run-level video dimensions, WAV metadata must match `audio/stats.json`, and every loaded nonvolatile slot must have a save report and output file. This keeps profile success tied to usable artifacts, not just simulator exit status.

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

Default APF command layout:

| Address | Meaning |
| --- | --- |
| `0xF8000000` | host command/status word |
| `0xF8000004` | host parameter pointer |
| `0xF8000008` | host response pointer |
| `0xF8000020` - `0xF800002C` | fallback host parameter words 0-3 used by common APF shells |
| `0xF8001000` | target command/status word |
| `0xF8001004` | target parameter pointer |
| `0xF8001008` | target response pointer |
| `0xF8001020` - `0xF800102C` | fallback target parameter words 0-3 used by common APF shells |
| `0xF8002000` | 32-entry data-slot ID/size table |

Command/status words use the common staged-magic form:

- `0x434Dxxxx`, `0x4255xxxx`, `0x4F4Bxxxx`: host command, busy, and result (`CM`/`BU`/`OK`).
- `0x636Dxxxx`, `0x6275xxxx`, `0x6F6Bxxxx`: target command, busy, and result (`cm`/`bu`/`ok`).

Some generated cores use a different `core_bridge_cmd` register layout. In that case, keep the C++ harness and adapt only `cpp/apf_commands.hpp` plus the bridge command helpers.

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

## Official Example Smoke Tests

The public tree ships profile manifests for the official openFPGA examples only:

```sh
git clone https://github.com/open-fpga/core-template /path/to/core-template
git clone https://github.com/open-fpga/core-example-interact /path/to/core-example-interact
git clone https://github.com/open-fpga/core-example-kbmouse-targetdata /path/to/core-example-kbmouse-targetdata
git clone https://github.com/open-fpga/core-example-basicassets /path/to/core-example-basicassets
git clone https://github.com/open-fpga/core-example-basicchip32 /path/to/core-example-basicchip32
```

Run individual profiles:

```sh
CORE_TEMPLATE_ROOT=/path/to/core-template bin/apfsim run --profile core_template
CORE_EXAMPLE_INTERACT_ROOT=/path/to/core-example-interact bin/apfsim run --profile interact
CORE_EXAMPLE_KBMOUSE_TARGETDATA_ROOT=/path/to/core-example-kbmouse-targetdata bin/apfsim run --profile kbmouse_targetdata
CORE_EXAMPLE_BASICASSETS_ROOT=/path/to/core-example-basicassets bin/apfsim run --profile basicassets
CORE_EXAMPLE_BASICCHIP32_ROOT=/path/to/core-example-basicchip32 bin/apfsim run --profile basicchip32
```

Or run the official example matrix:

```sh
CORE_TEMPLATE_ROOT=/path/to/core-template \
CORE_EXAMPLE_INTERACT_ROOT=/path/to/core-example-interact \
CORE_EXAMPLE_KBMOUSE_TARGETDATA_ROOT=/path/to/core-example-kbmouse-targetdata \
CORE_EXAMPLE_BASICASSETS_ROOT=/path/to/core-example-basicassets \
CORE_EXAMPLE_BASICCHIP32_ROOT=/path/to/core-example-basicchip32 \
  bin/apfsim test --matrix official-examples
```

`basicchip32` currently validates the public HDL path by loading the equivalent image/audio payloads and applying the display-enable bridge write. It does not execute the Chip32 VM yet. A future adapter can integrate `openfpga-chip32-sim` plus `bass-chip32` so this profile follows the actual Chip32 host program.
