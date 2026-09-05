# Detection range and triangulation geometry

Scope note: this document describes the *geometric* limits of two-sensor range
estimation — the same math the validator's triangulation path lives under. It is
model-conditional engineering analysis, not field validation. It does not claim
any deployed detection capability; it explains why distance is the binding
constraint on any passive optical triangulation system, infrared or visible.

## Why distance is the challenge

Two synchronized observers at known positions each measure a bearing to the
target. In the equal-range, far-field approximation, let `b_perp` be the
component of their baseline perpendicular to the line of sight. For target range
`r` and small per-sensor bearing noise `sigma_theta` in radians, the first-order
range scale is

```
sigma_r ≈ r^2 * sigma_theta / b_perp
```

Equivalently, because the small crossing angle obeys
`sin(phi) ≈ b_perp / r`, the same sensitivity can be written
`sigma_r ≈ r * sigma_theta / sin(phi)`. These are alternative
parameterizations; multiplying them would count the geometry twice.

Three consequences are structural:

1. **Quadratic in range for fixed baseline.** Double the target distance and the
   range uncertainty quadruples when `b_perp` and noise are fixed.

2. **Inversely proportional to perpendicular baseline.** Wider useful sensor
   separation buys linear improvement. Baseline parallel to the line of sight
   contributes little or no triangulation leverage.

3. **Poor at small crossing angle.** Triangulation quality collapses as `phi`
   approaches zero. The validator's conditioning and ray-consistency checks
   reject this same geometric degeneracy.

Checked orientation example: `sigma_theta = 0.1 deg = 0.001745 rad`,
`b_perp = 1 km`, and `r = 10 km` give
`(10,000 m)^2 * 0.001745 / 1,000 m ≈ 175 m`. At `r = 40 km`, the same
calculation gives about `2,793 m`. The 10 km geometry has a small crossing angle
of about `b_perp/r = 0.1 rad` (about `5.7 deg`), not 90 degrees. These are
first-order, geometry-conditional magnitudes rather than guarantees. Actual
performance depends on realized noise and synchronization, and the validator's
unconditional empirical-p95 construction (see README "Known limitation") is
wider by design.

## Detection range vs. validation range

A wide-angle camera system (e.g. 120 deg FOV) *detects* objects over a large
area; a triangulation pair *validates* a range claim for a specific event. The
distance at which a sensor can detect an object (signal vs. noise floor,
atmospheric attenuation — acute in infrared bands) and the distance at which a
declared geometry can support a range claim are different questions. This
repository addresses only the second. Nothing here remedies detection limits;
no amount of post-processing recovers signal a sensor never recorded.

## What this means for verdicts

- The `r^2 / b` scaling is why the triangulation path demands synchronized
  bearings, physical ray checks, and a relative uncertainty gate before any
  high-confidence label. Distant targets with short baselines will and should
  land on RANGE ESTIMATE — LOW CONFIDENCE or be rejected outright.
- A "good" triangulation verdict is a statement about one event's geometry
  under declared assumptions. It is not evidence about system-level capability
  at arbitrary range, and this tool makes no such claim.
- Infrared vs. visible sensors change the noise term (`sigma_theta`) and the
  detection envelope, not the geometry. The validator is sensor-agnostic: it
  consumes declared bearings and positions. Any sensor-specific noise model
  belongs in the analyst's declared assumptions, where it is visible and
  auditable, not hidden in the solver.

## Relation to the frozen holdout

The frozen crossing-angle holdout (see README) evaluated exactly this class of
geometry-dependent performance under its preregistration. Its Council-level
status remains **UNDETERMINED**; nothing in this document reruns, reinterprets,
or upgrades that record.
