#!/usr/bin/env python3
"""Persistent test suite for uap-intake.

Encodes the ship invariants so any future edit to intake.py fails loudly
instead of silently shipping a wrong number. Run:  python3 tests/run_tests.py
Exits non-zero on any failure.
"""
import json
import math
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from validator import assess_sighting, triangulate  # noqa: E402
import nested_sim                                # noqa: E402
from nested_sim import draw_world, bearing_rays  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def _load(name):
    with open(os.path.join(ROOT, "examples", name)) as fh:
        return json.load(fh)


# --- Invariant A: a straight, level CV-conditioned sighting must be REFUSED ----
def test_straight_line_refused():
    rec = _load("straight_level_sightlines.json")
    out = assess_sighting(rec)
    v = out.get("verdict", "")
    check("straight-line CV-conditioned sighting is refused",
          "CANNOT SUPPORT" in v, f"verdict={v!r}")


# --- Invariant B: two-sensor case solves and lands within its p95 bound --------
def test_two_sensor_solves():
    rec = _load("two_sensor_triangulation.json")
    assessed = assess_sighting(rec)
    scope = assessed.get("scope", "")
    check("direct API carries the model-conditional non-claim scope",
          all(token in scope for token in (
              "model-conditional validation only",
              "does not prove or disprove a sighting",
              "identify an object",
              "establish field accuracy",
          )), repr(scope))
    check("legacy established API key is only a measurements compatibility alias",
          assessed.get("established") == assessed.get("measurements") and
          isinstance(assessed.get("measurements"), list), str(assessed)[-240:])

    tri = assessed.get("triangulation", {})
    ok = tri.get("solvable") and tri.get("range_m", 0) > 0
    check("two-sensor triangulation solves", ok, str(tri)[:120])
    if not ok:
        return
    # truth for the canned example is range ~5916 m; bound must contain the error
    err = abs(tri["range_m"] - 5916.1)
    check("canned two-sensor range is within quoted bound",
          err <= max(tri["sigma_range_m"], 1.0) + 1.0,
          f"err={err} bound={tri['sigma_range_m']}")



# --- Invariant C: only physically valid, consistent rays establish range ------
def test_triangulation_claim_gates():
    base = {"timestamp_utc": "x", "sensor_position": [0, 0, 0],
            "position_datum": "ENU", "field_of_view_deg": 1,
            "bearing_noise_rad": 0}

    behind = dict(base, sensor_pos=[0, 0, 0], los_dir=[1, 0, 0],
                  sensor_pos_2=[10, 10, 0], los_dir_2=[0, 1, 0])
    out = assess_sighting(behind)
    check("behind-observer line intersection is rejected",
          out["triangulation"].get("solvable") is False and
          out["verdict"] != "RANGE SUPPORTED BY SYNCHRONIZED GEOMETRY", str(out)[-240:])

    skew = dict(base, sensor_pos=[0, 0, 0], los_dir=[1, 0, 0],
                sensor_pos_2=[0, 1, 1000], los_dir_2=[1, -1, 0])
    out = assess_sighting(skew)
    check("mutually inconsistent bearing rays are rejected",
          out["triangulation"].get("solvable") is False and
          "disagree" in out["triangulation"].get("reason", ""), str(out)[-240:])

    malformed = dict(base, sensor_pos=[0, 0, 0, 1, 0, 0],
                     los_dir=[1, 0, 0, 1, 0, 0],
                     sensor_pos_2=[10, 0, 0],
                     los_dir_2=[-1, 1, 0, -1, 1, 0])
    out = assess_sighting(malformed)
    check("mismatched xyz arrays fail closed without crashing",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    nonfinite = dict(base, sensor_pos=[0, 0, 0],
                     los_dir=[float("nan"), 0, 0],
                     sensor_pos_2=[10, 0, 0], los_dir_2=[-1, 1, 0])
    out = assess_sighting(nonfinite)
    check("non-finite bearings cannot establish range",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    frame_mismatch = dict(base, sensor_pos=[0, 0, 0], los_dir=[1, 1, 0],
                          sensor_pos_2=[10, 0, 0, 10, 0, 0],
                          los_dir_2=[0, 1, 0, 0, 1, 0])
    out = assess_sighting(frame_mismatch)
    check("cross-sensor frame counts must match",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    bad_track = dict(base, fps=1, sensor_pos=[0, 0, 0, 1, 0, 0],
                     los_dir=[1, 1, 0, 1, 1, 0], positions=[0])
    out = assess_sighting(bad_track)
    check("malformed fitted track fails closed without crashing",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    huge = dict(base, bearing_noise_rad=1e308,
                sensor_pos=[0, 0, 0], los_dir=[1, 1, 0],
                sensor_pos_2=[10, 0, 0], los_dir_2=[0, 1, 0])
    out = assess_sighting(huge)
    check("overflow-scale noise fails closed without crashing",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    huge = dict(base, sensor_pos=[0, 0, 0], los_dir=[1e308, 1, 0],
                sensor_pos_2=[10, 0, 0], los_dir_2=[0, 1, 0])
    out = assess_sighting(huge)
    check("overflow-scale vectors fail closed without crashing",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    huge_int = 10 ** 4000
    huge = dict(base, sensor_pos=[0, 0, 0], los_dir=[huge_int, 1, 0],
                sensor_pos_2=[10, 0, 0], los_dir_2=[0, 1, 0])
    out = assess_sighting(huge)
    check("arbitrary-precision integers fail closed without crashing",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    huge_fps = dict(base, fps=10 ** 4000,
                    sensor_pos=[0, 0, 0], los_dir=[1, 1, 0],
                    sensor_pos_2=[10, 0, 0], los_dir_2=[0, 1, 0])
    out = assess_sighting(huge_fps)
    check("arbitrary-precision fps fails triangulation closed",
          not out["triangulation"].get("solvable") and
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    overflow_fps = dict(base, fps=1e308,
                        sensor_pos=[0, 0, 0], los_dir=[1, 1, 0],
                        sensor_pos_2=[10, 0, 0], los_dir_2=[0, 1, 0])
    out = assess_sighting(overflow_fps)
    check("overflow-scale finite fps fails triangulation closed",
          not out["triangulation"].get("solvable") and
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    underflow_fps = dict(base, fps=5e-324,
                         sensor_pos=[0, 0, 0], los_dir=[1, 1, 0],
                         sensor_pos_2=[10, 0, 0], los_dir_2=[0, 1, 0])
    out = assess_sighting(underflow_fps)
    check("underflow-scale finite fps fails triangulation closed",
          not out["triangulation"].get("solvable") and
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    huge_timestamp = dict(base, times=[10 ** 4000],
                          sensor_pos=[0, 0, 0], los_dir=[1, 1, 0],
                          sensor_pos_2=[10, 0, 0], los_dir_2=[0, 1, 0])
    out = assess_sighting(huge_timestamp)
    check("arbitrary-precision timestamps fail triangulation closed",
          not out["triangulation"].get("solvable") and
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    above_pi_noise = dict(base, bearing_noise_rad=math.pi + 1e-6,
                          sensor_pos=[0, 0, 0], los_dir=[1, 1, 0],
                          sensor_pos_2=[10, 0, 0], los_dir_2=[0, 1, 0])
    out = assess_sighting(above_pi_noise)
    check("angular noise above pi radians fails closed",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    near_pi_noise = dict(base, bearing_noise_rad=3.12,
                         sensor_pos=[0, 0, 0], los_dir=[10, 10, 0],
                         sensor_pos_2=[10, 0, 0], los_dir_2=[0, 10, 0])
    tri = triangulate(near_pi_noise)
    check("finite angular noise below pi remains valid input",
          tri.get("input_valid") is not False and
          "bearing_noise_rad must" not in tri.get("reason", ""), str(tri)[-240:])

    # Components remain below the declared safe bound, but near-parallel geometry
    # can produce s/t large enough that s*s+t*t overflows. The physical miss gate
    # must remain finite and reject the inconsistent skew rays.
    from intake import MAX_SAFE_COMPONENT
    m = MAX_SAFE_COMPONENT / 2
    theta = 0.02
    overflow_gate = dict(base, bearing_noise_rad=1e-3,
                         sensor_pos=[0, 0, 0], los_dir=[1, 0, 0],
                         sensor_pos_2=[0, m, m],
                         los_dir_2=[math.cos(theta), -math.sin(theta), 0])
    out = assess_sighting(overflow_gate)
    check("large finite geometry cannot overflow the physical miss gate",
          out["verdict"] != "RANGE SUPPORTED BY SYNCHRONIZED GEOMETRY" and
          not out["triangulation"]["solvable"], str(out)[-240:])

    exact = dict(base, bearing_noise_rad=0,
                 sensor_pos=[0, 0, 0], los_dir=[5000, 3000, 1000],
                 sensor_pos_2=[2000, 0, 0], los_dir_2=[3000, 3000, 1000])
    tri = triangulate(exact) or {}
    check("zero-noise solve retains a numerical uncertainty floor",
          tri.get("solvable") and tri.get("sigma_range_m", 0) > 0 and
          tri.get("interval_kind") == "numerical-floor" and
          tri.get("rel_uncertainty") == 0.0001, str(tri)[-240:])
    out = assess_sighting(exact)
    check("timestamp-free sensor pairs cannot establish range",
          tri.get("sync_verified") is False and not tri.get("confident") and
          out["verdict"] == "RANGE ESTIMATE — LOW CONFIDENCE", str(out)[-240:])

    zero_bearing = dict(exact, los_dir=[0, 0, 0])
    out = assess_sighting(zero_bearing)
    check("zero-length bearing vector fails closed",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    duplicate_times = dict(
        exact, times=[0, 0],
        sensor_pos=[0, 0, 0, 0, 0, 0],
        los_dir=[5000, 3000, 1000, 5000, 3000, 1000],
        sensor_pos_2=[2000, 0, 0, 2000, 0, 0],
        los_dir_2=[3000, 3000, 1000, 3000, 3000, 1000])
    out = assess_sighting(duplicate_times)
    check("duplicate timestamps fail closed",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    repeated_frames = dict(
        exact, fps=30, time_sync_precision_s=0,
        sensor_pos=[0, 0, 0, 0, 0, 0],
        los_dir=[5000, 3000, 1000, 5000, 3000, 1000],
        sensor_pos_2=[2000, 0, 0, 2000, 0, 0],
        los_dir_2=[3000, 3000, 1000, 3000, 3000, 1000])
    out = assess_sighting(repeated_frames)
    check("multi-frame pairs report one synchronized frame without temporal averaging",
          out["triangulation"].get("solvable") and
          out["triangulation"].get("selected_frame_index") in (0, 1) and
          out["verdict"] == "RANGE SUPPORTED BY SYNCHRONIZED GEOMETRY",
          str(out)[-240:])
    noisy_repeated = dict(repeated_frames, bearing_noise_rad=1e-3)
    noisy_tri = triangulate(noisy_repeated)
    check("multi-frame Monte Carlo uncertainty remains finite",
          noisy_tri.get("solvable") and
          math.isfinite(noisy_tri.get("sigma_range_m", math.inf)) and
          math.isfinite(noisy_tri.get("rel_uncertainty", math.inf)),
          str(noisy_tri)[-240:])

    unsynced = dict(exact, times=[float("nan")])
    out = assess_sighting(unsynced)
    check("invalid timing cannot be overridden by a geometric solve",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    nonzero_sync = dict(exact, time_sync_precision_s=1.0)
    out = assess_sighting(nonzero_sync)
    check("nonzero synchronization uncertainty cannot support a high-confidence range",
          out["triangulation"].get("solvable") and
          out["triangulation"].get("sync_verified") is False and
          not out["triangulation"].get("confident") and
          out["verdict"] == "RANGE ESTIMATE — LOW CONFIDENCE", str(out)[-240:])

    tiny_nonzero_sync = dict(exact, time_sync_precision_s=1e-300)
    out = assess_sighting(tiny_nonzero_sync)
    check("tiny nonzero synchronization uncertainty cannot pass the exact-zero gate",
          out["triangulation"].get("solvable") and
          out["triangulation"].get("sync_verified") is False and
          not out["triangulation"].get("confident") and
          out["verdict"] == "RANGE ESTIMATE — LOW CONFIDENCE", str(out)[-240:])

    poor_sync = dict(exact, time_sync_precision_s=1.0001)
    out = assess_sighting(poor_sync)
    check("declared gross cross-sensor timing uncertainty fails closed",
          out["verdict"] == "INVALID SIGHTLINE DATA", str(out)[-240:])

    cancelling_frames = dict(
        base, fps=1, bearing_noise_rad=0,
        sensor_pos=[0, 0, 0, 0, 0, 0],
        los_dir=[5, 10, 10, 5, 10, -10],
        sensor_pos_2=[10, 0, 0, 10, 0, 0],
        los_dir_2=[-5, 10, -10, -5, 10, 10])
    out = assess_sighting(cancelling_frames)
    check("per-frame ray disagreement cannot cancel into an established average",
          not out["triangulation"].get("solvable") and
          out["verdict"] != "RANGE SUPPORTED BY SYNCHRONIZED GEOMETRY", str(out)[-240:])

    moving_frames = dict(
        base, fps=1, bearing_noise_rad=0, time_sync_precision_s=0,
        sensor_pos=[0, 0, 0, 0, 0, 0],
        los_dir=[100, 100, 0, 100, 200, 0],
        sensor_pos_2=[50, 0, 0, 50, 0, 0],
        los_dir_2=[50, 100, 0, 50, 200, 0])
    out = assess_sighting(moving_frames)
    check("moving target returns an actual selected-frame position, not an average",
          out["triangulation"].get("solvable") and
          out["triangulation"].get("selected_frame_index") == 0 and
          out["triangulation"].get("position_m") == [100.0, 100.0, 0.0] and
          out["verdict"] == "RANGE SUPPORTED BY SYNCHRONIZED GEOMETRY",
          str(out)[-240:])

    # Slow coherent motion must stay tied to one measured synchronized frame;
    # temporal averaging would manufacture a position that never existed.
    track1, track2, track_los1, track_los2 = [], [], [], []
    for i in range(30):
        target = (5000 + 2 * i, 3000, 1000)
        track1.extend([0, 0, 0]); track2.extend([2000, 0, 0])
        track_los1.extend(target)
        track_los2.extend([target[0] - 2000, target[1], target[2]])
    coherent_motion = dict(exact, sensor_pos=track1, los_dir=track_los1,
                           sensor_pos_2=track2, los_dir_2=track_los2,
                           fps=30, time_sync_precision_s=0, bearing_noise_rad=1e-3)
    out = assess_sighting(coherent_motion)
    check("coherent target track remains tied to one real frame",
          out["triangulation"].get("solvable") and
          out["triangulation"].get("selected_frame_index") == 14 and
          out["triangulation"].get("position_m") == [5028.0, 3000.0, 1000.0] and
          not out["verdict"].startswith("INVALID"),
          str(out)[-240:])

    malformed_sensor_count = dict(exact, sensor_count="two")
    out = assess_sighting(malformed_sensor_count)
    check("malformed sensor_count cannot crash assessment",
          isinstance(out, dict) and out["triangulation"].get("solvable"), str(out)[-240:])

    for malformed_record in (None, True, 0, "sighting", [], [{}]):
        out = assess_sighting(malformed_record)
        check("non-object top-level JSON fails closed",
              out["verdict"] == "INVALID SIGHTLINE DATA" and
              out["triangulation"].get("input_valid") is False, repr(malformed_record))

    target = (10000.0, 10000.0, 1000.0)
    s1, s2 = (0.0, 0.0, 0.0), (500.0, 0.0, 0.0)
    shallow = dict(base, bearing_noise_rad=5e-4,
                   sensor_pos=list(s1),
                   los_dir=[target[i] - s1[i] for i in range(3)],
                   sensor_pos_2=list(s2),
                   los_dir_2=[target[i] - s2[i] for i in range(3)])
    out = assess_sighting(shallow)
    check("low-confidence solve is labeled estimate, not established",
          out["triangulation"].get("solvable") and
          not out["triangulation"].get("confident") and
          out["verdict"] == "RANGE ESTIMATE — LOW CONFIDENCE", str(out)[-240:])


# --- Invariant D: false-good rate stays at zero across random worlds -----------
def test_false_good_zero(worlds=200):
    nested_sim.rng = random.Random(2026)
    n = 0
    danger = 0
    covered = 0
    finite_bounds = 0
    for _ in range(worlds):
        W = draw_world()
        T, s1, s2, noise, nn, fps = (W["T"], W["s1"], W["s2"],
                                     W["noise"], W["n"], W["fps"])
        ld1 = bearing_rays([*s1] * nn, T, noise)
        ld2 = bearing_rays([*s2] * nn, T, noise)
        tri = triangulate({"sensor_pos": [*s1] * nn, "los_dir": ld1,
                           "sensor_pos_2": [*s2] * nn, "los_dir_2": ld2,
                           "fps": fps, "bearing_noise_rad": noise,
                           "time_sync_precision_s": 0})
        if not tri or not tri.get("solvable"):
            continue
        n += 1
        finite_bounds += (math.isfinite(tri["sigma_range_m"]) and
                          math.isfinite(tri["rel_uncertainty"]))
        tr = math.dist(s1, T)
        covered += abs(tri["range_m"] - tr) <= tri["sigma_range_m"]
        err = math.dist(tri["position_m"], T)
        if tri["confident"] and err > 0.05 * tr:
            danger += 1
    check("false-good (dangerous overconfident) rate is zero", danger == 0,
          f"{danger}/{n}")
    check("triangulation actually solves on random worlds", n > 0, f"n={n}")
    check("every solved random world has finite uncertainty",
          n > 0 and finite_bounds == n, f"finite={finite_bounds}/{n}")
    check("empirical-p95 bound meets the declared 93% synthetic coverage floor",
          n > 0 and covered / n >= 0.93, f"coverage={covered}/{n}")


# --- Invariant E: Pearson uncertainty is paired, isolated, and explicit -------
def test_pearson_bootstrap_audit():
    pairs = [(-3.0, 4.0), (-2.0, 2.7), (-1.0, 2.2), (0.0, 0.4),
             (1.0, -0.2), (2.0, -2.4), (3.0, -2.8), (4.0, -4.7)]
    global_state = random.getstate()
    world_state = nested_sim.rng.getstate()
    first = nested_sim.pearson_pairs_bootstrap(pairs, B=1000, seed=918273)
    second = nested_sim.pearson_pairs_bootstrap(pairs, B=1000, seed=918273)
    check("solved-pairs bootstrap is exactly deterministic", first == second)
    check("Pearson bootstrap uses an isolated RNG",
          random.getstate() == global_state and nested_sim.rng.getstate() == world_state)
    check("Pearson bootstrap reports its complete conditional method",
          first["n"] == len(pairs) and first["B"] == 1000 and
          first["seed"] == 918273 and first["valid_B"] <= first["B"] and
          first["method"] == "independent solved-pairs bootstrap" and
          first["quantile_method"] == "type-7 linear interpolation" and
          "conditional on solvability" in first["estimand"], str(first))
    check("negative paired fixture has finite nonzero uncertainty",
          -1 <= first["r"] < 0 and math.isfinite(first["bootstrap_se"]) and
          first["bootstrap_se"] > 0 and
          -1 <= first["ci_low"] <= first["ci_high"] < 0, str(first))
    perfect = nested_sim.pearson_pairs_bootstrap(
        [(-2.0, 2.0), (-1.0, 1.0), (0.0, 0.0), (1.0, -1.0), (2.0, -2.0)],
        B=1000, seed=918273)
    check("perfect negative paired data retains its degenerate valid interval",
          math.isclose(perfect["r"], -1.0, abs_tol=1e-15) and
          perfect["bootstrap_se"] <= 1e-15 and
          math.isclose(perfect["ci_low"], -1.0, abs_tol=1e-15) and
          math.isclose(perfect["ci_high"], -1.0, abs_tol=1e-15), str(perfect))
    check("type-7 quantile interpolation is explicit",
          nested_sim._type7_quantile([0.0, 10.0, 20.0, 30.0], 0.25) == 7.5)

    invalid = [
        ([(1.0, 2.0)] * 3, 100, 1),
        ([(1.0, 2.0), (1.0, 3.0), (1.0, 4.0), (1.0, 5.0)], 100, 1),
        ([(0.0, 1.0), (1.0, 0.0), (2.0, float("nan")), (3.0, -2.0)], 100, 1),
        ([(0.0, 1.0), (1.0, 0.0), (2.0, -1.0), (3.0, -2.0)], 99, 1),
        ([(0.0, 1.0), (1.0, 0.0), (2.0, -1.0), (3.0, -2.0)], 100, True),
    ]
    rejected = 0
    for sample, B, seed in invalid:
        try:
            nested_sim.pearson_pairs_bootstrap(sample, B=B, seed=seed)
        except ValueError:
            rejected += 1
    check("Pearson bootstrap rejects undersized, degenerate, and malformed requests",
          rejected == len(invalid), f"rejected={rejected}/{len(invalid)}")


# --- Invariant F: CLI runs and gates pass --------------------------------------
def test_cli_and_gates():
    conditioning = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tests", "test_uap_conditioning.py")],
        capture_output=True, text=True, timeout=30)
    conditioning_out = conditioning.stdout + conditioning.stderr
    check("clean-room conditioning unit suite passes",
          conditioning.returncode == 0 and "OK" in conditioning_out,
          conditioning_out[-500:])
    r = subprocess.run([sys.executable, os.path.join(ROOT, "simulate.py")],
                       capture_output=True, text=True, timeout=180)
    out = r.stdout + r.stderr
    check("simulate.py runs clean", r.returncode == 0, out[-300:])
    check("ship gate passes", "SHIP GATE: PASS" in out, out[-300:])
    check("false-good rate is ~0", "false-good rate (must be ~0): 0.000%" in out,
          out[-300:])
    high_noise_line = next(
        (line for line in out.splitlines() if "noise= 2.0e-03 rad" in line), "")
    check("triangulation sweep propagates each declared noise level",
          "over 40 solves" in high_noise_line, high_noise_line)
    check("triangulation error rises monotonically across the declared sweep",
          "error monotonic in noise: True  OK" in out, out[-300:])
    nested = subprocess.run([sys.executable, os.path.join(ROOT, "nested_sim.py")],
                            capture_output=True, text=True, timeout=240)
    nested_out = nested.stdout + nested.stderr
    required = ("conditional on solvability", "B=10000", "seed=918273",
                "valid_B=10000", "bootstrap_SE=", "95% CI=",
                "quantile=type-7 linear interpolation",
                "DETERMINISTIC SYNTHETIC COVERAGE AUDIT: PASS")
    check("nested audit discloses conditional Pearson bootstrap uncertainty",
          nested.returncode == 0 and all(token in nested_out for token in required),
          nested_out[-700:])
    solved = subprocess.run(
        [sys.executable, os.path.join(ROOT, "uap_assess.py"),
         os.path.join(ROOT, "examples", "two_sensor_triangulation.json")],
        capture_output=True, text=True, timeout=180)
    solved_out = solved.stdout + solved.stderr
    check("CLI identifies the synchronized frame used for triangulation",
          solved.returncode == 0 and "selected frame 14" in solved_out,
          solved_out[-300:])
    check("CLI labels outputs as model-conditional and prints the non-claim scope",
          "MODEL-CONDITIONAL MEASUREMENTS:" in solved_out and
          "does not prove or disprove a sighting" in solved_out and
          "ESTABLISHED (by this assessment):" not in solved_out,
          solved_out[-500:])
    missing = subprocess.run(
        [sys.executable, os.path.join(ROOT, "uap_assess.py"),
         os.path.join(ROOT, "examples", "does-not-exist.json")],
        capture_output=True, text=True, timeout=30)
    missing_out = missing.stdout + missing.stderr
    check("CLI reports unreadable JSON without a traceback",
          missing.returncode == 2 and "ERROR: cannot read valid sighting JSON" in missing_out
          and "Traceback" not in missing_out, missing_out[-300:])
    invalid = subprocess.run(
        [sys.executable, os.path.join(ROOT, "uap_assess.py"), "/dev/stdin"],
        input=json.dumps({"sensor_pos": [0, 0, 0], "los_dir": [0, 0, 0], "fps": 1}),
        capture_output=True, text=True, timeout=30)
    invalid_out = invalid.stdout + invalid.stderr
    check("CLI returns nonzero for domain-invalid sightline data",
          invalid.returncode == 2 and "VERDICT: INVALID SIGHTLINE DATA" in invalid_out,
          invalid_out[-300:])


# --- Invariant G: public claims retain explicit scientific boundaries ---------
def test_public_claim_boundaries():
    def read_text(relative_path):
        with open(os.path.join(ROOT, relative_path), encoding="utf-8") as fh:
            return fh.read()

    readme = read_text("README.md")
    launch = read_text("REPO_AND_LAUNCH.md")
    provenance = read_text("PROVENANCE.md")
    with open(os.path.join(ROOT, "evidence", "results",
                           "holdout-2026080502.council-status.json"),
              encoding="utf-8") as fh:
        status = json.load(fh)

    readme_required = (
        "experimental, simulation-evaluated, open-source validation and",
        "prove or disprove a sighting",
        "fixed synthetic evaluation",
        "not field\nvalidation",
        "frozen holdout remains **UNDETERMINED**",
        "must\nnot be rerun, replaced, reanalyzed, reinterpreted, or resealed",
    )
    check("README carries intended-use and non-claim boundaries",
          all(token in readme for token in readme_required))

    launch_required = (
        "experimental, simulation-evaluated, open-source UAP intake validator",
        "does not prove or disprove a sighting",
        "fixed synthetic evaluation distribution",
        "not field or population validation",
        "Council-level UNDETERMINED",
        "not production or field validation",
    )
    check("standalone launch copy carries its own claim boundaries",
          all(token in launch for token in launch_required))

    check("frozen legacy calibration prose is explicitly non-authoritative",
          all(token in provenance for token in (
              "legacy comments describing an inner Monte Carlo",
              "not current release claims",
              "must not be quoted as evidence of independent\n95% calibration",
          )))

    check("frozen holdout machine record remains non-conformant and undetermined",
          status.get("decision") == "NOT_COUNCIL_CONFORMANT" and
          status.get("council_inferential_status") == "UNDETERMINED" and
          status.get("append_only") is True and
          "rerun or continue the completed holdout" in
          status.get("prohibited_actions", []))


if __name__ == "__main__":
    test_straight_line_refused()
    test_two_sensor_solves()
    test_triangulation_claim_gates()
    test_false_good_zero()
    test_pearson_bootstrap_audit()
    test_cli_and_gates()
    test_public_claim_boundaries()
    print("\n" + ("ALL TESTS PASS" if not FAILS else f"{len(FAILS)} FAILURES: {FAILS}"))
    sys.exit(1 if FAILS else 0)
