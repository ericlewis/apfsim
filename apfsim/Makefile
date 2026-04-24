SHELL := /bin/sh

TOP ?= core_top
FILELIST ?= examples/mock/filelist.f
MDIR ?= build/obj
VERILATOR ?= verilator
PYTHON ?= $(if $(wildcard ../.venv/bin/python),../.venv/bin/python,python3)
APFSIM ?= bin/apfsim
FRAMES ?= 5
PROFILE ?= mock
MATRIX ?= local-fast
SCENARIO ?= scenarios/boot_rom.yml
DUMP_ROOT ?= build/run
PACMAN_ROOT ?= /Users/ericlewis/Developer/openfpga-arcade-cores/our-pocket-cores/openFPGA-PacMan
PACMAN_FILELIST ?= examples/pacman/filelist.f
PACMAN_SCENARIO ?= examples/pacman/pacman_boot.yml
PACMAN_MDIR ?= build/pacman_obj
PACMAN_DUMP_ROOT ?= build/pacman_run
TEMPLATE_ROOT ?= /Users/ericlewis/Developer/openfpga-arcade-cores/ref-pocket-cores/agg23/template
TEMPLATE_FILELIST ?= examples/core_template/filelist.f
TEMPLATE_SCENARIO ?= examples/core_template/template_boot.yml
TEMPLATE_MDIR ?= build/template_obj
TEMPLATE_DUMP_ROOT ?= build/template_run
BASICASSETS_ROOT ?= /Users/ericlewis/Developer/core-example-basicassets
BASICASSETS_FILELIST ?= examples/basicassets/filelist.f
BASICASSETS_SCENARIO ?= examples/basicassets/basicassets_boot.yml
BASICASSETS_MDIR ?= build/basicassets_obj
BASICASSETS_DUMP_ROOT ?= build/basicassets_run
BASICASSETS_WRITE_IDLE ?= 64

CPP := cpp/main.cpp
COMMON_FLAGS := --cc --exe $(CPP) --top-module $(TOP) --Mdir $(MDIR) -f $(FILELIST) -Irtl_shims -Wno-fatal --assert -CFLAGS "-std=c++20 -O2 -Icpp"

.PHONY: lint build build-waves run-mock run-mock-waves build-pacman run-pacman build-template run-template build-basicassets run-basicassets doctor profile-build profile-run test test-matrix clean help

help:
	@echo "Targets: lint build build-waves run-mock run-mock-waves build-pacman run-pacman build-template run-template build-basicassets run-basicassets doctor profile-build profile-run test test-matrix clean"
	@echo "Override TOP=core_top FILELIST=build/verilator_filelist.f SCENARIO=scenarios/boot_rom.yml"
	@echo "Profile flow: make doctor PROFILE=mock; make profile-run PROFILE=mock; make test-matrix MATRIX=local-fast"

lint:
	$(VERILATOR) --lint-only --top-module $(TOP) -f $(FILELIST) -Irtl_shims -Wno-fatal --assert

build:
	mkdir -p $(MDIR)
	$(VERILATOR) $(COMMON_FLAGS) --build

build-waves:
	mkdir -p $(MDIR)
	$(VERILATOR) $(COMMON_FLAGS) --trace --trace-fst --trace-structs --build

run-mock: build
	rm -rf $(DUMP_ROOT)
	mkdir -p $(DUMP_ROOT)
	$(MDIR)/V$(TOP) --scenario $(SCENARIO) --frames $(FRAMES) --dump-frames $(DUMP_ROOT)/frames --dump-audio $(DUMP_ROOT)/audio/out.wav --audio-stats $(DUMP_ROOT)/audio/stats.json --dump-saves $(DUMP_ROOT)/saves --result-json $(DUMP_ROOT)/result.json --bridge-log $(DUMP_ROOT)/bridge.log

run-mock-waves: build-waves
	rm -rf $(DUMP_ROOT)
	mkdir -p $(DUMP_ROOT)
	APFSIM_WAVES=1 APFSIM_WAVE_PATH=$(DUMP_ROOT)/dump.fst $(MDIR)/V$(TOP) --scenario $(SCENARIO) --frames $(FRAMES) --dump-frames $(DUMP_ROOT)/frames --dump-audio $(DUMP_ROOT)/audio/out.wav --audio-stats $(DUMP_ROOT)/audio/stats.json --dump-saves $(DUMP_ROOT)/saves --result-json $(DUMP_ROOT)/result.json --bridge-log $(DUMP_ROOT)/bridge.log

build-pacman:
	mkdir -p $(PACMAN_MDIR)
	$(VERILATOR) --cc --exe $(CPP) --top-module $(TOP) --Mdir $(PACMAN_MDIR) -f $(PACMAN_FILELIST) -Irtl_shims -Wno-fatal --assert -CFLAGS "-std=c++20 -O2 -Icpp" --build

run-pacman: build-pacman
	rm -rf $(PACMAN_DUMP_ROOT)
	mkdir -p $(PACMAN_DUMP_ROOT)
	$(PACMAN_MDIR)/V$(TOP) --scenario $(PACMAN_SCENARIO) --video $(PACMAN_ROOT)/dist/Cores/ericlewis.PacMan/video.json --interact $(PACMAN_ROOT)/dist/Cores/ericlewis.PacMan/interact.json --frames $(FRAMES) --dump-frames $(PACMAN_DUMP_ROOT)/frames --dump-audio $(PACMAN_DUMP_ROOT)/audio/out.wav --audio-stats $(PACMAN_DUMP_ROOT)/audio/stats.json --result-json $(PACMAN_DUMP_ROOT)/result.json --bridge-log $(PACMAN_DUMP_ROOT)/bridge.log

build-template:
	mkdir -p $(TEMPLATE_MDIR)
	$(VERILATOR) --cc --exe $(CPP) --top-module $(TOP) --Mdir $(TEMPLATE_MDIR) -f $(TEMPLATE_FILELIST) -Irtl_shims -Wno-fatal --assert -CFLAGS "-std=c++20 -O2 -Icpp" --build

run-template: build-template
	rm -rf $(TEMPLATE_DUMP_ROOT)
	mkdir -p $(TEMPLATE_DUMP_ROOT)
	$(TEMPLATE_MDIR)/V$(TOP) --scenario $(TEMPLATE_SCENARIO) --data $(TEMPLATE_ROOT)/dist/Cores/Developer.CoreTemplate/data.json --video $(TEMPLATE_ROOT)/dist/Cores/Developer.CoreTemplate/video.json --interact $(TEMPLATE_ROOT)/dist/Cores/Developer.CoreTemplate/interact.json --frames $(FRAMES) --dump-frames $(TEMPLATE_DUMP_ROOT)/frames --dump-audio $(TEMPLATE_DUMP_ROOT)/audio/out.wav --audio-stats $(TEMPLATE_DUMP_ROOT)/audio/stats.json --result-json $(TEMPLATE_DUMP_ROOT)/result.json --bridge-log $(TEMPLATE_DUMP_ROOT)/bridge.log

build-basicassets:
	mkdir -p $(BASICASSETS_MDIR)
	mkdir -p build/generated
	sed 's/^module core_top/module basicassets_core_top_impl/' $(BASICASSETS_ROOT)/src/fpga/core/core_top.v > build/generated/basicassets_core_top_impl.v
	$(VERILATOR) --cc --exe $(CPP) --top-module $(TOP) --Mdir $(BASICASSETS_MDIR) -f $(BASICASSETS_FILELIST) -Irtl_shims -Wno-fatal --assert -CFLAGS "-std=c++20 -O2 -Icpp" --build

run-basicassets: build-basicassets
	rm -rf $(BASICASSETS_DUMP_ROOT)
	mkdir -p $(BASICASSETS_DUMP_ROOT)
	$(BASICASSETS_MDIR)/V$(TOP) --scenario $(BASICASSETS_SCENARIO) --data $(BASICASSETS_ROOT)/data.json --video $(BASICASSETS_ROOT)/video.json --interact $(BASICASSETS_ROOT)/interact.json --frames $(FRAMES) --write-idle-cycles $(BASICASSETS_WRITE_IDLE) --dump-frames $(BASICASSETS_DUMP_ROOT)/frames --dump-audio $(BASICASSETS_DUMP_ROOT)/audio/out.wav --audio-stats $(BASICASSETS_DUMP_ROOT)/audio/stats.json --result-json $(BASICASSETS_DUMP_ROOT)/result.json --bridge-log $(BASICASSETS_DUMP_ROOT)/bridge.log

doctor:
	$(APFSIM) doctor

profile-build:
	$(APFSIM) build --profile $(PROFILE)

profile-run:
	$(APFSIM) run --profile $(PROFILE) --frames $(FRAMES)

test:
	$(PYTHON) -m pytest -q tests

test-matrix:
	$(APFSIM) test --matrix $(MATRIX)

clean:
	rm -rf build frames audio dump.fst obj_dir
