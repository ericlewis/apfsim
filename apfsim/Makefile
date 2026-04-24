SHELL := /bin/sh

TOP ?= core_top
FILELIST ?= examples/mock/filelist.f
MDIR ?= build/obj
VERILATOR ?= verilator
FRAMES ?= 5
SCENARIO ?= scenarios/boot_rom.yml
DUMP_ROOT ?= build/run
PACMAN_ROOT ?= /Users/ericlewis/Developer/openfpga-arcade-cores/our-pocket-cores/openFPGA-PacMan
PACMAN_FILELIST ?= examples/pacman/filelist.f
PACMAN_SCENARIO ?= examples/pacman/pacman_boot.yml
PACMAN_MDIR ?= build/pacman_obj
PACMAN_DUMP_ROOT ?= build/pacman_run

CPP := cpp/main.cpp
COMMON_FLAGS := --cc --exe $(CPP) --top-module $(TOP) --Mdir $(MDIR) -f $(FILELIST) -Irtl_shims -Wno-fatal --assert -CFLAGS "-std=c++20 -O2 -Icpp"

.PHONY: lint build build-waves run-mock run-mock-waves build-pacman run-pacman test clean help

help:
	@echo "Targets: lint build build-waves run-mock run-mock-waves build-pacman run-pacman test clean"
	@echo "Override TOP=core_top FILELIST=build/verilator_filelist.f SCENARIO=scenarios/boot_rom.yml"

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
	$(MDIR)/V$(TOP) --scenario $(SCENARIO) --frames $(FRAMES) --dump-frames $(DUMP_ROOT)/frames --dump-audio $(DUMP_ROOT)/audio/out.wav --dump-saves $(DUMP_ROOT)/saves

run-mock-waves: build-waves
	rm -rf $(DUMP_ROOT)
	mkdir -p $(DUMP_ROOT)
	APFSIM_WAVES=1 APFSIM_WAVE_PATH=$(DUMP_ROOT)/dump.fst $(MDIR)/V$(TOP) --scenario $(SCENARIO) --frames $(FRAMES) --dump-frames $(DUMP_ROOT)/frames --dump-audio $(DUMP_ROOT)/audio/out.wav --dump-saves $(DUMP_ROOT)/saves

build-pacman:
	mkdir -p $(PACMAN_MDIR)
	$(VERILATOR) --cc --exe $(CPP) --top-module $(TOP) --Mdir $(PACMAN_MDIR) -f $(PACMAN_FILELIST) -Irtl_shims -Wno-fatal --assert -CFLAGS "-std=c++20 -O2 -Icpp" --build

run-pacman: build-pacman
	rm -rf $(PACMAN_DUMP_ROOT)
	mkdir -p $(PACMAN_DUMP_ROOT)
	$(PACMAN_MDIR)/V$(TOP) --scenario $(PACMAN_SCENARIO) --video $(PACMAN_ROOT)/dist/Cores/ericlewis.PacMan/video.json --interact $(PACMAN_ROOT)/dist/Cores/ericlewis.PacMan/interact.json --frames $(FRAMES) --dump-frames $(PACMAN_DUMP_ROOT)/frames --dump-audio $(PACMAN_DUMP_ROOT)/audio/out.wav

test:
	python3 -m pytest -q tests

clean:
	rm -rf build frames audio dump.fst obj_dir
