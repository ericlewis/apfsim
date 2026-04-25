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
- `source_provenance.json`: profile root, generated files, sim-only paths, and shim catalog provenance.
- `summary.json.row.shim_kinds` and `summary.json.row.shim_confidences`: compact `name:value` lists for separating compile shims, behavioral models, and bring-up-only models in corpus output.
- `source_provenance.json.memory_dependencies`: detected memory classes, evidence, model confidence, and risks.
- `source_provenance.json.wrapper_generation`: generated wrapper scaffolds such as external RAM helper modules.
- `memory_activity.json`: memory model provenance and, once wrappers wire counters, external RAM activity/error counters.
- `package_check.json`: package metadata and SD-card path validation, schema `apfsim.package_check.v1`.
- `summary.json`: normalized per-run row for corpus and generator consumption, schema `apfsim.run_summary.v1`.
- `summary.tsv`: one-row tab-separated form of `summary.json.row`.
- `corpus_summary.json`: aggregate manifest-run report from `corpus run`, schema `apfsim.corpus_summary.v1`.
- `corpus_summary.tsv`: one-row-per-core tab-separated form of `corpus_summary.json.cores`.
- `video/frame_*.json`: per-frame timing/content metadata.
- `video/frame_*.ppm`: captured frames.
- `audio/out.wav`: decoded stereo audio.
- `audio/stats.json`: audio statistics.
- `saves/slot_<id>.bin`: unloaded nonvolatile slots.
- `savestates/*.sta`: scenario-requested `0x00A0` savestate blobs.

`result.json` also includes:

- `host_commands`: every scenario-injected host command with command word, parameters, result, response words, execution cycle, transferred byte count, and output path when applicable.
- `savestate.reports`: support/query/start/final results, response address/size, copied byte count, checksum, poll count, and saved path for `savestate_save` events.
- `data_load`: slot ids, paths, address presence, file existence, load status/error, loaded byte counts, CRC32, FNV-1a checksums, optional APF bridge readback CRC/mismatch fields, and all-complete status.
- `video_protocol`: first APF video protocol error cycle and suggested trace window.
- `input_video_response`, `input_video_effect_seen`, and `video_activity`: frame-change-after-input measurements and optional named scenario phases, schema `apfsim.video_activity.v1`. Use this to distinguish a static attract screen from gameplay/video state that changes after coin/start input.
- `interact_readback`, `reset_action_seen`, and `control_plane`: compact control-plane probes.
- `input_trace` and `input_effect_seen`: scripted input delivery summary.
- `audio.activity`, `nonzero_samples`, `peak`, `mclk_seen`, and `lrclk_seen`: compact audio activity classification.

Validate an existing run:

```sh
bin/apfsim validate-artifacts path/to/run-dir
```

Classify an existing run into diagnostics:

```sh
bin/apfsim diagnose path/to/run-dir --strict
```

Validate package metadata:

```sh
bin/apfsim package-check --root /path/to/core-or-package --json-out package_check.json --strict
```

Flatten a run into a corpus row:

```sh
bin/apfsim summarize-run path/to/run-dir --json-out summary.json --tsv-out summary.tsv --strict
```

Run a manifest-driven bring-up corpus:

```sh
bin/apfsim corpus run --manifest corpus.yml --out output/corpus --strict
```

`corpus run` writes `corpus_summary.json`, `corpus_summary.tsv`, and one subdirectory per core under `cores/<name>/`. Root-missing entries are marked `skipped`; missing ROMs/assets, package errors, simulation failures, and diagnostic errors are marked `failed`.

The public example corpus manifest is:

```sh
bin/apfsim corpus run --manifest corpus/public_examples.yml --out output/public-examples
```

It includes the deterministic mock profiles and the supported official openFPGA example profiles. Official examples skip when their checkout environment variables are unset.

Public JSON schemas live in `schemas/*.schema.json`. These schemas are intentionally permissive for additive fields but strict about the stable contract keys used by downstream tools.
