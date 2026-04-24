# Diagnostics And Bring-Up

`apfsim` is moving from raw simulation artifacts toward an APF bring-up and diagnosis layer. A run should not only say that a core failed; it should classify the APF contract failure, point to evidence, and suggest the next repair to review.

## Stable Outputs

Every normal `run` and `play` path writes these files when possible:

- `result.json`: raw run summary from the Verilated core harness.
- `diagnostics.json`: stable diagnostic codes with observed/expected values, JSON evidence pointers, likely causes, and repair suggestions.
- `bringup-report.md`: concise human report for the current run.

`bringup --repair` also writes:

- `repair-plan.json`: reviewable repair suggestions derived from diagnostics.
- `patches/README.md`: placeholder until a repair rule can emit a real patch.

The tool does not silently mutate source trees. Automatic repairs must produce reviewable patches before anything is applied.

## Commands

Classify an existing run:

```sh
bin/apfsim diagnose build/profiles/mock_port_gate/run --profile mock_port_gate --strict
```

Run and diagnose a profile:

```sh
bin/apfsim run --profile mock_port_gate
```

High-level bring-up with repair planning:

```sh
bin/apfsim bringup \
  --profile mock_port_gate \
  --out output/bringup/mock_port_gate \
  --repair \
  --emit-patches
```

Generated candidate bring-up:

```sh
bin/apfsim bringup \
  --root /path/to/openFPGA-Core \
  --auto-profile \
  --rom /path/to/game.rom \
  --out output/bringup/core-name \
  --repair
```

Generated-profile bring-up currently creates a reviewable profile bundle under `output/bringup/core-name/generated-profile/` and run artifacts under `output/bringup/core-name/run/`.

## Diagnostic Shape

`diagnostics.json` uses `apfsim.diagnostics.v1`:

```json
{
  "schema": "apfsim.diagnostics.v1",
  "status": "fail",
  "summary": {
    "errors": 1,
    "warnings": 0,
    "infos": 0
  },
  "diagnostics": [
    {
      "schema": "apfsim.diagnostic.v1",
      "code": "VIDEO_WIDTH_MISMATCH",
      "phase": "video",
      "severity": "error",
      "summary": "Simulated active width does not match video metadata.",
      "observed": { "active_width": 289, "active_height": 224 },
      "expected": { "active_width": 288, "active_height": 224 },
      "evidence": [
        { "artifact": "video_shape.json", "json_pointer": "/video_shape/active_width" }
      ],
      "likely_causes": [
        "video_de asserted one cycle too early or too late",
        "upstream HBLK polarity or edge convention is mismatched"
      ],
      "repairs": [
        {
          "kind": "wrapper_patch",
          "confidence": 0.82,
          "description": "Gate or delay video_de so the APF active width matches the scaler metadata before patching video.json."
        }
      ]
    }
  ]
}
```

## Initial Diagnostic Codes

The first implemented taxonomy covers the APF-facing failures that block useful port bring-up:

- `BOOT_TIMEOUT`
- `RESET_NEVER_EXITED`
- `READY_TO_RUN_MISSING`
- `HOST_COMMAND_UNACKED`
- `DATA_SLOT_TABLE_MISSING`
- `DATA_SLOT_ADDRESS_INVALID`
- `DATA_SLOT_LOAD_SHORT`
- `INTERACT_WRITE_MISSING`
- `VIDEO_NO_DE`
- `VIDEO_STATIC_FRAME`
- `VIDEO_WIDTH_MISMATCH`
- `VIDEO_HEIGHT_MISMATCH`
- `VIDEO_PROTOCOL_ERROR`
- `VIDEO_EXTRA_ACTIVE_PIXEL`
- `VIDEO_FRAME_COUNT_MISMATCH`
- `VIDEO_UNSTABLE_DIMENSIONS`
- `AUDIO_NO_MCLK`
- `AUDIO_NO_LRCK`
- `AUDIO_NO_DAC_ACTIVITY`
- `INPUT_NOT_OBSERVED`
- `SAVE_SLOT_NOT_UNLOADED`
- `SAVE_ROUNDTRIP_MISMATCH`
- `SHIM_REQUIRED`
- `VHDL_ENTITY_STUBBED`
- `MEMORY_MODEL_REQUIRED`

The public schema does not restrict the code enum yet. New stable codes can be added without breaking older consumers, but existing code meanings should remain stable.

## Bring-Up Report

`bringup-report.md` is intentionally short:

```md
# Bring-Up Report: core-name

Status: FAIL

Blocking:
- VIDEO_EXTRA_ACTIVE_PIXEL: Simulated active width does not match video metadata.

Non-blocking: none

Recommended next action:
Apply or review: Gate or delay video_de so the APF active width matches the scaler metadata before patching video.json.

Artifacts:
- result.json
- diagnostics.json
- video_shape.json
- bridge.log
- bridge_summary.json
- lifecycle.json

Hardware confidence:
Low until blocking APF contract diagnostics are resolved.
```

## Current Limits

This is a diagnostic and repair-planning slice, not the full repair engine yet.

Current behavior:

- normal runs emit diagnostics and reports;
- `diagnose` can classify existing artifacts;
- `bringup` can run an existing profile or generate a candidate profile first;
- `--repair` writes a reviewable repair plan from diagnostic suggestions.

Not implemented yet:

- real source patch synthesis for wrapper/video/audio/shim repairs;
- automatic rerun after applying a repair;
- hardware trace comparator integration into diagnosis;
- corpus analytics over many cores;
- transactional external memory model selection from diagnostics.

Those are the next layers on top of the stable diagnostic contract.
