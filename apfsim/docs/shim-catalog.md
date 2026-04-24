# Shim And Substitution Catalog

The shim catalog is `catalogs/shims.json`. It stores reusable simulation substitutions that were previously buried in one-off profiles.

A catalog entry can provide:

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
