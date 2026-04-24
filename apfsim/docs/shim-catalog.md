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
- internal BRAM/RAM: `intel_bram_shims`
- FIFO primitives: `intel_fifo_shims`
- common LPM arithmetic: `intel_lpm_arithmetic`
- idealized request/ack SDRAM: `sdram_ideal_transactional`
- async external SRAM model library: `external_sram_pin_model`
- PSRAM/CRAM-like transactional model library: `psram_cram_transactional_models`

Model-library entries do not automatically prove hardware behavior. They make wrapper-generated memory interactions observable and must be reported in `source_provenance.json`.
