# apfsim

`apfsim` is a deterministic Verilator-based APF contract simulator for testing Analogue Pocket core integration locally.

It boots a `core_top` through the Pocket-facing APF lifecycle, drives bridge commands and data-slot transfers, feeds controller input, captures video/audio output, unloads nonvolatile saves, and writes structured artifacts for regression testing and CI.

It is not a consumer gameplay emulator. Its purpose is to prove that an APF core satisfies the host-facing contract before testing on real Pocket hardware.

## Purpose

`apfsim` catches APF integration failures before hardware deployment. It is built around the generated Pocket `core_top` interface instead of a generic HDL testbench, so the simulation environment looks like the APF-facing side of Pocket:

- BRIDGE transactions and host/target command flow.
- Data-slot table population and payload writes.
- Reset enter/exit lifecycle ordering.
- Persistent `interact.json` writes.
- Controller `cont*_key`, `cont*_joy`, and `cont*_trig` input delivery.
- APF video timing capture and runtime video contract discovery.
- I2S-style audio capture and basic activity/timing statistics.
- Nonvolatile save unloads.
- Machine-readable run artifacts suitable for CI gates.

Use it when you want to answer:

- Does my core boot through the APF lifecycle?
- Are data slots loaded to the expected bridge addresses?
- Did persistent settings land before reset exit?
- Is APF-facing video timing valid, and does it match `video.json`?
- Does audio produce sane I2S-like output?
- Can controller input, target data commands, saves, and lifecycle notifications be exercised reproducibly?

## Who It Is For

`apfsim` is for APF/openFPGA core authors, maintainers, and tooling developers who need repeatable local validation before deploying to Analogue Pocket hardware.

It is most useful as a regression gate, bring-up harness, profile generator, metadata validator, bridge protocol debugger, and artifact producer.

## Quick Start

From the repository root:

```sh
make lint
make profile-run PROFILE=mock FRAMES=2
apfsim/bin/apfsim validate-artifacts apfsim/build/profiles/mock/run
```

The deterministic contract-test core should report boot, video, audio, and status passes. Inspect these files first:

- `apfsim/build/profiles/mock/run/result.json`
- `apfsim/build/profiles/mock/run/bridge.log`
- `apfsim/build/profiles/mock/run/video_shape.json`

The main CLI lives at `apfsim/bin/apfsim`:

```sh
cd apfsim
bin/apfsim doctor
bin/apfsim build --profile mock
bin/apfsim run --profile mock --frames 2
bin/apfsim diagnose build/profiles/mock/run
bin/apfsim test --matrix ci
```

## What A Passing Run Proves

A passing `apfsim` run can prove that the simulated `core_top`:

- accepts the expected APF boot/reset lifecycle;
- receives data-slot payloads at configured bridge addresses;
- optionally reads loaded slots back through the APF bridge to catch RAM/address/byte-lane corruption;
- reaches running status;
- handles expected host commands and target commands;
- receives configured persistent `interact.json` writes;
- accepts scripted controller inputs;
- emits valid APF-facing video timing and stable active dimensions;
- emits I2S-style audio activity with basic clock/sample sanity;
- unloads configured nonvolatile saves;
- produces internally consistent machine-readable artifacts.

The exact proof depends on the profile and scenario expectations. Strict gates should encode expected dimensions, checksums, data-slot readback, reset timings, audio activity, save behavior, and bridge readbacks under `expect:`.

## What A Passing Run Does Not Prove

A passing run does not prove:

- FPGA timing closure;
- exact Pocket hardware behavior;
- correctness of placeholder DDR/SDRAM/CRAM models;
- gameplay correctness when gameplay RTL is stubbed or bypassed;
- vendor PLL/IP behavior unless modeled;
- full compatibility with every custom APF bridge implementation without adaptation;
- that hardware testing can be skipped.

Hardware remains the final authority. `apfsim` is intended to catch integration failures earlier and make failures reproducible.

## Core Workflows

### Diagnose A Run

Every profile run now emits a diagnostic layer on top of raw simulator artifacts:

```sh
bin/apfsim run --profile mock_port_gate
bin/apfsim diagnose build/profiles/mock_port_gate/run --profile mock_port_gate --strict
```

The stable outputs are:

- `diagnostics.json`: machine-readable APF contract failures with stable codes, evidence pointers, likely causes, and repair suggestions.
- `bringup-report.md`: a practical human report with blocking diagnostics, recommended next action, artifact paths, and hardware-confidence summary.
- `repair-plan.json`: optional reviewable repair suggestions from `bin/apfsim bringup --repair`.

This is the first layer of the porting-intelligence workflow. The goal is for tools and generators to consume diagnostic codes like `VIDEO_WIDTH_MISMATCH`, `DATA_SLOT_LOAD_SHORT`, or `READY_TO_RUN_MISSING` instead of scraping prose logs. See [Diagnostics And Bring-Up](docs/diagnostics.md).

Agents implementing full-auto bring-up should use [Full-Auto Agent Guide](docs/full-auto-agent-guide.md). It maps the stable artifact fields for video shape, first protocol failure windows, control-plane probes, input smoke, audio activity, data loading, package validation, and shim provenance.

Package and summary gates:

```sh
bin/apfsim package-check --root /path/to/core-or-package --json-out output/package_check.json --strict
bin/apfsim summarize-run output/bringup/core-name/run --json-out output/summary.json --tsv-out output/summary.tsv --strict
```

### Run A Bring-Up Corpus

Use `corpus run` when a generator or maintainer wants one manifest to drive many cores through bring-up or package-only stages:

```sh
bin/apfsim corpus run \
  --manifest output/corpus/manifest.yml \
  --out output/corpus/run \
  --strict
```

Example manifest:

```yaml
defaults:
  frames: 60
  timeout: 600
  repair: true
cores:
  - name: mock-gate
    profile: mock_port_gate
    family: direct-mode
  - name: generated-core
    root: /path/to/openFPGA-Core
    rom: /path/to/game.rom
    expected_platform_id: arcade_generated
    auto_profile: true
    family: direct-mode
  - name: package-only
    root: /path/to/SD-package
    expected_platform_id: arcade_generated
    stop_stage: package
```

Stable outputs:

- `corpus_summary.json`: aggregate pass/fail/skip totals, family counts, top blockers, and one normalized row per core.
- `corpus_summary.tsv`: spreadsheet-friendly view of the same per-core rows.
- `cores/<name>/run/summary.json`: the per-core run row emitted by `bringup`.

Root-missing entries are skipped so local inventories can be shared. Missing ROMs/assets are preflight failures because they indicate a generator/package input problem.

### Bring Up A Core

`bringup` is the high-level command intended to grow into discover, profile generation, simulation, diagnosis, repair planning, and rerun:

```sh
bin/apfsim bringup \
  --profile mock_port_gate \
  --out output/bringup/mock_port_gate \
  --repair \
  --emit-patches
```

For generated candidates:

```sh
bin/apfsim bringup \
  --root /path/to/openFPGA-Core \
  --auto-profile \
  --rom /path/to/game.rom \
  --out output/bringup/core-name \
  --repair
```

For an existing generated profile, pass the package/check-out root explicitly so `{root}` placeholders resolve and package validation is included in the run directory:

```sh
bin/apfsim bringup \
  --profile output/generated-profiles/core/core.json \
  --root /path/to/openFPGA-Core-or-package \
  --expected-platform-id arcade_core \
  --out output/bringup/core \
  --repair
```

Automatic source mutation is intentionally not performed. Repair output is patch-plan first; source patches will be emitted only by explicit repair rules.

### Run The Deterministic Mock Profile

```sh
cd apfsim
bin/apfsim run --profile mock_port_gate --bridge-trace
bin/apfsim validate-artifacts build/profiles/mock_port_gate/run
```

`mock_port_gate` is the deterministic contract gate for boot, reset, bridge, data, video, audio, input, interact, save, and artifact checks.

### Validate Official Example Integrations

The public tree ships profiles for official openFPGA examples only:

- `open-fpga/core-template`
- `open-fpga/core-example-interact`
- `open-fpga/core-example-kbmouse-targetdata`
- `open-fpga/core-example-basicassets`
- `open-fpga/core-example-basicchip32`

Clone the examples outside this repository and point profiles at them:

```sh
git clone https://github.com/open-fpga/core-template /path/to/core-template
git clone https://github.com/open-fpga/core-example-interact /path/to/core-example-interact
git clone https://github.com/open-fpga/core-example-kbmouse-targetdata /path/to/core-example-kbmouse-targetdata
git clone https://github.com/open-fpga/core-example-basicassets /path/to/core-example-basicassets
git clone https://github.com/open-fpga/core-example-basicchip32 /path/to/core-example-basicchip32
```

Run one profile:

```sh
CORE_EXAMPLE_BASICASSETS_ROOT=/path/to/core-example-basicassets \
  bin/apfsim run --profile basicassets
```

Run the official example matrix:

```sh
CORE_TEMPLATE_ROOT=/path/to/core-template \
CORE_EXAMPLE_INTERACT_ROOT=/path/to/core-example-interact \
CORE_EXAMPLE_KBMOUSE_TARGETDATA_ROOT=/path/to/core-example-kbmouse-targetdata \
CORE_EXAMPLE_BASICASSETS_ROOT=/path/to/core-example-basicassets \
CORE_EXAMPLE_BASICCHIP32_ROOT=/path/to/core-example-basicchip32 \
  bin/apfsim test --matrix official-examples
```

`basicchip32` currently validates the public HDL path by loading equivalent image/audio payloads and applying the display-enable bridge write. It does not execute the Chip32 VM yet.

### Discover Core Checkouts

Use discovery before hand-writing profiles for a batch of local cores:

```sh
bin/apfsim discover \
  --root /path/to/pocket-core-checkouts \
  --output output/core-inventory
```

Discovery reports package metadata, `core_top` candidates, HDL language mix, likely Verilator blockers, missing shims, and git cleanliness. See [Generated Profile Candidates](docs/generated-profiles.md).

### Generate A Profile Candidate

```sh
bin/apfsim generate-profile \
  --root /path/to/openFPGA-Core \
  --output output/generated-profiles \
  --json
```

Generated profiles are review artifacts, not trusted production gates. Review the generated filelist, scenario, notes, shim substitutions, and expected artifacts before copying anything into `profiles/`.

### Compare Simulated Video Shape With `video.json`

Every successful run writes `video_shape.json` and `result.json.video_shape`. This is the stable runtime video contract for tools such as core generators.

```sh
bin/apfsim video-shape --profile mock_port_gate --frames 20 --json-out output/mock_shape.json
bin/apfsim compare-video-json --shape output/mock_shape.json --video-json examples/mock/video.json
bin/apfsim apply-video-shape --shape output/mock_shape.json --video-json examples/mock/video.json --out output/video.json
```

Use this when generated `video.json` says one size but simulated APF output proves another. See [Video Shape Workflow](docs/video-shape.md).

## Artifacts

A run writes a stable artifact directory. Important files:

- `result.json`: top-level run status, phase status, boot/data/bridge/video/audio/input/save summaries.
- `diagnostics.json`: stable APF contract diagnostics with evidence and repair suggestions.
- `bringup-report.md`: human-readable bring-up summary.
- `repair-plan.json`: optional reviewable repair suggestions from `bringup --repair`.
- `package_check.json`: package metadata and SD-card path validation.
- `summary.json` / `summary.tsv`: normalized one-row output for corpus and generator consumption.
- `corpus_summary.json` / `corpus_summary.tsv`: aggregate output from `corpus run`.
- `source_provenance.json.memory_dependencies`: detected SDRAM/SRAM/CRAM/PSRAM/BRAM/FIFO needs and model confidence.
- `video_shape.json`: APF-facing runtime video contract.
- `lifecycle.json`: APF boot/reset/data/RTC/Ready-to-Run/running cycle markers.
- `bridge.log`: human-readable APF command and data-slot flow.
- `bridge_summary.json`: bridge counters and command history.
- `bridge_transactions.jsonl`: optional per-transaction trace with `--bridge-trace`.
- `video/frame_*.json`: per-frame timing/content metadata.
- `video/frame_*.ppm`: captured frames.
- `audio/out.wav`: decoded stereo audio.
- `audio/stats.json`: audio statistics.
- `saves/slot_<id>.bin`: unloaded nonvolatile slots.
- `savestates/*.sta`: scenario-requested savestate blobs.

See [Runtime Artifacts](docs/artifacts.md) and `schemas/*.schema.json`.

## Profiles

Public profiles live in `profiles/*.json`.

| Profile | Purpose |
| --- | --- |
| `mock` | Deterministic contract-test core. |
| `mock_port_gate` | Strict built-in APF contract gate. |
| `mock_target_commands` | Runtime target data-slot/read/write/flush/filename/open-file/debug-event regression. |
| `mock_lifecycle` | Host lifecycle injection regression for OS notify, data-slot update, and savestate save/query. |
| `core_template` | Official `open-fpga/core-template` smoke profile. |
| `interact` | Official `open-fpga/core-example-interact` settings/profile smoke. |
| `kbmouse_targetdata` | Official `open-fpga/core-example-kbmouse-targetdata` controller and target-data smoke. |
| `basicassets` | Official `open-fpga/core-example-basicassets` asset/audio/video smoke with SDRAM shim. |
| `basicchip32` | Official `open-fpga/core-example-basicchip32` HDL smoke; Chip32 VM execution is future work. |

Matrix modes:

| Matrix | Profiles |
| --- | --- |
| `ci` | Mock contract gates only. |
| `local-fast` | Mock gates plus available core template. |
| `local-real` | Mock gates plus all available official examples. |
| `official-examples` | Official examples only. |

## Scenario Format

Scenarios are declarative YAML. A minimal shape:

```yaml
name: boot_smoke
data_slots:
  - id: 1
    name: ROM
    file: assets/game.rom
    address: 0x10000000
    required: true
interact:
  writes:
    - frame: boot
      address: 0x50000010
      value: 1
inputs:
  - frame: 60
    player: 1
    button: Start
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

## Required `core_top` Contract

The harness expects APF-facing `core_top` ports for:

- `clk_74a`, `clk_74b`
- BRIDGE: `bridge_addr`, `bridge_rd`, `bridge_rd_data`, `bridge_wr`, `bridge_wr_data`, `bridge_endian_little`
- PAD: `cont1_key` through `cont4_key`, `cont1_joy` through `cont4_joy`, `cont1_trig` through `cont4_trig`
- VIDEO: `video_rgb_clock`, `video_rgb_clock_90`, `video_rgb`, `video_de`, `video_skip`, `video_vs`, `video_hs`
- AUDIO: `audio_mclk`, `audio_lrck`, `audio_dac`

If a core uses different names or widths, add a thin simulation wrapper and set the profile `top` to that wrapper.

## Limitations

- The command register layout is isolated but may need adaptation for a specific generated `core_bridge_cmd` implementation.
- `data.json`, `interact.json`, and scenario parsing are dependency-free subsets, not full JSON/YAML schema validators.
- PNG frame export is not included yet; PPM and JSON metadata are generated.
- DDR/CRAM/SDRAM controller models are placeholders unless a profile supplies a stronger transactional model.
- Audio validation is statistical today; it captures I2S words and emits WAV/stats but is not a full audio conformance suite.
- Public CI should default to mock-only profiles unless external official examples are explicitly provisioned.

## Full Documentation

- [APF Contract Coverage](docs/apf-contract.md)
- [Runtime Artifacts](docs/artifacts.md)
- [Runtime Video Contract Discovery](docs/video-shape.md)
- [Generated Profile Candidates](docs/generated-profiles.md)
- [Shim And Substitution Catalog](docs/shim-catalog.md)
- [Memory Dependencies And External RAM](docs/memory.md)
- [Log-Derived APF Runtime Flows](docs/log-derived-flows.md)
- [Public Readiness Notes](docs/public-readiness.md)

## Development Notes

Useful commands:

```sh
make -C apfsim lint
make -C apfsim build
make -C apfsim run-mock
make -C apfsim test
make -C apfsim test-matrix MATRIX=local-fast
```

`make test` uses `uv run pytest`, so Python test dependencies are resolved from the root `pyproject.toml` without requiring global installs.

```sh
uv run pytest -q apfsim/tests
make -C apfsim test
```

If `uv` is unavailable, install it from https://docs.astral.sh/uv/ or use a local virtual environment with `apfsim/requirements-dev.txt`.
