#!/usr/bin/env python3
"""Memory dependency classification for APF/core bring-up profiles."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "apfsim.memory_dependencies.v1"
EXTERNAL_CLASSES = ["sdram", "ddr", "psram", "cram", "sram"]
CLASS_ORDER = ["sdram", "ddr", "psram", "cram", "sram", "bram", "fifo", "rom"]

PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "sdram": [re.compile(r"\bsdram\b", re.I), re.compile(r"SDRAM[_A-Z0-9]", re.I)],
    "ddr": [re.compile(r"\bddr\b", re.I), re.compile(r"\bddr_", re.I), re.compile(r"\bddram\b", re.I), re.compile(r"\blpddr\b", re.I)],
    "psram": [re.compile(r"\bpsram\b", re.I), re.compile(r"pseudo[_-]?sram", re.I), re.compile(r"\bhyperram\b", re.I), re.compile(r"\bhyperbus\b", re.I)],
    "cram": [re.compile(r"\bcram\b", re.I), re.compile(r"CRAM[_A-Z0-9]", re.I), re.compile(r"cart[_-]?ram", re.I), re.compile(r"cartridge[_-]?ram", re.I)],
    "sram": [re.compile(r"\bsram\b", re.I), re.compile(r"SRAM[_A-Z0-9]", re.I), re.compile(r"async[_-]?ram", re.I)],
    "bram": [re.compile(r"\baltsyncram\b", re.I), re.compile(r"\bdpram\b", re.I), re.compile(r"\bspram\b", re.I), re.compile(r"dual[_-]?port[_-]?ram", re.I), re.compile(r"\bbram\b", re.I)],
    "fifo": [re.compile(r"\bdcfifo\b", re.I), re.compile(r"\bfifo\b", re.I)],
    "rom": [re.compile(r"\brom\b", re.I)],
}

MODEL_DEFAULTS: dict[str, dict[str, Any]] = {
    "sdram": {
        "selected": "ideal_transactional",
        "confidence": "bringup_only",
        "source": "rtl_shims/sdram_sim.sv",
        "notes": "Four-port request/ack behavioral model; not Pocket timing accurate.",
    },
    "ddr": {
        "selected": "missing",
        "confidence": "blocked",
        "source": "",
        "notes": "DDR/LPDDR requires a controller-specific transactional model.",
    },
    "psram": {
        "selected": "missing",
        "confidence": "blocked",
        "source": "",
        "notes": "Pocket CRAM/PSRAM-like external RAM model is not implemented yet.",
    },
    "cram": {
        "selected": "missing",
        "confidence": "blocked",
        "source": "",
        "notes": "Cartridge/CRAM external RAM model is not implemented yet.",
    },
    "sram": {
        "selected": "missing",
        "confidence": "blocked",
        "source": "",
        "notes": "Async external SRAM pin-level model is not implemented yet.",
    },
    "bram": {
        "selected": "behavioral_shims",
        "confidence": "sim_only",
        "source": "rtl_shims/altsyncram_sim.sv, rtl_shims/dpram_sim.sv",
        "notes": "Internal BRAM/FIFO shims are useful for APF contract bring-up.",
    },
    "fifo": {
        "selected": "behavioral_shim",
        "confidence": "sim_only",
        "source": "rtl_shims/dcfifo_sim.sv",
        "notes": "FIFO shim is functional, not vendor timing accurate.",
    },
    "rom": {
        "selected": "rtl_or_dataslot",
        "confidence": "depends_on_profile",
        "source": "",
        "notes": "ROM may be HDL-internal or loaded by APF data slots.",
    },
}

RISK_DEFAULTS: dict[str, dict[str, str]] = {
    "sdram": {"code": "SDRAM_TIMING_NOT_POCKET_LIKE", "severity": "warning", "message": "SDRAM dependency detected; current generic model is idealized for bring-up."},
    "ddr": {"code": "MEMORY_MODEL_REQUIRED", "severity": "error", "message": "DDR/LPDDR dependency detected; no generic timing model is selected."},
    "psram": {"code": "PSRAM_MODEL_REQUIRED", "severity": "error", "message": "PSRAM/HyperRAM dependency detected; external RAM model is required."},
    "cram": {"code": "CRAM_MODEL_REQUIRED", "severity": "error", "message": "CRAM/cartridge RAM dependency detected; external RAM model is required."},
    "sram": {"code": "SRAM_MODEL_REQUIRED", "severity": "error", "message": "Async external SRAM dependency detected; pin/bus model is required."},
}

AVAILABLE_MODELS: dict[str, list[dict[str, str]]] = {
    "sdram": [
        {
            "catalog_entry": "sdram_ideal_transactional",
            "model": "ideal_transactional",
            "confidence": "bringup_only",
            "source": "rtl_shims/sdram_sim.sv",
        }
    ],
    "sram": [
        {
            "catalog_entry": "external_sram_pin_model",
            "model": "async_sram_16_pin",
            "confidence": "sim_only",
            "source": "rtl_shims/external_memory_models.sv",
        }
    ],
    "psram": [
        {
            "catalog_entry": "psram_cram_transactional_models",
            "model": "psram_like_transactional",
            "confidence": "sim_only",
            "source": "rtl_shims/external_memory_models.sv",
        }
    ],
    "cram": [
        {
            "catalog_entry": "psram_cram_transactional_models",
            "model": "cram_like_transactional",
            "confidence": "sim_only",
            "source": "rtl_shims/external_memory_models.sv",
        }
    ],
}


def analyze_memory_sources(sources: Iterable[tuple[Path | str, str]]) -> dict[str, Any]:
    evidence: list[dict[str, str]] = []
    classes: list[str] = []
    for source, text in sources:
        source_text = str(source)
        for cls in CLASS_ORDER:
            for pattern in PATTERNS[cls]:
                match = pattern.search(text)
                if not match:
                    continue
                if cls not in classes:
                    classes.append(cls)
                if len([item for item in evidence if item["class"] == cls]) < 4:
                    evidence.append({
                        "class": cls,
                        "pattern": pattern.pattern,
                        "source": source_text,
                        "match": match.group(0)[:64],
                    })
                break
    classes = [cls for cls in CLASS_ORDER if cls in classes]
    return memory_doc(classes, evidence)


def memory_doc(classes: list[str], evidence: list[dict[str, str]] | None = None) -> dict[str, Any]:
    external = [cls for cls in classes if cls in EXTERNAL_CLASSES]
    models = {cls: dict(MODEL_DEFAULTS[cls]) for cls in classes if cls in MODEL_DEFAULTS}
    risks = [dict(RISK_DEFAULTS[cls]) for cls in external if cls in RISK_DEFAULTS]
    return {
        "schema": SCHEMA,
        "required": bool(classes),
        "classes": classes,
        "external_classes": external,
        "models": models,
        "available_models": {cls: AVAILABLE_MODELS[cls] for cls in classes if cls in AVAILABLE_MODELS},
        "risks": risks,
        "evidence": evidence or [],
    }


def merge_memory_docs(*docs: dict[str, Any]) -> dict[str, Any]:
    classes: list[str] = []
    evidence: list[dict[str, str]] = []
    for doc in docs:
        for cls in doc.get("classes", []):
            if cls not in classes:
                classes.append(str(cls))
        for item in doc.get("evidence", []):
            if isinstance(item, dict):
                evidence.append({str(k): str(v) for k, v in item.items()})
    ordered = [cls for cls in CLASS_ORDER if cls in classes]
    return memory_doc(ordered, evidence)


def risk_codes(doc: dict[str, Any]) -> list[str]:
    return [str(item.get("code")) for item in doc.get("risks", []) if isinstance(item, dict) and item.get("code")]
