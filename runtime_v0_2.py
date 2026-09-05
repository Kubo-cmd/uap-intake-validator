"""Version 0.2 active runtime for the UAP sighting-intake validator.

One question, answered honestly: can THIS sighting support a range/speed/size
claim at all? Output is split into ASSUMED (analyst-supplied) vs ESTABLISHED
(this tool's measurement) per LYTA doctrine.

This module is intentionally separate from frozen ``intake.py``. The latter is
part of the immutable v0.1.0 evidence bundle and is not an active import.

Stdlib-only. Methodology credit: upstream Sitrec2 (CV-family conditioning).
"""
from math import ceil, hypot, sqrt, log10, sin, cos, pi, isfinite
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
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 200_000
MAX_FRAMES = 10_000
MAX_STRING_CHARS = 65_536
RUNTIME_VERSION = "0.2.0-dev"
OPERATIVE_UNITS = "m"
ALLOWED_POSITION_FRAMES = frozenset(("ECEF", "ENU"))


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
        if not isinstance(values, list) or not values:
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


def _bounded_json_structure_error(record):
    """Iteratively reject non-JSON, cyclic, deep, wide, or huge-string API data."""
    nodes = 0
    active = set()
    stack = [(record, 0, False)]
    while stack:
        value, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(value))
            continue
        nodes += 1
        if nodes > MAX_JSON_NODES:
            return f"JSON structure exceeds {MAX_JSON_NODES} nodes"
        if isinstance(value, str):
            if len(value) > MAX_STRING_CHARS:
                return f"string exceeds {MAX_STRING_CHARS} characters"
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
                return "strings must contain only Unicode scalar values"
        elif value is None or isinstance(value, bool) or _finite_number(value):
            pass
        elif type(value) is dict or type(value) is list:
            if depth > MAX_JSON_DEPTH:
                return f"JSON structure exceeds maximum depth {MAX_JSON_DEPTH}"
            ident = id(value)
            if ident in active:
                return "cyclic containers are not valid JSON"
            active.add(ident)
            stack.append((value, depth, True))
            if type(value) is dict:
                for key, child in reversed(list(value.items())):
                    if not isinstance(key, str):
                        return "JSON object keys must be strings"
                    stack.append((child, depth + 1, False))
                    stack.append((key, depth + 1, False))
            else:
                for child in reversed(value):
                    stack.append((child, depth + 1, False))
        else:
            return f"unsupported non-JSON value type: {type(value).__name__}"
    return None


def _frame_count_preflight(record):
    """Reject oversized explicit arrays before numeric scans or matrix work."""
    if not isinstance(record, dict):
        return None
    for name in ("sensor_pos", "sensor_pos_ecef", "los_dir", "sensor_pos_2",
                 "los_dir_2", "positions"):
        values = record.get(name)
        if isinstance(values, list) and len(values) > 3 * MAX_FRAMES:
            return f"{name} exceeds the hard limit of {MAX_FRAMES} frames"
    times = record.get("times")
    if isinstance(times, list) and len(times) > MAX_FRAMES:
        return f"times exceeds the hard limit of {MAX_FRAMES} frames"
    return None


def validate_core_schema(record):
    """Validate bounded core types and the operative coordinate contract."""
    errors = []
    if not isinstance(record, dict):
        return ["top-level sighting record must be a JSON object"]
    structure_error = _bounded_json_structure_error(record)
    if structure_error:
        return [structure_error]
    preflight = _frame_count_preflight(record)
    if preflight:
        return [preflight]
    for name in ("timestamp_utc", "position_datum"):
        value = record.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 256):
            errors.append(f"{name} must be a non-empty string of at most 256 characters")
    fov = record.get("field_of_view_deg")
    if fov is not None and (not _finite_number(fov) or not 0 < fov <= 360):
        errors.append("field_of_view_deg must be a finite number in (0, 360]")
    count = record.get("bearing_count")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or
                              not 1 <= count <= MAX_FRAMES):
        errors.append(f"bearing_count must be an integer from 1 to {MAX_FRAMES}")
    sensor_count = record.get("sensor_count")
    if sensor_count is not None and (isinstance(sensor_count, bool) or
                                     not isinstance(sensor_count, int) or
                                     not 1 <= sensor_count <= 1024):
        errors.append("sensor_count must be an integer from 1 to 1024")
    operative = any(name in record for name in
                    ("sensor_pos", "sensor_pos_ecef", "sensor_pos_2", "positions"))
    if operative:
        units = record.get("position_units")
        frame = record.get("coordinate_frame")
        if units != OPERATIVE_UNITS:
            errors.append('position_units must be exactly "m"')
        if frame not in ALLOWED_POSITION_FRAMES:
            errors.append("coordinate_frame must be one of: " +
                          ", ".join(sorted(ALLOWED_POSITION_FRAMES)))
        if "sensor_pos_ecef" in record and frame != "ECEF":
            errors.append("sensor_pos_ecef requires coordinate_frame ECEF")
        if "sensor_pos" in record and "sensor_pos_ecef" in record:
            errors.append("sensor_pos and sensor_pos_ecef are mutually exclusive")
    if operative and record.get("bearing_units") != "dimensionless":
        errors.append('bearing_units must be exactly "dimensionless"')
    if "bearing_noise_rad" in record and record.get("bearing_noise_units") != "rad":
        errors.append('bearing_noise_units must be exactly "rad" when bearing_noise_rad is present')

    primary_pos = record.get("sensor_pos_ecef") if "sensor_pos_ecef" in record else record.get("sensor_pos")
    primary_los = record.get("los_dir")
    secondary_pos, secondary_los = record.get("sensor_pos_2"), record.get("los_dir_2")
    derived = None
    if primary_pos is not None or primary_los is not None:
        err = _vector_series_error(primary_pos, primary_los, "primary")
        if err:
            errors.append(err)
        elif primary_los:
            derived = len(primary_los) // 3
    if secondary_pos is not None or secondary_los is not None:
        err = _vector_series_error(secondary_pos, secondary_los, "secondary")
        if err:
            errors.append(err)
        elif derived is not None and len(secondary_los) // 3 != derived:
            errors.append("primary and secondary frame counts must match")
    if derived is not None and count is not None and count != derived:
        errors.append("bearing_count must equal the derived frame count")
    supplied_sensors = 2 if secondary_pos is not None or secondary_los is not None else (1 if derived else 0)
    if sensor_count is not None and supplied_sensors and sensor_count != supplied_sensors:
        errors.append("sensor_count must agree with supplied sensor sets")
    times = record.get("times")
    if times is not None:
        if not isinstance(times, list) or not times or any(not _finite_number(t) for t in times):
            errors.append("times must be a non-empty array of finite numbers")
        elif any(times[i] >= times[i + 1] for i in range(len(times) - 1)):
            errors.append("times must be strictly increasing")
        elif derived is not None and len(times) != derived:
            errors.append("times must contain one value per frame")
    if derived is not None and derived > 1 and times is not None and "fps" in record:
        errors.append("multi-frame input must declare exactly one timing basis: times or fps")
    return errors


def _schema_failure(error):
    return {
        "rcond": None, "log10Rcond": None, "effectiveRank": None,
        "conditioning": "poor", "valid": False, "error": error,
        "reading": f"INVALID SIGHTLINE DATA — {error}",
        "remediation": ["correct the bounded core schema before analysis"],
    }


def perturb_los_exponential(los_dir, sigma, rng):
    """Apply isotropic tangent-plane Gaussian noise through the sphere exp map."""
    out = list(los_dir)
    for i in range(len(los_dir) // 3):
        b = i * 3
        x, y, z = map(float, los_dir[b:b + 3])
        magnitude = hypot(x, y, z)
        ux, uy, uz = x / magnitude, y / magnitude, z / magnitude
        if abs(uz) < 0.9:
            ex, ey, ez = -uy, ux, 0.0
        else:
            ex, ey, ez = 0.0, -uz, uy
        en = hypot(ex, ey, ez)
        ex, ey, ez = ex / en, ey / en, ez / en
        fx, fy, fz = uy * ez - uz * ey, uz * ex - ux * ez, ux * ey - uy * ex
        a, c = rng.gauss(0.0, sigma), rng.gauss(0.0, sigma)
        theta = hypot(a, c)
        if theta:
            tx, ty, tz = ((a * ex + c * fx) / theta,
                          (a * ey + c * fy) / theta,
                          (a * ez + c * fz) / theta)
            ct, st = cos(theta), sin(theta)
            nx, ny, nz = ct * ux + st * tx, ct * uy + st * ty, ct * uz + st * tz
        else:
            nx, ny, nz = ux, uy, uz
        out[b:b + 3] = [magnitude * nx, magnitude * ny, magnitude * nz]
    return out


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
        noisy = perturb_los_exponential(los_dir, bearing_noise_rad, rng)
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
    schema_errors = validate_core_schema(record)
    if schema_errors:
        return _schema_failure("; ".join(schema_errors))
    sp = record.get("sensor_pos_ecef") or record.get("sensor_pos")
    ld = record.get("los_dir")
    if sp is None and ld is None:
        return None
    if not sp or not ld:
        return _schema_failure("primary sensor positions and bearing vectors must be non-empty")
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
    the nominal solve. This empirical tail quantity is preferable to a standard
    deviation here: the nested
    audit showed the range-error distribution is heavier-tailed than Gaussian, so
    a symmetric ±k*std under-covers (2σ caught only ~77%). Reporting the
    unconditional 95th-percentile deviation preserves the model-defined tail
    quantity without claiming independent field calibration.

    Returns unconditional nearest-rank p95, relative uncertainty, solve
    fraction, and trial/success/failure counts. Failed solves are +infinity.
    `trials=200` so the 95th percentile rests on ~10 tail samples, not 1-2."""
    import random as _r
    rng = _r.Random(seed)
    numeric_floor = NUMERIC_REL_FLOOR * rng_m
    if sigma <= 0:
        return numeric_floor, NUMERIC_REL_FLOOR, 1.0, 0, 0, 0
    sp1 = record.get("sensor_pos_ecef") or record.get("sensor_pos")
    sp2 = record.get("sensor_pos_2")
    ld1 = record.get("los_dir"); ld2 = record.get("los_dir_2")

    def perturb(ld):
        return perturb_los_exponential(ld, sigma, rng)

    devs = []
    for _ in range(trials):
        sub = {"sensor_pos": list(sp1), "los_dir": perturb(ld1),
               "sensor_pos_2": list(sp2), "los_dir_2": perturb(ld2),
               "bearing_noise_rad": sigma, "bearing_noise_units": "rad",
               "position_units": record["position_units"],
               "coordinate_frame": record["coordinate_frame"],
               "bearing_units": record["bearing_units"]}
        if "fps" in record:
            sub["fps"] = record["fps"]
        if "times" in record:
            sub["times"] = list(record["times"])
        tr = triangulate(sub, _mc=False)
        if tr and tr.get("solvable"):
            devs.append(abs(tr["range_m"] - rng_m))
    successes = len(devs)
    failures = trials - successes
    solve_fraction = successes / trials
    devs.sort()
    rank = int(ceil(0.95 * trials))
    p95 = devs[rank - 1] if successes >= rank else float("inf")
    p95 = max(p95, numeric_floor)
    return (p95, (p95 / rng_m if rng_m > 0 else float("inf")), solve_fraction,
            trials, successes, failures)


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
    schema_errors = validate_core_schema(record)
    if schema_errors:
        return {"solvable": False, "input_valid": False,
                "reason": "; ".join(schema_errors)}
    sp1 = record.get("sensor_pos_ecef") or record.get("sensor_pos")
    ld1 = record.get("los_dir")
    sp2 = record.get("sensor_pos_2")
    ld2 = record.get("los_dir_2")
    if sp2 is None and ld2 is None:
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
        # A six-sigma per-frame consistency envelope avoids turning the
        # all-frames gate into an accidental multiple-comparisons rejection.
        # Monte Carlo failures remain unbounded outcomes below.
        miss_limit = max(1e-6, 6.0 * sigma * hypot(s, t))
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
        (sigma_range, rel_unc, solve_fraction, mc_trials, mc_successes,
         mc_failures) = _mc_range_uncertainty(
            record, s, t, p1, d1, p2, d2, rng_m, sigma)
    else:
        sigma_range, rel_unc, solve_fraction = 0.0, 0.0, 1.0
        mc_trials = mc_successes = mc_failures = 0

    if _mc and (not isfinite(sigma_range) or not isfinite(rel_unc)):
        return {
            "solvable": False,
            "input_valid": True,
            "reason": ("uncertainty propagation failed: too few finite Monte Carlo "
                       "re-solves or more than 5% failed; failures are unbounded and "
                       "no range claim is permitted"),
            "selected_frame_index": selected_frame_index,
            "solve_fraction": round(solve_fraction, 4),
            "mc_trials": mc_trials,
            "mc_successes": mc_successes,
            "mc_failures": mc_failures,
            "quantile_method": "unconditional nearest-rank p95; failed re-solves are +infinity",
        }

    sync_verified = sync_precision is not None
    confident = (isfinite(rel_unc) and rel_unc < 0.05 and sync_verified and
                 solve_fraction >= 0.95)
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
        # Preserve the numerical center used by the uncertainty calculation;
        # early rounding can move the reported center outside its own interval.
        "range_m": rng_m,
        "miss_distance_m": round(miss, 2),
        "baseline_m": round(baseline, 1),
        # Quantize upward, never down, so display precision stays conservative.
        "sigma_range_m": ceil(sigma_range * 1000.0) / 1000.0,
        "interval_kind": "numerical-floor" if sigma <= 0 else "empirical-p95",
        "rel_uncertainty": round(rel_unc, 4),
        "solve_fraction": round(solve_fraction, 4),
        "mc_trials": mc_trials,
        "mc_successes": mc_successes,
        "mc_failures": mc_failures,
        "quantile_method": "unconditional nearest-rank p95; failed re-solves are +infinity",
        "sync_verified": sync_verified,
        "selected_frame_index": selected_frame_index,
        "confident": confident,
        "note": (f"two-sensor triangulation at synchronized frame "
                 f"{selected_frame_index} — a position independent of CV "
                 "conditioning. sigma_range is the model-conditional empirical "
                 f"p95 range deviation under bearing noise ({sigma:g} rad), "
                 f"baseline/range ratio {base_over_range:.3f}. Treat the range as "
                 f"±sigma_range within this simulation model; it is not independently "
                 f"calibrated for field coverage. {confidence_note}"),
    }


# ---------- top-level assessment ----------

def assess_sighting(record):
    schema_errors = validate_core_schema(record)
    intake = validate_intake(record)
    if schema_errors:
        intake = dict(intake)
        intake["complete"] = False
        intake["schema_errors"] = schema_errors
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
