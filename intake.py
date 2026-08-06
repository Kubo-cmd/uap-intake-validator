"""intake — UAP sighting-intake validator.

One question, answered honestly: can THIS sighting support a range/speed/size
claim at all? Output is split into ASSUMED (analyst-supplied) vs ESTABLISHED
(this tool's measurement) per LYTA doctrine.

Stdlib-only. Methodology credit: upstream Sitrec2 (CV-family conditioning).
"""
from math import hypot, sqrt, log10, sin, cos, pi, isfinite
from sys import float_info

from uap_conditioning import (
    assess_conditioning,
    LINEAR_RCOND_POOR,
    LINEAR_RCOND_MARGINAL,
)

REQUIRED_FIELDS = ["timestamp_utc", "sensor_position", "position_datum", "field_of_view_deg"]
RECOMMENDED_FIELDS = ["time_sync_precision_s", "platform_motion", "sensor_type", "bearing_count"]

COND_RANK = {"poor": 0, "marginal": 1, "good": 2}
MAX_SAFE_COMPONENT = sqrt(float_info.max) / 10
MIN_SAFE_FPS = 1.0 / MAX_SAFE_COMPONENT
NUMERIC_REL_FLOOR = 5e-5
MAX_TRIANGULATION_SYNC_S = 1.0


def _finite_number(value):
    """True for finite machine-usable numbers, including bounded Python ints."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except (OverflowError, ValueError):
        return False


def _valid_fps(value):
    if not _finite_number(value):
        return False
    return 0 < float(value) <= MAX_SAFE_COMPONENT


def _vector_series_error(sensor_pos, los_dir, label):
    """Return a human-readable error for malformed flat xyz series."""
    for name, values in (("sensor positions", sensor_pos), ("bearing vectors", los_dir)):
        if not isinstance(values, (list, tuple)) or not values:
            return f"{label} {name} must be a non-empty flat xyz array"
        if len(values) % 3:
            return f"{label} {name} length must be divisible by 3"
        if any(not _finite_number(v) for v in values):
            return f"{label} {name} must contain only finite numbers"
        if any(abs(v) > MAX_SAFE_COMPONENT for v in values):
            return f"{label} {name} exceeds the supported numeric magnitude"
    if len(sensor_pos) != len(los_dir):
        return f"{label} sensor-position and bearing counts must match"
    for i in range(0, len(los_dir), 3):
        if hypot(los_dir[i], los_dir[i + 1], los_dir[i + 2]) <= 0:
            return f"{label} bearing vector {i // 3} has zero length"
    return None


# ---------- intake completeness ----------

def _present(rec, key):
    v = rec.get(key)
    return v is not None and v != "" and v != []


def validate_intake(record):
    """Check required/recommended metadata. Returns completeness + assumed-notes."""
    if not isinstance(record, dict):
        return {
            "complete": False,
            "missing_required": list(REQUIRED_FIELDS),
            "missing_recommended": list(RECOMMENDED_FIELDS),
            "assumed": ["top-level sighting record must be a JSON object"],
        }
    missing_req = [f for f in REQUIRED_FIELDS if not _present(record, f)]
    missing_rec = [f for f in RECOMMENDED_FIELDS if not _present(record, f)]
    assumed = []
    if not _present(record, "platform_motion"):
        assumed.append("platform motion unknown — parallax cannot be assessed")
    if _present(record, "time_sync_precision_s"):
        try:
            if float(record["time_sync_precision_s"]) > 30:
                assumed.append("time sync worse than ±30s — satellite/star matches unreliable")
        except (TypeError, ValueError, OverflowError):
            assumed.append("time_sync_precision_s not numeric")
    return {
        "complete": not missing_req,
        "missing_required": missing_req,
        "missing_recommended": missing_rec,
        "assumed": assumed,
    }


# ---------- noise stability ----------

def noise_stability(sensor_pos, los_dir, times=None, fps=None,
                    bearing_noise_rad=5e-4, trials=24, seed=37):
    """Re-run conditioning under random bearing noise. A verdict that flips
    under tiny noise is not trustworthy — say so. Deterministic seed."""
    import random as _r
    rng = _r.Random(seed)
    n = len(los_dir) // 3
    if n < 2:
        return {"stable": None, "note": "insufficient frames"}
    base = assess_conditioning(sensor_pos, los_dir, times=times, fps=fps).get("conditioning")
    held = 0
    for _ in range(trials):
        noisy = list(los_dir)
        for i in range(n):
            b = i * 3
            noisy[b] += rng.gauss(0, bearing_noise_rad)
            noisy[b + 1] += rng.gauss(0, bearing_noise_rad)
        if assess_conditioning(sensor_pos, noisy, times=times, fps=fps).get("conditioning") == base:
            held += 1
    frac = held / trials
    stable = frac >= 0.9
    return {
        "verdict": base, "held": held, "trials": trials, "stable": stable,
        "note": (f"verdict '{base}' held in {held}/{trials} noisy trials "
                 f"(noise {bearing_noise_rad:g} rad)"
                 + ("" if stable else " — UNSTABLE: do not trust the headline conditioning alone")),
    }


# ---------- underdetermination flag ----------

def _remediation(record, res):
    if res.get("conditioning") == "good":
        return None
    out = []
    sensor_count = record.get("sensor_count", 1)
    has_multiple_sensors = (_finite_number(sensor_count) and sensor_count >= 2)
    if not has_multiple_sensors and not record.get("sensor_pos_2"):
        out.append("add a second simultaneous observer — triangulation resolves "
                   "range independent of CV geometry (strongest fix; provide "
                   "sensor_pos_2 + los_dir_2 and this tool will solve it)")
    out.append("widen the parallax baseline: turning/orbiting platform or a longer "
               "track raises conditioning monotonically")
    if res.get("conditioning") == "marginal":
        out.append("marginal is near the collapse threshold — a modest baseline "
                   "increase or second sensor is likely sufficient")
    out.append("method-local: a stationary-point or physics (wind/balloon) fit may "
               "succeed where CV collapses — a 'poor' CV flag is not 'unanalyzable "
               "by any method'")
    return out


def underdetermination_flag(record):
    """Run the CV-family conditioning diagnostic if sightlines are present."""
    if not isinstance(record, dict):
        error = "top-level sighting record must be a JSON object"
        return {
            "rcond": None, "log10Rcond": None, "effectiveRank": None,
            "conditioning": "poor", "valid": False, "error": error,
            "reading": f"INVALID SIGHTLINE DATA — {error}",
            "remediation": ["provide one JSON object containing the sighting fields"],
        }
    sp = record.get("sensor_pos_ecef") or record.get("sensor_pos")
    ld = record.get("los_dir")
    if not sp or not ld:
        return None
    error = _vector_series_error(sp, ld, "primary sensor")
    if error:
        return {
            "rcond": None, "log10Rcond": None, "effectiveRank": None,
            "conditioning": "poor", "valid": False, "error": error,
            "reading": f"INVALID SIGHTLINE DATA — {error}",
            "remediation": ["correct the primary sensor xyz arrays before analysis"],
        }
    times, fps = record.get("times"), record.get("fps")
    count = len(ld) // 3
    positions = record.get("positions")
    if positions is not None:
        error = _vector_series_error(positions, ld, "fitted track")
        if error:
            return {
                "rcond": None, "log10Rcond": None, "effectiveRank": None,
                "conditioning": "poor", "valid": False, "error": error,
                "reading": f"INVALID SIGHTLINE DATA — {error}",
                "remediation": ["correct the fitted-track xyz array before analysis"],
            }
    if times is not None:
        if (not isinstance(times, (list, tuple)) or len(times) != count or
                any(not _finite_number(v) for v in times)):
            error = "times must contain one finite numeric value per bearing"
            return {
                "rcond": None, "log10Rcond": None, "effectiveRank": None,
                "conditioning": "poor", "valid": False, "error": error,
                "reading": f"INVALID SIGHTLINE DATA — {error}",
                "remediation": ["correct the bearing timestamps before analysis"],
            }
    elif fps is None and count == 1:
        # A single bearing has no temporal spacing to validate; use a neutral
        # placeholder for the conditioning diagnostic without weakening multi-frame sync.
        fps = 1.0
    elif not _valid_fps(fps):
        error = "provide a finite positive fps or one timestamp per bearing"
        return {
            "rcond": None, "log10Rcond": None, "effectiveRank": None,
            "conditioning": "poor", "valid": False, "error": error,
            "reading": f"INVALID SIGHTLINE DATA — {error}",
            "remediation": ["add valid timing before conditioning analysis"],
        }
    noise = record.get("bearing_noise_rad", 5e-4)
    if not _finite_number(noise) or not 0 <= noise <= pi:
        error = "bearing_noise_rad must be a finite number from 0 to pi radians"
        return {
            "rcond": None, "log10Rcond": None, "effectiveRank": None,
            "conditioning": "poor", "valid": False, "error": error,
            "reading": f"INVALID SIGHTLINE DATA — {error}",
            "remediation": ["correct the angular-noise estimate before analysis"],
        }
    res = assess_conditioning(sp, ld, times=times, fps=fps, positions=positions)
    res["reading"] = (
        "RANGE UNRELIABLE — geometry cannot pin range for CV-family fits; a published "
        "range/speed/size is an artifact of the assumption"
        if res.get("conditioning") == "poor"
        else "marginal — treat range with caution"
        if res.get("conditioning") == "marginal"
        else "conditioning good — NOT a guarantee the range is correct (one-way warning)")
    res["remediation"] = _remediation(record, res)
    res["stability"] = noise_stability(sp, ld, times=times, fps=fps,
                                       bearing_noise_rad=noise)
    return res


# ---------- two-sensor triangulation (the actual fix) ----------

def _mc_range_uncertainty(record, s_nom, t_nom, p1, d1, p2, d2, rng_m, sigma,
                          trials=200, seed=7):
    """Estimate range uncertainty by perturbing EVERY bearing in both sensors by
    `sigma`, re-running the full averaging + closest-approach solve, and taking
    the EMPIRICAL 95th-percentile absolute deviation of the recovered range from
    the nominal solve. A calibrated interval beats a std-dev here: the nested
    audit showed the range-error distribution is heavier-tailed than Gaussian, so
    a symmetric ±k*std under-covers (2σ caught only ~77%). Reporting the actual
    95th-percentile deviation makes the quoted bound self-calibrating.

    Returns (p95_abs_dev_m, rel_uncertainty) where rel = p95 / nominal range.
    `trials=200` so the 95th percentile rests on ~10 tail samples, not 1-2."""
    import random as _r
    rng = _r.Random(seed)
    numeric_floor = NUMERIC_REL_FLOOR * rng_m
    if sigma <= 0:
        return numeric_floor, NUMERIC_REL_FLOOR
    sp1 = record.get("sensor_pos_ecef") or record.get("sensor_pos")
    sp2 = record.get("sensor_pos_2")
    ld1 = record.get("los_dir"); ld2 = record.get("los_dir_2")

    def perturb(ld):
        out = list(ld)
        for i in range(len(ld) // 3):
            b = i * 3
            x, y, z = ld[b], ld[b+1], ld[b+2]
            m = hypot(x, y, z) or 1.0
            x, y, z = x/m, y/m, z/m
            a = rng.gauss(0, sigma); bb = rng.gauss(0, sigma)
            x1 = x*cos(a) - y*sin(a); y1 = x*sin(a) + y*cos(a)
            y2 = y1*cos(bb) - z*sin(bb); z2 = y1*sin(bb) + z*cos(bb)
            out[b], out[b+1], out[b+2] = x1*m, y2*m, z2*m
        return out

    devs = []
    for _ in range(trials):
        sub = {"sensor_pos": list(sp1), "los_dir": perturb(ld1),
               "sensor_pos_2": list(sp2), "los_dir_2": perturb(ld2),
               "bearing_noise_rad": sigma}
        if "fps" in record:
            sub["fps"] = record["fps"]
        if "times" in record:
            sub["times"] = list(record["times"])
        tr = triangulate(sub, _mc=False)
        if tr and tr.get("solvable"):
            devs.append(abs(tr["range_m"] - rng_m))
    if len(devs) < 20:
        return float("inf"), float("inf")
    devs.sort()
    # empirical 95th percentile absolute deviation (linear interpolation)
    k = 0.95 * (len(devs) - 1)
    lo = int(k); frac = k - lo
    p95 = devs[lo] + (devs[lo + 1] - devs[lo]) * frac if lo + 1 < len(devs) else devs[-1]
    p95 = max(p95, numeric_floor)
    return p95, (p95 / rng_m if rng_m > 0 else float("inf"))


def triangulate(record, _mc=True):
    """If a second sensor (sensor_pos_2, los_dir_2) is present, solve the
    closest-approach of the two bearing rays → a REAL position, independent of
    the CV conditioning. This is the remediation made concrete.

    Solves every synchronized pair and reports the deterministic center frame.
    This keeps the result tied to one real frame even when the target moves and
    avoids best-of-N selection bias under bearing noise.
    Returns None if no second sensor exists."""
    if not isinstance(record, dict):
        return {"solvable": False, "input_valid": False,
                "reason": "top-level sighting record must be a JSON object"}
    sp1 = record.get("sensor_pos_ecef") or record.get("sensor_pos")
    ld1 = record.get("los_dir")
    sp2 = record.get("sensor_pos_2")
    ld2 = record.get("los_dir_2")
    if not sp2 and not ld2:
        return None
    if not (sp1 and ld1 and sp2 and ld2):
        return {"solvable": False, "input_valid": False,
                "reason": "both sensors require position and bearing xyz arrays"}
    error = (_vector_series_error(sp1, ld1, "primary sensor") or
             _vector_series_error(sp2, ld2, "second sensor"))
    if error:
        return {"solvable": False, "input_valid": False, "reason": error}
    if len(ld1) != len(ld2):
        return {"solvable": False, "input_valid": False,
                "reason": "both sensors require the same number of synchronized bearings"}
    fps = record.get("fps")
    if fps is not None and (
            not _finite_number(fps) or
            not MIN_SAFE_FPS <= fps <= MAX_SAFE_COMPONENT):
        return {"solvable": False, "input_valid": False,
                "reason": "fps must be finite and within the supported positive magnitude"}
    if len(ld1) // 3 > 1 and fps is None and "times" not in record:
        return {"solvable": False, "input_valid": False,
                "reason": "multi-frame triangulation requires fps or one timestamp per frame"}
    if "times" in record:
        raw_times = record.get("times")
        if (not isinstance(raw_times, (list, tuple)) or
                len(raw_times) != len(ld1) // 3 or
                any(not _finite_number(value) or abs(value) > MAX_SAFE_COMPONENT
                    for value in raw_times)):
            return {"solvable": False, "input_valid": False,
                    "reason": "times must contain one finite timestamp per bearing frame"}
        times = [float(value) for value in raw_times]
        if any(times[i] <= times[i - 1] for i in range(1, len(times))):
            return {"solvable": False, "input_valid": False,
                    "reason": "times must be strictly increasing"}
    sigma = record.get("bearing_noise_rad", 5e-4)
    if not _finite_number(sigma) or not 0 <= sigma <= pi:
        return {"solvable": False, "input_valid": False,
                "reason": "bearing_noise_rad must be a finite number from 0 to pi radians"}
    sync_precision = record.get("time_sync_precision_s")
    if sync_precision is not None and (
            not _finite_number(sync_precision) or
            not 0 <= sync_precision <= MAX_TRIANGULATION_SYNC_S):
        return {
            "solvable": False, "input_valid": False,
            "reason": ("time_sync_precision_s must be finite and between 0 and "
                       f"{MAX_TRIANGULATION_SYNC_S:g} seconds for triangulation"),
        }

    def ray(sp, ld, i):
        b = i * 3
        p = (sp[b], sp[b + 1], sp[b + 2])
        d = (ld[b], ld[b + 1], ld[b + 2])
        n = hypot(*d) or 1.0
        return p, (d[0] / n, d[1] / n, d[2] / n)

    def solve_pair(p1, d1, p2, d2):
        """Apply the physical forward-ray and stated-noise gates to one pair."""
        dot = sum(d1[k] * d2[k] for k in range(3))
        if 1.0 - abs(dot) < 1e-4:
            return {"solvable": False, "reason": "second-sensor rays near-parallel — "
                    "baseline too small to triangulate"}
        w0 = tuple(p1[k] - p2[k] for k in range(3))
        a = sum(d1[k] * d1[k] for k in range(3))
        b = sum(d1[k] * d2[k] for k in range(3))
        c = sum(d2[k] * d2[k] for k in range(3))
        dd = sum(d1[k] * w0[k] for k in range(3))
        e = sum(d2[k] * w0[k] for k in range(3))
        denom = a * c - b * b
        if abs(denom) < 1e-12:
            return {"solvable": False, "reason": "degenerate ray pair"}
        s = (b * e - c * dd) / denom
        t = (a * e - b * dd) / denom
        if s <= 0 or t <= 0:
            return {"solvable": False, "input_valid": True,
                    "reason": "closest line intersection lies behind an observer — "
                              "bearing rays do not support a physical position"}
        pt1 = tuple(p1[k] + s * d1[k] for k in range(3))
        pt2 = tuple(p2[k] + t * d2[k] for k in range(3))
        miss = hypot(pt1[0] - pt2[0], pt1[1] - pt2[1], pt1[2] - pt2[2])
        miss_limit = max(1e-6, 3.0 * sigma * hypot(s, t))
        if miss > miss_limit:
            return {
                "solvable": False, "input_valid": True,
                "reason": "bearing rays disagree beyond their stated angular uncertainty",
                "miss_distance_m": round(miss, 2),
                "miss_limit_m": round(miss_limit, 2),
            }
        return {"solvable": True, "s": s, "t": t, "pt1": pt1, "pt2": pt2,
                "miss": miss}

    # Opposite per-frame residuals must never cancel into a fictitious perfect
    # average ray. Every synchronized pair must pass the same physical gates.
    # Report one actual synchronized center frame rather than averaging a moving
    # target into a point that never existed. A deterministic frame also avoids the
    # winner's-curse uncertainty bias of selecting the noisiest apparent crossing.
    frame_solutions = []
    for i in range(len(ld1) // 3):
        p1_i, d1_i = ray(sp1, ld1, i)
        p2_i, d2_i = ray(sp2, ld2, i)
        frame = solve_pair(p1_i, d1_i, p2_i, d2_i)
        if not frame.get("solvable"):
            frame = dict(frame)
            frame["reason"] = f"synchronized frame pair {i}: {frame['reason']}"
            return frame
        frame.update({"index": i, "p1": p1_i, "d1": d1_i,
                      "p2": p2_i, "d2": d2_i})
        frame_solutions.append(frame)

    aggregate = frame_solutions[(len(frame_solutions) - 1) // 2]
    selected_frame_index = aggregate["index"]
    p1, d1 = aggregate["p1"], aggregate["d1"]
    p2, d2 = aggregate["p2"], aggregate["d2"]
    s, t = aggregate["s"], aggregate["t"]
    pt1, pt2 = aggregate["pt1"], aggregate["pt2"]
    mid = tuple((pt1[k] + pt2[k]) / 2 for k in range(3))
    miss = aggregate["miss"]
    baseline = hypot(p1[0]-p2[0], p1[1]-p2[1], p1[2]-p2[2])
    rng_m = hypot(mid[0]-p1[0], mid[1]-p1[1], mid[2]-p1[2])

    # Honest uncertainty via MONTE-CARLO noise propagation: perturb both bearing
    # sets by the reported angular noise, re-solve, and report the empirical
    # spread of the recovered position/range. Self-calibrating — no hand-tuned
    # error formula (a nested-simulation audit showed the naive first-order
    # estimate underestimates ~4x; MC propagation does not have that bias).
    base_over_range = baseline / rng_m if rng_m > 0 else 0.0
    if _mc:
        sigma_range, rel_unc = _mc_range_uncertainty(
            record, s, t, p1, d1, p2, d2, rng_m, sigma)
    else:
        sigma_range, rel_unc = 0.0, 0.0

    if _mc and (not isfinite(sigma_range) or not isfinite(rel_unc)):
        return {
            "solvable": False,
            "input_valid": True,
            "reason": ("uncertainty calibration failed: too few finite Monte Carlo "
                       "re-solves; no range claim is permitted"),
            "selected_frame_index": selected_frame_index,
        }

    sync_verified = sync_precision is not None
    confident = isfinite(rel_unc) and rel_unc < 0.05 and sync_verified
    if not sync_verified:
        confidence_note = ("LOW CONFIDENCE: cross-sensor synchronization precision was not "
                           "declared — range cannot be established from timestamp-free pairs.")
    elif confident:
        confidence_note = "Confidence OK."
    else:
        confidence_note = ("LOW CONFIDENCE: shallow baseline/range ratio amplifies angular "
                           "noise — treat the range as an estimate, widen the baseline or "
                           "add a third observer.")
    return {
        "solvable": True,
        "position_m": [round(v, 1) for v in mid],
        "range_m": round(rng_m, 1),
        "miss_distance_m": round(miss, 2),
        "baseline_m": round(baseline, 1),
        "sigma_range_m": round(sigma_range, 3),
        "interval_kind": "numerical-floor" if sigma <= 0 else "empirical-p95",
        "rel_uncertainty": round(rel_unc, 4),
        "sync_verified": sync_verified,
        "selected_frame_index": selected_frame_index,
        "confident": confident,
        "note": (f"two-sensor triangulation at synchronized frame "
                 f"{selected_frame_index} — a position independent of CV "
                 "conditioning. sigma_range is a CALIBRATED bound: the empirical "
                 f"95th-percentile range deviation under bearing noise ({sigma:g} rad), "
                 f"baseline/range ratio {base_over_range:.3f}. Treat the range as "
                 f"±sigma_range (≈95% coverage). {confidence_note}"),
    }


# ---------- top-level assessment ----------

def assess_sighting(record):
    intake = validate_intake(record)
    flag = underdetermination_flag(record)
    tri = triangulate(record)
    established = []
    if intake["complete"]:
        established.append("intake schema complete — analyzable in principle")
    if flag and flag.get("rcond") is not None:
        established.append(
            f"CV-family conditioning: rcond={flag['rcond']:.2e} "
            f"(log10={flag['log10Rcond']:.2f}, rank={flag['effectiveRank']}) -> {flag['conditioning']}")
        if flag.get("collapse"):
            established.append(f"fitted track COLLAPSED: {flag['collapseReason']}")
        if flag.get("stability") and flag["stability"].get("note"):
            established.append(f"noise stability: {flag['stability']['note']}")
    if tri:
        if tri.get("solvable"):
            established.append(
                f"TRIANGULATED: range {tri['range_m']} m at {tri['position_m']} "
                f"(miss {tri['miss_distance_m']} m, baseline {tri['baseline_m']} m) "
                f"— two-sensor position, CV-independent")
        else:
            established.append(f"triangulation attempted: {tri.get('reason')}")
    if flag and flag.get("error"):
        established.append(f"conditioning not run: {flag['error']}")
    if flag and flag.get("remediation"):
        for r in flag["remediation"]:
            established.append(f"remediation: {r}")

    # verdict
    if ((tri and tri.get("input_valid") is False) or
            (flag and flag.get("valid") is False)):
        verdict = "INVALID SIGHTLINE DATA"
    elif tri and tri.get("solvable") and tri.get("confident"):
        verdict = "RANGE ESTABLISHED (two-sensor triangulation)"
    elif tri and tri.get("solvable"):
        verdict = "RANGE ESTIMATE — LOW CONFIDENCE"

    elif flag and flag.get("conditioning") == "poor":
        verdict = "CANNOT SUPPORT RANGE CLAIM"
    elif not intake["complete"]:
        verdict = "INCOMPLETE INTAKE"
    else:
        verdict = "ANALYZABLE (with caveats)"

    return {
        "assumed": intake["assumed"],
        "established": established,
        "intake": intake,
        "underdetermination": flag,
        "triangulation": tri,
        "verdict": verdict,
    }
