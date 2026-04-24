import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"


OFFICIAL_PUBLIC_PROFILES = {
    "core_template",
    "interact",
    "kbmouse_targetdata",
    "basicassets",
    "basicchip32",
}

MOCK_PUBLIC_PROFILES = {
    "mock",
    "mock_port_gate",
    "mock_rom_stress",
    "mock_target_commands",
    "mock_lifecycle",
    "mock_memory_activity",
}


@pytest.mark.parametrize("profile", sorted(OFFICIAL_PUBLIC_PROFILES | MOCK_PUBLIC_PROFILES))
def test_public_profile_manifest_set(profile):
    assert (ROOT / "profiles" / f"{profile}.json").exists()


def test_public_tree_has_no_private_profile_manifests():
    profiles = {path.stem for path in (ROOT / "profiles").glob("*.json")}
    assert profiles == OFFICIAL_PUBLIC_PROFILES | MOCK_PUBLIC_PROFILES


@pytest.mark.parametrize(
    ("profile", "env_name", "expected"),
    [
        ("interact", "CORE_EXAMPLE_INTERACT_ROOT", [
            "PASS boot: reached running",
            "PASS interact: 7 persistent writes applied",
            "PASS video: 4 frames, 320x288 active",
            "PASS audio:",
        ]),
        ("kbmouse_targetdata", "CORE_EXAMPLE_KBMOUSE_TARGETDATA_ROOT", [
            "PASS boot: reached running",
            "PASS interact: 1 persistent writes verified",
            "PASS video: 5 frames, 320x288 active",
            "PASS input: scripted pulses delivered",
        ]),
        ("basicchip32", "CORE_EXAMPLE_BASICCHIP32_ROOT", [
            "PASS data: slot 32 loaded 184320 bytes",
            "PASS data: slot 99 loaded 1343824 bytes",
            "PASS interact: 2 persistent writes applied",
            "PASS video: 3 frames, 320x288 active",
        ]),
    ],
)
def test_official_example_profile_runs_when_checkout_is_available(tmp_path, profile, env_name, expected):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed")
    checkout = os.environ.get(env_name)
    if not checkout or not Path(checkout).exists():
        pytest.skip(f"{env_name} checkout not present")

    artifacts = tmp_path / profile
    r = subprocess.run(
        [
            str(CLI),
            "run",
            "--profile", profile,
            "--artifacts", str(artifacts),
            "--timeout", "240",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=260,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    for text in expected:
        assert text in r.stdout
    assert (artifacts / "result.json").exists()
    assert (artifacts / "video_shape.json").exists()
