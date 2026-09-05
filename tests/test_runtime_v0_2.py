#!/usr/bin/env python3
"""Adversarial regression tests for the separately versioned active runtime."""
import json
import math
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime_v0_2 as runtime
from verify_frozen_bundle import verify


def _record(**updates):
    record = {
        "sensor_pos": [0.0, 0.0, 0.0],
        "los_dir": [1.0, 0.0, 0.0],
        "position_units": "m",
        "coordinate_frame": "ENU",
        "bearing_units": "dimensionless",
        "fps": 1.0,
    }
    record.update(updates)
    return record


def test_tangent_plane_noise_is_seeded_unit_and_rotation_invariant():
    sigma = 0.02
    count = 20_000
    bearings = ([1.0, 0.0, 0.0] * count, [0.0, 0.0, 1.0] * count)
    radial_means = []
    for bearing in bearings:
        out = runtime.perturb_los_exponential(bearing, sigma, random.Random(73))
        radii = []
        for index in range(0, len(out), 3):
            vector = out[index:index + 3]
            assert math.isclose(math.hypot(*vector), 1.0, abs_tol=2e-12)
            original = bearing[index:index + 3]
            dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(vector, original))))
            radii.append(math.acos(dot))
        radial_means.append(sum(radii) / count)
    rayleigh_mean = sigma * math.sqrt(math.pi / 2)
    assert all(abs(value - rayleigh_mean) < 4e-4 for value in radial_means)
    assert abs(radial_means[0] - radial_means[1]) < 2e-4
    assert runtime.perturb_los_exponential(bearings[0][:30], sigma, random.Random(7)) == \
           runtime.perturb_los_exponential(bearings[0][:30], sigma, random.Random(7))

    random.seed(991)
    expected = random.random()
    random.seed(991)
    runtime.perturb_los_exponential(bearings[0][:30], sigma, random.Random(11))
    assert random.random() == expected


def test_monte_carlo_failure_boundary_is_unconditional(monkeypatch):
    record = _record(
        sensor_pos_2=[0.0, 100.0, 0.0],
        los_dir_2=[1.0, -0.02, 0.0],
        bearing_noise_rad=1e-4,
        bearing_noise_units="rad",
        times=[0.0],
    )

    def run_with_failures(failures):
        calls = iter(range(200))

        def fake_triangulate(_record, _mc=False):
            index = next(calls)
            if index < failures:
                return {"solvable": False}
            return {"solvable": True, "range_m": 1000.0, "range_m_2": 1001.0}

        monkeypatch.setattr(runtime, "triangulate", fake_triangulate)
        return runtime._mc_range_uncertainty(
            record, 1000.0, 1001.0,
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
            (0.0, 100.0, 0.0), (1.0, -0.02, 0.0),
            1000.5, 1e-4, trials=200,
        )

    finite = run_with_failures(10)
    assert finite[2] == 0.95
    assert math.isfinite(finite[0])
    forbidden = run_with_failures(11)
    assert forbidden[2] == 0.945
    assert math.isinf(forbidden[0])


def test_solver_output_retains_range_precision():
    target_x = 10.004
    record = _record(
        sensor_pos_2=[0.0, 10.0, 0.0],
        los_dir=[target_x, 0.0, 0.0],
        los_dir_2=[target_x, -10.0, 0.0],
        bearing_noise_rad=1e-4,
        bearing_noise_units="rad",
        times=[0.0],
    )
    result = runtime.triangulate(record, _mc=False)
    assert result["solvable"]
    assert math.isclose(result["range_m"], target_x, rel_tol=0.0, abs_tol=1e-10)
    assert result["range_m"] != round(result["range_m"], 1)


def test_schema_is_bounded_and_semantically_explicit():
    assert runtime.validate_core_schema(_record(sensor_pos=[]))
    both = _record(sensor_pos_ecef=[0.0, 0.0, 0.0], coordinate_frame="ECEF")
    assert any("mutually exclusive" in error for error in runtime.validate_core_schema(both))
    missing_units = {"sensor_pos": [0, 0, 0], "los_dir": [1, 0, 0]}
    assert any("position_units" in error for error in runtime.validate_core_schema(missing_units))
    too_many = _record(sensor_pos=[0.0, 0.0, 0.0] * 10_001,
                       los_dir=[1.0, 0.0, 0.0] * 10_001)
    assert any("10000 frames" in error for error in runtime.validate_core_schema(too_many))
    acquisition_only = {"sensor_position": "platform metadata", "position_datum": "WGS84"}
    assert runtime.validate_core_schema(acquisition_only) == []


def test_oversized_input_stops_before_expensive_work(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("expensive numerical path was entered")

    monkeypatch.setattr(runtime, "noise_stability", forbidden)
    monkeypatch.setattr(runtime, "_mc_range_uncertainty", forbidden)
    oversized = _record(
        sensor_pos=[0.0, 0.0, 0.0] * 10_001,
        los_dir=[1.0, 0.0, 0.0] * 10_001,
    )
    result = runtime.assess_sighting(oversized)
    assert result["verdict"] == "INVALID SIGHTLINE DATA"


def test_exact_frame_cap_is_admitted_by_structural_budget():
    count = 10_000
    record = _record(
        sensor_pos=[0.0, 0.0, 0.0] * count,
        los_dir=[1.0, 0.0, 0.0] * count,
        sensor_pos_2=[0.0, 10.0, 0.0] * count,
        los_dir_2=[1.0, -1.0, 0.0] * count,
        times=[float(index) for index in range(count)],
    )
    record.pop("fps")
    assert runtime.validate_core_schema(record) == []


def test_cli_rejects_duplicate_deep_invalid_utf8_and_oversize_without_traceback():
    cases = [
        b'{"timestamp_utc":"a","timestamp_utc":"b"}',
        (b'[' * 40) + b'0' + (b']' * 40),
        b'\xff\xfe',
        b'{"value":NaN}',
        b' ' * (1_048_576 + 1),
    ]
    for raw in cases:
        with tempfile.NamedTemporaryFile() as stream:
            stream.write(raw)
            stream.flush()
            result = subprocess.run([sys.executable, str(ROOT / "uap_assess.py"), stream.name],
                                    capture_output=True, timeout=10)
        output = result.stdout + result.stderr
        assert result.returncode == 2
        assert b"Traceback" not in output


def test_frozen_bundle_safe_verifier_and_path_containment():
    assert verify(ROOT) == []
    with tempfile.TemporaryDirectory() as folder:
        fake = Path(folder)
        (fake / "evidence/results").mkdir(parents=True)
        (fake / "evidence/results/holdout-2026080502.manifest.json").write_text("{}")
        assert verify(fake)
