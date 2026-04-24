# pocket_sim

This workspace contains `apfsim`, a deterministic Verilator-based APF contract simulator for testing Analogue Pocket `core_top` integration locally.

Start with:

```sh
make doctor
make profile-run PROFILE=mock FRAMES=2
make test
```

See [`apfsim/README.md`](apfsim/README.md) for build and real-core usage.
