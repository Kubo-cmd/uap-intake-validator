# Provenance and release boundaries

## Current conditioning implementation

`uap_conditioning.py` is a clean-room implementation written from a mathematical specification of a constant-velocity bearing-only design system. The implementer was isolated from this repository, existing implementations, and network sources. The admitted implementation was independently read, scanned before integration, tested, and then minimally hardened for strict JSON-number handling and compatibility constants.

No upstream source code or commentary is included in the current conditioning implementation.

Current SHA-256 identities:

- `uap_conditioning.py`: `4072a0b0e7e227d72d6cf06bbd55c7aeed26435f7ddd2cb7a10bdd6c92f6436a`
- `tests/test_uap_conditioning.py`: `552d583dd6d0aa05380d0fa8de2b72fb91b013c995f03d482dd1ca2c73850854`

These hashes identify the reviewed working files before the final release commit. The final commit and archive digest are separate release identities.

## Current runtime

Use `validator.py`, directly or through `uap_assess.py`. It applies conservative claim gates:

- exact-zero declared synchronization uncertainty is required for the high-confidence geometry verdict;
- absent or nonzero synchronization uncertainty remains low-confidence because target motion is not propagated;
- `empirical-p95` names an inner Monte Carlo construction, not independent 95% calibration;
- synthetic coverage does not imply field accuracy.

## Frozen historical evidence

`intake.py` and `evidence/stronger_evidence.py` remain byte-preserved because their hashes are bound into the frozen preregistration. The current `validator.py` claim-gating layer is separate, but it deliberately imports and delegates geometric and intake operations to the preserved `intake.py` implementation before applying stricter current gates. `evidence/stronger_evidence.py` is retained for the closed historical verifier. The active CLI and runtime tests enter through `validator.py`; this separates current verdict policy, not the underlying geometric implementation.

The frozen `intake.py` contains legacy comments describing an inner Monte Carlo
bound as "calibrated" or "self-calibrating." Those phrases are preserved bytes,
not current release claims. They must not be quoted as evidence of independent
95% calibration. Current public semantics are controlled by `validator.py`, which
labels the bound model-conditional and states that synthetic coverage does not
establish field accuracy.

The holdout protocol, result, rows, CSV, original manifest, and Council-status record remain unchanged. The status is `NOT_COUNCIL_CONFORMANT` with Council inferential status `UNDETERMINED`. The completed holdout must not be rerun, replaced, reanalyzed, reinterpreted, or resealed.
