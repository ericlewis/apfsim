# Video Shape Workflow

Every successful runtime profile writes the stable APF-facing video shape contract in two places:

- `result.json.video_shape`
- `video_shape.json`

The shape is measured from `video_rgb`, `video_de`, `video_hs`, `video_vs`, and `video_skip` after configured startup frames are ignored.

Stable automation fields:

- `video_shape.startup_frames_ignored`: configured startup/warmup frames excluded from the stable measurement.
- `video_shape.frames_considered`: number of completed frames used for the reported active shape.
- `video_shape.active_width` / `active_height`: stable active dimensions after startup filtering.
- `video_shape.total_width_min` / `total_width_max`: min/max pixel clocks per line after startup filtering.
- `video_shape.hs_to_de_gap_min`, `de_to_hs_gap_min`, `vs_to_first_de_lines`: porch-like APF timing gaps.
- `video_shape.first_error_cycle`: first observed APF video protocol failure, or `0` when none was observed.
- `video_shape.trace_window`: suggested cycle window around the first failure for an FST rerun.
- `result.json.video_protocol`: same first-error information grouped as a protocol diagnostic object.

Extract or run shape discovery:

```sh
bin/apfsim video-shape build/profiles/mock_port_gate/run --pretty
bin/apfsim video-shape --profile mock_port_gate --frames 20 --json-out output/mock_shape.json
```

Compare simulated output against package metadata:

```sh
bin/apfsim compare-video-json \
  --shape build/profiles/mock_port_gate/run \
  --video-json path/to/video.json
```

Patch generated metadata when the simulated APF output is the source of truth:

```sh
bin/apfsim apply-video-shape \
  --shape build/profiles/mock_port_gate/run \
  --video-json path/to/video.json \
  --out build/generated/video.json \
  --timing-hints
```

`apply-video-shape` refuses unstable dimensions or protocol-bad shapes unless `--force` is provided. Use `--in-place --backup` only when intentionally updating a checkout.

For coreir, consume `video_shape.active_width`, `video_shape.active_height`, `startup_frames_ignored`, `frames_considered`, `stable_dimensions`, and protocol error counters. Treat nonzero `de_errors`, `pulse_width_errors`, or `skip_errors` as failures. If `first_error_cycle` is nonzero, show `trace_window` in the generated failure message so the next agent can rerun with waves without searching the whole boot.
