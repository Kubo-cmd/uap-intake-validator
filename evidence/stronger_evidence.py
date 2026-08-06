#!/usr/bin/env python3
"""One-shot preregistered crossing-angle evidence harness.

The production solver is imported but never modified. Development and holdout
streams are domain-separated. The holdout command refuses to run unless the
protocol is frozen and its source hashes match, and refuses to overwrite an
existing result.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import platform
import random
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from intake import triangulate  # noqa: E402

SCHEMA = "uap_crossing_angle_holdout/v1"
PROTOCOL_PATH = ROOT / "evidence" / "preregistration.json"
RESULTS_DIR = ROOT / "evidence" / "results"
CROSSING_DEG = (2, 4, 8, 16, 32)
NOISE_RAD = (1e-4, 5e-4, 1e-3, 2e-3)
FRAMES = (1, 20, 60)
RANGES_M = (2000, 10000, 20000)
ORIENTATIONS = ("horizontal", "vertical", "oblique")
DEV_SEED = 2026080501
HOLDOUT_SEED = 2026080502
DEV_REPS = 4
HOLDOUT_REPS = 12
BOOTSTRAP_REPS = 10000
PRIMARY_PREDICTOR = "log(sigma_rad / sin(noise_free_crossing_angle_rad))"
PRIMARY_OUTCOME = "log(unrounded_3d_position_error_m / true_sensor1_range_m)"


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def domain_seed(master_seed, cell_id, replicate, stream):
    payload = f"{SCHEMA}|{master_seed}|{cell_id}|{replicate}|{stream}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:16], "big")


def normalize(v):
    n = math.hypot(*v)
    if not math.isfinite(n) or n <= 0:
        raise ValueError("cannot normalize vector")
    return tuple(float(x) / n for x in v)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def direction_pair(theta, orientation):
    if orientation == "horizontal":
        d1, axis = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    elif orientation == "vertical":
        d1, axis = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    elif orientation == "oblique":
        d1 = normalize((1.0, 1.0, 1.0))
        axis = normalize(cross(d1, (0.0, 0.0, 1.0)))
    else:
        raise ValueError("unknown orientation")
    d2 = normalize(tuple(math.cos(theta) * d1[i] + math.sin(theta) * axis[i]
                         for i in range(3)))
    return d1, d2


def tangent_basis(u):
    ref = (0.0, 0.0, 1.0) if abs(u[2]) < 0.9 else (0.0, 1.0, 0.0)
    e1 = normalize(cross(u, ref))
    e2 = normalize(cross(u, e1))
    return e1, e2


def perturb_tangent(u, sigma, rng):
    """Isotropic Gaussian tangent-plane draw mapped to the unit sphere."""
    e1, e2 = tangent_basis(u)
    a, b = rng.gauss(0.0, sigma), rng.gauss(0.0, sigma)
    radius = math.hypot(a, b)
    if radius == 0:
        return tuple(u)
    scale = math.sin(radius) / radius
    return normalize(tuple(math.cos(radius) * u[i] +
                           scale * (a * e1[i] + b * e2[i]) for i in range(3)))


def closest_midpoint(p1, d1, p2, d2):
    """Ungated closest-line midpoint using unrounded floating-point values."""
    b = dot(d1, d2)
    w0 = tuple(p1[i] - p2[i] for i in range(3))
    dd, ee = dot(d1, w0), dot(d2, w0)
    denom = 1.0 - b * b
    if not math.isfinite(denom) or denom <= 0:
        raise ValueError("degenerate ungated ray pair")
    s = (b * ee - dd) / denom
    t = (ee - b * dd) / denom
    pt1 = tuple(p1[i] + s * d1[i] for i in range(3))
    pt2 = tuple(p2[i] + t * d2[i] for i in range(3))
    mid = tuple((pt1[i] + pt2[i]) / 2.0 for i in range(3))
    return mid, s, t, math.dist(pt1, pt2)


def design_cells():
    cells = []
    for crossing, noise, frames, range_m, orientation in itertools.product(
            CROSSING_DEG, NOISE_RAD, FRAMES, RANGES_M, ORIENTATIONS):
        cell_id = (f"a{crossing:02d}_n{noise:.0e}_f{frames:02d}_"
                   f"r{range_m:05d}_{orientation}")
        cells.append({"cell_id": cell_id, "crossing_deg": crossing,
                      "noise_rad": noise, "frames": frames,
                      "range_m": range_m, "orientation": orientation})
    if len(cells) != 540 or len({c["cell_id"] for c in cells}) != 540:
        raise AssertionError("factorial design must contain 540 unique cells")
    return cells


def generate_world(cell, replicate, master_seed, production=True):
    theta = math.radians(cell["crossing_deg"])
    d1_true, d2_true = direction_pair(theta, cell["orientation"])
    target = tuple(cell["range_m"] * x for x in d1_true)
    p1 = (0.0, 0.0, 0.0)
    p2 = tuple(target[i] - cell["range_m"] * d2_true[i] for i in range(3))
    seed1 = domain_seed(master_seed, cell["cell_id"], replicate, "sensor-1-noise")
    seed2 = domain_seed(master_seed, cell["cell_id"], replicate, "sensor-2-noise")
    rng1, rng2 = random.Random(seed1), random.Random(seed2)
    dirs1 = [perturb_tangent(d1_true, cell["noise_rad"], rng1)
             for _ in range(cell["frames"])]
    dirs2 = [perturb_tangent(d2_true, cell["noise_rad"], rng2)
             for _ in range(cell["frames"])]
    center = (cell["frames"] - 1) // 2
    mid, s, t, miss = closest_midpoint(p1, dirs1[center], p2, dirs2[center])
    error = math.dist(mid, target)
    if not math.isfinite(error) or error <= 0:
        raise ValueError("primary log outcome is non-finite or non-positive")
    record = {
        "sensor_pos": list(p1) * cell["frames"],
        "los_dir": [v for d in dirs1 for v in d],
        "sensor_pos_2": list(p2) * cell["frames"],
        "los_dir_2": [v for d in dirs2 for v in d],
        "fps": 30.0,
        "bearing_noise_rad": cell["noise_rad"],
        "time_sync_precision_s": 0.0,
    }
    prod = triangulate(record) if production else None
    solved = bool(prod and prod.get("solvable")) if production else None
    reason = "solved" if solved else ((prod or {}).get("reason", "not-run"))
    row = dict(cell)
    row.update({
        "replicate": replicate,
        "world_id": f"{cell['cell_id']}_rep{replicate:02d}",
        "master_seed": master_seed,
        "sensor1_noise_seed": str(seed1),
        "sensor2_noise_seed": str(seed2),
        "true_target_m": list(target),
        "sensor2_position_m": list(p2),
        "center_noisy_dir_1": list(dirs1[center]),
        "center_noisy_dir_2": list(dirs2[center]),
        "ungated_midpoint_m": list(mid),
        "ungated_s_m": s,
        "ungated_t_m": t,
        "ungated_miss_m": miss,
        "position_error_3d_m": error,
        "relative_position_error": error / cell["range_m"],
        "x": math.log(cell["noise_rad"] / math.sin(theta)),
        "y": math.log(error / cell["range_m"]),
        "production_solved": solved,
        "production_reason": reason,
        "production_selected_frame": ((prod or {}).get("selected_frame_index")
                                      if production else None),
        "production_range_m": ((prod or {}).get("range_m") if solved else None),
        "production_rel_uncertainty": ((prod or {}).get("rel_uncertainty")
                                       if solved else None),
        "production_confident": ((prod or {}).get("confident") if solved else None),
    })
    return row


def design_matrix(rows, include_x=True, interactions=False):
    cols = ["intercept"]
    columns = [np.ones(len(rows), dtype=float)]
    x = np.array([r["x"] for r in rows], dtype=float)
    if include_x:
        cols.append("x")
        columns.append(x)
    factors = (("range_m", RANGES_M), ("frames", FRAMES),
               ("orientation", ORIENTATIONS))
    for key, levels in factors:
        for level in levels[1:]:
            cols.append(f"{key}={level}")
            columns.append(np.array([1.0 if r[key] == level else 0.0 for r in rows]))
    if interactions:
        for key, levels in (("frames", FRAMES), ("orientation", ORIENTATIONS)):
            for level in levels[1:]:
                indicator = np.array([1.0 if r[key] == level else 0.0 for r in rows])
                cols.append(f"x:{key}={level}")
                columns.append(x * indicator)
    return np.column_stack(columns), cols


def ols(rows, include_x=True, interactions=False):
    X, names = design_matrix(rows, include_x=include_x, interactions=interactions)
    y = np.array([r["y"] for r in rows], dtype=float)
    if np.linalg.matrix_rank(X) != X.shape[1]:
        raise ValueError("design matrix is rank deficient")
    bread = np.linalg.inv(X.T @ X)
    coef = bread @ X.T @ y
    resid = y - X @ coef
    return {"X": X, "y": y, "names": names, "coef": coef,
            "resid": resid, "bread": bread,
            "rmse": float(math.sqrt(float(np.mean(resid ** 2))))}


def cr2_cluster(model, rows):
    """Bell-McCaffrey CR2 residual adjustment; t df fixed at G-rank."""
    X, resid, bread = model["X"], model["resid"], model["bread"]
    groups = defaultdict(list)
    for i, row in enumerate(rows):
        groups[row["cell_id"]].append(i)
    meat = np.zeros((X.shape[1], X.shape[1]))
    for idxs in groups.values():
        idx = np.array(idxs, dtype=int)
        Xg, eg = X[idx, :], resid[idx]
        M = np.eye(len(idx)) - Xg @ bread @ Xg.T
        vals, vecs = np.linalg.eigh((M + M.T) / 2.0)
        if float(vals.min()) <= 1e-10:
            raise ValueError("CR2 cluster adjustment is singular")
        A = vecs @ np.diag(1.0 / np.sqrt(vals)) @ vecs.T
        score = Xg.T @ (A @ eg)
        meat += np.outer(score, score)
    cov = bread @ meat @ bread
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    df = len(groups) - X.shape[1]
    if df <= 0 or not np.all(np.isfinite(se)):
        raise ValueError("invalid CR2 result")
    return cov, se, df


def fit_summary(rows):
    model = ols(rows, include_x=True)
    cov, se, df = cr2_cluster(model, rows)
    j = model["names"].index("x")
    beta, beta_se = float(model["coef"][j]), float(se[j])
    t95 = float(stats.t.ppf(0.975, df))
    t90 = float(stats.t.ppf(0.95, df))
    return {
        "design_columns": model["names"],
        "coefficients": {n: float(v) for n, v in zip(model["names"], model["coef"])},
        "cr2_standard_errors": {n: float(v) for n, v in zip(model["names"], se)},
        "cr2_definition": "A_g=(I-X_g(X'X)^-1X_g')^-1/2; cluster meat=sum_g X_g'A_g e_g e_g'A_g X_g",
        "ci_reference": "Student-t with df=clusters-rank",
        "df": df,
        "beta_x": beta,
        "beta_x_se": beta_se,
        "beta_x_ci95": [beta - t95 * beta_se, beta + t95 * beta_se],
        "beta_x_ci90": [beta - t90 * beta_se, beta + t90 * beta_se],
        "rmse_in_sample": model["rmse"],
    }


def predict_rmse(rows, coefficients, include_x):
    X, names = design_matrix(rows, include_x=include_x)
    beta = np.array([coefficients[name] for name in names], dtype=float)
    y = np.array([r["y"] for r in rows], dtype=float)
    return float(math.sqrt(float(np.mean((y - X @ beta) ** 2))))


def bootstrap(rows, dev_models, seed, B=BOOTSTRAP_REPS):
    """Efficient whole-cell pairs bootstrap from per-cell sufficient statistics."""
    X, full_names = design_matrix(rows, include_x=True)
    X0, base_names = design_matrix(rows, include_x=False)
    y = np.array([r["y"] for r in rows], dtype=float)
    full_coef = np.array([dev_models["full_coefficients"][n] for n in full_names])
    base_coef = np.array([dev_models["baseline_coefficients"][n] for n in base_names])
    by_cell = defaultdict(list)
    cell_noise = {}
    for i, row in enumerate(rows):
        by_cell[row["cell_id"]].append(i)
        cell_noise[row["cell_id"]] = row["noise_rad"]
    stats_by_cell = {}
    for cell_id, indices in by_cell.items():
        idx = np.array(indices, dtype=int)
        Xg, X0g, yg = X[idx], X0[idx], y[idx]
        stats_by_cell[cell_id] = {
            "xtx": Xg.T @ Xg,
            "xty": Xg.T @ yg,
            "full_sse": float(np.sum((yg - Xg @ full_coef) ** 2)),
            "base_sse": float(np.sum((yg - X0g @ base_coef) ** 2)),
            "n": len(idx),
        }
    strata = []
    for noise in NOISE_RAD:
        cells = sorted(cell for cell in by_cell if cell_noise[cell] == noise)
        if len(cells) != 135:
            raise ValueError("bootstrap requires 135 complete cells per noise stratum")
        strata.append(cells)
    rng = random.Random(seed)
    betas, improvements = [], []
    beta_index = full_names.index("x")
    p = len(full_names)
    for _ in range(B):
        xtx = np.zeros((p, p))
        xty = np.zeros(p)
        full_sse = base_sse = 0.0
        n = 0
        for cells in strata:
            for _draw in range(len(cells)):
                stat = stats_by_cell[cells[rng.randrange(len(cells))]]
                xtx += stat["xtx"]
                xty += stat["xty"]
                full_sse += stat["full_sse"]
                base_sse += stat["base_sse"]
                n += stat["n"]
        coef = np.linalg.solve(xtx, xty)
        betas.append(float(coef[beta_index]))
        full_rmse = math.sqrt(full_sse / n)
        base_rmse = math.sqrt(base_sse / n)
        improvements.append((base_rmse - full_rmse) / base_rmse)
    return {
        "method": "noise-stratified whole-cell pairs bootstrap",
        "rng": "Python random.Random (MT19937)",
        "B": B,
        "seed": str(seed),
        "beta_x_ci95": [float(np.quantile(betas, 0.025, method="linear")),
                         float(np.quantile(betas, 0.975, method="linear"))],
        "rmse_improvement_ci95": [
            float(np.quantile(improvements, 0.025, method="linear")),
            float(np.quantile(improvements, 0.975, method="linear"))],
    }


def selection_summary(rows, all_beta):
    reasons = Counter(r["production_reason"] for r in rows)
    solved = [r for r in rows if r["production_solved"]]
    rejected = [r for r in rows if not r["production_solved"]]
    cells = defaultdict(list)
    for row in rows:
        cells[row["cell_id"]].append(row)
    per_cell = {key: sum(bool(r["production_solved"]) for r in values) / len(values)
                for key, values in cells.items()}
    solved_beta = None
    solved_fit_status = "insufficient solved rows"
    if len(solved) >= 100:
        try:
            solved_beta = fit_summary(solved)["beta_x"]
            solved_fit_status = "estimated conditionally on production solve"
        except (ValueError, np.linalg.LinAlgError) as exc:
            solved_fit_status = f"unavailable: {type(exc).__name__}"

    def x_summary(values):
        if not values:
            return None
        data = np.array([r["x"] for r in values], dtype=float)
        return {"n": len(values), "mean": float(np.mean(data)),
                "q10": float(np.quantile(data, 0.10, method="linear")),
                "median": float(np.median(data)),
                "q90": float(np.quantile(data, 0.90, method="linear"))}

    return {
        "attempted": len(rows), "solved": len(solved),
        "rejected": len(rows) - len(solved), "reasons": dict(sorted(reasons.items())),
        "overall_solvability": len(solved) / len(rows),
        "minimum_cell_solvability": min(per_cell.values()),
        "cells_below_80_percent": sorted(k for k, v in per_cell.items() if v < 0.8),
        "predictor_distribution_all": x_summary(rows),
        "predictor_distribution_solved": x_summary(solved),
        "predictor_distribution_rejected": x_summary(rejected),
        "solved_only_beta_x": solved_beta, "solved_only_fit_status": solved_fit_status,
        "absolute_solved_vs_all_beta_difference": (
            abs(solved_beta - all_beta) if solved_beta is not None else None),
    }


def descriptive_summary(rows, model):
    x = np.array([r["x"] for r in rows], dtype=float)
    y = np.array([r["y"] for r in rows], dtype=float)
    fitted = model["X"] @ model["coef"]
    for row, prediction, residual in zip(rows, fitted, y - fitted):
        row["primary_fitted_y"] = float(prediction)
        row["primary_residual"] = float(residual)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["cell_id"]].append(row["relative_position_error"])
    return {
        "pearson_r": float(np.corrcoef(x, y)[0, 1]),
        "spearman_rho": float(np.corrcoef(stats.rankdata(x), stats.rankdata(y))[0, 1]),
        "residual_mean": float(np.mean(y - fitted)),
        "residual_sd": float(np.std(y - fitted, ddof=model["X"].shape[1])),
        "cell_median_relative_errors": {cell: float(np.median(values))
                                         for cell, values in sorted(grouped.items())},
        "note": "Descriptive only; primary inference is the preregistered CR2 model.",
    }


def secondary_interactions(rows):
    model = ols(rows, include_x=True, interactions=True)
    cov, se, df = cr2_cluster(model, rows)
    pvals = []
    output = {}
    for name in model["names"]:
        if not name.startswith("x:"):
            continue
        j = model["names"].index(name)
        value, stderr = float(model["coef"][j]), float(se[j])
        p = 2.0 * float(stats.t.sf(abs(value / stderr), df)) if stderr > 0 else 0.0
        pvals.append((name, p))
        output[name] = {"coefficient": value, "cr2_se": stderr, "p_value": p}
    ordered = sorted(pvals, key=lambda item: item[1])
    adjusted = {}
    running = 0.0
    m = len(ordered)
    for rank, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[name] = running
    for name in output:
        output[name]["holm_adjusted_p"] = adjusted[name]
    return {"definition": "prespecified X-by-frame and X-by-orientation interactions",
            "results": output}


def source_hashes():
    paths = [ROOT / "intake.py", Path(__file__).resolve()]
    return {str(p.relative_to(ROOT)): sha256_file(p) for p in paths}


def environment_manifest():
    import scipy
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "platform": platform.platform(), "numpy": np.__version__, "scipy": scipy.__version__}


def load_protocol(require_frozen=False):
    data = json.loads(PROTOCOL_PATH.read_text())
    if require_frozen and data.get("status") != "frozen":
        raise RuntimeError("holdout protocol is not frozen")
    if require_frozen and data.get("source_hashes") != source_hashes():
        raise RuntimeError("frozen source hashes do not match current files")
    return data


def write_rows_csv(path, rows):
    scalar_keys = [k for k, v in rows[0].items() if not isinstance(v, (list, dict))]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=scalar_keys, lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: row[k] for k in scalar_keys} for row in rows)


def execute_design(master_seed, reps, production):
    rows = []
    for cell in design_cells():
        for replicate in range(reps):
            rows.append(generate_world(cell, replicate, master_seed, production=production))
    return rows


def run_dev(output):
    if output.exists():
        raise RuntimeError("development result already exists; refusing overwrite")
    rows = execute_design(DEV_SEED, DEV_REPS, production=False)
    full = ols(rows, include_x=True)
    baseline = ols(rows, include_x=False)
    result = {
        "schema": SCHEMA, "phase": "development", "seed": DEV_SEED,
        "worlds": len(rows), "cells": len(design_cells()), "replicates_per_cell": DEV_REPS,
        "fit": fit_summary(rows),
        "prediction_models": {
            "full_coefficients": {n: float(v) for n, v in zip(full["names"], full["coef"])},
            "baseline_coefficients": {n: float(v) for n, v in zip(baseline["names"], baseline["coef"])},
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(result))
    rows_path = output.with_suffix(".rows.json")
    rows_path.write_bytes(canonical_bytes(rows))
    print(json.dumps({"phase": "development", "result": str(output),
                      "sha256": sha256_file(output), "worlds": len(rows)}, sort_keys=True))


def freeze_protocol(dev_path):
    data = load_protocol(require_frozen=False)
    if data.get("status") == "frozen":
        raise RuntimeError("protocol already frozen")
    dev = json.loads(dev_path.read_text())
    if dev.get("phase") != "development" or dev.get("seed") != DEV_SEED:
        raise RuntimeError("invalid development artifact")
    data["status"] = "frozen"
    data["source_hashes"] = source_hashes()
    data["development_artifact"] = {
        "path": str(dev_path.relative_to(ROOT)), "sha256": sha256_file(dev_path),
        "prediction_models": dev["prediction_models"],
    }
    frozen = canonical_bytes(data)
    PROTOCOL_PATH.write_bytes(frozen)
    print(json.dumps({"status": "frozen", "protocol": str(PROTOCOL_PATH),
                      "sha256": sha256_bytes(frozen)}, sort_keys=True))


def run_holdout():
    protocol = load_protocol(require_frozen=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_path = RESULTS_DIR / "holdout-2026080502.json"
    rows_json = RESULTS_DIR / "holdout-2026080502.rows.json"
    rows_csv = RESULTS_DIR / "holdout-2026080502.rows.csv"
    manifest_path = RESULTS_DIR / "holdout-2026080502.manifest.json"
    for path in (result_path, rows_json, rows_csv, manifest_path):
        if path.exists():
            raise RuntimeError(f"one-shot holdout artifact already exists: {path}")
    started_wall = time.time()
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_wall))
    rows = execute_design(HOLDOUT_SEED, HOLDOUT_REPS, production=True)
    primary_model = ols(rows, include_x=True)
    primary = fit_summary(rows)
    descriptive = descriptive_summary(rows, primary_model)
    dev_models = protocol["development_artifact"]["prediction_models"]
    full_rmse = predict_rmse(rows, dev_models["full_coefficients"], True)
    base_rmse = predict_rmse(rows, dev_models["baseline_coefficients"], False)
    improvement = (base_rmse - full_rmse) / base_rmse
    bootstrap_seed = domain_seed(HOLDOUT_SEED, "all-cells", 0, "bootstrap")
    boot = bootstrap(rows, dev_models, bootstrap_seed)
    selection = selection_summary(rows, primary["beta_x"])
    secondary = secondary_interactions(rows)
    criteria = {
        "1_cr2_ci95_beta_above_zero": primary["beta_x_ci95"][0] > 0,
        "2_cr2_ci90_beta_within_0.75_1.25": (
            primary["beta_x_ci90"][0] >= 0.75 and primary["beta_x_ci90"][1] <= 1.25),
        "3_holdout_rmse_improvement_at_least_10pct_and_ci_above_zero": (
            improvement >= 0.10 and boot["rmse_improvement_ci95"][0] > 0),
        "4_all_6480_statuses_reported": selection["attempted"] == 6480,
        "5_selection_thresholds": (
            selection["overall_solvability"] >= 0.90 and
            selection["minimum_cell_solvability"] >= 0.80 and
            selection["absolute_solved_vs_all_beta_difference"] is not None and
            selection["absolute_solved_vs_all_beta_difference"] <= 0.15),
        "6_prespecified_interactions_reported": len(secondary["results"]) == 4,
    }
    physical = all(criteria[k] for k in list(criteria)[:3])
    production = all(criteria.values())
    if production:
        verdict = "Fresh holdout strengthened physical-law and production-output evidence."
    elif physical:
        verdict = "Fresh holdout supported the physical error law; production gating induces material selection or reporting limits."
    else:
        verdict = "Fresh holdout did not provide stronger evidence."
    result = {
        "schema": SCHEMA, "phase": "holdout", "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "source_hashes": source_hashes(), "seed": HOLDOUT_SEED,
        "worlds": len(rows), "cells": len(design_cells()), "replicates_per_cell": HOLDOUT_REPS,
        "primary_predictor": PRIMARY_PREDICTOR, "primary_outcome": PRIMARY_OUTCOME,
        "primary_fit": primary,
        "development_frozen_prediction": {
            "full_rmse": full_rmse, "baseline_rmse": base_rmse,
            "relative_rmse_improvement": improvement,
        },
        "bootstrap": boot, "selection": selection, "secondary": secondary,
        "descriptive": descriptive,
        "criteria": criteria, "physical_law_supported": physical,
        "production_output_supported": production, "verdict": verdict,
        "zero_or_quantized_primary_error_count": sum(r["position_error_3d_m"] <= 0 for r in rows),
    }
    result_bytes = canonical_bytes(result)
    if result_bytes != canonical_bytes(json.loads(result_bytes)):
        raise RuntimeError("canonical result serialization is not byte-stable")
    rows_bytes = canonical_bytes(rows)
    result_path.write_bytes(result_bytes)
    rows_json.write_bytes(rows_bytes)
    write_rows_csv(rows_csv, rows)
    ended_wall = time.time()
    manifest = {
        "schema": f"{SCHEMA}/run-manifest", "started_utc": started_utc,
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ended_wall)),
        "runtime_seconds": ended_wall - started_wall, "environment": environment_manifest(),
        "artifacts": {str(p.relative_to(ROOT)): sha256_file(p)
                      for p in (PROTOCOL_PATH, result_path, rows_json, rows_csv)},
        "reproduction_command": "python3 evidence/stronger_evidence.py verify",
        "one_shot_rule": "No alternate seed, threshold, transform, sample size, or rerun is permitted.",
    }
    manifest_path.write_bytes(canonical_bytes(manifest))
    print(json.dumps({"verdict": verdict, "criteria": criteria,
                      "result": str(result_path), "manifest": str(manifest_path)}, sort_keys=True))


def verify():
    protocol = load_protocol(require_frozen=True)
    result_path = RESULTS_DIR / "holdout-2026080502.json"
    rows_json = RESULTS_DIR / "holdout-2026080502.rows.json"
    rows_csv = RESULTS_DIR / "holdout-2026080502.rows.csv"
    manifest_path = RESULTS_DIR / "holdout-2026080502.manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for rel, expected in manifest["artifacts"].items():
        path = ROOT / rel
        if not path.exists() or sha256_file(path) != expected:
            raise RuntimeError(f"artifact verification failed: {rel}")
    result = json.loads(result_path.read_text())
    rows = json.loads(rows_json.read_text())
    if result_path.read_bytes() != canonical_bytes(result):
        raise RuntimeError("result JSON is not canonical byte-for-byte")
    if rows_json.read_bytes() != canonical_bytes(rows):
        raise RuntimeError("row JSON is not canonical byte-for-byte")
    if len(rows) != 6480 or result.get("worlds") != 6480:
        raise RuntimeError("holdout completeness check failed")
    print(json.dumps({"verified": True, "protocol_status": protocol["status"],
                      "result_sha256": sha256_file(result_path),
                      "rows_sha256": sha256_file(rows_json),
                      "csv_sha256": sha256_file(rows_csv)}, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    dev = sub.add_parser("dev")
    dev.add_argument("--output", type=Path,
                     default=ROOT / "evidence" / "results" / "development-2026080501.json")
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--dev", type=Path,
                        default=ROOT / "evidence" / "results" / "development-2026080501.json")
    sub.add_parser("holdout")
    sub.add_parser("verify")
    args = parser.parse_args(argv)
    if args.command == "dev":
        run_dev(args.output)
    elif args.command == "freeze":
        freeze_protocol(args.dev)
    elif args.command == "holdout":
        run_holdout()
    else:
        verify()


if __name__ == "__main__":
    main()
