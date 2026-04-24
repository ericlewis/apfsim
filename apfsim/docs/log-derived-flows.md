# Log-Derived APF Runtime Flows

This captures lifecycle details observed in local Pocket debug logs and reflected in `apfsim` scenarios. The goal is not to replay proprietary firmware internals; it is to reproduce APF-visible command order, parameters, and bridge-side side effects that real cores see.

## Runtime Data Slot Update (`0x008A`)

Observed in MacPlus and PC Engine CD logs.

Flow:

1. Pocket enters menu state with `0x00B0` when the user opens the OS menu.
2. User selects a reloadable data slot.
3. Pocket records the selected path and file size.
4. Pocket updates the data-slot ID/size table at `0xF8002000 + slot_index * 8`.
5. Pocket sends host command `0x008A Data slot update`.
6. Parameters are slot ID and expected size.
7. Core returns result `0` when accepted.
8. Deferred-load cores then issue target data-slot reads against the updated slot image.

`apfsim` support:

```yaml
host_commands:
  - frame: 2
    command: data_slot_update
    slot: 1
    file: examples/assets/mock.rom
    size: 1024
    update_slot_table: true
```

The simulator updates the slot image, writes the slot table entry, sends `0x008A`, and records the event in `result.json.host_commands` and `bridge_summary.json`.

## Savestate Save (`0x00A0`)

Observed in Pocket handheld and Arduboy-style logs.

Flow:

1. Query support with host command `0x00A0` and `p0=0`.
2. Read response words from the core response pointer. Response word 0 bit 0 indicates support.
3. Request state creation with `0x00A0` and `p0=1`.
4. Poll `0x00A0` with `p0=0` while result is busy.
5. When result is done, read response address and response size.
6. Copy the savestate blob from that bridge address.

`apfsim` support:

```yaml
host_commands:
  - frame: 3
    command: savestate_save
    output: mock_state.sta
```

The simulator writes the copied blob to `savestates/mock_state.sta` by default under the artifact directory and records query/start/final results plus address, size, checksum, and poll count in `result.json.savestate.reports`.

## OS Notify Commands

Observed broadly across the supplied logs.

Supported scenario injection:

```yaml
host_commands:
  - frame: 0
    command: os_notify_cartridge_adapter
    p0: 0x00008000
  - frame: 1
    command: os_notify_menu_state
    p0: 1
  - frame: 1
    command: os_notify_docked_state
    p0: 0
  - frame: 2
    command: os_notify_display_mode
    p0: 0x00001000
```

Supported commands:

- `0x00B0 OS Notify: Menu State`
- `0x00B1 OS Notify: Cartridge Adapter`
- `0x00B2 OS Notify: Docked State`
- `0x00B8 OS Notify: Display Mode`

## Still Needed

- `0x00A4 Savestate Load/Query` blob injection. The current log set did not include a clean real `00A4` load sequence.
- Full runtime reload semantics for data-slot parameter bits 6, 7, and 8, where Pocket may reset, restart, or reload the bitstream around the slot operation.
