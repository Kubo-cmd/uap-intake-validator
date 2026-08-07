# Detection range and triangulation geometry

Scope note: this document describes the *geometric* limits of two-sensor range
estimation — the same math the validator's triangulation path lives under. It is
model-conditional engineering analysis, not field validation. It does not claim
any deployed detection capability; it explains why distance is the binding
constraint on any passive optical triangulation system, infrared or visible.

## Why distance is the challenge

Two synchronized observers at known positions, separated by baseline `b`, each
measure a bearing to the target. The range estimate comes from intersecting the
two bearing rays. For a target at range `r` with bearing noise `sigma_theta`
(radians, per sensor), the first-order range uncertainty of the intersection is

```
sigma_r ≈ r^2 * sigma_theta / (b * sin(phi))
```

where `phi` is the crossing angle between the two rays (the angle at the target
between the lines to the two sensors). Three consequences, all structural:

1. **Quadratic in range.** Double the target distance and the range uncertainty
   quadruples, everything else held fixed. This is the dominant term and the
   reason "the main challenge is the distance" is not an implementation detail —
   it is the geometry.

2. **Inversely proportional to baseline.** Wider sensor separation `b` buys
   linear improvement. Long-baseline deployments are the only structural lever
   that scales against the quadratic range term. Short baselines on a single
   platform cannot compensate at distance.

3. **Inversely proportional to sin(phi).** Triangulation quality collapses as
   the crossing angle approaches zero (target nearly on the baseline axis — both
   sensors looking down the same line). At `phi = 90 deg` the geometry is
   optimal. The validator already rejects degenerate geometries through its
   conditioning diagnostic and ray-consistency checks; this is the same
   phenomenon viewed from the range side.

For orientation only: with `sigma_theta = 0.1 deg`, `b = 1 km`, and a favorable
crossing angle (`sin(phi) ≈ 1`), a target at `r = 10 km` carries a first-order
range uncertainty on the order of hundreds of meters. At `r = 40 km` it is on
the order of kilometers. These are geometry-conditional magnitudes, not
guarantees — actual performance depends on the realized noise, sync precision,
and crossing angle of the specific event, and the validator's empirical-p95
construction (see README "Known limitation") is wider than this first-order form
by design.

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
