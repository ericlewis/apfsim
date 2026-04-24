# Memory Dependencies And External RAM

`apfsim` treats memory as part of the APF contract because many ports boot only after RAM controllers, slot loaders, and save paths behave plausibly.

This layer is intentionally split into two parts:

- Memory dependency intelligence: detect what a core depends on and report model confidence.
- Memory behavior models: provide RTL shims or transactional models that let the Verilated core run.

## Stable Artifact Fields

Generated profiles and discovery reports may include:

```json
{
  "memory": {
    "schema": "apfsim.memory_dependencies.v1",
    "required": true,
    "classes": ["sdram", "bram", "fifo"],
    "external_classes": ["sdram"],
    "models": {
      "sdram": {
        "selected": "ideal_transactional",
        "confidence": "bringup_only",
        "source": "rtl_shims/sdram_sim.sv"
      }
    },
    "risks": [
      {
        "code": "SDRAM_TIMING_NOT_POCKET_LIKE",
        "severity": "warning",
        "message": "SDRAM dependency detected; current generic model is idealized for bring-up."
      }
    ]
  }
}
```

Runtime provenance writes the same information to `source_provenance.json`:

- `memory_dependencies`: detected memory classes, evidence, risks, and default model choices.
- `memory_models`: flattened selected model entries.

`summary.json.row` and `corpus_summary.tsv` include:

- `memory_classes`
- `memory_models`
- `memory_risks`

`memory.available_models` points at catalog entries that can be used by a generated wrapper. This is deliberately separate from `memory.models`: an available model is not selected until the profile/wrapper actually instantiates or includes it.

## ROM/Data-Slot Readback Verification

External RAM corruption is easiest to diagnose immediately after APF loads the asset. For bridge-readable load windows, enable readback on a slot:

```yaml
data_slots:
  - id: 1
    file: game.rom
    address: 0x10000000
    verify_readback: true

expect:
  data:
    require_readback_match: true
```

`apfsim` writes the file through the normal bridge path, then reads the same APF-facing address range back and compares bytes. The stable fields are:

- `result.data.slots[].readback_attempted`
- `result.data.slots[].readback_matches`
- `result.data.slots[].readback_crc32`
- `result.data.slots[].readback_checksum`
- `result.data.slots[].readback_mismatch_count`
- `result.data.slots[].readback_first_mismatch_offset`
- `result.data_load.slots[].readback_crc`
- `summary.json.row.data_readback_mismatches`

Readback failures are reported as `DATA_SLOT_READBACK_MISMATCH`. Common causes are byte-lane swaps, endian packing mistakes, truncated address bits, too-short write strobes, or a readback path mapped to a different RAM window than the write path.

Do not enable this blindly for write-only loader windows. If a real core can load external RAM but cannot expose that memory to bridge reads, leave readback disabled and rely on checksum, write-count, and downstream boot/video evidence.

## Classes

| Class | Meaning | Current Support |
| --- | --- | --- |
| `bram` | Internal FPGA RAM such as `altsyncram`, `dpram`, simple dual-port RAM. | Behavioral shims exist. |
| `fifo` | Internal FIFO such as `dcfifo`. | Behavioral shim exists. |
| `sdram` | SDRAM controller or Sorgelig-style request/ack SDRAM module. | Idealized four-port bring-up model exists. |
| `sram` | External async SRAM pins or controller. | Generic async 16-bit pin model exists; wrapper wiring required. |
| `psram` | PSRAM/HyperRAM/HyperBus style external RAM. | Generic transactional model library exists; controller-specific wiring required. |
| `cram` | Cartridge RAM / CRAM-like external RAM. | Generic transactional model library exists; controller-specific wiring required. |
| `ddr` | DDR/LPDDR-style external RAM. | Detected, model required. |
| `rom` | Internal ROM or ROM-like source references. | Depends on profile/data-slot strategy. |

## Current SDRAM Model

`rtl_shims/sdram_sim.sv` is useful for APF bring-up when a core instantiates a common four-port request/ack `sdram` module. It provides deterministic storage and request completion so the core can boot far enough to validate bridge/data/video/audio behavior.

It is not a Pocket-accurate SDRAM timing model. A pass with this model should be reported as `bringup_only` confidence, not hardware confidence.

## External RAM Direction

The first external RAM model library is `rtl_shims/external_memory_models.sv`:

- `apfsim_async_sram_16_model`: async 16-bit SRAM pin model with `CE/OE/WE/LB/UB`, activity counters, byte-enable checks, and contention detection.
- `apfsim_transactional_ram_model`: request/ack RAM model with configurable latency, byte enables, overrun detection, and read/write counters.
- `apfsim_psram_like_model`: 16-bit latency-configurable transactional wrapper.
- `apfsim_cram_like_model`: 16-bit latency-configurable transactional wrapper.

These are model libraries for generated wrappers. They do not magically match every upstream controller port list.

Future external RAM work should add model families with explicit confidence levels:

- `ideal`: deterministic zero/low-latency transactions for early bring-up.
- `strict_sync`: registered timing and read-after-write behavior to catch combinational assumptions.
- `pocket_sram_like`: async 16-bit SRAM bus with output-enable/write-enable behavior and contention checks.
- `pocket_psram_like`: latency, byte-lane, burst, and wait-state behavior for PSRAM/CRAM-like uses.
- `sdram_basic`: controller-facing transactional SDRAM with init/refresh/activity counters.
- `random_latency`: stress profile with deterministic seed for wait-state/fault injection.

Preferred diagnostics for future models:

- `MEMORY_MODEL_REQUIRED`
- `MEMORY_WIDTH_MISMATCH`
- `MEMORY_BYTE_ENABLE_MISMATCH`
- `MEMORY_UNINITIALIZED_READ`
- `MEMORY_OUT_OF_RANGE`
- `MEMORY_NO_ACTIVITY`
- `MEMORY_STALL_TIMEOUT`
- `SDRAM_INIT_TIMEOUT`
- `SDRAM_REFRESH_MISSING`
- `CRAM_MODEL_REQUIRED`
- `PSRAM_MODEL_REQUIRED`
- `SRAM_MODEL_REQUIRED`
- `SRAM_BUS_CONTENTION`

## Generator Policy

A generator should consume memory fields as confidence data:

- `bram`/`fifo` only: usually acceptable for APF contract smoke if shims are present.
- `sdram` with `ideal_transactional`: useful bring-up signal, but hardware confidence remains limited.
- `sram`, `psram`, `cram`, or `ddr`: classify as requiring an external RAM model unless the profile explicitly supplies one.

Do not silently stub an external RAM path and call the core certified. Mark the model, confidence, and risk in the profile and artifacts.
