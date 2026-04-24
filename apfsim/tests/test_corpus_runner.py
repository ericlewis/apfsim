import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"
sys.path.insert(0, str(ROOT / "scripts"))

from corpus_runner import load_manifest, run_corpus_manifest


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def fake_apfsim(tmp_path: Path) -> Path:
    script = tmp_path / "fake_apfsim.py"
    script.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

args = sys.argv[1:]
cmd = args[0]

def arg_value(flag, default=''):
    if flag in args:
        idx = args.index(flag)
        return args[idx + 1]
    return default

if cmd == 'bringup':
    out = Path(arg_value('--out'))
    run = out / 'run'
    run.mkdir(parents=True, exist_ok=True)
    name = out.name
    failed = 'fail' in name
    code = 'VIDEO_WIDTH_MISMATCH' if failed else ''
    row = {
        'ok': not failed,
        'first_error_code': code,
        'blocking_codes': [code] if failed else [],
        'warning_codes': ['VIDEO_STATIC_FRAME'] if not failed else [],
        'package_ok': True,
        'active_width': 289 if failed else 256,
        'active_height': 224,
        'frames_considered': 3,
        'video_protocol_valid': True,
        'audio_activity': 'active',
        'audio_nonzero_samples': 32,
        'loaded_bytes_total': 1024,
        'data_crc_list': ['0x12345678'],
        'shimmed_modules': ['mf_pllbase_sim'],
        'memory_classes': ['sdram'],
        'memory_models': ['sdram:ideal_transactional'],
        'memory_risks': ['SDRAM_TIMING_NOT_POCKET_LIKE'],
        'artifact_dir': str(run),
    }
    doc = {
        'schema': 'apfsim.run_summary.v1',
        'artifact_dir': str(run),
        'ok': not failed,
        'row': row,
        'diagnostics': {
            'first_error_code': code,
            'blocking_codes': row['blocking_codes'],
            'warning_codes': row['warning_codes'],
        },
    }
    (run / 'summary.json').write_text(json.dumps(doc, indent=2) + '\\n')
    (run / 'package_check.json').write_text(json.dumps({'schema': 'apfsim.package_check.v1', 'ok': True, 'package_errors': [], 'package_warnings': []}) + '\\n')
    print('fake bringup ' + name)
    raise SystemExit(1 if failed else 0)

if cmd == 'package-check':
    out = Path(arg_value('--json-out'))
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {'schema': 'apfsim.package_check.v1', 'ok': True, 'package_errors': [], 'package_warnings': []}
    out.write_text(json.dumps(doc, indent=2) + '\\n')
    print('fake package-check')
    raise SystemExit(0)

raise SystemExit('unsupported fake command: ' + cmd)
"""
    )
    script.chmod(script.stat().st_mode | 0o111)
    return script


def test_corpus_manifest_runner_aggregates_pass_fail_skip_and_preflight(tmp_path):
    fake = fake_apfsim(tmp_path)
    root = tmp_path / "core-root"
    root.mkdir()
    rom = tmp_path / "game.rom"
    rom.write_bytes(b"rom")
    manifest = tmp_path / "corpus.json"
    write_json(manifest, {
        "schema": "apfsim.corpus_manifest.v1",
        "defaults": {"frames": 2, "timeout": 10, "repair": True},
        "cores": [
            {"name": "pass-core", "profile": "mock_port_gate", "family": "direct-mode"},
            {"name": "fail-core", "profile": "bad_profile", "family_hint": "shell-mode"},
            {"name": "missing-root", "root": str(tmp_path / "missing"), "auto_profile": True},
            {"name": "missing-rom", "root": str(root), "rom": str(tmp_path / "missing.rom")},
            {"name": "with-rom", "root": str(root), "rom": str(rom), "auto_profile": True},
        ],
    })

    doc = run_corpus_manifest(manifest, tmp_path / "out", apfsim_cmd=fake)

    assert doc["schema"] == "apfsim.corpus_summary.v1"
    assert doc["totals"] == {"total": 5, "passed": 2, "failed": 2, "skipped": 1}
    rows = {row["name"]: row for row in doc["cores"]}
    assert rows["pass-core"]["status"] == "passed"
    assert rows["fail-core"]["first_error_code"] == "VIDEO_WIDTH_MISMATCH"
    assert rows["missing-root"]["status"] == "skipped"
    assert rows["missing-root"]["skip_reason"] == "root_missing"
    assert rows["missing-rom"]["first_error_code"] == "ROM_MISSING"
    assert rows["with-rom"]["loaded_bytes_total"] == 1024
    assert rows["with-rom"]["memory_classes"] == ["sdram"]
    blockers = {item["code"]: item["count"] for item in doc["top_blockers"]}
    assert blockers["VIDEO_WIDTH_MISMATCH"] == 1
    assert blockers["ROM_MISSING"] == 1
    assert (tmp_path / "out" / "corpus_summary.json").exists()
    tsv = (tmp_path / "out" / "corpus_summary.tsv").read_text()
    assert "pass-core" in tsv
    assert "sdram:ideal_transactional" in tsv


def test_corpus_cli_accepts_simple_yaml_manifest(tmp_path):
    fake = fake_apfsim(tmp_path)
    manifest = tmp_path / "corpus.yml"
    manifest.write_text(
        """
defaults:
  frames: 2
  timeout: 10
cores:
  - name: yaml-pass
    profile: mock_port_gate
    family: direct-mode
""".strip()
        + "\n"
    )

    loaded = load_manifest(manifest)
    assert loaded["defaults"]["frames"] == 2
    assert loaded["cores"][0]["name"] == "yaml-pass"

    out = tmp_path / "corpus-out"
    r = subprocess.run(
        [str(CLI), "corpus", "run", "--manifest", str(manifest), "--out", str(out), "--apfsim-cmd", str(fake)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert r.returncode == 0, r.stdout + r.stderr
    assert "corpus: total=1 passed=1 failed=0 skipped=0" in r.stdout
    doc = json.loads((out / "corpus_summary.json").read_text())
    assert doc["cores"][0]["name"] == "yaml-pass"


def test_corpus_cli_strict_fails_when_core_fails(tmp_path):
    fake = fake_apfsim(tmp_path)
    manifest = tmp_path / "corpus.json"
    write_json(manifest, {"cores": [{"name": "fail-core", "profile": "bad"}]})
    out = tmp_path / "corpus-out"

    r = subprocess.run(
        [str(CLI), "corpus", "run", "--manifest", str(manifest), "--out", str(out), "--apfsim-cmd", str(fake), "--strict"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert r.returncode == 1
    assert "top blockers: VIDEO_WIDTH_MISMATCH=1" in r.stdout


def test_corpus_cli_reports_invalid_manifest_without_traceback(tmp_path):
    out = tmp_path / "corpus-out"

    r = subprocess.run(
        [str(CLI), "corpus", "run", "--manifest", str(tmp_path), "--out", str(out)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert r.returncode == 2
    assert "apfsim corpus error:" in r.stderr
    assert "Traceback" not in r.stderr
