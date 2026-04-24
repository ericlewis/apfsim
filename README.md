# pocket_sim

This workspace contains `apfsim`, a Verilator APF/Pocket host emulator scaffold for running Analogue Pocket `core_top` modules locally.

Start with:

```sh
make doctor
make profile-run PROFILE=mock FRAMES=2
make test
```

See [`apfsim/README.md`](apfsim/README.md) for build and real-core usage.
