# Provenance and release boundaries

## Current conditioning implementation

`uap_conditioning.py` is a clean-room implementation written from a mathematical specification of a constant-velocity bearing-only design system. The implementer was isolated from this repository, existing implementations, and network sources. The admitted implementation was independently read, scanned before integration, tested, and then minimally hardened for strict JSON-number handling and compatibility constants.

No upstream source code or commentary is included in the current conditioning implementation.

Current SHA-256 identities:

- `uap_conditioning.py`: `4072a0b0e7e227d72d6cf06bbd55c7aeed26435f7ddd2cb7a10bdd6c92f6436a`
- `tests/test_uap_conditioning.py`: `552d583dd6d0aa05380d0fa8de2b72fb91b013c995f03d482dd1ca2c73850854`

These hashes identify the reviewed working files before the final release commit. The final commit and archive digest are separate release identities.

## Current runtime

Use `validator.py`, directly or through `uap_assess.py`. The active numerical
implementation is separately versioned in `runtime_v0_2.py`; it does not import
the hash-bound historical `intake.py`. It applies conservative claim gates:

- exact-zero declared synchronization uncertainty is required for the high-confidence geometry verdict;
- absent or nonzero synchronization uncertainty remains low-confidence because target motion is not propagated;
- `empirical-p95` names an inner Monte Carlo construction, not independent 95% calibration;
- synthetic coverage does not imply field accuracy.

## Frozen historical evidence

`intake.py` and `evidence/stronger_evidence.py` remain byte-preserved because
their hashes are bound into the frozen preregistration. They are not active
runtime dependencies. `evidence/stronger_evidence.py` is retained only for the
closed historical verifier. The separate `verify_frozen_bundle.py` performs a
non-executing file verification against a source-embedded trusted manifest
digest and an exact artifact-name allowlist.

The frozen `intake.py` contains legacy comments describing an inner Monte Carlo
bound as "calibrated" or "self-calibrating." Those phrases are preserved bytes,
not current release claims. They must not be quoted as evidence of independent
95% calibration. Current public semantics are controlled by `validator.py`, which
labels the bound model-conditional and states that synthetic coverage does not
establish field accuracy.

The holdout protocol, result, rows, CSV, original manifest, and Council-status record remain unchanged. The status is `NOT_COUNCIL_CONFORMANT` with Council inferential status `UNDETERMINED`. The completed holdout must not be rerun, replaced, reanalyzed, reinterpreted, or resealed.

## Immutable historical release identity

The published `v0.1.0` tag is an immutable historical exception to the current
neutral release-identity policy. It is documented rather than rewritten:

- tag commit: `687d263dba1b5409037256a1c7ccbcca225ca20f`
- tag tree: `5551c70774789ea166f45b7bc2e31f0c855a43f3`
- committed release archive SHA-256: `c32f758d535e8fd4987ad4fc26ec1020f775218a8aa6db478d0d0f5168d57d57`

Current work is explicitly `0.2.0-dev`; it is post-release development, not a
retroactive alteration, reinterpretation, or reseal of `v0.1.0`. Future release
commits must use a neutral project identity. No published tag is moved.
