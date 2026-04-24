# Full-Auto Agent Guide

This document is for agents wiring `apfsim` into a generator or corpus runner. Prefer these fields and commands over scraping stdout.

## Agent Contract

`apfsim` is an APF contract lab, not a gameplay emulator. A full-auto agent should use it to decide whether a generated Pocket core is ready for Quartus/hardware, needs a profile/shim/wrapper repair, or should be classified as architecture-blocked.

Use this loop:

1. `discover` or provide a manifest row.
2. `generate-profile` or `bringup --auto-profile`.
3. Run sim until a contract gate or selected stop stage.
4. Read stable artifacts.
5. Emit diagnostics and repair plan.
6. Reduce generator bugs into tests before continuing the corpus.

Do not silently patch source trees. Use reviewable patches and rerun.

## Commands

Existing profile:

```sh
bin/apfsim bringup \
  --profile mock_port_gate \
  --out output/bringup/mock_port_gate \
  --repair \
  --emit-patches
```

Generated candidate:

```sh
bin/apfsim bringup \
  --root /path/to/openFPGA-Core \
  --auto-profile \
  --rom /path/to/game.rom \
  --out output/bringup/core-name \
  --repair
```

Existing generated profile with an explicit package/check-out root:

```sh
bin/apfsim bringup \
  --profile output/generated/core/profile.json \
  --root /path/to/openFPGA-Core-or-package \
  --expected-platform-id arcade-platform \
  --out output/bringup/core-name \
  --repair
```

When `--profile` and `--root` are both supplied, `apfsim` binds `{root}` placeholders in the profile and writes `run/package_check.json` before `summary.json` is generated.

Existing run diagnosis:

```sh
bin/apfsim diagnose output/bringup/core-name/run --profile profile.json --strict --json --pretty
```

Package validation:

```sh
bin/apfsim package-check \
  --root /path/to/openFPGA-Core-or-SD-package \
  --expected-platform-id arcade-platform \
  --json-out output/package_check.json \
  --strict
```

Normalized one-row summary:

```sh
bin/apfsim summarize-run \
  output/bringup/core-name/run \
  --json-out output/summary.json \
  --tsv-out output/summary.tsv \
  --strict
```

Manifest-driven corpus:

```sh
bin/apfsim corpus run \
  --manifest output/corpus/manifest.yml \
  --out output/corpus/run \
  --strict
```

Video shape loop:

```sh
bin/apfsim video-shape output/bringup/core-name/run --json-out output/shape.pre.json --pretty
bin/apfsim apply-video-shape --shape output/shape.pre.json --video-json path/to/video.json --out output/video.json --timing-hints
bin/apfsim run --profile profile.json --artifacts output/bringup/core-name/rerun
```

## Stable Artifacts

Read these first:

- `result.json`: phase summaries and normalized sim observables.
- `diagnostics.json`: stable failure codes, evidence pointers, likely causes, repair suggestions.
- `bringup-report.md`: human report for handoff.
- `video_shape.json`: APF-facing runtime video contract.
- `bridge_summary.json`: bridge counters and command transcript.
- `source_provenance.json`: sim-only shims/generated files/provenance.
- `memory_activity.json`: memory model provenance and live counter status when wrapper probes are connected.
- `package_check.json`: APF metadata and SD-card path validation.
- `summary.json` / `summary.tsv`: normalized one-row output for corpus/coreir consumption.
- `corpus_summary.json` / `corpus_summary.tsv`: aggregate manifest-run output for batch decisions.
- `repair-plan.json`: optional repair suggestions from `bringup --repair`.

## Observable Field Map

| Need | Purpose | Stable field(s) |
| --- | --- | --- |
| Startup/stable-frame policy | Avoid early-frame mismatches being treated as stable shape. | `video_shape.startup_frames_ignored`, `video_shape.frames_considered`, `result.video.startup_frames_ignored`, `result.video.frames_considered` |
| First video protocol failure window | Make protocol failures actionable without opening a full waveform. | `result.video_protocol.first_error_cycle`, `result.video_protocol.first_error_code`, `result.video_protocol.trace_window`, mirrored in `video_shape` |
| Control-plane write/read probe | Catch interact persistence and reset-action failures before hardware. | `result.interact_readback`, `result.reset_action_seen`, `result.control_plane`, `bridge_transactions.jsonl` when `--bridge-trace` is enabled |
| Input injection smoke | Prove scripted gamepad bits are driven into APF controller pins. | `result.input.input_trace`, `result.input.input_effect_seen`, top-level `result.input_trace`, top-level `result.input_effect_seen` |
| Audio activity report | Distinguish no clock, no LRCK, silence, stuck sample, and active waveform. | `result.audio.activity`, `result.audio.nonzero_samples`, `result.audio.peak`, `result.audio.mclk_seen`, `result.audio.lrclk_seen`, `audio/stats.json` |
| Data-load transcript | Catch wrong ROM/JSON, slot id, size, path, checksum, or bridge-visible RAM corruption before SD copy. | `result.data_load.slots[]`, `loaded_bytes`, `crc`, `checksum_fnv1a64`, `readback_attempted`, `readback_matches`, `readback_mismatch_count`, `done_seen`, `bridge_summary.slot_table_ok` |
| Manifest/package validator | Catch core/platform/asset naming mismatches before hardware. | `package_check.package_errors[]`, `package_check.package_warnings[]`, `package_check.sd_paths[]` |
| Shim/source provenance | Make sim-only VHDL, primitive shims, and memory model libraries visible in pass results. | `source_provenance.shimmed_modules[]`, `kind`, `confidence`, `modules`, `memory_classes`, `source_provenance.generated_files[]`, `source_provenance.sim_only_paths[]` |
| Memory dependency intelligence | Classify SDRAM/SRAM/CRAM/PSRAM/BRAM/FIFO needs and model confidence. | `profile.memory`, `candidate.json.memory`, `source_provenance.memory_dependencies`, `source_provenance.wrapper_generation`, `memory_activity.json`, `summary.row.memory_classes`, `summary.row.memory_models`, `summary.row.memory_risks`, `summary.row.memory_activity_observed`, `summary.row.memory_error_codes` |

## Per-Core Row Normalization

A corpus runner should flatten each run into one JSON/TSV row. Recommended columns:

- `core_id`
- `root`
- `profile`
- `family`: `direct-mode`, `shell-mode`, or `architecture-block`
- `stage`: `discover`, `profile`, `build`, `run`, `diagnose`, `package`, `hardware-queued`
- `ok`
- `first_error_code`
- `blocking_codes`
- `warning_codes`
- `active_width`
- `active_height`
- `frames_considered`
- `video_protocol_valid`
- `audio_activity`
- `loaded_bytes_total`
- `data_crc_list`
- `shimmed_modules`
- `shim_kinds`
- `shim_confidences`
- `memory_classes`
- `memory_models`
- `memory_risks`
- `memory_activity_observed`
- `memory_error_codes`
- `artifact_dir`

`bin/apfsim summarize-run` emits this row today as `summary.json.row` and `summary.tsv`. `bringup` writes both automatically after package-check, run, diagnose, and optional repair-plan.

Profile `expected_artifacts` is a runtime-only contract. Do not put `diagnostics.json`, `bringup-report.md`, `repair-plan.json`, `summary.json`, `summary.tsv`, or `package_check.json` in that list, because those are bring-up postprocess outputs created after runtime artifact validation.

The first blocking diagnostic should determine the immediate next action. Do not treat `boot reached running` as a pass if video/audio/data/package gates fail.

## Corpus Manifest

Use `corpus run` as the batch boundary between a generator and `apfsim`. The manifest can be JSON or the simple YAML subset below:

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

Recommended row fields:

- `name`: stable generator-facing core id.
- `profile`: existing `apfsim` profile name or path.
- `root`: checkout or SD package root for `bringup --auto-profile` or `package-check`.
- `rom`: primary ROM/asset path to bind to slot 1 unless `rom_slot_id` is set.
- `expected_platform_id`: package validator assertion.
- `family`: `direct-mode`, `shell-mode`, or `architecture-block`.
- `stop_stage`: `bringup` by default, or `package` for metadata-only queue checks.

`corpus_summary.json` is the batch API:

- `totals`: total, passed, failed, skipped.
- `family_counts`: distribution across the early family classification.
- `top_blockers`: stable failure-code counts for roadmap selection.
- `cores[]`: one normalized row per manifest entry, including `summary_path`, `package_check_path`, `first_error_code`, video/audio/data fields, and artifact paths.

Root-missing entries are skipped so agents can share manifests across machines. Missing ROMs/assets are failures with `ROM_MISSING` because they indicate a bad generator input or package manifest. Use `--strict` when the corpus is a CI gate; omit it for exploratory inventory runs.

The public tree includes a ready-made public-example manifest:

```sh
bin/apfsim corpus run --manifest corpus/public_examples.yml --out output/public-examples
```

It includes the deterministic contract-test profiles plus the supported official openFPGA examples. External official profiles skip cleanly unless the documented checkout environment variables are present.

Package validation permits data slots with no `address` field. This is valid for setup-only JSON/instance slots that the core does not receive as a bridge payload. If a corpus run needs `apfsim` to load bytes for that slot, the generated scenario/profile must still provide a concrete bridge address.

## Shape Repair Loop

Use shape auto-repair only when the video protocol is valid:

1. Run enough frames to skip startup instability.
2. Read `video_shape.stable_dimensions` and protocol counters.
3. If protocol counters are nonzero, repair wrapper timing first.
4. If protocol is valid but `video.json` dimensions differ, use `apply-video-shape` to emit a patched metadata file.
5. Rerun and store both pre/post artifacts.

Do not patch `video.json` to match a bad wrapper. A common failure is one extra active pixel from HBLK/DE polarity or edge adaptation. Fix wrapper timing before metadata.

For JTFRAME Pocket exports, also check whether the logical wrapper is using the high-speed physical video clock instead of the pixel-enable cadence. If `video_shape.active_width` is an exact multiple of `video.json` width, the correct repair is usually wrapper clock/pixel-enable adaptation, not metadata patching.

## Hardware Queue Policy

Only emit a copy-to-SD checklist when all are true:

- build/profile preflight passed;
- boot/reset lifecycle passed;
- required data slots loaded with expected sizes/checksums;
- video protocol and shape gates passed;
- audio passed or has an explicit waiver;
- input smoke passed or is explicitly not applicable;
- saves passed or are not declared;
- package validation passed.

If package validation is not run, mark hardware queue status as `blocked_package_validator_missing` rather than pretending it passed. `bringup` runs package validation automatically when `--root` is supplied or when the profile has a resolved external root.

## Regression Promotion Rule

When a core exposes a generator bug:

1. Capture the smallest failing artifact directory.
2. Record the diagnostic code and evidence pointer.
3. Reduce the source pattern into a focused test fixture.
4. Add a test before continuing broad corpus work.

This prevents full-auto from repeatedly rediscovering the same wrapper/profile/shim bug.

## Family Strategy

Classify early so generic shims do not consume time on architecture-blocked cores:

- `direct-mode`: Verilator can compile the generated `core_top` with catalog shims.
- `shell-mode`: APF shell/profile can be tested but gameplay RTL is stubbed or mixed-language.
- `architecture-block`: requires a new memory model, translated VHDL, or major wrapper synthesis before meaningful simulation.

Use `source_provenance.json`, generated-profile warnings, discovery risks, and diagnostics like `VHDL_ENTITY_STUBBED`, `SHIM_REQUIRED`, and `MEMORY_MODEL_REQUIRED` to set this classification.

Memory classification policy:

- `bram` and `fifo` generally mean internal behavioral shims are enough for APF contract smoke.
- `sdram` currently means the generic idealized SDRAM model can unblock bring-up, but hardware confidence remains limited.
- `sram`, `psram`, or `cram` can select public model-library scaffolds; treat the “missing model” risk as cleared only when `profile.memory.selected_model_classes` includes that class, but still require live wiring evidence before hardware confidence improves.
- `ddr` should be treated as requiring explicit external RAM model work unless the profile names a stronger model.
- Generated profiles emit `apfsim_memory_models.sv` for `sram`/`psram`/`cram` as a reviewable scaffold. Do not treat it as live memory validation until `memory_activity.observed` is true or a run-specific counter probe exists.
