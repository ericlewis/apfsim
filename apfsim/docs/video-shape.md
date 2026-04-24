# Video Shape Workflow

Every successful runtime profile writes the stable APF-facing video shape contract in two places:

- `result.json.video_shape`
- `video_shape.json`

The shape is measured from `video_rgb`, `video_de`, `video_hs`, `video_vs`, and `video_skip` after configured startup frames are ignored.

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

For coreir, consume `video_shape.active_width`, `video_shape.active_height`, `stable_dimensions`, and protocol error counters. Treat nonzero `de_errors`, `pulse_width_errors`, or `skip_errors` as failures.
