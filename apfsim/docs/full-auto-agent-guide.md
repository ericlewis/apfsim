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
- `package_check.json`: APF metadata and SD-card path validation.
- `summary.json` / `summary.tsv`: normalized one-row output for corpus/coreir consumption.
- `repair-plan.json`: optional repair suggestions from `bringup --repair`.

## Observable Field Map

| Need | Purpose | Stable field(s) |
| --- | --- | --- |
| Startup/stable-frame policy | Avoid early-frame mismatches being treated as stable shape. | `video_shape.startup_frames_ignored`, `video_shape.frames_considered`, `result.video.startup_frames_ignored`, `result.video.frames_considered` |
| First video protocol failure window | Make protocol failures actionable without opening a full waveform. | `result.video_protocol.first_error_cycle`, `result.video_protocol.first_error_code`, `result.video_protocol.trace_window`, mirrored in `video_shape` |
| Control-plane write/read probe | Catch interact persistence and reset-action failures before hardware. | `result.interact_readback`, `result.reset_action_seen`, `result.control_plane`, `bridge_transactions.jsonl` when `--bridge-trace` is enabled |
| Input injection smoke | Prove scripted gamepad bits are driven into APF controller pins. | `result.input.input_trace`, `result.input.input_effect_seen`, top-level `result.input_trace`, top-level `result.input_effect_seen` |
| Audio activity report | Distinguish no clock, no LRCK, silence, stuck sample, and active waveform. | `result.audio.activity`, `result.audio.nonzero_samples`, `result.audio.peak`, `result.audio.mclk_seen`, `result.audio.lrclk_seen`, `audio/stats.json` |
| Data-load transcript | Catch wrong ROM/JSON, slot id, size, path, or checksum before SD copy. | `result.data_load.slots[]`, `loaded_bytes`, `crc`, `checksum_fnv1a64`, `done_seen`, `bridge_summary.slot_table_ok` |
| Manifest/package validator | Catch core/platform/asset naming mismatches before hardware. | `package_check.package_errors[]`, `package_check.package_warnings[]`, `package_check.sd_paths[]` |
| Shim/source provenance | Make sim-only VHDL or primitive shims visible in pass results. | `source_provenance.shimmed_modules[]`, `source_provenance.generated_files[]`, `source_provenance.sim_only_paths[]` |

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
- `artifact_dir`

`bin/apfsim summarize-run` emits this row today as `summary.json.row` and `summary.tsv`. `bringup` writes both automatically after package-check, run, diagnose, and optional repair-plan.

The first blocking diagnostic should determine the immediate next action. Do not treat `boot reached running` as a pass if video/audio/data/package gates fail.

## Shape Repair Loop

Use shape auto-repair only when the video protocol is valid:

1. Run enough frames to skip startup instability.
2. Read `video_shape.stable_dimensions` and protocol counters.
3. If protocol counters are nonzero, repair wrapper timing first.
4. If protocol is valid but `video.json` dimensions differ, use `apply-video-shape` to emit a patched metadata file.
5. Rerun and store both pre/post artifacts.

Do not patch `video.json` to match a bad wrapper. A common failure is one extra active pixel from HBLK/DE polarity or edge adaptation. Fix wrapper timing before metadata.

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
