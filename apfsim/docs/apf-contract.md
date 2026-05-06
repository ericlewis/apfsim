# APF Contract Coverage

This document is the working APF contract used by `apfsim` regression gates. It is intentionally concise: public Analogue documentation remains the source of truth, while this file records what the simulator enforces.

## Runtime Harness

`apfsim run` drives the APF-facing `core_top` environment:

- BRIDGE bus at `0xF8000000` for host commands, target commands, data-slot table, settings, and implementation-specific load addresses.
- PAD inputs for up to 4 controllers through `cont*_key`, `cont*_joy`, and `cont*_trig`.
- VIDEO capture from `video_rgb_clock`, `video_rgb`, `video_de`, `video_hs`, `video_vs`, and `video_skip`.
- AUDIO I2S capture from `audio_mclk`, `audio_lrck`, and `audio_dac`.
- Data-slot loading, nonvolatile save unload, interact persistent writes, and controller scenario events.

Host command coverage:

- `0x0000` Request Status.
- `0x0010` Reset Enter.
- `0x0011` Reset Exit.
- `0x0080` Data slot request read for save unload paths.
- `0x0082` Data slot request write for boot loads.
- `0x008A` Data slot update for scenario-driven runtime reload/deferred-slot updates; the driver can update the slot-size table, swap the in-memory slot image, and send the host command.
- `0x008F` Data slot access all complete.
- `0x0090` Real-time clock data.
- `0x00A0` Savestate Start/Query save flow, including support query, start request, busy polling, response-pointer reads, and blob copy-out.
- `0x00A4` Savestate Load/Query is named/log-analyzed; load blob transfer is not implemented yet.
- `0x00B0`, `0x00B1`, `0x00B2`, and `0x00B8` OS notify commands are scenario-injectable and traceable.

Target command coverage:

- `0x0140` Ready to Run.
- `0x0152` Debug Event Log.
- `0x0180` and `0x0181` Data slot read, including 48-bit offsets.
- `0x0184` and `0x0185` Data slot write, including 48-bit offsets.
- `0x0188` Data slot flush.
- `0x0190` Get filename of data slot.
- `0x0192` Open new file into data slot.

## Runtime Video Shape

Every run emits `result.json.video_shape` and `video_shape.json`. The stable contract includes:

- Active width and height after startup frames.
- Min/max total pixel clocks per line.
- HS-to-DE and DE-to-HS gap minima.
- VS-to-first-active-line distance.
- DE, sync pulse-width, and SKIP protocol error counters.
- Dimension stability and protocol validity booleans.

Use `bin/apfsim compare-video-json` to compare simulated APF output against generated `video.json`, and `bin/apfsim apply-video-shape` to patch generated metadata when simulation discovers a mismatch.

## Input-Driven Video Activity

Scenarios may require video to change after scripted input. This is useful for cores where attract mode is static but gameplay should visibly change after coin/start.

```yaml
inputs:
  - frame: 2
    player: 1
    button: Select
    hold_frames: 1
  - frame: 3
    player: 1
    button: Start
    hold_frames: 1
phases:
  - name: gameplay
    after_input: true
    duration_frames: 3
    require_changed: true
expect:
  video:
    require_change_after_input: true
    input_response_window_frames: 3
```

Runs always emit `result.input_video_response`, `result.input_video_effect_seen`, and `result.video_activity` when input/video data exists. A required post-input gate failure is classified as `VIDEO_NO_POST_INPUT_CHANGE` instead of a generic static-frame warning.

## Input-Driven Audio Activity

Scenarios may also require decoded I2S audio activity after scripted input. This catches cores that clock audio during attract but never produce gameplay audio after coin/start.

```yaml
expect:
  audio:
    require_activity_after_input: true
    input_response_window_frames: 3
    min_samples_after_input: 1
    min_nonzero_samples_after_input: 1
    min_peak_after_input: 1
```

Runs emit `result.input_audio_response`, `result.input_audio_effect_seen`, and `result.audio_activity`. A required post-input audio gate failure is classified as `AUDIO_NO_POST_INPUT_ACTIVITY`.

## Runtime Lifecycle Injection

Scenarios may include `host_commands:` entries to reproduce Pocket runtime behavior observed in hardware logs. Supported command names include numeric command words plus readable names such as `os_notify_menu_state`, `os_notify_cartridge_adapter`, `os_notify_docked_state`, `os_notify_display_mode`, `data_slot_update`, and `savestate_save`.

Example:

```yaml
host_commands:
  - frame: 1
    command: os_notify_menu_state
    p0: 1
  - frame: 2
    command: data_slot_update
    slot: 1
    file: examples/assets/mock.rom
    size: 1024
    update_slot_table: true
  - frame: 3
    command: savestate_save
    output: mock_state.sta
```

`data_slot_update` follows the log-observed order: update the data-slot ID/size table, then send host command `0x008A` with slot ID and size. `savestate_save` follows the log-observed `0x00A0` sequence: query support, request blob creation, poll while busy, read response words, then copy the blob from the returned BRIDGE address.

## Known Gaps

- Savestate load/replay for `0x00A4` is not implemented.
- Runtime data reload currently covers `0x008A`; full user-reload semantics for parameters bits 6, 7, and 8 still need reset/restart/bitstream-reload orchestration.
- Package validation does not prove that every `interact.json` bridge address has matching HDL read/write decode; runtime profiles should add readback checks for that.
- Package validation allows data slots with no `address` field. Setup-only JSON/instance slots may not have a bridge load address. Runtime scenarios still need an address when `apfsim` is expected to write a payload into core memory.
- Physical cartridge, link port, IR, PSRAM, SRAM, and SDRAM timing are outside the generic APF gate unless a profile provides explicit models/checks.
