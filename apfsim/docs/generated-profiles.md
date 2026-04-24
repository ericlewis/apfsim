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

The generator uses `discover`-style metadata to find `core_top`, package JSON files, assets, video modes, and likely blockers. It also applies the shim/substitution catalog when a known public pattern is detected, for example a reusable vendor RAM or PLL substitution.

When a Quartus `.qsf` is present, the generated filelist is QSF-aware:

- Verilog/SystemVerilog sources come from `set_global_assignment -name VERILOG_FILE` and `SYSTEMVERILOG_FILE` in QSF order.
- `SEARCH_PATH` and `USER_LIBRARIES` become `+incdir+` entries.
- `VERILOG_MACRO`, `SYSTEMVERILOG_MACRO`, `VERILOG_DEFINE`, and `SYSTEMVERILOG_DEFINE` become `+define+` entries.
- QIP files are recursively expanded when they contain Verilog/SystemVerilog assignments, including Quartus `[file join $::quartus(qip_path) ...]` paths.
- VHDL files and non-RTL QIP/IP files are recorded in `candidate.json` but are not passed directly to Verilator.
- Known APF shell/vendor IP files such as `apf_top`, `mf_pllbase`, `altsyncram`, `dcfifo`, and DDIO wrappers are filtered and replaced by simulator shims where available.
- Shim catalog entries may add generated replacement files or static filelist entries such as simulator-only VHDL/RAM compatibility stubs.
- If no QSF is found, the generator falls back to filesystem source discovery under common Pocket HDL roots.

`candidate.json.qsf` is the machine-readable provenance report. It includes the QSF path, QSF/QIP-expanded source counts, emitted defines, include paths, VHDL/QIP references, missing sources, and filtered/replaced source entries.

Generated candidates also include memory dependency intelligence when HDL references known RAM classes. The profile `memory` object and `candidate.json.memory` use schema `apfsim.memory_dependencies.v1` and report classes such as `sdram`, `sram`, `psram`, `cram`, `bram`, and `fifo`, selected model confidence, evidence, and risks. See [Memory Dependencies And External RAM](memory.md).

Review checklist:

- Confirm the selected ROM asset is the intended one. Filename matching is best-effort when package `data.json` names do not exactly match local asset filenames.
- Confirm `filelist.f` excludes vendor generated IP and includes any required generated shim files.
- Confirm memory dependencies are modeled honestly. `sdram` currently uses an idealized bring-up model; `sram`, `psram`, `cram`, and `ddr` require explicit external RAM model work for hardware-confidence simulation.
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
