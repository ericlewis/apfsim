# Generated Profile Candidates

`apfsim generate-profile` creates a reviewable starting point for a new runtime profile. It does not modify `profiles/` by default.

```sh
bin/apfsim generate-profile \
  --root /path/to/openFPGA-Core \
  --output output/generated-profiles \
  --json
```

Generated bundle:

- `<output>/<name>/<name>.json`: profile manifest candidate.
- `<output>/<name>/filelist.f`: conservative Verilator filelist.
- `<output>/<name>/scenario.yml`: boot/data/video/audio smoke scenario.
- `<output>/<name>/NOTES.md`: review notes and suggested commands.
- `<output>/<name>/candidate.json`: machine-readable generation report.

The generator uses `discover`-style metadata to find APF-facing top RTL, package JSON files, assets, video modes, and likely blockers. It also applies the shim/substitution catalog when a known public pattern is detected, for example a reusable vendor RAM or PLL substitution.

When a Quartus `.qsf` is present, the generated filelist is QSF-aware:

- Verilog/SystemVerilog sources come from `set_global_assignment -name VERILOG_FILE` and `SYSTEMVERILOG_FILE` in QSF order.
- `TOP_LEVEL_ENTITY` becomes the profile `top`. This matters for public JTCORES Pocket exports, which commonly use `pocket_top` instead of `core_top`.
- `SEARCH_PATH` and `USER_LIBRARIES` become `+incdir+` entries.
- `VERILOG_MACRO`, `SYSTEMVERILOG_MACRO`, `VERILOG_DEFINE`, and `SYSTEMVERILOG_DEFINE` become `+define+` entries.
- QIP files are recursively expanded when they contain Verilog/SystemVerilog assignments, including Quartus `[file join $::quartus(qip_path) ...]` paths.
- VHDL files and non-RTL QIP/IP files are recorded in `candidate.json` but are not passed directly to Verilator.
- Known APF shell/vendor IP files such as `apf_top`, `mf_pllbase`, `altsyncram`, `dcfifo`, and DDIO wrappers are filtered and replaced by simulator shims where available.
- Public JTFRAME Pocket exports with QSF top `pocket_top` are wrapped as a logical `core_top` candidate when `jtframe_pocket` is present. The generated wrapper bypasses the physical SPI/PAD/DDIO shell and presents apfsim's APF bridge, controller, video, and audio contract directly.
- Generated JTFRAME logical wrappers instantiate the public SDRAM pin model when SDRAM pins are present, drive that model from JTFRAME's Verilator-only SDRAM write-data sideband during write bursts, feed accepted JTFRAME programming writes into ROM coverage, expose `apfsim_sdram_*` activity/corruption counters, and opt the profile into `memory_activity.top_port_classes: ["sdram"]`.
- Shim catalog entries may add generated replacement files or static filelist entries such as simulator-only VHDL/RAM compatibility stubs.
- Generated candidates auto-select public catalog entries when inventory flags, memory classes, or source regexes match. Treat this as a suggestion: review `candidate.json.selected_shims`, `candidate.json.selected_shim_details`, `profile.shim_catalog`, and `NOTES.md` before committing the profile.
- If no QSF is found, the generator falls back to filesystem source discovery under common Pocket HDL roots.

`candidate.json.qsf` is the machine-readable provenance report. It includes the QSF path, QSF top-level entity, QSF/QIP-expanded source counts, emitted defines, include paths, VHDL/QIP references, missing sources, and filtered/replaced source entries.

When VHDL sources are detected, generated profiles and `candidate.json.risks[]` also carry an entry with code `VHDL_ENTITY_STUBBED`. This is deliberate: Verilator does not compile VHDL in this flow, so a profile needs translated RTL, a faithful SystemVerilog shim, or an explicitly marked mixed-language strategy before gameplay behavior should be trusted.

Generated candidates also include memory dependency intelligence when HDL references known RAM classes. The profile `memory` object and `candidate.json.memory` use schema `apfsim.memory_dependencies.v1` and report classes such as `sdram`, `sram`, `psram`, `cram`, `bram`, and `fifo`, selected model confidence, evidence, risks, and optional `rom_regions[]` for exact ROM/source-file mapping. See [Memory Dependencies And External RAM](memory.md).

Data slot generation policy:

- Slots with a normal 32-bit `address` become host-loaded data slots.
- Nonvolatile slots use the mock save seed unless a more specific scenario is supplied.
- Setup-only or instance JSON slots may omit `address`. If the slot is JSON-like or has APF parameter bit 4 set, the generated scenario emits it as `setup_only: true` and `deferload: true`. The file size can still populate the APF data-slot table, but no bridge write is generated to address zero.
- A non-JSON slot without an address is still considered untranslatable and must be fixed in metadata or scenario overrides.

Review checklist:

- Confirm the selected ROM asset is the intended one. Filename matching is best-effort when package `data.json` names do not exactly match local asset filenames.
- Confirm `filelist.f` excludes vendor generated IP and includes any required generated shim files.
- For generated JTFRAME wrappers, confirm `video_rgb_clock` is derived from `video_pxl_cen` cadence rather than the faster physical PLL clock. If the wrapper samples every PLL cycle, `video_shape.active_width` will be an integer multiple of the true width.
- Confirm memory dependencies are modeled honestly. `sdram` may use either the idealized request/ack model or the generated public SDRAM pin model. For generated JTFRAME wrappers, `sdram_rom_preload_count` should be nonzero after a ROM load, `sdram_rom_mismatch_count` and `sdram_rom_unwritten_read_count` must remain zero, and `sdram_rom_coverage_gap_count` should be treated as evidence of an incomplete or wrong ROM payload unless explicitly expected. When a profile supplies `memory.rom_regions[]`, ROM mismatch diagnostics should report `source.rule = profile_rom_region` and exact slot/file/source offset. A clean SDRAM model pass proves the wrapper's observed pin traffic matches the accepted JTFRAME programming sideband; it is still not a cycle-accurate Pocket SDRAM model. `sram`, `psram`, and `cram` may select public model libraries and a generated scaffold. Hardware confidence still requires live wrapper wiring, `memory_activity.observed`, and zero memory error counters.
- Confirm the QSF-derived order matches the intended Quartus compile order, especially for packages, macro-controlled source variants, and framework files.
- Confirm `scenario.yml` uses the intended data-slot IDs, addresses, save files, and expected video dimensions.
- Run preflight before building:

```sh
bin/apfsim build --profile output/generated-profiles/<name>/<name>.json --preflight-only
```

Then build/run explicitly:

```sh
bin/apfsim build --profile output/generated-profiles/<name>/<name>.json
bin/apfsim run --profile output/generated-profiles/<name>/<name>.json --artifacts output/<name>-generated
```

For bring-up with package validation, pass the package/check-out root explicitly. This also binds `{root}` placeholders for generated profile paths:

```sh
bin/apfsim bringup \
  --profile output/generated-profiles/<name>/<name>.json \
  --root /path/to/openFPGA-Core-or-package \
  --expected-platform-id arcade_platform \
  --out output/bringup/<name>
```

`expected_artifacts` is checked immediately after the simulator run and before bring-up postprocessing. List runtime artifacts only, such as `result.json`, `video_shape.json`, `lifecycle.json`, `bridge.log`, frame JSON/PPM files, audio files, and save dumps. Do not list postprocess artifacts such as `diagnostics.json`, `bringup-report.md`, `repair-plan.json`, `summary.json`, `summary.tsv`, or `package_check.json`; those are produced by `bringup` after runtime artifact validation.

Only copy the candidate into `profiles/` after it builds, boots, and produces artifacts worth keeping as a regression profile.
