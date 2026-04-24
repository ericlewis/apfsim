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
CORE_TEMPLATE_ROOT ?= $(TEMPLATE_ROOT)
TEMPLATE_FILELIST ?= examples/core_template/filelist.f
TEMPLATE_SCENARIO ?= examples/core_template/template_boot.yml
TEMPLATE_MDIR ?= build/template_obj
TEMPLATE_DUMP_ROOT ?= build/template_run
BASICASSETS_ROOT ?= $(CORE_EXAMPLE_BASICASSETS_ROOT)
BASICASSETS_FILELIST ?= examples/basicassets/filelist.f
BASICASSETS_SCENARIO ?= examples/basicassets/basicassets_boot.yml
BASICASSETS_MDIR ?= build/basicassets_obj
BASICASSETS_DUMP_ROOT ?= build/basicassets_run
BASICASSETS_WRITE_IDLE ?= 64

CPP := cpp/main.cpp
COMMON_FLAGS := --cc --exe $(CPP) --top-module $(TOP) --Mdir $(MDIR) -f $(FILELIST) -Irtl_shims -Wno-fatal --assert -CFLAGS "-std=c++20 -O2 -Icpp"

.PHONY: lint build build-waves run-mock run-mock-waves build-template run-template build-basicassets run-basicassets doctor profile-build profile-run profile-play test test-matrix clean help check-template-root check-basicassets-root

help:
	@echo "Targets: lint build build-waves run-mock run-mock-waves build-template run-template build-basicassets run-basicassets doctor profile-build profile-run profile-play test test-matrix clean"
	@echo "Override TOP=core_top FILELIST=build/verilator_filelist.f SCENARIO=scenarios/boot_rom.yml"
	@echo "Profile flow: make doctor PROFILE=mock; make profile-run PROFILE=mock; make test-matrix MATRIX=local-fast"
	@echo "External legacy targets require CORE_TEMPLATE_ROOT or CORE_EXAMPLE_BASICASSETS_ROOT."

check-template-root:
	@test -n "$(CORE_TEMPLATE_ROOT)" || (echo "Set CORE_TEMPLATE_ROOT=/path/to/core-template" >&2; exit 2)

check-basicassets-root:
	@test -n "$(BASICASSETS_ROOT)" || (echo "Set CORE_EXAMPLE_BASICASSETS_ROOT=/path/to/core-example-basicassets" >&2; exit 2)

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

build-template: check-template-root
	CORE_TEMPLATE_ROOT="$(CORE_TEMPLATE_ROOT)" $(APFSIM) build --profile core_template

run-template: build-template
	CORE_TEMPLATE_ROOT="$(CORE_TEMPLATE_ROOT)" $(APFSIM) run --profile core_template --no-build --frames $(FRAMES) --artifacts $(TEMPLATE_DUMP_ROOT)

build-basicassets: check-basicassets-root
	CORE_EXAMPLE_BASICASSETS_ROOT="$(BASICASSETS_ROOT)" $(APFSIM) build --profile basicassets

run-basicassets: build-basicassets
	CORE_EXAMPLE_BASICASSETS_ROOT="$(BASICASSETS_ROOT)" $(APFSIM) run --profile basicassets --no-build --frames $(FRAMES) --write-idle-cycles $(BASICASSETS_WRITE_IDLE) --artifacts $(BASICASSETS_DUMP_ROOT)

doctor:
	$(APFSIM) doctor

profile-build:
	$(APFSIM) build --profile $(PROFILE)

profile-run:
	$(APFSIM) run --profile $(PROFILE) --frames $(FRAMES)

profile-play:
	$(APFSIM) play --profile $(PROFILE)

test:
	$(PYTHON) -m pytest -q tests

test-matrix:
	$(APFSIM) test --matrix $(MATRIX)

clean:
	rm -rf build frames audio dump.fst obj_dir
