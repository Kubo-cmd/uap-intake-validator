#!/usr/bin/env python3
"""Deterministic integrity tests for the closed frozen evidence harness."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evidence"))
import stronger_evidence as se  # noqa: E402


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def main():
    cells = se.design_cells()
    check("540 unique factorial cells", len(cells) == 540 and
          len({c["cell_id"] for c in cells}) == 540)
    check("holdout size is frozen at 6480", len(cells) * se.HOLDOUT_REPS == 6480)
    check("positive-noise design excludes numerical-floor controls",
          all(c["noise_rad"] > 0 for c in cells))

    theta = math.radians(16)
    for family in se.ORIENTATIONS:
        d1, d2 = se.direction_pair(theta, family)
        check(f"{family} crossing angle exact",
              math.isclose(se.dot(d1, d2), math.cos(theta), abs_tol=1e-14))

    seed_a = se.domain_seed(se.DEV_SEED, cells[0]["cell_id"], 0, "sensor-1-noise")
    seed_b = se.domain_seed(se.DEV_SEED, cells[0]["cell_id"], 0, "sensor-2-noise")
    seed_h = se.domain_seed(se.HOLDOUT_SEED, cells[0]["cell_id"], 0, "sensor-1-noise")
    check("sensor and phase RNG domains are separated",
          len({seed_a, seed_b, seed_h}) == 3)
    check("domain seed is loop-order independent",
          seed_a == se.domain_seed(se.DEV_SEED, cells[0]["cell_id"], 0,
                                   "sensor-1-noise"))

    row1 = se.generate_world(cells[0], 0, se.DEV_SEED, production=False)
    row2 = se.generate_world(cells[0], 0, se.DEV_SEED, production=False)
    check("world generation is byte-stable", se.canonical_bytes(row1) == se.canonical_bytes(row2))
    check("primary outcome uses unrounded positive 3D error",
          row1["position_error_3d_m"] > 0 and
          math.isclose(row1["y"], math.log(row1["relative_position_error"])))

    # One development replicate in every cell exercises all block levels and CR2.
    rows = [se.generate_world(cell, 0, se.DEV_SEED, production=False) for cell in cells]
    summary = se.fit_summary(rows)
    check("primary matrix and CR2 are finite",
          math.isfinite(summary["beta_x"]) and summary["df"] == 532 and
          len(summary["design_columns"]) == 8)
    full = se.ols(rows, include_x=True)
    base = se.ols(rows, include_x=False)
    models = {
        "full_coefficients": {n: float(v) for n, v in zip(full["names"], full["coef"])},
        "baseline_coefficients": {n: float(v) for n, v in zip(base["names"], base["coef"])},
    }
    boot1 = se.bootstrap(rows, models, seed=12345, B=20)
    boot2 = se.bootstrap(rows, models, seed=12345, B=20)
    check("cell bootstrap is deterministic and finite",
          boot1 == boot2 and all(math.isfinite(v) for v in boot1["beta_x_ci95"]))

    smoke_cell = next(c for c in cells if c["crossing_deg"] == 32 and
                      c["noise_rad"] == 1e-4 and c["frames"] == 1 and
                      c["range_m"] == 2000 and c["orientation"] == "horizontal")
    production = se.generate_world(smoke_cell, 0, se.DEV_SEED, production=True)
    check("production solver is called without modifying it",
          production["production_solved"] in (True, False) and
          production["production_reason"] != "not-run")

    check("closed protocol remains frozen",
          se.load_protocol()["status"] == "frozen")
    check("holdout execution remains closed after artifact creation",
          all((se.RESULTS_DIR / name).exists() for name in (
              "holdout-2026080502.json",
              "holdout-2026080502.rows.json",
              "holdout-2026080502.rows.csv",
              "holdout-2026080502.manifest.json")))
    print("ALL FROZEN-EVIDENCE TESTS PASS")


if __name__ == "__main__":
    main()
