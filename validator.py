"""Current public runtime for the UAP intake validator.

The frozen one-shot evidence implementation remains in ``intake.py`` so its
recorded source digest and historical verifier stay reproducible. New release
semantics live here and fail closed when synchronization uncertainty is not
modeled.
"""
from math import isfinite

import runtime_v0_2 as _runtime


GEOMETRY_SUPPORTED = "RANGE SUPPORTED BY SYNCHRONIZED GEOMETRY"
LOW_CONFIDENCE = "RANGE ESTIMATE — LOW CONFIDENCE"


def _exact_sync(record):
    """Return True only for an explicit, finite, exact-zero sync uncertainty."""
    value = record.get("time_sync_precision_s")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value) and float(value) == 0.0
    except (OverflowError, TypeError, ValueError):
        return False


def triangulate(record, _mc=True):
    """Run the versioned active geometric solver with conservative claim gates.

    A nonzero synchronization uncertainty is accepted as input when the active
    solver accepts it, but it cannot produce a high-confidence range claim
    because target motion is not part of the uncertainty propagation model.
    """
    result = _runtime.triangulate(record, _mc=_mc)
    if not result or not result.get("solvable"):
        return result

    sync_verified = _exact_sync(record)
    result = dict(result)
    result["sync_verified"] = sync_verified
    result["confident"] = bool(result.get("confident") and sync_verified)
    if not sync_verified:
        result["note"] = (
            "LOW CONFIDENCE: synchronization uncertainty is absent or nonzero, "
            "and target motion is not propagated into the range bound."
        )
    else:
        result["note"] = (
            f"two-sensor geometric solve at synchronized frame "
            f"{result.get('selected_frame_index')} under the declared bearing-noise model; "
            "synthetic coverage does not establish field accuracy."
        )
    return result


def _measurement_lines(intake_result, flag, tri):
    lines = []
    if intake_result["complete"]:
        lines.append("intake schema complete — analyzable in principle")
    if flag and flag.get("rcond") is not None:
        lines.append(
            f"CV-family conditioning: rcond={flag['rcond']:.2e} "
            f"(log10={flag['log10Rcond']:.2f}, rank={flag['effectiveRank']}) "
            f"-> {flag['conditioning']}"
        )
        if flag.get("collapse"):
            lines.append(f"fitted track collapse warning: {flag['collapseReason']}")
        if flag.get("stability") and flag["stability"].get("note"):
            lines.append(f"noise stability: {flag['stability']['note']}")
    if tri:
        if tri.get("solvable"):
            lines.append(
                f"GEOMETRIC SOLVE: range {tri['range_m']} m at {tri['position_m']} "
                f"(miss {tri['miss_distance_m']} m, baseline {tri['baseline_m']} m); "
                "interpret only under the declared sensor and timing assumptions"
            )
        else:
            lines.append(f"triangulation attempted: {tri.get('reason')}")
    if flag and flag.get("error"):
        lines.append(f"conditioning not run: {flag['error']}")
    if flag and flag.get("remediation"):
        lines.extend(f"remediation: {item}" for item in flag["remediation"])
    return lines


def assess_sighting(record):
    """Assess one sighting with current conservative release semantics."""
    schema_errors = _runtime.validate_core_schema(record)
    intake_result = _runtime.validate_intake(record)
    if schema_errors:
        intake_result = dict(intake_result)
        intake_result["complete"] = False
        intake_result["schema_errors"] = schema_errors
    flag = _runtime.underdetermination_flag(record)
    tri = triangulate(record)

    if ((tri and tri.get("input_valid") is False) or
            (flag and flag.get("valid") is False)):
        verdict = "INVALID SIGHTLINE DATA"
    elif tri and tri.get("solvable") and tri.get("confident"):
        verdict = GEOMETRY_SUPPORTED
    elif tri and tri.get("solvable"):
        verdict = LOW_CONFIDENCE
    elif flag and flag.get("conditioning") == "poor":
        verdict = "CANNOT SUPPORT RANGE CLAIM"
    elif not intake_result["complete"]:
        verdict = "INCOMPLETE INTAKE"
    else:
        verdict = "ANALYZABLE (with caveats)"

    measurements = _measurement_lines(intake_result, flag, tri)
    return {
        "scope": (
            "model-conditional validation only; does not prove or disprove a "
            "sighting, identify an object, or establish field accuracy"
        ),
        "assumed": intake_result["assumed"],
        # Backward-compatible alias from the frozen historical API. Public
        # interfaces should prefer ``measurements`` and present them as
        # model-conditional rather than independently established facts.
        "established": measurements,
        "measurements": measurements,
        "intake": intake_result,
        "underdetermination": flag,
        "triangulation": tri,
        "verdict": verdict,
    }
