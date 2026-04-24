# Shim And Substitution Catalog

The shim catalog is `catalogs/shims.json`. It stores reusable simulation substitutions that were previously buried in one-off profiles.

A catalog entry can provide:

- `kind`: `compile_shim`, `behavioral_model`, or `behavioral_model_library`.
- `confidence`: how much trust to assign to a passing run that uses this entry.
- `modules`: module names supplied or replaced by the entry.
- `memory_classes`: memory dependency classes affected by the entry.
- `detect`: conservative auto-selection rules used by generated-profile candidates.
- `diagnostic_codes`: likely diagnostics related to the entry.
- `source_candidates`: external source paths to search for reusable public simulation sources.
- `required_paths`: paths that must exist before the profile can build.
- `fallback_filelist_entries` and `fallback_required_paths`: explicit compile-only fallback files used when no `source_candidates` exist.
- `generated_files`: `copy_replace` or other profile `generated_files` blocks.
- `verilator_flags`: optional flags to append when the entry is selected.
- `expected_artifacts`: optional artifacts to require after a run.

Profiles opt in explicitly:

```json
{
  "shim_catalog": [
    "public_vendor_ram"
  ]
}
```

Inspect catalog contents:

```sh
bin/apfsim shim-catalog --json
bin/apfsim shim-catalog --profile mock --json
```

Current policy: catalog entries are conservative and explicit. Auto-generation may suggest entries, but generated bundles remain review artifacts until a human confirms the filelist and substitutions.

Current public entries cover:

- deterministic PLL wrappers: `intel_pllbase_sim`
- Intel DDIO pin primitives: `intel_ddio_shims`
- internal BRAM/RAM: `intel_bram_shims`
- FIFO primitives: `intel_fifo_shims`
- common LPM arithmetic: `intel_lpm_arithmetic`
- JTFRAME T80s public translation/fallback strategy: `jtframe_t80s_public_translation`
- idealized request/ack SDRAM: `sdram_ideal_transactional`
- async external SRAM model library: `external_sram_pin_model`
- PSRAM/CRAM-like transactional model library: `psram_cram_transactional_models`

Model-library entries do not automatically prove hardware behavior. They make wrapper-generated memory interactions observable and must be reported in `source_provenance.json`.

JTFRAME policy:

- `jtframe_t80s_public_translation` first searches for `modules/jtframe/hdl/cpu/t80/T80s.v` under the core root, parent roots, or `$JTCORES_ROOT`.
- If the translated public RTL exists, it is added to the generated filelist and the detail record has `fallback_used: false`.
- If it does not exist, `rtl_shims/jtframe_t80s_stub.sv` is used only as an explicit compile-only fallback. Treat any passing run with that fallback as shell/profile validation, not gameplay validation.
- QSF top `pocket_top` plus public `jtframe_pocket` enables generated logical-wrapper mode. The wrapper replaces the physical Pocket shell, adapts the bridge directly, emits one-cycle APF HS/VS pulses, and exposes video at `video_pxl_cen` cadence so video-shape discovery sees the real active width.
