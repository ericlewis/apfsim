import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"


def run_cli(*args, timeout=120):
    return subprocess.run([str(CLI), *args], cwd=ROOT, text=True, capture_output=True, timeout=timeout)


def test_analyze_log_extracts_full_apf_lifecycle(tmp_path):
    log = tmp_path / "bridge.log"
    report = tmp_path / "report.json"
    log.write_text("""
apfsim bridge log
HOST CM Request Status cmd=0x00000000 p0=0x00000000 p1=0x00000000 p2=0x00000000 p3=0x00000000
HOST OK Request Status result=0x00000002
HOST CM Reset Enter cmd=0x00000010 p0=0x00000000 p1=0x00000000 p2=0x00000000 p3=0x00000000
HOST OK Reset Enter result=0x00000000
DATASLOT table populate entries=2
DATASLOT load begin id=1 bytes=1024 address=0x10000000 file=examples/assets/mock.rom
HOST CM Data slot request write cmd=0x00000082 p0=0x00000001 p1=0x00000400 p2=0x10000000 p3=0x00000000
HOST OK Data slot request write result=0x00000000
DATASLOT load done id=1 writes32=256
HOST CM Data slot access all complete cmd=0x0000008F p0=0x00000000 p1=0x00000000 p2=0x00000000 p3=0x00000000
HOST OK Data slot access all complete result=0x00000000
HOST CM Real-time clock data cmd=0x00000090 p0=0x00000000 p1=0x00000000 p2=0x00000000 p3=0x00000000
HOST OK Real-time clock data result=0x00000000
TARGET CM Ready to Run word=0x636D0140
TARGET OK Ready to Run
HOST CM Reset Exit cmd=0x00000011 p0=0x00000000 p1=0x00000000 p2=0x00000000 p3=0x00000000
HOST OK Reset Exit result=0x00000000
HOST CM Request Status cmd=0x00000000 p0=0x00000000 p1=0x00000000 p2=0x00000000 p3=0x00000000
HOST OK Request Status result=0x00000004
""")

    r = run_cli("analyze-log", str(log), "--json", str(report), "--strict-lifecycle", "--verbose")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "lifecycle=ok" in r.stdout
    assert "data slot 1: bytes=1024 address=0x10000000 writes32=256" in r.stdout
    assert "Ready to Run" in r.stdout

    data = json.loads(report.read_text())
    item = data["files"][0]
    assert item["sequence_ok"] is True
    assert item["missing_phases"] == []
    assert item["phases"]["reset_enter"] < item["phases"]["reset_exit"] < item["phases"]["status_running"]
    assert item["data_slots"][0]["id"] == 1
    assert item["data_slots"][0]["bytes"] == 1024
    assert item["data_slots"][0]["address"] == 0x10000000


def test_analyze_log_strict_lifecycle_flags_missing_phases(tmp_path):
    log = tmp_path / "partial.log"
    log.write_text("HOST CM Reset Enter cmd=0x00000010\n")

    r = run_cli("analyze-log", str(log), "--strict-lifecycle")
    assert r.returncode == 1
    assert "lifecycle=incomplete" in r.stdout
    assert "status_setup" in r.stdout
    assert "status_running" in r.stdout
