# Runtime Artifacts

A profile run writes a stable artifact directory. Important files:

- `result.json`: top-level run status, phase status, boot/data/bridge/video/audio/input/save summaries.
- `diagnostics.json`: stable APF contract diagnostics, schema `apfsim.diagnostics.v1`.
- `bringup-report.md`: concise human-readable blocking/non-blocking bring-up report.
- `repair-plan.json`: optional repair suggestions from `bringup --repair`, schema `apfsim.repair_plan.v1`.
- `video_shape.json`: APF-facing shape contract, schema `apfsim.video_shape.v1`.
- `lifecycle.json`: APF boot/reset/data/RTC/Ready-to-Run/running cycle markers, schema `apfsim.lifecycle.v1`.
- `bridge.log`: human-readable APF command and data-slot flow.
- `bridge_summary.json`: bridge counters and command history.
- `video/frame_*.json`: per-frame timing/content metadata.
- `video/frame_*.ppm`: captured frames.
- `audio/out.wav`: decoded stereo audio.
- `audio/stats.json`: audio statistics.
- `saves/slot_<id>.bin`: unloaded nonvolatile slots.
- `savestates/*.sta`: scenario-requested `0x00A0` savestate blobs.

`result.json` also includes:

- `host_commands`: every scenario-injected host command with command word, parameters, result, response words, execution cycle, transferred byte count, and output path when applicable.
- `savestate.reports`: support/query/start/final results, response address/size, copied byte count, checksum, poll count, and saved path for `savestate_save` events.

Validate an existing run:

```sh
bin/apfsim validate-artifacts path/to/run-dir
```

Classify an existing run into diagnostics:

```sh
bin/apfsim diagnose path/to/run-dir --strict
```

Public JSON schemas live in `schemas/*.schema.json`. These schemas are intentionally permissive for additive fields but strict about the stable contract keys used by downstream tools.
