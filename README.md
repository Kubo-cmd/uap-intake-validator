# UAP Intake Validator — Run the software

## Start here

This project has three connected repositories. Choose the one that matches what
you want to do:

| Goal | Repository | What is there |
|---|---|---|
| Run or inspect the research software | **[UAP Intake Validator](https://github.com/Kubo-cmd/uap-intake-validator)** | Canonical code, tests, methodology, and scientific evidence |
| Understand the current status and its history | **[UAP Witness Ledger](https://github.com/Kubo-cmd/uap-witness-validator)** | Solver-free append-only status records and exact evidence hashes |
| Verify or recover the frozen release | **[UAP Release Vault](https://github.com/Kubo-cmd/releases)** | Frozen release files, checksums, seals, receipts, and offline verification |

Recommended flow: **1. Run the software → 2. Read the status history → 3. Verify
the frozen release.** The three repositories are connected by release names,
versions, commits, and SHA-256 hashes, but each has one distinct job.

Release candidate: `0.1.0` — experimental, simulation-evaluated research software.

A UAP sighting-intake validator with a built-in **underdetermination flag** and
**two-sensor triangulation**. One question, answered honestly: **can this sighting
support a range/speed/size claim at all?** With a second observer, it reports the
position supported by the declared synchronized-ray geometry and assumptions.

## Scope and non-claims

This is an **experimental, simulation-evaluated, open-source validation and
research tool**. It tests whether declared sighting data and assumptions can
support specific geometry-limited claims.

It does **not**:

- prove or disprove a sighting, identify an object, or determine what occurred;
- establish field performance, population performance, or universal 95% coverage;
- turn a `good`, `solvable`, or high-confidence result into independent evidence
  that a sighting account is true;
- authorize reinterpretation or rerun of the frozen historical holdout.

All reported performance values come from a **fixed synthetic evaluation
distribution**. They are model-conditional engineering evidence, not field
validation. The frozen holdout remains **UNDETERMINED** at Council level and must
not be rerun, replaced, reanalyzed, reinterpreted, or resealed.

Most single-sensor UAP footage cannot pin range — not because the object is
debunked, but because the geometry is *underdetermined*. A camera on a
straight-and-level path watching a constant-velocity object yields a rank-deficient
design system: infinitely many ranges fit the same angular track. Any single number
is then an artifact of the analyst's prior, not the data.

Even with two synchronized observers, range uncertainty grows quadratically with
target distance and shrinks only linearly with sensor baseline — see
[`docs/DETECTION-RANGE.md`](docs/DETECTION-RANGE.md). This tool validates the
geometry of a specific event; it does not detect objects and makes no claim about
system-level detection capability at any range, for any sensor type (infrared or
visible).

## What it does

`validator.assess_sighting(record)` splits analyst-supplied assumptions from
computed measurements and caveats:

- **intake completeness** — required/recommended metadata
- **underdetermination flag** — clean-room stdlib implementation of a CV-family
  conditioning diagnostic: reciprocal condition number of the column-equilibrated
  6x6 design matrix over the bearings
- **noise stability** — Monte-Carlo re-test of the verdict under bearing noise.
  A "good" that flips under tiny noise is not trustworthy; the tool says so.
- **two-sensor triangulation** — when `sensor_pos_2` + `los_dir_2` are present, solves
  the closest approach of the two bearing rays, independent of CV
  conditioning. It rejects intersections behind either observer, inconsistent rays,
  malformed/non-finite/overflow-scale arrays, unsynchronized bearing counts,
  malformed frame-rate/timestamp metadata, declared cross-sensor timing precision
  above 1 second, per-frame ray disagreement, and angular noise outside 0..pi radians.
  For multi-frame tracks it reports the deterministic center synchronized frame
  instead of averaging positions across time.
  Reports range, 3D miss distance, baseline, and a simulation-derived uncertainty
  estimate under the declared bearing-noise model.
- **remediation** — when not "good", actionable next steps.

## The one-way warning (doctrine)

- **"poor" is load-bearing**: range unreliable for CV-family fits (Sitrec BOT Bench:
  82% collapse at log10(rcond)~-3).
- **"good" is NEVER a guarantee**: pointing error inflates apparent conditioning.
- **method-local**: speaks for the constant-velocity family only.
- **triangulation is the exception**: two simultaneous observers can geometrically
  support range independent of CV geometry. The high-confidence verdict requires an
  explicit exact-zero synchronization-uncertainty declaration, physical ray checks,
  and simulation-derived relative uncertainty below 5%. Any absent or nonzero sync
  uncertainty remains a low-confidence estimate because target motion is not modeled.
  Multi-frame inputs are never temporally averaged: the output identifies the
  deterministic center synchronized frame, so temporal averaging cannot create a
  fictitious in-between position or a best-of-N selection bias.
  Timestamp-free pairs remain labeled RANGE ESTIMATE — LOW CONFIDENCE.
  Otherwise a solvable result is labeled RANGE ESTIMATE — LOW CONFIDENCE.

## Verifying the claims

The current runtime claims are re-checkable with one command:

```
python3 tests/run_tests.py
```

The suite re-runs the ship invariants (straight-line refusal, a canned two-sensor
solve within its model-conditional empirical-p95 bound, zero dangerous
overconfident results across a fixed 200-world synthetic audit, and the full
Monte-Carlo gate) and exits non-zero if any regress. `simulate.py` prints the raw
synthetic results.

The historical one-shot evidence has separate read-only gates:

```
python3 -m pip install -r requirements-evidence.txt
python3 evidence/test_stronger_evidence.py
python3 evidence/stronger_evidence.py verify
```

These commands verify the frozen historical record; they do not upgrade its
Council status or validate the current runtime in the field. `intake.py` and
`evidence/stronger_evidence.py` are retained at their original paths solely because
the preregistration binds their exact hashes; active runtime entrypoints use
`validator.py`. See [`PROVENANCE.md`](PROVENANCE.md).

### Frozen crossing-angle holdout status

A one-shot 6,480-world holdout met its own preregistered physical-error-law
criteria but failed its production-selection gate. The result is valid only
under that frozen preregistration and is not Council-conformant; it was not
rerun or replaced post hoc. Its Council-level inferential status is
**UNDETERMINED**—not PASS and not retroactive FAIL.

The append-only status record binds the frozen artifact hashes and controls any
mention of the holdout:
[`evidence/results/holdout-2026080502.council-status.json`](evidence/results/holdout-2026080502.council-status.json).

## Known limitation (read before trusting a range)

`sigma_range` is an **empirical-p95 Monte Carlo construction**, not a raw Gaussian
standard deviation and not an independently validated 95% interval.
Early versions reported the Monte-Carlo standard deviation, which a nested-simulation
audit (200 random worlds) showed ran tight — only ~55% of true errors fell within 1σ,
~77% within 2σ, because the range-error distribution is heavier-tailed than Gaussian.
The tool reports the **empirical 95th-percentile range deviation** under the
stated bearing noise (`interval_kind: "empirical-p95"`). A 0.005% numerical floor
(`interval_kind: "numerical-floor"`) covers floating-point solve error when declared
bearing noise is zero. A deterministic nested audit measured aggregate inclusion
across its fixed synthetic mix of noise levels.

- Treat **±sigma_range** only as a model-conditional synthetic uncertainty summary.
- The dangerous failure mode stays covered: **0/191** solvable cases were both
  confidently reported and more than 5% wrong in 3D across the deterministic
  200-world audit. Larger-error solves were labeled low-confidence. The tool errs
  toward "don't trust this" when uncertain — the correct asymmetry, since its
  purpose is stopping artifact-as-fact.
- The same fixed audit measured **180/191 (94.2%)** inclusion inside the quoted
  empirical-p95 range bound. This is not a per-stratum, population, or field guarantee.
- To tighten a solve: widen the baseline, lower bearing noise, or add a third
  observer.

## Verified

- 4 deterministic cases: 0 false-good, 0 false-poor
- 640-trial Monte-Carlo (bearing noise 0→0.06 deg): 0.000% both ways — SHIP GATE PASS
- boundary gradient: conditioning rises monotonically with parallax
- triangulation regression: noise-free recovery to 1e-6 m; position error grows
  monotonically across the declared bearing-noise sweep while all 40 deterministic
  trials per level remain solvable. Run `python3 simulate.py`.
- nested-simulation audit (`python3 nested_sim.py`): 0 dangerous
  overconfident solves across 200 randomized worlds. The audit also reports a
  deterministic independent solved-pairs bootstrap for the Pearson association
  between log baseline/range and log 3D error. That uncertainty is descriptive,
  conditional on solvability and the simulator world distribution, and is not a
  calibration PASS/FAIL gate or a real-population inference.

## Use

```
python3 uap_assess.py examples/straight_level_sightlines.json   # single sensor: flagged
python3 uap_assess.py examples/two_sensor_triangulation.json    # two sensors: solved
python3 simulate.py                                             # reproduce verification
python3 nested_sim.py                                           # calibration audit
```

## Related integrity repositories

This repository is the only canonical implementation of the validator. Two
solver-free companions preserve different trust boundaries under the same
public account:

- `uap-witness-validator` — append-only status and evidence ledger with an
  offline verifier; it contains no working solver.
- `releases` — independent Git-history mirror of the frozen v0.1.0 artifacts,
  checksums, seal, relic, and publication receipt.

Both companions point back here. Neither replaces this source tree, its tests,
or its scientific scope.

Current validator runtime: Python 3.9+, stdlib-only, MIT license. The frozen
historical evidence harness additionally requires the exact versions in
`requirements-evidence.txt`. Methodology credit: the upstream Sitrec2 project;
no upstream source code is included in the current conditioning implementation.
An open-science instrument for testing whether declared data support narrowly
defined geometric claims—not for adjudicating sightings.
